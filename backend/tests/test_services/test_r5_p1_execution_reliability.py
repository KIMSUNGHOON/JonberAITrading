"""R5-P1: execution reliability (audit 2026-07-12, A3/A4 + open-queue scheduler).

- A4 (t1): the coordinator's restart-critical state (positions WITH stop levels,
  trade queue, daily trade count) lived only in memory, so a restart left the
  risk monitor watching nothing → stop-losses became a silent no-op. These tests
  pin persist→restore round-trips via SQLite (app_settings blob).
- A3 (t2/t3): fills were assumed (accept == full fill) and a defensive close
  removed the position even when the sell did not fill.
- Scheduler (t4): a queue built while the market was closed is auto-processed on
  the closed→open transition.

Spec: docs/superpowers/specs/2026-07-13-r5-p1-execution-reliability.md
"""

import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

import services.storage_service as ss
from services.kiwoom.models import FilledOrder, OrderResponse
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import (
    AlertType,
    AllocationPlan,
    ManagedPosition,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    QueueStatus,
    TradingAlert,
)
from services.trading.order_agent import OrderAgent


@pytest_asyncio.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _sample_position() -> ManagedPosition:
    return ManagedPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=100,
        avg_price=72_500,
        current_price=71_000,
        stop_loss=68_875,
        take_profit=79_750,
        risk_score=7,
        analysis_session_id="s-restart",
    )


# -------------------------------------------
# A4 — persist / restore positions (with stops)
# -------------------------------------------


async def test_persist_restore_round_trips_position_with_stops(temp_storage):
    """A4: a restart must recover the position AND its stop levels, and re-register
    it with the risk monitor so defense resumes."""
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1._add_position(_sample_position())
    await coord1._persist_state()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    assert coord2._state.positions == []
    await coord2._restore_state()

    assert len(coord2._state.positions) == 1
    restored = coord2._state.positions[0]
    assert restored.ticker == "005930"
    assert restored.stop_loss == 68_875
    assert restored.take_profit == 79_750
    assert restored.risk_score == 7
    assert restored.analysis_session_id == "s-restart"
    # Re-registered with the risk monitor (defense resumes).
    assert "005930" in coord2.risk_monitor._watching


async def test_persist_restore_round_trips_trade_queue(temp_storage):
    """A4: queued autonomous trades (with quantity) survive a restart."""
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1.add_to_queue(
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
    await coord1._persist_state()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    await coord2._restore_state()

    assert len(coord2._state.trade_queue) == 1
    q = coord2._state.trade_queue[0]
    assert q.ticker == "005930"
    assert q.quantity == 7
    assert q.autonomous is True
    assert q.status == QueueStatus.PENDING


async def test_restore_resets_daily_count_on_new_day(temp_storage):
    """A4: the daily trade count must reset when restored on a later calendar day,
    not carry a stale count that blocks the day's first trades."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    await temp_storage.set_app_setting(
        "trading:coordinator_state",
        json.dumps(
            {
                "positions": [],
                "trade_queue": [],
                "daily_trades_count": 5,
                "daily_count_date": yesterday,
            }
        ),
    )

    coord = ExecutionCoordinator(kiwoom_client=None)
    await coord._restore_state()

    assert coord._state.daily_trades_count == 0


async def test_restore_preserves_daily_count_same_day(temp_storage):
    """A4: a same-day restore keeps the count (a restart must not reset the limit)."""
    await temp_storage.set_app_setting(
        "trading:coordinator_state",
        json.dumps(
            {
                "positions": [],
                "trade_queue": [],
                "daily_trades_count": 3,
                "daily_count_date": date.today().isoformat(),
            }
        ),
    )

    coord = ExecutionCoordinator(kiwoom_client=None)
    await coord._restore_state()

    assert coord._state.daily_trades_count == 3


async def test_restore_noop_when_nothing_persisted(temp_storage):
    """A4: a first run (empty storage) restores cleanly to an empty state."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    await coord._restore_state()
    assert coord._state.positions == []
    assert coord._state.trade_queue == []


async def test_stop_persists_state(temp_storage):
    """A4: a graceful stop() of a running session persists state so the next
    start() can restore it."""
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    await coord1.start()
    coord1._add_position(_sample_position())
    await coord1.stop()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    await coord2._restore_state()
    assert len(coord2._state.positions) == 1
    assert coord2._state.positions[0].stop_loss == 68_875


async def test_start_restores_state(temp_storage):
    """A4: start() restores persisted positions before monitoring begins."""
    coord1 = ExecutionCoordinator(kiwoom_client=None)
    coord1._add_position(_sample_position())
    await coord1._persist_state()

    coord2 = ExecutionCoordinator(kiwoom_client=None)
    await coord2.start()
    try:
        assert any(p.ticker == "005930" for p in coord2._state.positions)
    finally:
        await coord2.stop()


# -------------------------------------------
# A3 — a defensive/close SELL must track the ACTUAL fill
# -------------------------------------------


def _coord_with_position(qty: int = 100) -> ExecutionCoordinator:
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._add_position(
        ManagedPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=qty,
            avg_price=72_500,
            current_price=68_000,
            stop_loss=68_875,
            take_profit=79_750,
        )
    )
    return coord


