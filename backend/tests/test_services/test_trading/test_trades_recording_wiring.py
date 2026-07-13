"""P1-1 wiring: ExecutionCoordinator fill choke points call record_trade_fill
with the correct side/qty/price, landing a real row in kr_stock_trades.

Trade-fill recording is gated by `_persistence_active` — the same rule
`_schedule_persist` already uses — so a coordinator built in a bare unit test
never touches real storage (the "automatic persistence is only active within
a session" contract documented on ExecutionCoordinator.__init__). These tests
opt in explicitly, exactly like a real start()ed session would.

Fixture pattern follows test_f3_fill_tracking.py / test_r5_p1_execution_reliability.py.
"""

from datetime import date

import pytest
import pytest_asyncio

import services.storage_service as ss
from services.kiwoom.models import FilledOrder
from services.trading import trade_log
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import OrderRequest, OrderResult, OrderSide
from services.trading.pending_order_tracker import TrackedOrder

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _active_coordinator(kiwoom_client=None) -> ExecutionCoordinator:
    """A coordinator with persistence active, as a real start()ed session
    would have — without paying for start()'s account refresh/market checks."""
    coord = ExecutionCoordinator(kiwoom_client=kiwoom_client)
    coord._persistence_active = True
    return coord


async def _flush():
    await trade_log.wait_for_pending_trade_fill_writes()


# ---------------------------------------------------------------------------
# _execute_order — BUY placement fills
# ---------------------------------------------------------------------------


async def test_execute_order_buy_fill_records_trade(temp_storage):
    coord = _active_coordinator()

    async def _exec(order):
        return OrderResult(
            order_id="ORD1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70500,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    order = OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        quantity=10,
        price=70000,
        session_id="sess-1",
    )
    await coord._execute_order(order)
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["stk_cd"] == "005930"
    assert row["stk_nm"] == "삼성전자"
    assert row["side"] == "buy"
    assert row["price"] == 70500
    assert row["quantity"] == 10
    assert row["executed_quantity"] == 10
    assert row["status"] == "completed"
    assert row["order_id"] == "ORD1"
    assert row["session_id"] == "sess-1"


async def test_execute_order_buy_partial_fill_records_partial_status(temp_storage):
    coord = _active_coordinator()

    async def _exec(order):
        return OrderResult(
            order_id="ORD1b",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=4,
            avg_price=70200,
            status="partial",
        )

    coord.order_agent.execute_order = _exec

    order = OrderRequest(ticker="005930", side=OrderSide.BUY, quantity=10, price=70000)
    await coord._execute_order(order)
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert rows[0]["status"] == "partial"
    assert rows[0]["quantity"] == 10
    assert rows[0]["executed_quantity"] == 4


