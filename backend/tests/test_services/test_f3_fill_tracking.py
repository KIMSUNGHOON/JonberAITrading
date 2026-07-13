"""F3 t4: coordinator integration of PendingOrderTracker (registration, 30s
poll, market-close expiry, blob persistence, queue post-fill annotation).

Real 2026-07-13 live gap: a BUY that didn't fill at placement time (limit
below market) was dropped entirely — the coordinator only ever registered a
position on the FILLED portion, so a later broker-side fill went unwatched by
every defense engine. `ExecutionCoordinator.fill_tracker` (a
`PendingOrderTracker`) closes that gap: `on_trade_approved` registers any
pending/partial BUY remainder, the existing 30s queue-scheduler tick polls
ka10076 for post-fills, the market open→closed edge expires anything still
unfilled, and both round-trip through the R5-P1 blob.

Fixture pattern follows `test_r5_p1_execution_reliability.py`: `temp_storage`
wires an isolated SQLite into the `get_storage_service()` singleton;
`_stub_market`/`_FakeKiwoomClient`/`_filled` are the same shapes used there.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import services.storage_service as ss
from services.kiwoom.models import FilledOrder, OrderResponse
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import (
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    StopLossMode,
    TradingMode,
)
from services.trading.order_agent import OrderAgent
from services.trading.pending_order_tracker import TrackedOrder, TrackedOrderStatus

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _stub_market(coord, is_open):
    coord._market_hours.get_market_session = lambda market: SimpleNamespace(
        is_open=is_open, message=""
    )


def _stub_execute_order(coord, filled_quantity, status, order_id="ORD1", avg_price=None):
    async def _exec(order):
        return OrderResult(
            order_id=order_id,
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=filled_quantity,
            avg_price=avg_price if avg_price is not None else (order.price or 0),
            status=status,
        )

    coord._execute_order = _exec


def _ready_coordinator() -> ExecutionCoordinator:
    """A coordinator ready to execute on_trade_approved immediately (not queue)."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    _stub_market(coord, is_open=True)
    return coord


class _FakeKiwoomClient:
    """Minimal Kiwoom client: reports fills from a fixed ka10076 snapshot."""

    def __init__(self, filled_orders=None):
        self._filled_orders = filled_orders if filled_orders is not None else []
        self.calls = 0

    async def get_filled_orders(
        self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True
    ):
        self.calls += 1
        return list(self._filled_orders)


def _filled(ord_no, qty, price):
    return FilledOrder(
        ord_no=ord_no,
        stk_cd="005930",
        stk_nm="삼성전자",
        ccld_qty=qty,
        ccld_uv=price,
        ccld_amt=qty * price,
        ccld_dt="",
        ccld_tm="",
        buy_sell_tp="매수",
    )


def _tracked_order(ord_no="ORD1", total=48, filled=0, **kw):
    base = dict(
        ord_no=ord_no,
        ticker="005930",
        stock_name="삼성전자",
        side="buy",
        total_quantity=total,
        filled_quantity=filled,
        filled_amount=filled * 260_000,
        limit_price=260_000,
        stop_loss=246_560,
        take_profit=289_440,
        trade_date=date.today().strftime("%Y%m%d"),
    )
    base.update(kw)
    return TrackedOrder(**base)


# -------------------------------------------
# 1) on_trade_approved: unfilled BUY registers a TrackedOrder
# -------------------------------------------


async def test_pending_buy_registers_tracked_order(temp_storage):
    coord = _ready_coordinator()
    _stub_execute_order(coord, filled_quantity=0, status="pending", order_id="ORD1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=246_560,
        take_profit=289_440,
        risk_score=5,
        quantity_override=48,
    )

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.ord_no == "ORD1"
    assert order.total_quantity == 48
    assert order.filled_quantity == 0
    assert order.stop_loss == 246_560
    assert order.take_profit == 289_440
    assert order.trade_date == date.today().strftime("%Y%m%d")
    assert order.source_session_id == "s1"
    # No position was opened — nothing filled yet.
    assert coord._state.positions == []


# -------------------------------------------
# 2) on_trade_approved: partial BUY registers the filled portion as a
#    position AND tracks the remainder
# -------------------------------------------


async def test_partial_buy_registers_position_and_remainder(temp_storage):
    coord = _ready_coordinator()
    _stub_execute_order(
        coord, filled_quantity=20, status="partial", order_id="ORD2", avg_price=260_000
    )

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=246_560,
        take_profit=289_440,
        risk_score=5,
        quantity_override=48,
    )

    # Existing behavior: the filled 20 shares are a tracked position.
    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 20

    # New behavior: the remaining 28 shares are tracked for a post-fill.
    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.ord_no == "ORD2"
    assert order.total_quantity == 48
    assert order.filled_quantity == 20
    assert order.stop_loss == 246_560