def _stub_execute_order(coord, filled_quantity, status="filled"):
    async def _exec(order):
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=filled_quantity,
            avg_price=order.price or 68_000,
            status=status,
        )

    coord._execute_order = _exec


async def test_close_position_retains_position_when_sell_unfilled(temp_storage):
    """A3: a close whose SELL does not fill must KEEP the position (and its stops)
    — dropping it on an unfilled sell orphans the exposure with no defense."""
    coord = _coord_with_position()
    _stub_execute_order(coord, filled_quantity=0, status="rejected")

    await coord._close_position("005930")

    assert any(p.ticker == "005930" for p in coord._state.positions)
    assert "005930" in coord.risk_monitor._watching


async def test_close_position_removes_when_fully_filled(temp_storage):
    """A3 guard: a fully-filled close removes the position from tracking."""
    coord = _coord_with_position(qty=100)
    _stub_execute_order(coord, filled_quantity=100)

    await coord._close_position("005930")

    assert coord._state.positions == []
    assert "005930" not in coord.risk_monitor._watching


async def test_close_position_reduces_when_partially_filled(temp_storage):
    """A3: a partially-filled close reduces the tracked quantity and keeps
    monitoring the remainder, not silently dropping the whole position."""
    coord = _coord_with_position(qty=100)
    _stub_execute_order(coord, filled_quantity=40)

    await coord._close_position("005930")

    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 60
    assert "005930" in coord.risk_monitor._watching


async def test_monitor_stop_execution_reduces_on_partial_fill(temp_storage):
    """A3: a stop-loss/take-profit order that only partially fills must reduce the
    tracked quantity, not remove the whole position on any fill > 0."""
    coord = _coord_with_position(qty=100)
    _stub_execute_order(coord, filled_quantity=40)

    order = OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.SELL,
        quantity=100,
        price=68_000,
    )
    await coord._execute_order_from_monitor(order)

    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 60


# -------------------------------------------
# A3 — fill confirmation via ka10076 (no "accept == full fill")
# -------------------------------------------


class _FakeKiwoomClient:
    """Minimal Kiwoom client: accepts orders and reports fills from ka10076."""

    def __init__(self, ord_no="ORD1", filled_orders=None):
        self._ord_no = ord_no
        self._filled_orders = filled_orders if filled_orders is not None else []

    async def place_buy_order(self, stk_cd, qty, price=None, order_type=None):
        return OrderResponse(ord_no=self._ord_no, return_code=0, return_msg="ok")

    async def place_sell_order(self, stk_cd, qty, price=None, order_type=None):
        return OrderResponse(ord_no=self._ord_no, return_code=0, return_msg="ok")

    async def get_filled_orders(
        self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True
    ):
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


def _order_agent(fake):
    return OrderAgent(
        kiwoom_client=fake, fill_confirm_attempts=1, fill_confirm_interval=0
    )


def _buy_order(qty=100, price=50_000):
    return OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        quantity=qty,
        price=price,
        order_type=OrderType.LIMIT,
    )


async def test_kiwoom_order_reports_confirmed_partial_fill():
    """A3: a partially-filled order reports the ACTUAL filled quantity (ka10076),
    not the requested quantity assumed filled."""
    fake = _FakeKiwoomClient(ord_no="ORD1", filled_orders=[_filled("ORD1", 40, 50_000)])
    result = await _order_agent(fake).execute_order(_buy_order(qty=100), split=False)

    assert result.filled_quantity == 40
    assert result.status == "partial"


