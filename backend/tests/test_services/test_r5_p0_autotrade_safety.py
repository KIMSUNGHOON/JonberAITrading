"""R5-P0: autotrade safety fixes (audit 2026-07-12, findings A1/A2/A5).

The autotrade model audit found three order-blocking defects in the
decision→execution translation layer. These tests pin the corrected behavior:

- A1: an ADD (add-to-position) decision was reversed into a SELL order by the
  side-mapping in ExecutionCoordinator.on_trade_approved.
- A2: the PositionManager defensive-close path (stop-loss / take-profit /
  agent-decision SELL) executed WITHOUT passing the shared autonomy gate that
  the offensive BUY path already enforces.
- A5: an autonomous BUY/ADD that got QUEUED lost its quantity (add_to_queue had
  no quantity param) → the execution-time re-gate denied it at notional_cap
  ("quantity unknown for a BUY/ADD") → every queued autonomous buy was cancelled.

Spec: docs/superpowers/specs/2026-07-12-autotrade-model-audit.md §A
"""

import asyncio
import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

import services.autonomy as autonomy_pkg
import services.storage_service as ss
from services.autonomy import GateDecision
from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import (
    AllocationPlan,
    ManagedPosition,
    OrderRequest,
    OrderResult,
    OrderSide,
    QueueStatus,
    StopLossMode,
    TradingMode,
)


@pytest_asyncio.fixture(autouse=True)
async def _isolated_storage(tmp_path, monkeypatch):
    """T7 fix (review CRITICAL 2): PositionManager mutators fire-and-forget
    persist stop levels whenever a running event loop exists, so the real-PM
    A2 tests below were writing their fixture stops (68875/79750) into the
    LIVE data/storage.db. Isolate the whole module behind a temp SQLite DB
    (same pattern as test_r5_p1_execution_reliability.py). Otherwise behavior
    is unchanged: every test here monkeypatches the autonomy gate and none
    reads app settings from storage."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


@pytest.fixture
def master_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUTONOMY_ENABLED", True)


def _open_session() -> MarketSession:
    return MarketSession(
        is_open=True,
        current_time=datetime.now(),
        next_open=None,
        next_close=None,
        message="open",
    )


def _live_coordinator() -> ExecutionCoordinator:
    """A coordinator wired to execute immediately (ACTIVE + market open)."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(return_value=_open_session())
    coord._refresh_account_info = AsyncMock()
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=OrderSide.BUY,
            quantity=1,
            entry_price=50_000,
            estimated_amount=50_000,
            position_pct=1.0,
            rationale="stub allocation",
            rebalance_orders=[],
        )
    )
    return coord


async def _capture_executed_order(coord: ExecutionCoordinator) -> list:
    captured = []

    async def _record(order):
        captured.append(order)
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=order.price or 50_000,
            status="filled",
        )

    coord._execute_order = _record
    return captured


# -------------------------------------------
# A1 — ADD must execute as a BUY, not a SELL
# -------------------------------------------


async def test_add_action_executes_as_buy_order():
    """A1: an ADD decision must place a BUY order (grow the position), not SELL."""
    coord = _live_coordinator()
    captured = await _capture_executed_order(coord)

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="ADD",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=1,
    )

    assert len(captured) == 1
    assert captured[0].side == OrderSide.BUY, "ADD must map to a BUY order side"


async def test_reduce_action_executes_as_sell_order():
    """A1 guard: REDUCE (partial exit) must still map to a SELL order side."""
    coord = _live_coordinator()
    captured = await _capture_executed_order(coord)

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="REDUCE",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=1,
    )

    assert len(captured) == 1
    assert captured[0].side == OrderSide.SELL


# -------------------------------------------
# A5 — queued autonomous BUY/ADD must keep its quantity
# -------------------------------------------


