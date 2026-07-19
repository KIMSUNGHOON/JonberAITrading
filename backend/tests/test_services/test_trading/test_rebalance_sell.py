"""E1-4 (scope 1): rebalancing SELL — autonomy gate + ledger record +
position decrement + unfilled-remainder tracking.

Real gap: `on_trade_approved`'s rebalance loop (`allocation.rebalance_orders`,
produced by `PortfolioAgent._check_rebalancing_needed` to trim an UNRELATED
existing position and make room for the trade actually being approved)
placed the order and did NOTHING else — no autonomy gate (a system-computed
SELL of a position the human never explicitly approved trimming), no ledger
record, no local position decrement, no unfilled-remainder tracking. This is
the same category of gap E1-1/E1-2/E1-3 already closed for every OTHER
coordinator-level SELL site (`_close_position`/`_reduce_position`/
`_execute_order_from_monitor`) — this task closes it for the rebalance site
too, via the SAME choke points:

- `check_autonomy("kiwoom", action="SELL", ...)` — UNCONDITIONALLY, per item,
  mirroring `_execute_order_from_monitor`/`PositionManager._execute_close_
  position` (R5-P0 A2). A denial skips ONLY that rebalance item (continues
  the loop) and logs a rejection — it must NOT abort the primary trade below.
- `_apply_sell_fill` — records the ledger row and reconciles the local
  position (decrement/remove + realized P&L).
- `_register_unfilled_sell` — tracks a partial/unfilled remainder the same
  way every other SELL site does.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.autonomy as autonomy_pkg
import services.storage_service as ss
from services.autonomy import GateDecision
from services.trading import trade_log
from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import (
    ActivityType,
    AllocationPlan,
    ManagedPosition,
    OrderRequest,
    OrderResult,
    OrderSide,
    TradingMode,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton
    (same pattern as test_sell_fill_tracking.py / test_trades_recording_wiring.py)."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


async def _flush():
    await trade_log.wait_for_pending_trade_fill_writes()


def _open_session() -> MarketSession:
    return MarketSession(
        is_open=True,
        current_time=datetime.now(),
        next_open=None,
        next_close=None,
        message="open",
    )


def _rebalance_order(
    ticker="000660", stock_name="SK하이닉스", quantity=20, price=None
) -> OrderRequest:
    return OrderRequest(
        ticker=ticker,
        stock_name=stock_name,
        side=OrderSide.SELL,
        quantity=quantity,
        price=price,
        reason="Rebalancing to accommodate new position",
    )


def _coordinator_with_rebalance(
    rebalance_orders, main_quantity: int = 5
) -> ExecutionCoordinator:
    """A coordinator wired to execute a main BUY trade immediately (ACTIVE +
    market open), with `rebalance_orders` attached to the mocked allocation,
    and persistence active as a real start()ed session would have."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._persistence_active = True
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(return_value=_open_session())
    coord._refresh_account_info = AsyncMock()
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=OrderSide.BUY,
            quantity=main_quantity,
            entry_price=70_000,
            estimated_amount=main_quantity * 70_000,
            position_pct=5.0,
            rationale="stub main allocation",
            rebalance_orders=rebalance_orders,
        )
    )
    return coord


def _add_position(
    coord: ExecutionCoordinator,
    ticker: str,
    stock_name: str,
    quantity: int,
    avg_price: float = 100_000,
    session_id: str = "s-rebal",
    risk_score: int = 6,
) -> ManagedPosition:
    position = ManagedPosition(
        ticker=ticker,
        stock_name=stock_name,
        quantity=quantity,
        avg_price=avg_price,
        current_price=avg_price,
        analysis_session_id=session_id,
        risk_score=risk_score,
    )
    coord._add_position(position)
    return position


async def _approve_main_buy(coord: ExecutionCoordinator, session_id: str = "sess-main"):
    return await coord.on_trade_approved(
        session_id=session_id,
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=70_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )


def _allow_gate(monkeypatch):
    async def _gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", _gate)


# -------------------------------------------
# 1) Gate denied -> skip that item, loop continues, position untouched
# -------------------------------------------