async def test_queue_processed_trade_threads_queue_id(temp_storage):
    """The queue-processor path (`_process_trade_queue_inner`) passes its
    QueuedTrade.id through so a later post-fill can annotate it back."""
    coord = _ready_coordinator()
    _stub_execute_order(coord, filled_quantity=0, status="pending", order_id="ORD3")
    queued = coord.add_to_queue(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=246_560,
        take_profit=289_440,
        risk_score=5,
        reason="Market closed",
        autonomous=False,
        quantity=48,
    )

    await coord.process_trade_queue()

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    assert tracking[0].source_queue_id == queued.id


# -------------------------------------------
# 3) polling tick: TRACKING + new fills -> register_fill_as_position +
#    one notification + FILLED transition; idempotent on same-tick re-run
# -------------------------------------------


async def test_poll_tick_registers_fill_and_notifies_once(temp_storage):
    coord = ExecutionCoordinator(kiwoom_client=_FakeKiwoomClient(
        filled_orders=[_filled("ORD1", 48, 260_000)]
    ))
    coord.fill_tracker.register(_tracked_order(ord_no="ORD1", total=48, filled=0))

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord.set_alert_callback(_capture_alert)

    await coord._poll_tracked_fills()

    assert len(coord._state.positions) == 1
    position = coord._state.positions[0]
    assert position.ticker == "005930"
    assert position.quantity == 48
    assert position.stop_loss == 246_560

    assert len(alerts) == 1  # exactly one notification for the fill

    order = coord.fill_tracker._orders["ORD1"]
    assert order.status == TrackedOrderStatus.FILLED
    assert coord.fill_tracker.tracking() == []

    kiwoom_calls = coord._kiwoom.calls
    # Re-running the same tick must not re-call the broker or re-notify —
    # the order already transitioned out of TRACKING.
    await coord._poll_tracked_fills()
    assert coord._kiwoom.calls == kiwoom_calls
    assert len(alerts) == 1
    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 48


async def test_poll_tick_annotates_originating_queue_entry(temp_storage):
    coord = ExecutionCoordinator(kiwoom_client=_FakeKiwoomClient(
        filled_orders=[_filled("ORD1", 48, 260_000)]
    ))
    queued = coord.add_to_queue(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=246_560,
        take_profit=289_440,
        risk_score=5,
        reason="Market closed",
        autonomous=False,
        quantity=48,
    )
    coord.fill_tracker.register(
        _tracked_order(ord_no="ORD1", total=48, filled=0, source_queue_id=queued.id)
    )

    await coord._poll_tracked_fills()

    assert "사후체결 48주" in queued.reason
    assert "Market closed" in queued.reason  # original reason preserved, appended-to


# -------------------------------------------
# 4) polling tick: no TRACKING orders -> broker not called (flow control)
# -------------------------------------------


async def test_poll_tick_skips_broker_call_when_nothing_tracking(temp_storage):
    fake = _FakeKiwoomClient(filled_orders=[])
    coord = ExecutionCoordinator(kiwoom_client=fake)

    await coord._poll_tracked_fills()

    assert fake.calls == 0


# -------------------------------------------
# 5) market open->closed edge: expire all TRACKING + notify; stays closed ->
#    no re-notification
# -------------------------------------------


async def test_market_close_edge_expires_tracking_and_notifies(temp_storage):
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord.fill_tracker.register(_tracked_order(ord_no="A"))
    coord.fill_tracker.register(_tracked_order(ord_no="B"))
    coord._market_was_open = True

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord.set_alert_callback(_capture_alert)
    _stub_market(coord, is_open=False)

    await coord._check_queue_on_market_open()

    assert coord.fill_tracker.tracking() == []
    assert len(alerts) == 2  # one per expired order
    assert coord._market_was_open is False

    # Closed stays closed on the next tick — no re-notification.
    await coord._check_queue_on_market_open()
    assert len(alerts) == 2


async def test_market_stays_open_does_not_expire_tracking(temp_storage):
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord.fill_tracker.register(_tracked_order(ord_no="A"))
    coord._market_was_open = True
    _stub_market(coord, is_open=True)

    await coord._check_queue_on_market_open()

    assert len(coord.fill_tracker.tracking()) == 1


# -------------------------------------------
# 6) persist -> restore round trip
# -------------------------------------------