async def test_execute_order_sell_fill_not_recorded_here(temp_storage):
    """SELL fills are recorded once via _apply_sell_fill — _execute_order must
    not ALSO record them, or every SELL caller (which invokes both) would
    double-count."""
    coord = _active_coordinator()

    async def _exec(order):
        return OrderResult(
            order_id="ORD2",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    order = OrderRequest(ticker="005930", side=OrderSide.SELL, quantity=10, price=70000)
    await coord._execute_order(order)
    await _flush()

    assert await temp_storage.get_kr_stock_trades() == []


async def test_execute_order_unfilled_records_nothing(temp_storage):
    coord = _active_coordinator()

    async def _exec(order):
        return OrderResult(
            order_id="ORD3",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=0,
            avg_price=0,
            status="rejected",
        )

    coord.order_agent.execute_order = _exec

    order = OrderRequest(ticker="005930", side=OrderSide.BUY, quantity=10, price=70000)
    await coord._execute_order(order)
    await _flush()

    assert await temp_storage.get_kr_stock_trades() == []


async def test_execute_order_gated_off_when_not_persistence_active(temp_storage):
    """A coordinator that never started a session (bare unit-test construction)
    must not write to storage — mirrors _schedule_persist's own gate."""
    coord = ExecutionCoordinator(kiwoom_client=None)  # _persistence_active=False

    async def _exec(order):
        return OrderResult(
            order_id="ORD4",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    order = OrderRequest(ticker="005930", side=OrderSide.BUY, quantity=10, price=70000)
    await coord._execute_order(order)
    await _flush()

    assert await temp_storage.get_kr_stock_trades() == []


# ---------------------------------------------------------------------------
# _apply_sell_fill — SELL fills
# ---------------------------------------------------------------------------


async def test_apply_sell_fill_records_trade(temp_storage):
    coord = _active_coordinator()
    order = OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.SELL,
        quantity=10,
        price=71000,
        session_id="sess-2",
    )
    result = OrderResult(
        order_id="ORD5",
        ticker="005930",
        side=OrderSide.SELL,
        requested_quantity=10,
        filled_quantity=10,
        avg_price=71200,
        status="filled",
    )

    coord._apply_sell_fill("005930", 10, order=order, result=result)
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["stk_cd"] == "005930"
    assert row["side"] == "sell"
    assert row["price"] == 71200
    assert row["quantity"] == 10
    assert row["executed_quantity"] == 10
    assert row["status"] == "completed"
    assert row["order_id"] == "ORD5"
    assert row["session_id"] == "sess-2"


async def test_apply_sell_fill_partial_records_partial_status(temp_storage):
    coord = _active_coordinator()
    order = OrderRequest(ticker="005930", side=OrderSide.SELL, quantity=10, price=71000)
    result = OrderResult(
        order_id="ORD6",
        ticker="005930",
        side=OrderSide.SELL,
        requested_quantity=10,
        filled_quantity=4,
        avg_price=71100,
        status="partial",
    )

    coord._apply_sell_fill("005930", 4, order=order, result=result)
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert rows[0]["status"] == "partial"
    assert rows[0]["executed_quantity"] == 4
    assert rows[0]["quantity"] == 10


async def test_apply_sell_fill_no_fill_records_nothing(temp_storage):
    coord = _active_coordinator()
    order = OrderRequest(ticker="005930", side=OrderSide.SELL, quantity=10, price=71000)
    result = OrderResult(
        order_id="ORD7",
        ticker="005930",
        side=OrderSide.SELL,
        requested_quantity=10,
        filled_quantity=0,
        avg_price=0,
        status="rejected",
    )

    coord._apply_sell_fill("005930", 0, order=order, result=result)
    await _flush()

    assert await temp_storage.get_kr_stock_trades() == []


async def test_apply_sell_fill_gated_off_when_not_persistence_active(temp_storage):
    coord = ExecutionCoordinator(kiwoom_client=None)  # _persistence_active=False
    order = OrderRequest(ticker="005930", side=OrderSide.SELL, quantity=10, price=71000)
    result = OrderResult(
        order_id="ORD8",
        ticker="005930",
        side=OrderSide.SELL,
        requested_quantity=10,
        filled_quantity=10,
        avg_price=71000,
        status="filled",
    )

    coord._apply_sell_fill("005930", 10, order=order, result=result)
    await _flush()

    assert await temp_storage.get_kr_stock_trades() == []


# ---------------------------------------------------------------------------
# _poll_tracked_fills — F3 post-fill discovery
# ---------------------------------------------------------------------------


class _FakeKiwoomClient:
    def __init__(self, filled_orders):
        self._filled_orders = filled_orders

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


async def test_poll_tracked_fills_full_fill_records_completed_trade(temp_storage):
    client = _FakeKiwoomClient([_filled("ORD9", 48, 260_000)])
    coord = _active_coordinator(kiwoom_client=client)
    coord.fill_tracker.register(
        TrackedOrder(
            ord_no="ORD9",
            ticker="005930",
            stock_name="삼성전자",
            side="buy",
            total_quantity=48,
            filled_quantity=0,
            limit_price=260_000,
            source_session_id="sess-3",
            trade_date=date.today().strftime("%Y%m%d"),
        )
    )

    await coord._poll_tracked_fills()
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["stk_cd"] == "005930"
    assert row["side"] == "buy"
    assert row["order_type"] == "limit"
    assert row["price"] == 260_000
    assert row["quantity"] == 48
    assert row["executed_quantity"] == 48
    assert row["status"] == "completed"
    assert row["order_id"] == "ORD9"
    assert row["session_id"] == "sess-3"


async def test_poll_tracked_fills_partial_records_partial_status(temp_storage):
    client = _FakeKiwoomClient([_filled("ORD10", 20, 260_000)])
    coord = _active_coordinator(kiwoom_client=client)
    coord.fill_tracker.register(
        TrackedOrder(
            ord_no="ORD10",
            ticker="005930",
            stock_name="삼성전자",
            side="buy",
            total_quantity=48,
            filled_quantity=0,
            limit_price=260_000,
            trade_date=date.today().strftime("%Y%m%d"),
        )
    )

    await coord._poll_tracked_fills()
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert rows[0]["status"] == "partial"
    assert rows[0]["executed_quantity"] == 20
    assert rows[0]["quantity"] == 48


async def test_poll_tracked_fills_gated_off_when_not_persistence_active(temp_storage):
    client = _FakeKiwoomClient([_filled("ORD11", 48, 260_000)])
    coord = ExecutionCoordinator(kiwoom_client=client)  # _persistence_active=False
    coord.fill_tracker.register(
        TrackedOrder(
            ord_no="ORD11",
            ticker="005930",
            stock_name="삼성전자",
            side="buy",
            total_quantity=48,
            filled_quantity=0,
            limit_price=260_000,
            trade_date=date.today().strftime("%Y%m%d"),
        )
    )

    await coord._poll_tracked_fills()
    await _flush()

    assert await temp_storage.get_kr_stock_trades() == []
