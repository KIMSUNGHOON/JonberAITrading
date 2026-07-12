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

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.autonomy as autonomy_pkg
from services.autonomy import GateDecision
from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import (
    AllocationPlan,
    OrderResult,
    OrderSide,
    QueueStatus,
    TradingMode,
)


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

    async def _close(ticker):
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

    async def _close(ticker):
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
