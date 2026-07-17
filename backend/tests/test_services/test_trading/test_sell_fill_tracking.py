"""E1-1/E1-2/E1-3: SELL/REDUCE post-fill handling — tracking through reconciliation.

Real incident: the ledger recorded 41 sold shares against a real 155-share
broker sell (114주 missing) because fill-tracker registration was BUY-only
(F3 gate `if side == OrderSide.BUY and result.status in ("pending",
"partial")`) — the 30s ka10076 poll never learned about SELL remainders.

E1-1 closed the registration gap: the F3 BUY block is generalized into
`ExecutionCoordinator._track_unfilled`, a side-agnostic helper that
`on_trade_approved` now calls for BOTH the BUY path and the SELL/REDUCE
order-result. BUY behavior must stay byte-identical through the helper —
pinned here (test 4) AND by the pre-existing `test_f3_fill_tracking.py`
suite staying GREEN (the real evidence, per the task brief).

E1-2 closes the reconciliation gap: `_poll_tracked_fills`'s SELL delta branch
now reconciles the LOCAL position (decrement/remove) and records realized
P&L via `ExecutionCoordinator._apply_sell_position_delta` — the same helper
`_apply_sell_fill` composes onto (extracted from it, no behavior change
there; see the pre-existing `_apply_sell_fill` test coverage in
`test_trades_recording_wiring.py` / `test_r5_p1_execution_reliability.py`
staying GREEN as the byte-equivalence evidence). `register_fill_as_position`
stays BUY-only — a SELL delta must never flow through it (would double-count
a sell as a buy growing a position); this is now pinned by tests 5-7 as the
FULL post-fill behavior (record + reconcile + notify), not just a guard.

E1-3 extends the SAME registration to the three SELL order sites OUTSIDE
`on_trade_approved` — `_close_position` (defensive/user-initiated close),
`_reduce_position` (partial reduce), and `_execute_order_from_monitor`
(AGENT_AUTO stop-loss/take-profit) — via a new shared
`ExecutionCoordinator._register_unfilled_sell` helper that wraps
`_track_unfilled` (test section 8, below). The graph's independent
registration path (`agents/graph/kr_stock_nodes/execution.py`) gets the
symmetric SELL/REDUCE fix separately — see `test_kr_execution_fill_confirm.py`.
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.autonomy as autonomy_pkg
import services.storage_service as ss
from services.autonomy import GateDecision
from services.kiwoom.models import FilledOrder
from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import (
    AllocationPlan,
    ManagedPosition,
    OrderRequest,
    OrderResult,
    OrderSide,
    StopLossMode,
    TradingMode,
)
from services.trading.pending_order_tracker import TrackedOrder

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton
    (same pattern as test_f3_fill_tracking.py)."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _open_session() -> MarketSession:
    return MarketSession(
        is_open=True,
        current_time=datetime.now(),
        next_open=None,
        next_close=None,
        message="open",
    )


def _live_coordinator(side: OrderSide, quantity: int) -> ExecutionCoordinator:
    """A coordinator wired to execute immediately, with allocation quantity
    fixed via a mocked `calculate_allocation` — mirrors
    test_r5_p0_autotrade_safety._live_coordinator. The order's REAL side is
    driven by `on_trade_approved`'s own `_order_side_for_action(action)`, not
    by this mock's `.side` (see coordinator.py's `order = OrderRequest(...,
    side=side, ...)`), so the mock's side value here is cosmetic."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(return_value=_open_session())
    coord._refresh_account_info = AsyncMock()
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=side,
            quantity=quantity,
            entry_price=260_000,
            estimated_amount=quantity * 260_000,
            position_pct=1.0,
            rationale="stub allocation",
            rebalance_orders=[],
        )
    )
    return coord


def _stub_execute_order(coord, requested, filled, status, order_id, avg_price=260_000):
    async def _exec(order):
        return OrderResult(
            order_id=order_id,
            ticker=order.ticker,
            side=order.side,
            requested_quantity=requested,
            filled_quantity=filled,
            avg_price=avg_price,
            status=status,
        )

    coord._execute_order = _exec