async def test_persist_restore_round_trips_tracked_orders(temp_storage):
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1.fill_tracker.register(_tracked_order(ord_no="ORD1"))
    await coord1._persist_state()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    _stub_market(coord2, is_open=True)  # M1c determinism: closed would expire
    await coord2._restore_state()

    tracking = coord2.fill_tracker.tracking()
    assert len(tracking) == 1
    assert tracking[0].ord_no == "ORD1"
    assert tracking[0].stop_loss == 246_560


async def test_restore_expires_stale_dated_tracked_order(temp_storage):
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1.fill_tracker.register(_tracked_order(ord_no="OLD", trade_date=yesterday))
    await coord1._persist_state()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    await coord2._restore_state()

    assert coord2.fill_tracker.tracking() == []
    order = coord2.fill_tracker._orders["OLD"]
    assert order.status == TrackedOrderStatus.EXPIRED


async def test_restore_keeps_same_day_tracked_order(temp_storage):
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1.fill_tracker.register(_tracked_order(ord_no="TODAY"))
    await coord1._persist_state()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    _stub_market(coord2, is_open=True)  # M1c determinism: closed would expire
    await coord2._restore_state()

    assert len(coord2.fill_tracker.tracking()) == 1
    assert coord2.fill_tracker.tracking()[0].ord_no == "TODAY"


# -------------------------------------------
# F3 review fixes — CRITICAL: split orders must be tracked per part
# -------------------------------------------


class _SplitFakeKiwoomClient:
    """Accepts every placement with a DISTINCT broker ord_no per part —
    the shape of the real incident (144주 = 48×3 split, three ord_nos)."""

    def __init__(self, filled_orders=None):
        self._filled_orders = filled_orders if filled_orders is not None else []
        self.placed = 0

    async def place_buy_order(self, stk_cd, qty, price=None, order_type=None):
        self.placed += 1
        return OrderResponse(
            ord_no=f"ORD{self.placed}", return_code=0, return_msg="ok"
        )

    async def place_sell_order(self, stk_cd, qty, price=None, order_type=None):
        self.placed += 1
        return OrderResponse(
            ord_no=f"ORD{self.placed}", return_code=0, return_msg="ok"
        )

    async def get_filled_orders(
        self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True
    ):
        return list(self._filled_orders)


async def _no_sleep(_seconds):
    return None


async def test_split_zero_fill_aggregates_pending_with_all_part_ord_nos(monkeypatch):
    """CRITICAL(1): a split order with 0 total fill but successful placements
    must aggregate to "pending" (NOT "rejected") and expose each part's real
    broker ord_no via `parts` — the motivating incident was exactly this
    (3-way split, 0-fill at placement, filled hours later, never tracked)."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)  # skip inter-split delays
    fake = _SplitFakeKiwoomClient(filled_orders=[])
    agent = OrderAgent(
        kiwoom_client=fake, fill_confirm_attempts=1, fill_confirm_interval=0
    )
    order = OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        quantity=144,  # > SPLIT_THRESHOLD(100) → 48×3
        price=260_000,
        order_type=OrderType.LIMIT,
    )

    result = await agent.execute_order(order, split=True)

    assert result.status == "pending"
    assert result.filled_quantity == 0
    assert result.parts is not None and len(result.parts) == 3
    assert [p.order_id for p in result.parts] == ["ORD1", "ORD2", "ORD3"]
    assert all(p.status == "pending" for p in result.parts)
    assert sum(p.requested_quantity for p in result.parts) == 144


async def test_split_all_parts_rejected_still_aggregates_rejected(monkeypatch):
    """CRITICAL(1) guard: "rejected" is still the aggregate when EVERY part
    failed placement — a dead order must not be tracked as pending."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    class _RejectingClient(_SplitFakeKiwoomClient):
        async def place_buy_order(self, stk_cd, qty, price=None, order_type=None):
            return OrderResponse(ord_no="", return_code=1, return_msg="rejected")

    agent = OrderAgent(
        kiwoom_client=_RejectingClient(),
        fill_confirm_attempts=1,
        fill_confirm_interval=0,
    )
    order = OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        quantity=144,
        price=260_000,
        order_type=OrderType.LIMIT,
    )

    result = await agent.execute_order(order, split=True)

    assert result.status == "rejected"
    assert result.filled_quantity == 0