async def test_add_to_queue_stores_quantity():
    """A5: add_to_queue must persist the quantity onto the QueuedTrade."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    queued = coord.add_to_queue(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        reason="Market closed",
        autonomous=True,
        quantity=7,
    )

    assert queued.quantity == 7


async def test_queued_autonomous_buy_preserves_quantity_through_regate(
    master_on, monkeypatch
):
    """A5: a queued autonomous BUY must reach the execution-time re-gate WITH its
    quantity, so the notional cap is evaluated on the real size instead of being
    fail-closed denied for an unknown quantity."""
    coord = ExecutionCoordinator(kiwoom_client=None)  # mode STOPPED → queues

    # Queue an autonomous BUY the way the chat coordinator does (quantity known).
    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=7,
        autonomous=True,
    )
    assert coord._state.trade_queue[0].quantity == 7, "queued quantity was lost"

    # The re-gate must see the preserved quantity (not None → not fail-closed).
    gate_calls = []

    async def recording_gate(market, **kwargs):
        gate_calls.append(kwargs)
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", recording_gate)

    executed = []

    async def record_on_trade_approved(*args, **kwargs):
        executed.append(kwargs.get("quantity_override"))
        return AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=OrderSide.BUY,
            quantity=7,
            entry_price=50_000,
            estimated_amount=350_000,
            position_pct=1.0,
            rationale="executed",
        )

    coord.on_trade_approved = record_on_trade_approved

    await coord.process_trade_queue()

    assert gate_calls, "re-gate was not invoked for the autonomous queued trade"
    assert gate_calls[0]["quantity"] == 7
    assert executed == [7]
    assert coord._state.trade_queue[0].status == QueueStatus.COMPLETED


# -------------------------------------------
# A2 — autonomous defensive close must pass the autonomy gate
# -------------------------------------------


def _position_manager_with_position():
    from services.agent_chat.position_manager import (
        PositionManager,
        PositionManagerConfig,
    )

    pm = PositionManager(config=PositionManagerConfig())
    position = pm.add_position(
        ticker="005930",
        stock_name="삼성전자",
        quantity=100,
        avg_price=72_500,
        current_price=68_000,
        stop_loss=68_875,
        take_profit=79_750,
    )
    return pm, position


async def test_defensive_close_blocked_when_gate_denies(monkeypatch):
    """A2: a stop-loss/take-profit close must NOT execute when the autonomy gate
    denies (e.g. mode flipped to HITL) — and the position must stay monitored so
    a human can act on it."""
    pm, position = _position_manager_with_position()

    closed = []
    fake_coord = MagicMock()

    async def _close(ticker, decision_id=None):
        closed.append(ticker)

    fake_coord._close_position = _close
    monkeypatch.setattr(
        "app.dependencies.get_trading_coordinator", AsyncMock(return_value=fake_coord)
    )

    async def deny_gate(market, **kwargs):
        return GateDecision(
            allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode"
        )

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

    await pm._execute_close_position(position, "stop_loss")

    assert closed == [], "gate-denied defensive close must not execute an order"
    assert position.ticker in pm._positions, "blocked position must stay monitored"


async def test_repeated_gate_denied_close_notifies_once(monkeypatch):
    """A2 (review CONFIRMED): a persistently gate-denied defensive close must
    notify the human ONCE per denied episode, not on every monitor cycle. With
    auto_execute enabled the STOP_LOSS_HIT event re-fires each cycle and the
    denied position stays monitored, so an un-throttled notice would flood
    Telegram every check_interval_seconds — the gate's own breaker notice is
    throttled once per day for the very same trigger."""
    pm, position = _position_manager_with_position()

    async def deny_gate(market, **kwargs):
        return GateDecision(
            allowed=False, reason="daily loss >= limit", check="daily_loss_breaker"
        )

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

    notices = []

    async def spy_notify(pos, reason, gate_reason):
        notices.append(pos.ticker)

    pm._notify_close_gate_denied = spy_notify

    # Three monitor cycles deny the same stopped-out position.
    await pm._execute_close_position(position, "stop_loss")
    await pm._execute_close_position(position, "stop_loss")
    await pm._execute_close_position(position, "stop_loss")

    assert notices == ["005930"], "denied close must notify once, not every cycle"
    assert position.ticker in pm._positions


async def test_defensive_close_proceeds_when_gate_allows(monkeypatch):
    """A2 guard: when the gate allows, the defensive close executes and the
    position is dropped from monitoring."""
    pm, position = _position_manager_with_position()

    closed = []
    fake_coord = MagicMock()

    async def _close(ticker, decision_id=None):
        closed.append(ticker)

    fake_coord._close_position = _close
    monkeypatch.setattr(
        "app.dependencies.get_trading_coordinator", AsyncMock(return_value=fake_coord)
    )

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

    await pm._execute_close_position(position, "stop_loss")

    assert closed == [position.ticker]
    assert position.ticker not in pm._positions


# -------------------------------------------
# I1 — AGENT_AUTO defensive sell (RiskMonitor stop-loss/take-profit) must
# pass the autonomy gate before ExecutionCoordinator places the SELL order.
# -------------------------------------------


def _coordinator_with_watched_position():
    """A coordinator with one AGENT_AUTO position already tracked + watched,
    mirroring what on_trade_approved/_restore_state produce before a
    RiskMonitor trigger calls back into _execute_order_from_monitor."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    position = ManagedPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=10,
        avg_price=72_500,
        current_price=68_000,
        stop_loss=68_000,
        take_profit=79_750,
        stop_loss_mode=StopLossMode.AGENT_AUTO,
    )
    coord._add_position(position)
    return coord, position