# -------------------------------------------
# 1) SELL pending/partial registers with side="sell"
# -------------------------------------------


async def test_partial_sell_registers_tracked_order_with_sell_side(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=144)
    _stub_execute_order(coord, requested=144, filled=37, status="partial", order_id="SELL1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=144,
    )

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "sell"
    assert order.ord_no == "SELL1"
    assert order.total_quantity == 144
    assert order.filled_quantity == 37
    assert order.source_session_id == "s1"


# -------------------------------------------
# 2) SELL fully filled -> nothing registered
# -------------------------------------------


async def test_full_sell_does_not_register(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=144)
    _stub_execute_order(coord, requested=144, filled=144, status="filled", order_id="SELL2")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=144,
    )

    assert coord.fill_tracker.tracking() == []


# -------------------------------------------
# 3) REDUCE (partial exit) registers its own remainder too
# -------------------------------------------


async def test_partial_reduce_registers_tracked_order(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=50)
    _stub_execute_order(coord, requested=50, filled=10, status="partial", order_id="REDUCE1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="REDUCE",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=50,
    )

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "sell"
    assert order.total_quantity == 50
    assert order.filled_quantity == 10


# -------------------------------------------
# 4) BUY path through the shared helper stays unchanged — smoke-level pin;
#    full BUY coverage (incl. split parts) lives in test_f3_fill_tracking.py,
#    which staying GREEN is the byte-equivalence evidence for the refactor.
# -------------------------------------------


async def test_partial_buy_still_registers_with_buy_side(temp_storage):
    coord = _live_coordinator(OrderSide.BUY, quantity=144)
    _stub_execute_order(coord, requested=144, filled=37, status="partial", order_id="BUY1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=246_560,
        take_profit=289_440,
        risk_score=5,
        quantity_override=144,
    )

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "buy"
    assert order.stop_loss == 246_560
    assert order.take_profit == 289_440


# -------------------------------------------
# 5) _poll_tracked_fills SELL delta with NO local position to reconcile
#    (e.g. cleared by the reconciler, or a source that never locally tracked
#    it) — the position decrement is a no-op (warned), but everything else
#    (ledger record already happened above in the loop; notification here)
#    still fires, same as any other post-fill discovery. `sell` must still
#    NEVER flow into register_fill_as_position (would wrongly GROW a
#    position from a sell fill).
# -------------------------------------------


class _FakeKiwoomClient:
    def __init__(self, filled_orders):
        self._filled_orders = filled_orders
        self.calls = 0

    async def get_filled_orders(self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True):
        self.calls += 1
        return list(self._filled_orders)


def _filled(ord_no, qty, price, buy_sell_tp="매도"):
    return FilledOrder(
        ord_no=ord_no,
        stk_cd="005930",
        stk_nm="삼성전자",
        ccld_qty=qty,
        ccld_uv=price,
        ccld_amt=qty * price,
        ccld_dt="",
        ccld_tm="",
        buy_sell_tp=buy_sell_tp,
    )


def _tracked_sell_order(ord_no="SELL1", total=144, filled=0, **kw):
    base = dict(
        ord_no=ord_no,
        ticker="005930",
        stock_name="삼성전자",
        side="sell",
        total_quantity=total,
        filled_quantity=filled,
        filled_amount=filled * 260_000,
        trade_date=date.today().strftime("%Y%m%d"),
    )
    base.update(kw)
    return TrackedOrder(**base)


def _active_coordinator(kiwoom_client=None) -> ExecutionCoordinator:
    """A coordinator with persistence active, as a real start()ed session
    would have — mirrors test_trades_recording_wiring.py's helper."""
    coord = ExecutionCoordinator(kiwoom_client=kiwoom_client)
    coord._persistence_active = True
    return coord


