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
    OrderType,
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
    # I1 (final-review fix, spec D2): source_session_id now comes from the
    # PLACED ORDER's own session_id (the exit's decision_id, threaded via
    # `_close_position(decision_id=...)`), NOT the position's entry-side
    # `analysis_session_id` ("s-close" here) -- this call passes no
    # decision_id (the user-initiated-close/mechanical shape), which
    # correctly has NO upstream decision to cite. See
    # test_close_position_with_decision_id_registers_sell_remainder_with_
    # decision_id below for the discussion-driven-exit case, where this
    # field correctly carries the EXIT decision id instead.
    assert order.source_session_id is None
    assert order.risk_score == 7
    assert order.stop_loss is None
    assert order.take_profit is None


async def test_close_position_with_decision_id_registers_sell_remainder_with_decision_id(
    temp_storage,
):
    """I1 regression: a discussion-driven exit (decision_id threaded into
    `_close_position`) must register the fill-tracker remainder's
    `source_session_id` as the EXIT decision id -- NOT the position's entry
    `analysis_session_id` ("s-entry" here, deliberately distinct from the
    decision_id, so a pre-fix implementation that reads
    `position.analysis_session_id` fails this assertion). This is the
    post-fill exit-decision_id/ledger-row lineage the poll path
    (`_poll_tracked_fills` -> `_apply_sell_position_delta` ->
    `record_kr_realized_pnl(exit_decision_id=...)`) ultimately reads."""
    coord, position = _coordinator_with_position(
        quantity=8, session_id="s-entry", risk_score=7
    )
    _stub_execute_order(coord, requested=8, filled=3, status="partial", order_id="CLOSE-DEC1")

    result = await coord._close_position("005930", decision_id="dec-close-discuss-1")

    assert result.filled_quantity == 3
    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.source_session_id == "dec-close-discuss-1"
    assert order.source_session_id != "s-entry"


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
    # I1: source_session_id is the placed order's own session_id (None here
    # -- no decision_id was threaded into this _reduce_position call), NOT
    # the position's entry-side analysis_session_id ("s-reduce").
    assert order.source_session_id is None
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
    # I1: source_session_id is the placed order's own session_id.
    # `_stop_loss_order()` (RiskMonitor's real construction, mirrored) never
    # sets OrderRequest.session_id -- a mechanical stop-loss/take-profit has
    # no upstream decision to cite (spec D2) -- so this is None, NOT the
    # position's entry-side analysis_session_id ("s-monitor").
    assert order.source_session_id is None
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

# -------------------------------------------
# 9) E1-4 (scope 2) — on_trade_approved's SELL/REDUCE branch now decrements
#    the LOCAL position too, not just the ledger. Previously this branch
#    (the P1-1 PART 2 fix) called `record_trade_fill` directly and stopped
#    there — `_state.positions` was never touched, so a fill placed through
#    THIS entry point (agent-chat direct decisions + queue replays) left a
#    phantom leftover position exactly the size of the fill; only a LATER
#    poll delta (E1-2, section 6/7 above) would shave anything off, never the
#    placement-time fill itself. It now routes through `_apply_sell_fill`
#    (the SAME choke point every other SELL site already uses), which
#    records the ledger row AND reconciles the position (decrement/remove +
#    realized P&L) in one call — replacing the direct `record_trade_fill`
#    call rather than adding a second one (double-recording the same fill).
# -------------------------------------------


def _entry_position(quantity=30) -> ManagedPosition:
    return ManagedPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=quantity,
        avg_price=250_000,
        current_price=260_000,
        analysis_session_id="s-entry",
        risk_score=6,
    )


