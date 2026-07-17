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

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import services.storage_service as ss
from services.agent_chat.position_manager import MonitoredPosition
from services.kiwoom.models import AccountBalance, FilledOrder, Holding, OrderResponse
from services.trading import eod_orchestrator
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import (
    ManagedPosition,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    QueueStatus,
    StopLossMode,
    TradingMode,
)
from services.trading.order_agent import OrderAgent
from services.trading.pending_order_tracker import TrackedOrder, TrackedOrderStatus
from services.trading.reconciler import ReconcileReport, reconcile

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


@pytest.fixture(autouse=True)
def _stub_telegram_notifier(monkeypatch):
    """E3-3: ExecutionCoordinator._notify_eod_summary (now part of the
    market-close edge every test in this file may exercise) calls
    services.telegram.get_telegram_notifier(). Stub it to a never-ready
    fake so nothing here can ever reach the real Telegram API -- this
    repo's real .env has live bot credentials. Tests that specifically
    want to observe the notify step (see the E3-3 section near the end of
    this file) override this via their own monkeypatch/spy as needed."""
    import services.telegram as telegram_module

    class _NotReadyNotifier:
        is_ready = False

    async def _fake_get_telegram_notifier():
        return _NotReadyNotifier()

    monkeypatch.setattr(telegram_module, "get_telegram_notifier", _fake_get_telegram_notifier)


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

    # E3-2: the open->closed edge now runs run_eod_review's one LLM call
    # (narrate_eod_digest) — stub it so this F3 fill-tracking test (which
    # predates E3-2 and only cares about expiry/notification behavior)
    # doesn't touch a real backend.
    with patch.object(eod_orchestrator, "narrate_eod_digest", AsyncMock(return_value=None)):
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

    # E3-2: stub the one LLM call the open->closed edge now makes
    # (narrate_eod_digest via run_eod_review) — see the note on
    # test_market_close_edge_expires_tracking_and_notifies above.
    with patch.object(eod_orchestrator, "narrate_eod_digest", AsyncMock(return_value=None)):
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


# -------------------------------------------
# F3 t6: broker-local reconciler
#
# reconcile(coordinator) reads get_account_balance() as truth and converges
# the coordinator and the agent-chat PositionManager toward it: adopts
# broker-only "orphan" holdings, removes positions the broker no longer
# holds (unless a TRACKING sell explains a transient zero), and fixes any
# quantity drift between an engine and the broker.
# -------------------------------------------


def _holding(stk_cd="005930", stk_nm="삼성전자", qty=48, avg=260_000, cur=260_000):
    evlu_amt = cur * qty
    pfls_amt = (cur - avg) * qty
    pfls_rt = ((cur - avg) / avg * 100) if avg else 0.0
    return Holding(
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        hldg_qty=qty,
        avg_buy_prc=avg,
        cur_prc=cur,
        evlu_amt=evlu_amt,
        evlu_pfls_amt=pfls_amt,
        evlu_pfls_rt=pfls_rt,
    )


class _BalanceKiwoomClient:
    """Minimal Kiwoom client: reports get_account_balance() from a fixed
    holdings list (or raises, for the failure-path test). Records the
    use_cache kwarg so tests can pin the fresh-snapshot contract (review M1)."""

    def __init__(self, holdings=None, raise_error=False):
        self._holdings = holdings if holdings is not None else []
        self._raise_error = raise_error
        self.balance_calls = 0
        self.last_use_cache = None

    async def get_account_balance(self, qry_tp="0", exchange=None, use_cache=True):
        self.balance_calls += 1
        self.last_use_cache = use_cache
        if self._raise_error:
            raise RuntimeError("kt00004 down")
        return AccountBalance(holdings=list(self._holdings))


def _chat_coordinator(pm):
    """A stand-in for ChatCoordinator exposing only `.position_manager`,
    matching the shape `_get_position_manager` reads (same pattern as
    test_position_registration.py)."""
    return SimpleNamespace(position_manager=pm)