async def test_poll_sell_delta_with_no_local_position_is_noop_but_still_notifies(temp_storage):
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("SELL1", 37, 260_000)])
    )
    coord.fill_tracker.register(_tracked_sell_order(ord_no="SELL1", total=144, filled=0))

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord.set_alert_callback(_capture_alert)

    await coord._poll_tracked_fills()

    # No local position existed, so nothing was opened/grown — the sell
    # fill did NOT flow into register_fill_as_position, and the decrement
    # was a no-op (no position to decrement).
    assert coord._state.positions == []
    # But the fill was still discovered and notified — E1-2's full handling
    # fires the same as a BUY post-fill would, regardless of whether a local
    # position existed to reconcile.
    assert len(alerts) == 1
    assert alerts[0].ticker == "005930"
    assert "매도" in alerts[0].message
    assert any(
        "사후 매도 체결" in a.message for a in coord._state.activity_log
    )
    # The delta WAS applied to the tracked order itself — apply_fills
    # already advanced filled_quantity regardless of local position state.
    order = coord.fill_tracker._orders["SELL1"]
    assert order.filled_quantity == 37


async def test_poll_guard_still_registers_buy_fill_as_position(temp_storage):
    """Guard regression check: the sell-only branch must not swallow BUY
    fills — they still flow through register_fill_as_position as before."""
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("BUY1", 48, 260_000, buy_sell_tp="매수")])
    )
    coord.fill_tracker.register(
        TrackedOrder(
            ord_no="BUY1",
            ticker="005930",
            stock_name="삼성전자",
            side="buy",
            total_quantity=48,
            filled_quantity=0,
            trade_date=date.today().strftime("%Y%m%d"),
        )
    )

    await coord._poll_tracked_fills()

    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 48


# -------------------------------------------
# 6) _poll_tracked_fills SELL delta WITH a local position — full E1-2
#    reconciliation: decrement/remove + realized P&L, on top of the ledger
#    record. Real-incident shape: 37 shares were already recorded/decremented
#    at order-placement time (via `_apply_sell_fill`, the existing SELL
#    choke point), the remaining 107 were tracked as a remainder, and this
#    poll tick discovers them — 37+107=144 must be the TRUE total, with no
#    double count (idempotent apply_fills diffing, already proven for BUY).
# -------------------------------------------


def _sell_order_request(session_id="s-exit", price=260_000) -> OrderRequest:
    return OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.SELL,
        quantity=144,
        price=price,
        session_id=session_id,
    )


def _sell_order_result(order_id="SELL1", filled=37, avg_price=260_000) -> OrderResult:
    return OrderResult(
        order_id=order_id,
        ticker="005930",
        side=OrderSide.SELL,
        requested_quantity=144,
        filled_quantity=filled,
        avg_price=avg_price,
        status="partial",
    )


async def test_poll_sell_delta_full_removal_sums_with_placement_fill_and_records_pnl(
    temp_storage,
):
    coord = _active_coordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("SELL1", 144, 260_000)])
    )
    coord._add_position(
        ManagedPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=144,
            avg_price=250_000,
            current_price=260_000,
            analysis_session_id="s-entry",
        )
    )

    # Order-placement time: 37 of 144 filled immediately — the REAL choke
    # point (`_apply_sell_fill`) records the ledger row AND decrements the
    # local position (144 -> 107), exactly like every other SELL caller.
    coord._apply_sell_fill(
        "005930", 37, order=_sell_order_request(), result=_sell_order_result(filled=37)
    )
    assert coord._state.positions[0].quantity == 107

    # The remainder (107) is what E1-1's _track_unfilled would have
    # registered — reproduced directly here since this test targets
    # _poll_tracked_fills's reconciliation in isolation.
    coord.fill_tracker.register(
        _tracked_sell_order(
            ord_no="SELL1", total=144, filled=37, source_session_id="s-exit"
        )
    )

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord.set_alert_callback(_capture_alert)

    from services.trading import trade_log

    await coord._poll_tracked_fills()
    await trade_log.wait_for_pending_trade_fill_writes()

    # Full position removal: 107 (remaining) - 107 (poll delta) = 0.
    assert coord._state.positions == []
    assert "005930" not in coord.risk_monitor._watching

    # SUM check — the placement-time fill (37) and the poll delta (107) are
    # two SEPARATE ledger rows that together equal the TRUE total (144), not
    # a double count of either portion.
    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 2
    assert sum(r["executed_quantity"] for r in rows) == 144

    # Realized P&L recorded for BOTH portions (37 then 107), same 37+107=144.
    pnl_rows = await temp_storage.get_kr_realized_pnl(stk_cd="005930")
    assert len(pnl_rows) == 2
    assert sum(r["quantity"] for r in pnl_rows) == 144
    for r in pnl_rows:
        assert r["entry_price"] == 250_000

    assert len(alerts) == 1
    assert "매도" in alerts[0].message

    # Idempotent re-poll: the tracked order already transitioned to FILLED
    # (144/144), so a same-tick re-run must not re-call the broker, re-
    # record, or re-notify — apply_fills's diff semantics apply to sell
    # exactly like they already do for buy.
    kiwoom_calls = coord._kiwoom.calls
    await coord._poll_tracked_fills()
    assert coord._kiwoom.calls == kiwoom_calls
    rows_after = await temp_storage.get_kr_stock_trades()
    assert len(rows_after) == 2
    assert len(alerts) == 1