async def test_kiwoom_order_reports_pending_when_no_fill_confirmed():
    """A3: an accepted-but-unfilled order must NOT be assumed filled — it reports
    0 filled / pending so the coordinator does not track a phantom position."""
    fake = _FakeKiwoomClient(ord_no="ORD1", filled_orders=[])
    result = await _order_agent(fake).execute_order(_buy_order(qty=100), split=False)

    assert result.filled_quantity == 0
    assert result.status == "pending"


async def _market_closed_coordinator_with_queue():
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord.add_to_queue(
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
    coord._market_was_open = False
    coord.process_trade_queue = AsyncMock()
    return coord


def _stub_market(coord, is_open):
    coord._market_hours.get_market_session = lambda market: SimpleNamespace(
        is_open=is_open
    )


async def test_queue_processed_on_market_open_transition(temp_storage):
    """t4: a queue built while closed is auto-processed on the closed→open edge."""
    coord = await _market_closed_coordinator_with_queue()
    _stub_market(coord, is_open=True)

    await coord._check_queue_on_market_open()

    coord.process_trade_queue.assert_awaited_once()
    assert coord._market_was_open is True


async def test_queue_not_processed_while_market_stays_closed(temp_storage):
    """t4: no processing while the market remains closed."""
    coord = await _market_closed_coordinator_with_queue()
    _stub_market(coord, is_open=False)

    await coord._check_queue_on_market_open()

    coord.process_trade_queue.assert_not_awaited()


async def test_queue_not_reprocessed_when_market_already_open(temp_storage):
    """t4: only the closed→open EDGE triggers — an already-open market does not
    re-process every tick."""
    coord = await _market_closed_coordinator_with_queue()
    coord._market_was_open = True  # already open
    _stub_market(coord, is_open=True)

    await coord._check_queue_on_market_open()

    coord.process_trade_queue.assert_not_awaited()


async def test_queue_open_transition_noop_when_queue_empty(temp_storage):
    """t4: an open transition with an empty queue does nothing."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._market_was_open = False
    coord.process_trade_queue = AsyncMock()
    _stub_market(coord, is_open=True)

    await coord._check_queue_on_market_open()

    coord.process_trade_queue.assert_not_awaited()
    assert coord._market_was_open is True


async def test_kiwoom_order_reports_full_fill_with_actual_avg_price():
    """A3: a fully-filled order reports the ACTUAL average fill price (ka10076),
    not the limit price assumed."""
    fake = _FakeKiwoomClient(
        ord_no="ORD1", filled_orders=[_filled("ORD1", 100, 50_100)]
    )
    result = await _order_agent(fake).execute_order(
        _buy_order(qty=100, price=50_000), split=False
    )

    assert result.filled_quantity == 100
    assert result.status == "filled"
    assert result.avg_price == 50_100


async def test_kiwoom_order_ignores_unrelated_fills():
    """A3: fills for a DIFFERENT order number must not be counted as this order's."""
    fake = _FakeKiwoomClient(
        ord_no="ORD1", filled_orders=[_filled("OTHER", 100, 50_000)]
    )
    result = await _order_agent(fake).execute_order(_buy_order(qty=100), split=False)

    assert result.filled_quantity == 0
    assert result.status == "pending"


async def test_fill_confirmation_bypasses_cache():
    """Review #1: fill confirmation must bypass the 5s ka10076 cache, else every
    retry within the TTL replays the same stale (pre-fill) snapshot."""
    seen = {}

    class Rec(_FakeKiwoomClient):
        async def get_filled_orders(
            self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True
        ):
            seen["use_cache"] = use_cache
            return list(self._filled_orders)

    fake = Rec(ord_no="ORD1", filled_orders=[_filled("ORD1", 100, 50_000)])
    await _order_agent(fake).execute_order(_buy_order(qty=100), split=False)

    assert seen.get("use_cache") is False


# -------------------------------------------
# Adversarial-review fixes (8 CONFIRMED)
# -------------------------------------------


def _alert(ticker="005930"):
    return TradingAlert(
        id="a1",
        alert_type=AlertType.STOP_LOSS_TRIGGERED,
        ticker=ticker,
        title="t",
        message="m",
    )


async def test_execute_stop_loss_retains_position_when_unfilled(temp_storage):
    """Review #8: user-confirmed EXECUTE_STOP_LOSS must keep the position when the
    sell does not fill — the A3 orphan bug remained on this manual path."""
    coord = _coord_with_position(qty=100)
    coord._state.pending_alerts.append(_alert())
    _stub_execute_order(coord, filled_quantity=0, status="rejected")

    await coord.handle_alert_action("a1", "EXECUTE_STOP_LOSS")

    assert any(p.ticker == "005930" for p in coord._state.positions)
    assert "005930" in coord.risk_monitor._watching


async def test_execute_take_profit_reduces_on_partial_fill(temp_storage):
    """Review #8: EXECUTE_TAKE_PROFIT with a partial fill reduces (keeps) the
    remainder instead of dropping the whole position."""
    coord = _coord_with_position(qty=100)
    coord._state.pending_alerts.append(_alert())
    _stub_execute_order(coord, filled_quantity=30)

    await coord.handle_alert_action("a1", "EXECUTE_TAKE_PROFIT")

    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 70


async def test_adjust_stop_loss_updates_managed_position(temp_storage):
    """Review #4: ADJUST_STOP_LOSS must update the ManagedPosition (not only the
    monitor's WatchConfig) so the adjustment survives a restart via persistence."""
    coord = _coord_with_position(qty=100)  # stop_loss starts at 68_875
    coord._state.pending_alerts.append(_alert())

    await coord.handle_alert_action("a1", "ADJUST_STOP_LOSS", {"stop_loss": 70_000})

    assert coord._state.positions[0].stop_loss == 70_000
    assert coord.risk_monitor._watching["005930"].stop_loss == 70_000


async def test_risk_monitor_partial_stop_keeps_reduced_position(temp_storage):
    """Review #5b: a risk-monitor auto-executed stop-loss with a partial fill must
    keep monitoring the reduced remainder — the monitor's own remove_position must
    no longer clobber the coordinator's _apply_sell_fill re-registration."""
    coord = _coord_with_position(qty=100)
    _stub_execute_order(coord, filled_quantity=40)
    config = coord.risk_monitor._watching["005930"]

    await coord.risk_monitor._execute_stop_loss("005930", config, 68_000)

    assert coord._state.positions[0].quantity == 60
    assert "005930" in coord.risk_monitor._watching


async def test_risk_monitor_full_stop_still_removes_position(temp_storage):
    """Review #5b guard: removing the monitor's own unconditional remove must NOT
    break the normal case — a FULL fill still drops the position and stops it
    being watched (via the coordinator's _apply_sell_fill)."""
    coord = _coord_with_position(qty=100)
    _stub_execute_order(coord, filled_quantity=100)
    config = coord.risk_monitor._watching["005930"]

    await coord.risk_monitor._execute_stop_loss("005930", config, 68_000)

    assert coord._state.positions == []
    assert "005930" not in coord.risk_monitor._watching


async def test_process_trade_queue_is_not_reentrant(temp_storage):
    """Review #6: concurrent process_trade_queue calls must not double-execute a
    queued trade (now reachable from start(), the scheduler, and manual calls)."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord.add_to_queue(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        reason="x",
        autonomous=False,
        quantity=5,
    )

    calls = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_approve(*args, **kwargs):
        calls.append(kwargs.get("ticker"))
        started.set()
        await release.wait()
        return AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=OrderSide.BUY,
            quantity=5,
            entry_price=50_000,
            estimated_amount=250_000,
            position_pct=1.0,
        )

    coord.on_trade_approved = slow_approve

    first = asyncio.create_task(coord.process_trade_queue())
    await started.wait()
    second = asyncio.create_task(coord.process_trade_queue())
    await asyncio.sleep(0)  # let the second run hit the re-entrancy guard
    release.set()
    await asyncio.gather(first, second)

    assert calls == ["005930"], "queued trade must execute exactly once"


async def test_startup_drain_persists_when_market_open(temp_storage):
    """Review #3: _persistence_active must be True BEFORE the startup queue drain,
    so trades executed at open are persisted (else a crash re-executes them)."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord.add_to_queue(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=50_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        reason="Market closed",
        autonomous=False,
        quantity=5,
    )
    _stub_market(coord, is_open=True)

    active_at_drain = {}
    orig = coord.process_trade_queue

    async def spy():
        active_at_drain["v"] = coord._persistence_active
        # Do not actually execute — just record the flag state at drain time.
        return None

    coord.process_trade_queue = spy
    await coord.start()
    await coord.stop()

    assert active_at_drain.get("v") is True