class _FakePM:
    """A tiny stand-in for agent_chat.PositionManager with real (not mocked)
    absolute-assignment semantics — needed for the convergence test, which
    re-reads state across two reconcile() calls."""

    def __init__(self, positions=None):
        self._positions = dict(positions or {})

    def get_position(self, ticker):
        return self._positions.get(ticker)

    def get_all_positions(self):
        return list(self._positions.values())

    def add_position(self, *, ticker, stock_name, quantity, avg_price,
                      current_price=None, stop_loss=None, take_profit=None,
                      trailing_stop_pct=None):
        position = MonitoredPosition(
            ticker=ticker,
            stock_name=stock_name,
            quantity=quantity,
            avg_price=avg_price,
            current_price=current_price or avg_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        self._positions[ticker] = position
        return position

    def update_position(self, ticker, quantity=None, current_price=None,
                         stop_loss=None, take_profit=None, trailing_stop_pct=None):
        position = self._positions.get(ticker)
        if position is None:
            return None
        if quantity is not None:
            position.quantity = quantity
        if current_price is not None:
            position.current_price = current_price
        if stop_loss is not None:
            position.stop_loss = stop_loss
        if take_profit is not None:
            position.take_profit = take_profit
        return position

    def remove_position(self, ticker):
        return self._positions.pop(ticker, None) is not None


def _patch_pm(monkeypatch, pm):
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(pm)),
    )