async def test_poll_sell_delta_partial_reduce_keeps_watching_remainder(temp_storage):
    coord = _active_coordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("SELL2", 40, 260_000)])
    )
    coord._add_position(
        ManagedPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=200,
            avg_price=250_000,
            current_price=260_000,
            analysis_session_id="s-entry",
        )
    )
    coord.fill_tracker.register(
        _tracked_sell_order(ord_no="SELL2", total=100, filled=0, source_session_id="s-exit")
    )

    from services.trading import trade_log

    await coord._poll_tracked_fills()
    await trade_log.wait_for_pending_trade_fill_writes()

    # Partial reduce, not a full close — 200 - 40 = 160, still monitored.
    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 160
    assert "005930" in coord.risk_monitor._watching

    # The tracked order itself stays TRACKING — only 40 of its own 100 have
    # filled so far.
    order = coord.fill_tracker._orders["SELL2"]
    assert order.filled_quantity == 40
    assert coord.fill_tracker.tracking() != []

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    assert rows[0]["quantity"] == 100  # order.total_quantity
    assert rows[0]["executed_quantity"] == 40

    pnl_rows = await temp_storage.get_kr_realized_pnl(stk_cd="005930")
    assert len(pnl_rows) == 1
    assert pnl_rows[0]["quantity"] == 40
    assert pnl_rows[0]["entry_price"] == 250_000


# -------------------------------------------
# 8) E1-3 — the remaining SELL order sites (_close_position/_reduce_position/
#    _execute_order_from_monitor) each register their own unfilled remainder
#    too, via the shared `ExecutionCoordinator._register_unfilled_sell`
#    helper — closing the SAME registration gap E1-1 closed for
#    on_trade_approved's SELL/REDUCE path, but for the three sites that place
#    a SELL order OUTSIDE that entry-point (a defensive close, a partial
#    reduce, and an AGENT_AUTO stop-loss/take-profit trigger from
#    RiskMonitor). stop_loss/take_profit are always None on these — every
#    caller here is an EXIT, which carries no defense levels of its own
#    forward (mirrors the graph node's own SELL registration, E1-3).
# -------------------------------------------


def _coordinator_with_position(
    quantity=10,
    session_id="s-entry",
    risk_score=7,
    stop_loss_mode=StopLossMode.USER_APPROVAL,
):
    coord = ExecutionCoordinator(kiwoom_client=None)
    position = ManagedPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=quantity,
        avg_price=250_000,
        current_price=260_000,
        stop_loss_mode=stop_loss_mode,
        analysis_session_id=session_id,
        risk_score=risk_score,
    )
    coord._add_position(position)
    return coord, position