async def test_on_trade_approved_sell_decrements_local_position(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=10)
    coord._add_position(_entry_position(quantity=30))
    _stub_execute_order(coord, requested=10, filled=10, status="filled", order_id="SELL-DEC1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    position = next((p for p in coord._state.positions if p.ticker == "005930"), None)
    assert position is not None
    assert position.quantity == 20  # 30 - 10


async def test_on_trade_approved_reduce_partial_fill_decrements_by_actual_fill(temp_storage):
    """A REDUCE that only partially fills at the broker must decrement by the
    ACTUAL filled amount, not the requested one."""
    coord = _live_coordinator(OrderSide.SELL, quantity=10)
    coord._add_position(_entry_position(quantity=30))
    _stub_execute_order(coord, requested=10, filled=4, status="partial", order_id="SELL-DEC2")

    await coord.on_trade_approved(
        session_id="s2",
        ticker="005930",
        stock_name="삼성전자",
        action="REDUCE",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    position = next((p for p in coord._state.positions if p.ticker == "005930"), None)
    assert position is not None
    assert position.quantity == 26  # 30 - 4


async def test_on_trade_approved_sell_full_fill_removes_position_entirely(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=15)
    coord._add_position(_entry_position(quantity=15))
    _stub_execute_order(coord, requested=15, filled=15, status="filled", order_id="SELL-DEC3")

    await coord.on_trade_approved(
        session_id="s3",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    assert all(p.ticker != "005930" for p in coord._state.positions)
    assert "005930" not in coord.risk_monitor._watching


async def test_on_trade_approved_sell_records_realized_pnl_when_persistence_active(
    temp_storage,
):
    """Realized P&L, gated by `_persistence_active` like the ledger write,
    is now recorded too — previously the direct `record_trade_fill` call
    never touched `record_kr_realized_pnl` at all."""
    coord = _live_coordinator(OrderSide.SELL, quantity=10)
    coord._persistence_active = True
    coord._add_position(_entry_position(quantity=30))
    _stub_execute_order(
        coord, requested=10, filled=10, status="filled", order_id="SELL-DEC4", avg_price=260_000
    )

    await coord.on_trade_approved(
        session_id="s4",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    from services.trading import trade_log

    await trade_log.wait_for_pending_trade_fill_writes()

    pnl_rows = await temp_storage.get_kr_realized_pnl(stk_cd="005930")
    assert len(pnl_rows) == 1
    assert pnl_rows[0]["quantity"] == 10
    assert pnl_rows[0]["entry_price"] == 250_000
    assert pnl_rows[0]["exit_price"] == 260_000

    # Ledger row is STILL recorded exactly once (no double-count from routing
    # through _apply_sell_fill instead of the old direct record_trade_fill).
    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    assert rows[0]["side"] == "sell"
    assert rows[0]["executed_quantity"] == 10


async def test_on_trade_approved_sell_no_local_position_still_records_ledger_only(
    temp_storage,
):
    """No pre-existing local position (e.g. a stray SELL for a ticker this
    coordinator never tracked) must still record the ledger row — same as
    before this change — but skip the decrement/P&L as a no-op, not raise."""
    coord = _live_coordinator(OrderSide.SELL, quantity=10)
    coord._persistence_active = True
    _stub_execute_order(coord, requested=10, filled=10, status="filled", order_id="SELL-DEC5")

    await coord.on_trade_approved(
        session_id="s5",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    from services.trading import trade_log

    await trade_log.wait_for_pending_trade_fill_writes()

    assert coord._state.positions == []
    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    assert rows[0]["executed_quantity"] == 10



# -------------------------------------------
# 10) L2 (decision lineage restoration) — an optional decision_id parameter
#     threads into OrderRequest.session_id for the three bare-OrderRequest
#     sites named in the L2 brief (spec "끊김 A"): _close_position,
#     _reduce_position, and _add_to_position. Default None keeps every
#     EXISTING call site above (all of section 8/9, none of which pass
#     decision_id) byte-for-byte unchanged — pinned directly here by
#     capturing the actual OrderRequest _execute_order receives and
#     asserting .session_id is None when the parameter is omitted.
#     risk_monitor._execute_stop_loss/_execute_take_profit,
#     handle_alert_action, and portfolio_agent's rebalance orders are
#     UNCHANGED (spec D2 — mechanical/user/system exits stay NULL,
#     commented in place at each OrderRequest construction).
# -------------------------------------------


def _stub_execute_order_capturing(coord, filled, status, order_id, avg_price=260_000):
    """Like `_stub_execute_order`, but also returns the list of OrderRequest
    objects `_execute_order` was actually invoked with, so a test can assert
    on request-side fields (e.g. `session_id`) the returned OrderResult
    doesn't carry."""
    captured: list = []

    async def _exec(order):
        captured.append(order)
        return OrderResult(
            order_id=order_id,
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=filled,
            avg_price=avg_price,
            status=status,
        )

    coord._execute_order = _exec
    return captured


async def test_close_position_threads_decision_id_into_order_session_id(temp_storage):
    coord, position = _coordinator_with_position(quantity=8)
    captured = _stub_execute_order_capturing(coord, filled=8, status="filled", order_id="CLOSE-D1")

    await coord._close_position("005930", decision_id="dec-close-1")

    assert captured[0].session_id == "dec-close-1"


async def test_close_position_decision_id_defaults_to_none(temp_storage):
    """Step 1 test 4: the existing call shape (no decision_id argument) is
    byte-for-byte unchanged — session_id stays None."""
    coord, position = _coordinator_with_position(quantity=8)
    captured = _stub_execute_order_capturing(coord, filled=8, status="filled", order_id="CLOSE-D2")

    await coord._close_position("005930")

    assert captured[0].session_id is None


async def test_reduce_position_threads_decision_id_into_order_session_id(temp_storage):
    coord, position = _coordinator_with_position(quantity=50)
    captured = _stub_execute_order_capturing(coord, filled=6, status="partial", order_id="REDUCE-D1")

    await coord._reduce_position("005930", 20, decision_id="dec-reduce-1")

    assert captured[0].session_id == "dec-reduce-1"


async def test_reduce_position_decision_id_defaults_to_none(temp_storage):
    coord, position = _coordinator_with_position(quantity=50)
    captured = _stub_execute_order_capturing(coord, filled=6, status="partial", order_id="REDUCE-D2")

    await coord._reduce_position("005930", 20)

    assert captured[0].session_id is None


async def test_reduce_position_delegated_full_close_threads_decision_id(temp_storage):
    """The oversell-clamp delegation to `_close_position` must forward
    `decision_id` too, not silently drop it on the collapsed-to-full-close
    path."""
    coord, position = _coordinator_with_position(quantity=10)
    captured = _stub_execute_order_capturing(
        coord, filled=4, status="partial", order_id="COLLAPSE-D1"
    )

    await coord._reduce_position("005930", 999, decision_id="dec-collapse-1")  # clamps to full close

    assert captured[0].session_id == "dec-collapse-1"


async def test_add_to_position_threads_decision_id_into_order_session_id(temp_storage):
    coord, position = _coordinator_with_position(quantity=20)
    captured = _stub_execute_order_capturing(coord, filled=5, status="filled", order_id="ADD-D1")

    await coord._add_to_position("005930", 5, decision_id="dec-add-1")

    assert captured[0].session_id == "dec-add-1"


async def test_add_to_position_decision_id_defaults_to_none(temp_storage):
    """Existing caller (PositionManager._execute_add_position) calls
    `_add_to_position(ticker, quantity)` positionally with no decision_id —
    must stay session_id=None."""
    coord, position = _coordinator_with_position(quantity=20)
    captured = _stub_execute_order_capturing(coord, filled=5, status="filled", order_id="ADD-D2")

    await coord._add_to_position("005930", 5)

    assert captured[0].session_id is None



# -------------------------------------------
# 11) S-3 (survival discipline) — defensive exits submit MARKET orders, not
#     LIMIT. `_close_position`/`_reduce_position` previously left
#     OrderRequest.order_type at its default (`OrderType.LIMIT`, models.py)
#     submitted AT the position's current_price — in a gap/crash a LIMIT
#     order records a fill at that (favorable) price instead of the worse
#     real fill (same rationale as risk_monitor.py's P2-4 fix for
#     `_execute_stop_loss`/`_execute_take_profit`, now extended to these
#     coordinator-level sites). `on_trade_approved`'s own SELL/REDUCE main
#     order gets the same treatment; BUY/ADD stays LIMIT — the global
#     invariant (entry BUY/ADD LIMIT, s-global-constraints.md) is untouched
#     by this switch.
#     Spec: docs/superpowers/specs/2026-07-19-survival-discipline-design.md
#     §2 S-3.
# -------------------------------------------


async def test_close_position_submits_market_order(temp_storage):
    coord, position = _coordinator_with_position(quantity=8)
    captured = _stub_execute_order_capturing(
        coord, filled=8, status="filled", order_id="MKT-CLOSE1"
    )

    await coord._close_position("005930")

    assert captured[0].order_type == OrderType.MARKET


async def test_reduce_position_submits_market_order(temp_storage):
    coord, position = _coordinator_with_position(quantity=50)
    captured = _stub_execute_order_capturing(
        coord, filled=6, status="partial", order_id="MKT-REDUCE1"
    )

    await coord._reduce_position("005930", 20)

    assert captured[0].order_type == OrderType.MARKET


async def test_reduce_position_delegated_full_close_submits_market_order(temp_storage):
    """The oversell-clamp delegation into `_close_position` must also be
    MARKET, not silently fall back to LIMIT on the collapsed-to-full-close
    path."""
    coord, position = _coordinator_with_position(quantity=10)
    captured = _stub_execute_order_capturing(
        coord, filled=4, status="partial", order_id="MKT-COLLAPSE1"
    )

    await coord._reduce_position("005930", 999)  # clamps to full close

    assert captured[0].order_type == OrderType.MARKET


async def test_on_trade_approved_sell_main_order_submits_market(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=10)
    coord._add_position(_entry_position(quantity=30))
    captured = _stub_execute_order_capturing(
        coord, filled=10, status="filled", order_id="MKT-SELL1"
    )

    await coord.on_trade_approved(
        session_id="s-mkt1",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    assert captured[0].order_type == OrderType.MARKET


async def test_on_trade_approved_reduce_main_order_submits_market(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=10)
    coord._add_position(_entry_position(quantity=30))
    captured = _stub_execute_order_capturing(
        coord, filled=10, status="filled", order_id="MKT-REDUCE-MAIN1"
    )

    await coord.on_trade_approved(
        session_id="s-mkt2",
        ticker="005930",
        stock_name="삼성전자",
        action="REDUCE",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    assert captured[0].order_type == OrderType.MARKET


async def test_on_trade_approved_buy_main_order_stays_limit(temp_storage):
    """Pin: BUY entries must stay LIMIT — the global invariant (entry
    BUY/ADD LIMIT) is untouched by the S-3 defensive-exit MARKET switch."""
    coord = _live_coordinator(OrderSide.BUY, quantity=10)
    captured = _stub_execute_order_capturing(
        coord, filled=10, status="filled", order_id="MKT-BUY1"
    )

    await coord.on_trade_approved(
        session_id="s-mkt3",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    assert captured[0].order_type == OrderType.LIMIT


async def test_on_trade_approved_add_main_order_stays_limit(temp_storage):
    """Pin: ADD entries must stay LIMIT too — same invariant as BUY."""
    coord = _live_coordinator(OrderSide.BUY, quantity=10)
    captured = _stub_execute_order_capturing(
        coord, filled=10, status="filled", order_id="MKT-ADD1"
    )

    await coord.on_trade_approved(
        session_id="s-mkt4",
        ticker="005930",
        stock_name="삼성전자",
        action="ADD",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )

    assert captured[0].order_type == OrderType.LIMIT


# -------------------------------------------
# 12) Task 1 (dual-engine removal symmetry) — `_apply_sell_position_delta`
#     mirrors its coordinator-side removal/decrement into the agent-chat
#     PositionManager via `mirror_sell_to_position_manager`, closing the
#     gap where a coordinator-path SELL left a stale position in the PM
#     (coordinator showed 0, PM count 1) until a manual /positions/sync.
# -------------------------------------------


async def test_apply_sell_position_delta_full_close_mirrors_pm_remove(temp_storage):
    """전량 SELL → coordinator _remove_position + mirror(ticker, 0)."""
    from unittest.mock import patch

    coord, position = _coordinator_with_position(quantity=60)

    with patch("services.trading.coordinator.mirror_sell_to_position_manager") as mir:
        coord._apply_sell_position_delta("005930", 60, avg_price=None)

    assert not any(p.ticker == "005930" for p in coord._state.positions)  # coordinator 제거
    mir.assert_called_once_with("005930", 0)


async def test_apply_sell_position_delta_partial_mirrors_pm_remaining(temp_storage):
    """부분 SELL → coordinator 잔량 차감 + mirror(ticker, remaining)."""
    from unittest.mock import patch

    coord, position = _coordinator_with_position(quantity=60)

    with patch("services.trading.coordinator.mirror_sell_to_position_manager") as mir:
        coord._apply_sell_position_delta("005930", 25, avg_price=None)

    pos = next(p for p in coord._state.positions if p.ticker == "005930")
    assert pos.quantity == 35  # 60-25
    mir.assert_called_once_with("005930", 35)