def _managed_position(ticker="005930", quantity=48, avg=260_000,
                       stop_loss=246_560, take_profit=289_440):
    return ManagedPosition(
        ticker=ticker,
        stock_name="삼성전자",
        quantity=quantity,
        avg_price=avg,
        current_price=avg,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


# 1) orphan + fill_tracker FILLED record -> adopt with that stop, notify once
async def test_reconcile_orphan_adopts_using_fill_tracker_stop(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(holdings=[_holding(qty=48, avg=260_000, cur=265_000)])
    )
    coord.fill_tracker.register(
        _tracked_order(
            ord_no="OLD1",
            total=48,
            filled=48,
            status=TrackedOrderStatus.FILLED,
            stop_loss=246_560,
            take_profit=289_440,
        )
    )
    _patch_pm(monkeypatch, None)

    alerts = []

    async def _capture(a):
        alerts.append(a)

    coord.set_alert_callback(_capture)

    report = await reconcile(coord)

    assert report == ReconcileReport(orphans_adopted=1, externally_closed=0, quantity_fixed=0)
    assert len(coord._state.positions) == 1
    position = coord._state.positions[0]
    assert position.ticker == "005930"
    assert position.quantity == 48
    assert position.stop_loss == 246_560
    assert position.take_profit == 289_440
    assert len(alerts) == 1
    assert alerts[0].ticker == "005930"


# 2) orphan + no tracker record but a COMPLETED BUY in trade_queue -> that stop
async def test_reconcile_orphan_adopts_using_trade_queue_stop(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(holdings=[_holding(qty=48, avg=260_000, cur=260_000)])
    )
    queued = coord.add_to_queue(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=250_000,
        take_profit=280_000,
        risk_score=6,
        reason="장 마감",
        autonomous=False,
        quantity=48,
    )
    queued.status = QueueStatus.COMPLETED
    _patch_pm(monkeypatch, None)

    report = await reconcile(coord)

    assert report.orphans_adopted == 1
    position = coord._state.positions[0]
    assert position.stop_loss == 250_000
    assert position.take_profit == 280_000


# 3) orphan + no provenance at all -> default ±8% off avg price, notified as such
async def test_reconcile_orphan_falls_back_to_default_stop(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(holdings=[_holding(qty=10, avg=250_000, cur=250_000)])
    )
    _patch_pm(monkeypatch, None)

    alerts = []

    async def _capture(a):
        alerts.append(a)

    coord.set_alert_callback(_capture)

    report = await reconcile(coord)

    assert report.orphans_adopted == 1
    position = coord._state.positions[0]
    assert position.stop_loss == pytest.approx(230_000)
    assert position.take_profit == pytest.approx(270_000)
    assert "기본 스탑" in alerts[0].message


# 4) reverse: coordinator manages it, broker no longer does -> remove both,
# notify. The broker snapshot stays NON-empty (another managed holding is
# still there) — an all-empty snapshot is the M2 mass-removal guard's case.
async def test_reconcile_removes_position_absent_from_broker(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(
            holdings=[_holding(stk_cd="000660", stk_nm="SK하이닉스", qty=10)]
        )
    )
    coord._add_position(_managed_position())  # 005930 — gone at the broker
    coord._add_position(
        _managed_position(ticker="000660", quantity=10, stop_loss=None, take_profit=None)
    )  # still held — keeps the snapshot non-empty and is itself untouched
    _patch_pm(monkeypatch, None)

    alerts = []

    async def _capture(a):
        alerts.append(a)

    coord.set_alert_callback(_capture)

    report = await reconcile(coord)

    assert report.externally_closed == 1
    assert [p.ticker for p in coord._state.positions] == ["000660"]
    assert len(alerts) == 1
    assert alerts[0].ticker == "005930"


# 5) reverse exception: a TRACKING sell for the ticker suppresses the removal.
# Broker snapshot kept NON-empty (another managed holding) so the skip is
# attributable to the TRACKING-sell branch, not the M2 zero-holdings guard.
async def test_reconcile_reverse_check_skips_when_tracking_sell_exists(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(
            holdings=[_holding(stk_cd="000660", stk_nm="SK하이닉스", qty=10)]
        )
    )
    coord._add_position(_managed_position())  # 005930 — absent at the broker
    coord._add_position(
        _managed_position(ticker="000660", quantity=10, stop_loss=None, take_profit=None)
    )
    coord.fill_tracker.register(
        _tracked_order(ord_no="SELL1", ticker="005930", side="sell", total=10, filled=0)
    )
    _patch_pm(monkeypatch, None)

    report = await reconcile(coord)

    assert report.externally_closed == 0
    assert any(p.ticker == "005930" for p in coord._state.positions)


# 6) quantity mismatch (broker 30 vs managed 48) -> corrected to broker qty
async def test_reconcile_fixes_quantity_mismatch(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(holdings=[_holding(qty=30, avg=260_000, cur=260_000)])
    )
    coord._add_position(_managed_position(quantity=48))
    _patch_pm(monkeypatch, None)

    alerts = []

    async def _capture(a):
        alerts.append(a)

    coord.set_alert_callback(_capture)

    report = await reconcile(coord)

    assert report.quantity_fixed == 1
    assert coord._state.positions[0].quantity == 30
    assert len(alerts) == 1


# 7) get_account_balance failure -> all-zero report, managed state untouched
async def test_reconcile_returns_empty_report_on_balance_fetch_failure(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(kiwoom_client=_BalanceKiwoomClient(raise_error=True))
    coord._add_position(_managed_position(quantity=48))
    _patch_pm(monkeypatch, None)

    report = await reconcile(coord)

    assert report == ReconcileReport(orphans_adopted=0, externally_closed=0, quantity_fixed=0)
    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 48


# 8) double-count-window convergence (F3 t3 review subtlety): PositionManager
# syncs ABSOLUTE broker quantities while the fill tracker applies INCREMENTAL
# deltas — a race can leave PM double-counted (its own sync plus a delta the
# broker snapshot already included) while the coordinator, which only ever
# applied the single delta, stays correct. Broker truth wins for both sides;
# PM's update_position assigns absolutely so one correction converges it, and
# re-reconciling finds nothing left to fix.
async def test_reconcile_converges_pm_double_count_window(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(holdings=[_holding(qty=48, avg=260_000, cur=260_000)])
    )
    coord._add_position(_managed_position(quantity=48))  # already correct
    pm = _FakePM({
        "005930": MonitoredPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=76,  # double-counted: 48 (sync) + 28 (incremental delta)
            avg_price=260_000,
            current_price=260_000,
            stop_loss=246_560,
            take_profit=289_440,
        )
    })
    _patch_pm(monkeypatch, pm)

    alerts = []

    async def _capture(a):
        alerts.append(a)

    coord.set_alert_callback(_capture)

    report = await reconcile(coord)

    assert report.quantity_fixed == 1
    assert coord._state.positions[0].quantity == 48  # untouched — already correct
    assert pm.get_position("005930").quantity == 48  # corrected to broker truth
    assert len(alerts) == 1

    # Stable fixed point — re-reconciling finds nothing left to fix.
    report2 = await reconcile(coord)
    assert report2 == ReconcileReport(orphans_adopted=0, externally_closed=0, quantity_fixed=0)
    assert len(alerts) == 1  # no duplicate notification


# 9) decision 1, reverse direction: coordinator already manages it, PM doesn't
# -> PM gets backfilled directly from the coordinator's data (not counted as
# an "orphan adoption" — the broker holding was already known/trusted).
async def test_reconcile_backfills_pm_when_only_coordinator_manages(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(holdings=[_holding(qty=48, avg=260_000, cur=260_000)])
    )
    coord._add_position(_managed_position(quantity=48))
    pm = _FakePM({})
    _patch_pm(monkeypatch, pm)

    report = await reconcile(coord)

    assert report.orphans_adopted == 0
    assert report.quantity_fixed == 0
    pm_position = pm.get_position("005930")
    assert pm_position is not None
    assert pm_position.quantity == 48
    assert pm_position.stop_loss == 246_560


# 10) wiring: the 30s queue-scheduler loop calls reconcile() every 2nd tick
async def test_scheduler_calls_reconcile_every_second_tick(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._check_queue_on_market_open = AsyncMock()
    coord._poll_tracked_fills = AsyncMock()

    calls = []

    async def _fake_reconcile(c):
        calls.append(c)
        return ReconcileReport()

    monkeypatch.setattr("services.trading.coordinator.reconcile", _fake_reconcile)

    tick_count = {"n": 0}

    async def _fake_sleep(_seconds):
        tick_count["n"] += 1
        if tick_count["n"] > 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)

    await coord._queue_scheduler_loop()

    assert tick_count["n"] == 3  # two ticks ran, the third stopped the loop
    assert len(calls) == 1  # reconcile fired exactly once, on the 2nd tick
    assert calls[0] is coord


# -------------------------------------------
# F3 t6 review fixes (M1/M2/m1/m2)
# -------------------------------------------


# M1: reconcile must read a FRESH balance snapshot — the client's 30s TTL
# entry can predate a fill the poll just registered, and a stale snapshot
# would remove the just-registered position as "외부 매도" (oscillation).
async def test_reconcile_requests_fresh_balance_snapshot(temp_storage, monkeypatch):
    fake = _BalanceKiwoomClient(holdings=[])
    coord = ExecutionCoordinator(kiwoom_client=fake)
    _patch_pm(monkeypatch, None)

    await reconcile(coord)

    assert fake.balance_calls == 1
    assert fake.last_use_cache is False


# M2: a SUCCESSFUL response with EMPTY holdings while positions are managed
# must not mass-remove everything — the client manufactures [] from a
# malformed kt00004 payload, so an empty list is not trustworthy enough to
# liquidate all local defense in one pass. Skip the removal pass + warn;
# adoption/quantity passes still run.
async def test_reconcile_zero_holdings_skips_entire_removal_pass(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(kiwoom_client=_BalanceKiwoomClient(holdings=[]))
    coord._add_position(_managed_position(ticker="005930"))
    coord._add_position(_managed_position(ticker="000660", stop_loss=None, take_profit=None))
    _patch_pm(monkeypatch, None)

    warnings = []
    import services.trading.reconciler as reconciler_module

    monkeypatch.setattr(
        reconciler_module.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg))
    )

    alerts = []

    async def _capture(a):
        alerts.append(a)

    coord.set_alert_callback(_capture)

    report = await reconcile(coord)

    assert report.externally_closed == 0
    assert len(coord._state.positions) == 2  # nothing removed
    assert alerts == []  # and no removal notifications
    assert any("ZERO holdings" in w for w in warnings)  # warning logged