async def test_close_position_partial_fill_registers_sell_remainder(temp_storage):
    coord, position = _coordinator_with_position(
        quantity=8, session_id="s-close", risk_score=7
    )
    _stub_execute_order(coord, requested=8, filled=3, status="partial", order_id="CLOSE1")

    result = await coord._close_position("005930")

    assert result.filled_quantity == 3
    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "sell"
    assert order.ord_no == "CLOSE1"
    assert order.total_quantity == 8
    assert order.filled_quantity == 3
    assert order.source_session_id == "s-close"
    assert order.risk_score == 7
    assert order.stop_loss is None
    assert order.take_profit is None


async def test_close_position_full_fill_does_not_register(temp_storage):
    coord, position = _coordinator_with_position(quantity=8)
    _stub_execute_order(coord, requested=8, filled=8, status="filled", order_id="CLOSE2")

    result = await coord._close_position("005930")

    assert result.filled_quantity == 8
    assert coord.fill_tracker.tracking() == []


async def test_reduce_position_partial_fill_registers_sell_remainder(temp_storage):
    coord, position = _coordinator_with_position(
        quantity=50, session_id="s-reduce", risk_score=4
    )
    _stub_execute_order(coord, requested=20, filled=6, status="partial", order_id="REDUCE9")

    result = await coord._reduce_position("005930", 20)

    assert result.filled_quantity == 6
    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "sell"
    assert order.ord_no == "REDUCE9"
    assert order.total_quantity == 20
    assert order.filled_quantity == 6
    assert order.source_session_id == "s-reduce"
    assert order.risk_score == 4


async def test_reduce_position_delegated_full_close_registers_once_not_twice(temp_storage):
    """When the oversell clamp collapses a reduce into a full close,
    `_reduce_position` delegates to `_close_position` — which already
    registers its own remainder. `_reduce_position` must NOT register a
    second time for the same order."""
    coord, position = _coordinator_with_position(quantity=10, session_id="s-collapse")
    _stub_execute_order(coord, requested=10, filled=4, status="partial", order_id="COLLAPSE1")

    result = await coord._reduce_position("005930", 999)  # clamps to 10 -> full close

    assert result.filled_quantity == 4
    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    assert tracking[0].ord_no == "COLLAPSE1"


def _stop_loss_order(quantity=10, price=68_000) -> OrderRequest:
    return OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.SELL,
        quantity=quantity,
        price=price,
        reason="Stop-loss auto-execution",
    )


async def test_monitor_defensive_sell_partial_fill_registers_sell_remainder(
    temp_storage, monkeypatch
):
    coord, position = _coordinator_with_position(
        quantity=10,
        session_id="s-monitor",
        risk_score=5,
        stop_loss_mode=StopLossMode.AGENT_AUTO,
    )
    _stub_execute_order(coord, requested=10, filled=4, status="partial", order_id="MON1")

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

    await coord._execute_order_from_monitor(_stop_loss_order())

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "sell"
    assert order.ord_no == "MON1"
    assert order.total_quantity == 10
    assert order.filled_quantity == 4
    assert order.source_session_id == "s-monitor"
    assert order.risk_score == 5
    assert order.stop_loss is None
    assert order.take_profit is None


async def test_monitor_defensive_sell_full_fill_does_not_register(temp_storage, monkeypatch):
    coord, position = _coordinator_with_position(
        quantity=10, stop_loss_mode=StopLossMode.AGENT_AUTO
    )
    _stub_execute_order(coord, requested=10, filled=10, status="filled", order_id="MON2")

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

    await coord._execute_order_from_monitor(_stop_loss_order())

    assert coord.fill_tracker.tracking() == []


async def test_monitor_defensive_sell_gate_denied_does_not_register(temp_storage, monkeypatch):
    """A gate-denied defensive sell places nothing at all — no order, so
    nothing should be tracked either."""
    coord, position = _coordinator_with_position(
        quantity=10, stop_loss_mode=StopLossMode.AGENT_AUTO
    )
    captured = []

    async def _exec(order):
        captured.append(order)
        raise AssertionError("gate-denied sell must not place an order")

    coord._execute_order = _exec

    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="denied", check="market_mode")

    monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

    await coord._execute_order_from_monitor(_stop_loss_order())

    assert captured == []
    assert coord.fill_tracker.tracking() == []