def _split_parts_result(part_specs, ticker="005930"):
    """Aggregate OrderResult with per-part results (as _aggregate_results now
    produces): part_specs = [(order_id, requested, filled, status), ...]."""
    parts = [
        OrderResult(
            order_id=order_id,
            ticker=ticker,
            side=OrderSide.BUY,
            requested_quantity=requested,
            filled_quantity=filled,
            avg_price=260_000 if filled else 0,
            status=status,
        )
        for order_id, requested, filled, status in part_specs
    ]
    total_filled = sum(p.filled_quantity for p in parts)
    total_requested = sum(p.requested_quantity for p in parts)
    if total_filled >= total_requested:
        agg_status = "filled"
    elif total_filled > 0:
        agg_status = "partial"
    else:
        agg_status = "pending"
    return OrderResult(
        order_id=parts[0].order_id,
        ticker=ticker,
        side=OrderSide.BUY,
        requested_quantity=total_requested,
        filled_quantity=total_filled,
        avg_price=260_000 if total_filled else 0,
        status=agg_status,
        parts=parts,
    )


async def test_split_pending_registers_one_tracked_order_per_part(temp_storage):
    """CRITICAL(2): the coordinator registers one TrackedOrder PER part with
    its own broker ord_no — a single aggregate entry would poison the ka10076
    diff arithmetic (three broker orders summed against one total)."""
    coord = _ready_coordinator()
    result = _split_parts_result(
        [("ORD1", 48, 0, "pending"), ("ORD2", 48, 0, "pending"), ("ORD3", 48, 0, "pending")]
    )

    async def _exec(order):
        return result

    coord._execute_order = _exec

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

    tracking = sorted(coord.fill_tracker.tracking(), key=lambda o: o.ord_no)
    assert [o.ord_no for o in tracking] == ["ORD1", "ORD2", "ORD3"]
    assert all(o.total_quantity == 48 for o in tracking)
    assert all(o.filled_quantity == 0 for o in tracking)
    assert all(o.stop_loss == 246_560 for o in tracking)


async def test_split_partial_tracks_only_unfilled_parts(temp_storage):
    """CRITICAL(2) guard: a filled part is NOT tracked; a partial part tracks
    with its OWN filled_quantity so the per-part diff arithmetic stays sound."""
    coord = _ready_coordinator()
    result = _split_parts_result(
        [("ORD1", 48, 48, "filled"), ("ORD2", 48, 20, "partial"), ("ORD3", 48, 0, "pending")]
    )

    async def _exec(order):
        return result

    coord._execute_order = _exec

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

    tracking = sorted(coord.fill_tracker.tracking(), key=lambda o: o.ord_no)
    assert [o.ord_no for o in tracking] == ["ORD2", "ORD3"]
    by_ord = {o.ord_no: o for o in tracking}
    assert by_ord["ORD2"].total_quantity == 48
    assert by_ord["ORD2"].filled_quantity == 20
    assert by_ord["ORD3"].filled_quantity == 0


async def test_poll_applies_fills_across_all_split_parts(temp_storage):
    """CRITICAL(2): a ka10076 snapshot with fills under all three ord_nos
    produces three FillDeltas and the positions sum to the full 144 shares."""
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(
            filled_orders=[
                _filled("ORD1", 48, 260_000),
                _filled("ORD2", 48, 260_000),
                _filled("ORD3", 48, 261_000),
            ]
        )
    )
    for ord_no in ("ORD1", "ORD2", "ORD3"):
        coord.fill_tracker.register(_tracked_order(ord_no=ord_no, total=48))

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord.set_alert_callback(_capture_alert)

    await coord._poll_tracked_fills()

    assert coord.fill_tracker.tracking() == []
    assert len(alerts) == 3
    # _add_position merges same-ticker fills → one position with the sum.
    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 144


# -------------------------------------------
# F3 review fixes — HIGH: close-edge polls BEFORE expiring (closing-auction
# fills land in the final post-close snapshot)
# -------------------------------------------


async def test_close_edge_polls_fills_before_expiring(temp_storage):
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("ORD1", 48, 260_000)])
    )
    coord.fill_tracker.register(_tracked_order(ord_no="ORD1", total=48))
    coord.fill_tracker.register(_tracked_order(ord_no="ORD2", total=48))
    coord._market_was_open = True
    _stub_market(coord, is_open=False)

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord.set_alert_callback(_capture_alert)

    await coord._check_queue_on_market_open()

    # ORD1's closing-auction fill was registered as a position…
    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 48
    assert coord.fill_tracker._orders["ORD1"].status == TrackedOrderStatus.FILLED
    # …and only the true remainder (ORD2) expired.
    assert coord.fill_tracker._orders["ORD2"].status == TrackedOrderStatus.EXPIRED
    assert coord.fill_tracker.tracking() == []
    # 1 fill alert (ORD1) + 1 expiry alert (ORD2) — the filled order must NOT
    # get an expiry notification.
    assert len(alerts) == 2