def _stop_loss_order(quantity: int = 10, price: float = 68_000) -> OrderRequest:
    return OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.SELL,
        quantity=quantity,
        price=price,
        reason="Stop-loss auto-execution",
    )


async def test_monitor_defensive_sell_blocked_when_gate_denies(monkeypatch):
    """I1: an AGENT_AUTO stop-loss/take-profit sell triggered by RiskMonitor must
    NOT execute when the autonomy gate denies — order_agent must not be
    invoked and the position must stay tracked/watched for a human to act."""
    coord, position = _coordinator_with_watched_position()
    captured = await _capture_executed_order(coord)

    async def deny_gate(market, **kwargs):
        return GateDecision(
            allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode"
        )

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

    await coord._execute_order_from_monitor(_stop_loss_order())

    assert captured == [], "gate-denied defensive sell must not place an order"
    assert any(p.ticker == "005930" for p in coord._state.positions), (
        "blocked position must stay in _state.positions"
    )


async def test_monitor_defensive_sell_notifies_once_per_denied_episode(monkeypatch):
    """I1: repeated gate denials for the same ticker must notify once, not on
    every RiskMonitor tick (mirrors A2's close_gate_denied_notified latch)."""
    coord, position = _coordinator_with_watched_position()
    await _capture_executed_order(coord)

    async def deny_gate(market, **kwargs):
        return GateDecision(
            allowed=False, reason="daily loss >= limit", check="daily_loss_breaker"
        )

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

    notices = []

    async def spy_notify(order, gate_reason):
        notices.append(order.ticker)

    coord._notify_monitor_gate_denied = spy_notify

    order = _stop_loss_order()
    # Three RiskMonitor ticks deny the same stopped-out position.
    await coord._execute_order_from_monitor(order)
    await coord._execute_order_from_monitor(order)
    await coord._execute_order_from_monitor(order)

    assert notices == ["005930"], "denied defensive sell must notify once, not every tick"
    assert any(p.ticker == "005930" for p in coord._state.positions)


async def test_monitor_defensive_sell_proceeds_when_gate_allows(monkeypatch):
    """I1 guard: when the gate allows, the defensive sell executes normally and
    the fill is reconciled as before (full fill removes the position)."""
    coord, position = _coordinator_with_watched_position()
    captured = await _capture_executed_order(coord)

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

    await coord._execute_order_from_monitor(_stop_loss_order())

    assert len(captured) == 1
    assert captured[0].ticker == "005930"
    assert not any(p.ticker == "005930" for p in coord._state.positions), (
        "fully filled defensive sell must remove the position"
    )



# -------------------------------------------
# S-2 review fix — dual-engine concurrent defensive-exit race guard
# -------------------------------------------
#
# RiskMonitor (1s tick, via `_execute_order_from_monitor`) and PositionManager
# (30s tick, via `_execute_close_position` -> `_close_position`) can each
# detect the SAME breached stop and race to close the SAME position: both
# read `_state.positions` for the CURRENT quantity, then `await` an order
# submission. If the second engine's read lands before the first engine's
# fill has been reconciled back into `_state.positions` (`_apply_sell_fill`),
# it still sees the pre-fill quantity and submits a SECOND full-size SELL —
# a genuine double-liquidation (the paper broker fills unconditionally, with
# no holdings check). `_acquire_defensive_exit_guard`/
# `_release_defensive_exit_guard` (a ticker-scoped in-flight `set`, see
# `ExecutionCoordinator.__init__`) close this gap.
#
# Spec: docs/superpowers/specs/2026-07-19-survival-discipline-design.md
# (S-2 review fixes, Critical finding)