# M2 guard must NOT block a genuine single-position close: broker holdings
# are non-empty overall, just lacking the managed ticker -> still removed.
async def test_reconcile_still_removes_missing_ticker_when_other_holdings_exist(
    temp_storage, monkeypatch
):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(
            holdings=[_holding(stk_cd="000660", stk_nm="SK하이닉스", qty=10)]
        )
    )
    coord._add_position(_managed_position(ticker="005930"))
    _patch_pm(monkeypatch, None)

    report = await reconcile(coord)

    assert report.externally_closed == 1
    assert all(p.ticker != "005930" for p in coord._state.positions)


# m1: the true-orphan adoption path must register with the coordinator's
# stop_loss_mode and the provenance risk_score (parity with the fill-poll
# path's register semantics).
async def test_reconcile_true_orphan_carries_stop_mode_and_risk_score(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(kiwoom_client=_BalanceKiwoomClient(holdings=[_holding()]))
    coord.risk_params.stop_loss_mode = StopLossMode.AGENT_AUTO
    coord.fill_tracker.register(
        _tracked_order(
            ord_no="OLD1",
            total=48,
            filled=48,
            status=TrackedOrderStatus.FILLED,
            risk_score=7,
        )
    )
    _patch_pm(monkeypatch, None)

    report = await reconcile(coord)

    assert report.orphans_adopted == 1
    position = coord._state.positions[0]
    assert position.stop_loss_mode == StopLossMode.AGENT_AUTO
    assert position.risk_score == 7


# m1: the bypass branch (PM already tracks the ticker) must carry the same
# stop_loss_mode/risk_score on the directly-registered ManagedPosition.
async def test_reconcile_bypass_branch_carries_stop_mode_and_risk_score(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(kiwoom_client=_BalanceKiwoomClient(holdings=[_holding()]))
    coord.risk_params.stop_loss_mode = StopLossMode.AGENT_AUTO
    coord.fill_tracker.register(
        _tracked_order(
            ord_no="OLD1",
            total=48,
            filled=48,
            status=TrackedOrderStatus.FILLED,
            risk_score=7,
        )
    )
    pm = _FakePM({
        "005930": MonitoredPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=48,
            avg_price=260_000,
            current_price=260_000,
            stop_loss=246_560,
            take_profit=289_440,
        )
    })
    _patch_pm(monkeypatch, pm)

    report = await reconcile(coord)

    assert report.orphans_adopted == 1
    position = coord._state.positions[0]
    assert position.stop_loss_mode == StopLossMode.AGENT_AUTO
    assert position.risk_score == 7


# m2: the quantity fix must refresh current_price from the broker BEFORE
# re-registering with the RiskMonitor — a stale last_price can trip the
# sudden-move detector (PAUSED -> all stop checks skipped). Also pins the
# re-register itself (reviewer L4): the watch config reflects the corrected
# quantity/price and keeps its stops.
async def test_reconcile_quantity_fix_refreshes_price_and_risk_monitor(temp_storage, monkeypatch):
    coord = ExecutionCoordinator(
        kiwoom_client=_BalanceKiwoomClient(holdings=[_holding(qty=30, avg=260_000, cur=270_000)])
    )
    coord._add_position(_managed_position(quantity=48))  # current_price=260_000 (stale)
    _patch_pm(monkeypatch, None)

    report = await reconcile(coord)

    assert report.quantity_fixed == 1
    position = coord._state.positions[0]
    assert position.quantity == 30
    assert position.current_price == 270_000  # refreshed from broker cur_prc

    config = coord.risk_monitor._watching["005930"]
    assert config.quantity == 30
    assert config.last_price == 270_000
    assert config.stop_loss == 246_560  # stops preserved through the re-register
    assert config.take_profit == 289_440



# -------------------------------------------
# E3-3: market-close edge appends _notify_eod_summary after
# reconcile_trade_ledger. Source ordering itself is pinned via
# inspect.getsource in test_ledger_reconcile.py (mirrors the
# run_eod_review/run_strategy_consensus/reconcile_trade_ledger ordering
# pins already there); these two tests pin RUNTIME behavior instead: the
# step is actually invoked with today's trade_date on the close edge, and
# a Telegram/WS delivery failure never breaks the rest of the close-edge
# chain that already ran above it (never-raise, mirroring every other EOD
# chain step's contract).
# -------------------------------------------


async def test_close_edge_invokes_eod_summary_notify_with_trade_date(temp_storage):
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._market_was_open = True
    _stub_market(coord, is_open=False)

    calls = []

    async def _spy_notify(trade_date):
        calls.append(trade_date)

    coord._notify_eod_summary = _spy_notify

    with patch.object(eod_orchestrator, "narrate_eod_digest", AsyncMock(return_value=None)):
        await coord._check_queue_on_market_open()

    assert len(calls) == 1
    assert calls[0] == date.today().strftime("%Y-%m-%d")


async def test_close_edge_survives_eod_summary_notify_failure(temp_storage, monkeypatch):
    """Telegram/WS delivery failing (e.g. broadcast_eod_summary raising)
    must not break the market-close edge -- the whole notify step is one
    never-raise try, mirroring every other EOD chain step's contract."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord.fill_tracker.register(_tracked_order(ord_no="A"))
    coord._market_was_open = True
    _stub_market(coord, is_open=False)

    async def _boom(digest, narrative=None):
        raise RuntimeError("ws broadcast boom")

    monkeypatch.setattr("app.api.routes.websocket.broadcast_eod_summary", _boom)

    with patch.object(eod_orchestrator, "narrate_eod_digest", AsyncMock(return_value=None)):
        await coord._check_queue_on_market_open()  # must not raise

    # The rest of the close-edge chain (which ran BEFORE the notify step)
    # completed normally.
    assert coord.fill_tracker.tracking() == []
    assert coord._market_was_open is False


# Review fix: get_eod_reviews(limit=1) returns the newest row on disk
# regardless of whether TODAY's run_eod_review actually wrote one this
# tick (its own try/except can fail before reaching save_eod_review and
# just return False -- see its docstring). Without a trade_date match
# check, _notify_eod_summary would silently re-send YESTERDAY's
# digest/narrative relabeled as today's. Exercises _notify_eod_summary
# directly (not through the full close edge) -- faster and isolates the
# guard from run_eod_review/run_strategy_consensus's own real-LLM cost.
async def test_notify_eod_summary_skips_stale_review_row(temp_storage, monkeypatch, caplog):
    import json
    import logging

    import app.api.routes.websocket as ws_module
    import services.telegram as telegram_module

    coord = ExecutionCoordinator(kiwoom_client=None)

    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    today = date.today().strftime("%Y-%m-%d")

    await temp_storage.save_eod_review({
        "trade_date": yesterday,
        "report_json": json.dumps(
            {"digest": {"trade_date": yesterday}, "narrative": "어제 요약"}
        ),
    })

    telegram_calls = []
    ws_calls = []

    class _ReadyNotifier:
        is_ready = True

        async def send_daily_summary(self, digest, narrative=None):
            telegram_calls.append((digest, narrative))
            return True

    async def _fake_get_telegram_notifier():
        return _ReadyNotifier()

    async def _fake_broadcast(digest, narrative=None):
        ws_calls.append((digest, narrative))

    monkeypatch.setattr(telegram_module, "get_telegram_notifier", _fake_get_telegram_notifier)
    monkeypatch.setattr(ws_module, "broadcast_eod_summary", _fake_broadcast)

    with caplog.at_level(logging.WARNING):
        await coord._notify_eod_summary(today)

    assert telegram_calls == []
    assert ws_calls == []
    assert any("eod_summary_stale_skipped" in rec.message for rec in caplog.records)