# -------------------------------------------
# F3 review fixes — M1c: restore while market closed = one final poll,
# then expire (logs only) — no overnight polling, no next-day bogus entries
# -------------------------------------------


async def test_restore_with_market_closed_polls_once_then_expires(temp_storage):
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1.fill_tracker.register(_tracked_order(ord_no="ORD1"))
    await coord1._persist_state()

    fake = _FakeKiwoomClient(filled_orders=[])
    coord2 = ExecutionCoordinator(kiwoom_client=fake)
    _stub_market(coord2, is_open=False)

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord2.set_alert_callback(_capture_alert)

    await coord2._restore_state()

    assert fake.calls == 1  # one final post-close poll was attempted
    assert coord2.fill_tracker.tracking() == []  # nothing left to poll overnight
    assert coord2.fill_tracker._orders["ORD1"].status == TrackedOrderStatus.EXPIRED
    assert alerts == []  # logs only — no restart notification storm


async def test_restore_with_market_closed_still_registers_final_fill(temp_storage):
    """The one final poll is a REAL poll — a fill that landed while the
    backend was down still becomes a defended position."""
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1.fill_tracker.register(_tracked_order(ord_no="ORD1", total=48))
    await coord1._persist_state()

    fake = _FakeKiwoomClient(filled_orders=[_filled("ORD1", 48, 260_000)])
    coord2 = ExecutionCoordinator(kiwoom_client=fake)
    _stub_market(coord2, is_open=False)

    await coord2._restore_state()

    assert len(coord2._state.positions) == 1
    assert coord2._state.positions[0].quantity == 48
    assert coord2.fill_tracker._orders["ORD1"].status == TrackedOrderStatus.FILLED
    assert coord2.fill_tracker.tracking() == []


# -------------------------------------------
# F3 review fixes — LOW: poll-path semantics pins
# -------------------------------------------


async def test_poll_passes_stop_loss_mode_and_risk_score(temp_storage):
    """LOW-a: the poll path registers with the coordinator's stop_loss_mode
    and the TrackedOrder's risk_score — matching the placement-fill path
    (coordinator.py:597-600) semantics."""
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("ORD1", 48, 260_000)])
    )
    coord.risk_params.stop_loss_mode = StopLossMode.AGENT_AUTO
    coord.fill_tracker.register(_tracked_order(ord_no="ORD1", risk_score=7))

    await coord._poll_tracked_fills()

    position = coord._state.positions[0]
    assert position.stop_loss_mode == StopLossMode.AGENT_AUTO
    assert position.risk_score == 7


async def test_registration_records_proposal_risk_score(temp_storage):
    """LOW-a: on_trade_approved threads its risk_score onto the TrackedOrder
    so the eventual post-fill position carries the analysis risk."""
    coord = _ready_coordinator()
    _stub_execute_order(coord, filled_quantity=0, status="pending", order_id="ORD1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=246_560,
        take_profit=289_440,
        risk_score=7,
        quantity_override=48,
    )

    assert coord.fill_tracker.tracking()[0].risk_score == 7


async def test_poll_bypasses_ka10076_cache(temp_storage):
    """LOW-b: every poll must see the LATEST fills — a cached (stale) snapshot
    within the 5s TTL would replay pre-fill state every tick."""
    seen = {}

    class _Recording(_FakeKiwoomClient):
        async def get_filled_orders(
            self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True
        ):
            seen["use_cache"] = use_cache
            return list(self._filled_orders)

    coord = ExecutionCoordinator(kiwoom_client=_Recording(filled_orders=[]))
    coord.fill_tracker.register(_tracked_order(ord_no="ORD1"))

    await coord._poll_tracked_fills()

    assert seen.get("use_cache") is False


async def test_poll_exception_leaves_tracked_state_unchanged(temp_storage):
    """LOW-b: a broker query failure is logged and retried next tick — it must
    not mutate tracked state, register positions, or notify."""

    class _FailingClient(_FakeKiwoomClient):
        async def get_filled_orders(
            self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True
        ):
            raise RuntimeError("ka10076 down")

    coord = ExecutionCoordinator(kiwoom_client=_FailingClient())
    coord.fill_tracker.register(_tracked_order(ord_no="ORD1", total=48, filled=20))

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord.set_alert_callback(_capture_alert)

    await coord._poll_tracked_fills()

    order = coord.fill_tracker._orders["ORD1"]
    assert order.status == TrackedOrderStatus.TRACKING
    assert order.filled_quantity == 20
    assert coord._state.positions == []
    assert alerts == []