async def test_second_defensive_exit_skipped_while_first_inflight(monkeypatch, caplog):
    """(1) Race reproduction: engine 1 (RiskMonitor path,
    `_execute_order_from_monitor`) submits an order and is held inside the
    broker await (simulating the submit-to-fill-confirmation window) while
    engine 2 (PositionManager path, `_close_position`) detects the SAME
    breached stop and attempts to close it too. Pre-fix (no guard), engine 2
    would read the same pre-fill quantity and place its OWN full SELL — two
    orders for one position. Post-fix: engine 2 is skipped as a no-op,
    logs `defensive_exit_skipped_inflight`, and places zero orders."""
    coord, position = _coordinator_with_watched_position()

    entered = asyncio.Event()
    hold = asyncio.Event()
    call_count = {"n": 0}

    async def slow_execute(order):
        call_count["n"] += 1
        entered.set()
        await hold.wait()
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=order.price or 68_000,
            status="filled",
        )

    coord._execute_order = slow_execute

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

    # Engine 1: begins order submission and blocks inside slow_execute —
    # this is the submit-await-confirm window the race exploits.
    task1 = asyncio.create_task(coord._execute_order_from_monitor(_stop_loss_order()))
    await entered.wait()

    # Engine 2: detects the SAME breached stop while engine 1's order is
    # still in flight.
    with caplog.at_level(logging.WARNING, logger="services.trading.coordinator"):
        result2 = await coord._close_position("005930")

    assert result2 is None, "the second concurrent exit must be skipped as a no-op"
    assert call_count["n"] == 1, "only ONE order may reach the broker while the first is in flight"
    skip_logs = [
        r for r in caplog.records if "defensive_exit_skipped_inflight" in r.getMessage()
    ]
    assert len(skip_logs) == 1, "the skip must be logged"

    # Let engine 1 finish.
    hold.set()
    await task1

    assert call_count["n"] == 1, "still only one order after the first execution completes"


async def test_defensive_exit_guard_released_after_completion_allows_retry(monkeypatch):
    """(2) After the first execution finishes, the `finally`-discard must
    release the guard — a later, independent defensive exit for the SAME
    ticker must proceed normally, not be permanently blocked by a stale
    guard entry."""
    coord, position = _coordinator_with_watched_position()
    captured = await _capture_executed_order(coord)

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

    await coord._execute_order_from_monitor(_stop_loss_order())

    assert "005930" not in coord._defensive_exit_inflight, (
        "the guard must be released once the first execution completes"
    )

    # A fresh position (e.g. a new AGENT_AUTO fill) re-establishes the
    # ticker; a second, independent defensive exit must NOT be skipped.
    coord._add_position(
        ManagedPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=5,
            avg_price=72_500,
            current_price=68_000,
            stop_loss=68_000,
            stop_loss_mode=StopLossMode.AGENT_AUTO,
        )
    )
    result = await coord._close_position("005930")

    assert result is not None
    assert len(captured) == 2, "the retry must place a genuine second order, not be skipped"


async def test_reduce_delegating_to_close_does_not_self_deadlock_or_double_acquire():
    """(3) `_reduce_position`'s oversell clamp collapses into a delegated
    `_close_position` call for the SAME ticker within the SAME call stack.
    This must neither deadlock (ruling out `asyncio.Lock`, whose re-entrant
    acquire would deadlock here) nor silently self-skip via a naive
    double-acquire of the in-flight guard (which would return a spurious
    None instead of actually closing the position)."""
    coord, position = _coordinator_with_watched_position()  # quantity=10
    captured = await _capture_executed_order(coord)

    result = await asyncio.wait_for(
        coord._reduce_position("005930", 999),  # clamps to full close (>= held)
        timeout=2.0,
    )

    assert result is not None, (
        "the delegated close must actually execute, not be silently skipped "
        "by a self-collision with its own caller's guard"
    )
    assert len(captured) == 1, "exactly one order must be placed, not zero or two"
    assert "005930" not in coord._defensive_exit_inflight, (
        "the guard must be fully released after the delegated call completes"
    )


async def test_buy_path_unaffected_by_inflight_sell_guard():
    """(4) The SELL-direction in-flight guard must never block a BUY —
    `on_trade_approved`'s `is_sell_main` gate keeps the BUY/ADD path
    untouched even when this exact ticker already has a SELL exit in
    flight."""
    coord = _live_coordinator()
    captured = await _capture_executed_order(coord)

    # Simulate a SELL defensive exit already in flight for this ticker.
    coord._defensive_exit_inflight.add("005930")

    result = await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=1,
    )

    assert len(captured) == 1, "a BUY must never be blocked by the SELL-direction guard"
    assert captured[0].side == OrderSide.BUY
    assert result.quantity == 1


async def test_sell_main_path_skipped_while_defensive_exit_inflight(monkeypatch):
    """(4b) Symmetric guard check on `on_trade_approved`'s OWN SELL/REDUCE
    main path: a discussion-issued SELL for a ticker that already has a
    defensive exit in flight (e.g. RiskMonitor mid-stop-loss) must be
    skipped as a no-op — quantity 0, rejection rationale, zero orders."""
    coord = _live_coordinator()
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=OrderSide.SELL,
            quantity=1,
            entry_price=50_000,
            estimated_amount=50_000,
            position_pct=1.0,
            rationale="stub allocation",
            rebalance_orders=[],
        )
    )
    captured = await _capture_executed_order(coord)

    coord._defensive_exit_inflight.add("005930")

    result = await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=1,
    )

    assert captured == [], "no order may be placed while a defensive exit is in flight"
    assert result.quantity == 0