async def test_rebalance_gate_denied_skips_order_and_continues_main_trade(
    temp_storage, monkeypatch
):
    coord = _coordinator_with_rebalance([_rebalance_order(quantity=20)])
    _add_position(coord, "000660", "SK하이닉스", quantity=50, session_id="s-rebal")

    placed = []

    async def _exec(order):
        placed.append(order.ticker)
        return OrderResult(
            order_id="MAIN1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    async def deny_gate(market, **kwargs):
        return GateDecision(
            allowed=False, reason="daily loss >= limit", check="daily_loss_breaker"
        )

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

    await _approve_main_buy(coord)

    # Rebalance order must NEVER have been placed at the broker.
    assert "000660" not in placed
    # The primary (human-approved) trade still executes — denial doesn't abort.
    assert placed == ["005930"]
    # Position untouched.
    position = next(p for p in coord._state.positions if p.ticker == "000660")
    assert position.quantity == 50
    # Rejection logged against the rebalance ticker specifically.
    rejections = [
        a
        for a in coord._state.activity_log
        if a.activity_type == ActivityType.TRADE_REJECTED and a.ticker == "000660"
    ]
    assert len(rejections) == 1
    assert "daily loss" in rejections[0].message.lower() or "daily_loss" in rejections[0].message


# -------------------------------------------
# 2) Gate allowed + partial position reduce -> ledger row + decrement
# -------------------------------------------


async def test_rebalance_gate_allowed_reduces_position_and_records_ledger(
    temp_storage, monkeypatch
):
    coord = _coordinator_with_rebalance([_rebalance_order(quantity=20)])
    _add_position(coord, "000660", "SK하이닉스", quantity=50, session_id="s-rebal")

    async def _exec(order):
        if order.ticker == "000660":
            return OrderResult(
                order_id="REBAL1",
                ticker=order.ticker,
                side=order.side,
                requested_quantity=20,
                filled_quantity=20,
                avg_price=105_000,
                status="filled",
            )
        return OrderResult(
            order_id="MAIN2",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec
    _allow_gate(monkeypatch)

    await _approve_main_buy(coord)
    await _flush()

    position = next(p for p in coord._state.positions if p.ticker == "000660")
    assert position.quantity == 30  # 50 - 20

    rows = await temp_storage.get_kr_stock_trades()
    sell_rows = [r for r in rows if r["stk_cd"] == "000660"]
    assert len(sell_rows) == 1
    assert sell_rows[0]["side"] == "sell"
    assert sell_rows[0]["executed_quantity"] == 20
    assert sell_rows[0]["quantity"] == 20
    assert sell_rows[0]["status"] == "completed"
    assert sell_rows[0]["order_id"] == "REBAL1"


# -------------------------------------------
# 3) Gate allowed + fill == full position -> position removed entirely
# -------------------------------------------


async def test_rebalance_full_fill_removes_position_entirely(temp_storage, monkeypatch):
    coord = _coordinator_with_rebalance([_rebalance_order(quantity=20)])
    _add_position(coord, "000660", "SK하이닉스", quantity=20, session_id="s-rebal")

    async def _exec(order):
        if order.ticker == "000660":
            return OrderResult(
                order_id="REBAL2",
                ticker=order.ticker,
                side=order.side,
                requested_quantity=20,
                filled_quantity=20,
                avg_price=105_000,
                status="filled",
            )
        return OrderResult(
            order_id="MAIN3",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec
    _allow_gate(monkeypatch)

    await _approve_main_buy(coord)

    assert all(p.ticker != "000660" for p in coord._state.positions)


# -------------------------------------------
# 4) Gate allowed + partial fill -> unfilled remainder tracked
# -------------------------------------------


async def test_rebalance_partial_fill_registers_unfilled_remainder(temp_storage, monkeypatch):
    coord = _coordinator_with_rebalance([_rebalance_order(quantity=20, price=104_000)])
    _add_position(coord, "000660", "SK하이닉스", quantity=50, session_id="s-rebal", risk_score=6)

    async def _exec(order):
        if order.ticker == "000660":
            return OrderResult(
                order_id="REBAL3",
                ticker=order.ticker,
                side=order.side,
                requested_quantity=20,
                filled_quantity=12,
                avg_price=105_000,
                status="partial",
            )
        return OrderResult(
            order_id="MAIN4",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec
    _allow_gate(monkeypatch)

    await _approve_main_buy(coord)

    position = next(p for p in coord._state.positions if p.ticker == "000660")
    assert position.quantity == 38  # 50 - 12

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.ticker == "000660"
    assert order.side == "sell"
    assert order.ord_no == "REBAL3"
    assert order.total_quantity == 20
    assert order.filled_quantity == 12
    # I1 (final-review fix, spec D2): source_session_id is the placed
    # rebalance order's own session_id -- `_rebalance_order()`/
    # portfolio_agent's rebalance orders never set OrderRequest.session_id
    # (a system-computed rebalance sell has no upstream decision to cite),
    # so this is None, NOT the (unrelated) position's entry-side
    # analysis_session_id ("s-rebal").
    assert order.source_session_id is None
    assert order.risk_score == 6
    assert order.stop_loss is None
    assert order.take_profit is None


# -------------------------------------------
# 5) Multiple rebalance items: one denied, one allowed -> loop is NOT aborted
# -------------------------------------------


async def test_rebalance_multiple_orders_one_denied_one_allowed(temp_storage, monkeypatch):
    orders = [
        _rebalance_order(ticker="000660", stock_name="SK하이닉스", quantity=10),
        _rebalance_order(ticker="035420", stock_name="NAVER", quantity=5),
    ]
    coord = _coordinator_with_rebalance(orders)
    _add_position(coord, "000660", "SK하이닉스", quantity=30, session_id="s1")
    _add_position(coord, "035420", "NAVER", quantity=15, session_id="s2")

    placed = []

    async def _exec(order):
        placed.append(order.ticker)
        if order.ticker == "000660":
            raise AssertionError("gate-denied rebalance sell must not place an order")
        return OrderResult(
            order_id=f"ORD-{order.ticker}",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=200_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    async def selective_gate(market, **kwargs):
        if kwargs.get("quantity") == 10:  # the 000660 item
            return GateDecision(allowed=False, reason="denied", check="market_mode")
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", selective_gate)

    await _approve_main_buy(coord)

    assert "000660" not in placed
    assert placed == ["035420", "005930"]

    pos_000660 = next(p for p in coord._state.positions if p.ticker == "000660")
    assert pos_000660.quantity == 30  # untouched

    pos_035420 = next(p for p in coord._state.positions if p.ticker == "035420")
    assert pos_035420.quantity == 10  # 15 - 5


# -------------------------------------------
# 6) No rebalance orders -> no gate calls at all, existing behavior untouched
# -------------------------------------------


async def test_no_rebalance_orders_never_calls_gate(temp_storage, monkeypatch):
    coord = _coordinator_with_rebalance([])

    gate_calls = []

    async def recording_gate(market, **kwargs):
        gate_calls.append(kwargs)
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", recording_gate)

    async def _exec(order):
        return OrderResult(
            order_id="MAIN5",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    await _approve_main_buy(coord)

    assert gate_calls == []



# -------------------------------------------
# N1 (final-review fix, S final): rebalance-sell in-flight guard — the 6th
# SELL entry point. `on_trade_approved`'s rebalance loop above places a
# SYSTEM-computed SELL of an UNRELATED position to free up room for the
# trade actually approved. S-2/S-3 wired `_acquire_defensive_exit_guard`/
# `_release_defensive_exit_guard` into 5 other SELL entry points
# (`_execute_order_from_monitor`/`_close_position`/`_reduce_position`/
# `on_trade_approved`'s own SELL/REDUCE main path/`handle_alert_action`'s
# EXECUTE_STOP_LOSS/EXECUTE_TAKE_PROFIT) but never this rebalance loop —
# a BUY approval that triggers a rebalance sell of ticker X can race a
# concurrent defensive exit (RiskMonitor/PositionManager) of the SAME
# ticker X, producing a real double full-liquidation exactly like the
# race the other 5 sites already guard against (see `_close_position`'s
# docstring for the full dual-engine race rationale).
# -------------------------------------------


async def test_rebalance_sell_skipped_while_target_ticker_inflight(
    temp_storage, monkeypatch
):
    """(1) The rebalance ticker already has a defensive exit in flight (e.g.
    RiskMonitor mid-stop-loss for 000660) at the moment a BUY approval's
    rebalance loop reaches it. Pre-fix (no guard on this loop): the
    rebalance sell places a SECOND full-size order for the same ticker — a
    real double-liquidation. Post-fix: this rebalance item is skipped as a
    no-op (zero orders for 000660), logged as
    `rebalance_sell_skipped_inflight`, while the primary BUY and any OTHER
    rebalance item still proceed untouched."""
    coord = _coordinator_with_rebalance([_rebalance_order(quantity=20)])
    _add_position(coord, "000660", "SK하이닉스", quantity=50, session_id="s-rebal")

    placed = []

    async def _exec(order):
        placed.append(order.ticker)
        return OrderResult(
            order_id="MAIN-N1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec
    _allow_gate(monkeypatch)

    # Simulate a concurrent defensive exit (e.g. RiskMonitor's AGENT_AUTO
    # tick) already owning 000660's SELL exit.
    coord._defensive_exit_inflight.add("000660")

    await _approve_main_buy(coord)

    # The rebalance sell for the in-flight ticker must NEVER reach the
    # broker -- a duplicate full liquidation is exactly what this guards.
    assert "000660" not in placed
    # The primary (human-approved) trade still executes -- the in-flight
    # guard denial on an UNRELATED rebalance item must not abort it.
    assert placed == ["005930"]
    # Position untouched by this (skipped) rebalance sell.
    position = next(p for p in coord._state.positions if p.ticker == "000660")
    assert position.quantity == 50
    # Skip logged against the rebalance ticker specifically.
    rejections = [
        a
        for a in coord._state.activity_log
        if a.activity_type == ActivityType.TRADE_REJECTED and a.ticker == "000660"
    ]
    assert len(rejections) == 1
    assert "in flight" in rejections[0].message.lower()


async def test_rebalance_sell_not_inflight_executes_and_releases_guard(
    temp_storage, monkeypatch
):
    """(2) Not in flight: the rebalance sell executes normally (unchanged
    behavior) AND the guard is released afterward -- a later, independent
    rebalance/defensive exit for the SAME ticker must not be permanently
    blocked by a stale guard entry (mirrors the S-2 release-allows-retry
    contract for the other 5 guarded sites)."""
    coord = _coordinator_with_rebalance([_rebalance_order(quantity=20)])
    _add_position(coord, "000660", "SK하이닉스", quantity=50, session_id="s-rebal")

    async def _exec(order):
        if order.ticker == "000660":
            return OrderResult(
                order_id="REBAL-N1",
                ticker=order.ticker,
                side=order.side,
                requested_quantity=20,
                filled_quantity=20,
                avg_price=105_000,
                status="filled",
            )
        return OrderResult(
            order_id="MAIN-N1b",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec
    _allow_gate(monkeypatch)

    await _approve_main_buy(coord)
    await _flush()

    # The rebalance sell actually executed (unaffected by the new guard
    # when nothing else holds it).
    position = next(p for p in coord._state.positions if p.ticker == "000660")
    assert position.quantity == 30  # 50 - 20

    # Guard released -- re-entrant for a future rebalance/defensive exit.
    assert "000660" not in coord._defensive_exit_inflight
    assert coord._acquire_defensive_exit_guard("000660") is True
    coord._defensive_exit_inflight.discard("000660")  # cleanup


async def test_rebalance_sell_releases_guard_on_exception(temp_storage, monkeypatch):
    """(3) An exception during the rebalance order's own execution must
    still release the in-flight guard via `finally` -- a raised exception
    can never leave a ticker permanently stuck as "in flight" (same
    contract `_release_defensive_exit_guard`'s docstring promises for
    every other guarded SELL site)."""
    coord = _coordinator_with_rebalance([_rebalance_order(quantity=20)])
    _add_position(coord, "000660", "SK하이닉스", quantity=50, session_id="s-rebal")

    async def _exec(order):
        if order.ticker == "000660":
            raise RuntimeError("simulated broker failure")
        return OrderResult(
            order_id="MAIN-N1c",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec
    _allow_gate(monkeypatch)

    with pytest.raises(RuntimeError, match="simulated broker failure"):
        await _approve_main_buy(coord)

    assert "000660" not in coord._defensive_exit_inflight, (
        "the guard must be released even when the rebalance order's own "
        "execution raises"
    )
