"""P1-1 wiring: ExecutionCoordinator fill choke points call record_trade_fill
with the correct side/qty/price, landing a real row in kr_stock_trades.

Trade-fill recording is gated by `_persistence_active` — the same rule
`_schedule_persist` already uses — so a coordinator built in a bare unit test
never touches real storage (the "automatic persistence is only active within
a session" contract documented on ExecutionCoordinator.__init__). These tests
opt in explicitly, exactly like a real start()ed session would.

Fixture pattern follows test_f3_fill_tracking.py / test_r5_p1_execution_reliability.py.
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

import services.storage_service as ss
from services.kiwoom.models import FilledOrder
from services.trading import trade_log
from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import (
    AllocationPlan,
    OrderRequest,
    OrderResult,
    OrderSide,
    TradingMode,
)
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


# ---------------------------------------------------------------------------
# on_trade_approved — SELL/REDUCE fills (PART 2 gap)
#
# `_execute_order` only records BUY fills — its SELL branch defers to
# `_apply_sell_fill`, the choke point every OTHER SELL caller
# (_execute_order_from_monitor, RiskMonitor triggers) invokes right after.
# `on_trade_approved` (agent-chat direct decisions + queue replays) never
# calls `_apply_sell_fill`, so its SELL/REDUCE fills recorded nothing.
# ---------------------------------------------------------------------------


def _open_session() -> MarketSession:
    return MarketSession(
        is_open=True,
        current_time=datetime.now(),
        next_open=None,
        next_close=None,
        message="open",
    )


def _sell_ready_coordinator(sell_quantity: int = 10) -> ExecutionCoordinator:
    """A coordinator wired to execute a SELL immediately (ACTIVE + market
    open), with persistence active as a real start()ed session would have."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._persistence_active = True
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(return_value=_open_session())
    coord._refresh_account_info = AsyncMock()
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=OrderSide.SELL,
            quantity=sell_quantity,
            entry_price=71_000,
            estimated_amount=sell_quantity * 71_000,
            position_pct=0,
            rationale="stub sell allocation",
            rebalance_orders=[],
        )
    )
    return coord


async def test_on_trade_approved_sell_records_trade(temp_storage):
    coord = _sell_ready_coordinator(sell_quantity=10)

    async def _exec(order):
        return OrderResult(
            order_id="ORD-SELL-1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=71_200,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    await coord.on_trade_approved(
        session_id="sess-sell-1",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=71_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["stk_cd"] == "005930"
    assert row["stk_nm"] == "삼성전자"
    assert row["side"] == "sell"
    assert row["executed_quantity"] == 10
    assert row["quantity"] == 10
    assert row["status"] == "completed"
    assert row["order_id"] == "ORD-SELL-1"
    assert row["session_id"] == "sess-sell-1"


async def test_on_trade_approved_reduce_partial_fill_records_partial_status(
    temp_storage,
):
    coord = _sell_ready_coordinator(sell_quantity=10)

    async def _exec(order):
        return OrderResult(
            order_id="ORD-SELL-2",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=4,
            avg_price=71_100,
            status="partial",
        )

    coord.order_agent.execute_order = _exec

    await coord.on_trade_approved(
        session_id="sess-sell-2",
        ticker="005930",
        stock_name="삼성전자",
        action="REDUCE",
        entry_price=71_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    assert rows[0]["side"] == "sell"
    assert rows[0]["status"] == "partial"
    assert rows[0]["executed_quantity"] == 4
    assert rows[0]["quantity"] == 10


async def test_on_trade_approved_sell_no_fill_records_nothing(temp_storage):
    coord = _sell_ready_coordinator(sell_quantity=10)

    async def _exec(order):
        return OrderResult(
            order_id="ORD-SELL-3",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=0,
            avg_price=0,
            status="rejected",
        )

    coord.order_agent.execute_order = _exec

    await coord.on_trade_approved(
        session_id="sess-sell-3",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=71_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )
    await _flush()

    assert await temp_storage.get_kr_stock_trades() == []


async def test_on_trade_approved_sell_gated_off_when_not_persistence_active(
    temp_storage,
):
    coord = _sell_ready_coordinator(sell_quantity=10)
    coord._persistence_active = False  # bare unit-test construction

    async def _exec(order):
        return OrderResult(
            order_id="ORD-SELL-4",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=71_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    await coord.on_trade_approved(
        session_id="sess-sell-4",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=71_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )
    await _flush()

    assert await temp_storage.get_kr_stock_trades() == []


async def test_on_trade_approved_buy_not_double_recorded(temp_storage):
    """BUY fills through on_trade_approved are already recorded inside
    `_execute_order` — the new SELL-recording branch must not ALSO record
    them, or a BUY approval would double-count."""
    coord = _sell_ready_coordinator(sell_quantity=10)
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=OrderSide.BUY,
            quantity=5,
            entry_price=70_000,
            estimated_amount=350_000,
            position_pct=1.0,
            rationale="stub buy allocation",
            rebalance_orders=[],
        )
    )

    async def _exec(order):
        return OrderResult(
            order_id="ORD-BUY-1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=70_000,
            status="filled",
        )

    coord.order_agent.execute_order = _exec

    await coord.on_trade_approved(
        session_id="sess-buy-1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=70_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
    )
    await _flush()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    assert rows[0]["side"] == "buy"


# ---------------------------------------------------------------------------
# Critical 1 (final review): split orders must record ONE ledger row PER
# PART (its own broker order_id/quantity/executed_quantity), not one
# aggregate row under part0's order_id. The pre-fix aggregate recording made
# `reconcile_trade_ledger`'s per-(order_id, stk_cd) EOD diff see every OTHER
# part's ord_no as entirely missing from the ledger and re-append it at
# EOD, double-counting both the ledger and its realized P&L (reviewer repro:
# a split SELL's placement-time fill recorded as one row, then the EOD
# reconciler treating the other broker order as "never recorded" — the
# review's 200->300 finding). These tests pin the fix end-to-end: per-part
# rows at placement time, and a subsequent `reconcile_trade_ledger` run
# against a broker snapshot that matches those parts exactly stays a true
# no-op (diff 0) instead of re-appending anything.
# ---------------------------------------------------------------------------


def _split_result(parts, *, total_quantity, side: OrderSide) -> OrderResult:
    total_filled = sum(p.filled_quantity for p in parts)
    status = (
        "filled" if total_filled >= total_quantity
        else "partial" if total_filled > 0
        else "pending"
    )
    return OrderResult(
        order_id=parts[0].order_id,
        ticker="005930",
        side=side,
        requested_quantity=total_quantity,
        filled_quantity=total_filled,
        avg_price=parts[0].avg_price,
        status=status,
        parts=parts,
    )


async def test_apply_sell_fill_split_records_one_row_per_part_and_reconcile_is_noop(
    temp_storage,
):
    coord = _active_coordinator()
    order = OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.SELL,
        quantity=200,
        price=250_000,
        session_id="sess-split-sell",
    )
    parts = [
        OrderResult(
            order_id="SPLIT-SELL-A", ticker="005930", side=OrderSide.SELL,
            requested_quantity=100, filled_quantity=100, avg_price=250_000,
            status="filled",
        ),
        OrderResult(
            order_id="SPLIT-SELL-B", ticker="005930", side=OrderSide.SELL,
            requested_quantity=100, filled_quantity=60, avg_price=250_000,
            status="partial",
        ),
    ]
    result = _split_result(parts, total_quantity=200, side=OrderSide.SELL)
    assert result.filled_quantity == 160  # sanity: matches the review's shape

    coord._apply_sell_fill("005930", result.filled_quantity, order=order, result=result)
    await _flush()

    rows = await temp_storage.get_kr_stock_trades(stk_cd="005930")
    assert len(rows) == 2
    by_order_id = {r["order_id"]: r for r in rows}
    assert by_order_id["SPLIT-SELL-A"]["quantity"] == 100
    assert by_order_id["SPLIT-SELL-A"]["executed_quantity"] == 100
    assert by_order_id["SPLIT-SELL-A"]["status"] == "completed"
    assert by_order_id["SPLIT-SELL-B"]["quantity"] == 100
    assert by_order_id["SPLIT-SELL-B"]["executed_quantity"] == 60
    assert by_order_id["SPLIT-SELL-B"]["status"] == "partial"
    assert sum(r["executed_quantity"] for r in rows) == 160

    # EOD: the broker's cumulative daily snapshot for the day exactly matches
    # what each part already filled (no further intraday fills beyond
    # placement) -> reconcile must be a genuine no-op, not a re-append.
    from datetime import date

    from services.kiwoom.models import FilledOrder
    from services.trading.ledger_reconcile import reconcile_trade_ledger

    class _EodKiwoom:
        async def get_filled_orders(self, use_cache=True):
            return [
                FilledOrder(
                    ord_no="SPLIT-SELL-A", stk_cd="005930", stk_nm="삼성전자",
                    ccld_qty=100, ccld_uv=250_000, ccld_amt=100 * 250_000,
                    ccld_dt="", ccld_tm="", buy_sell_tp="2",
                ),
                FilledOrder(
                    ord_no="SPLIT-SELL-B", stk_cd="005930", stk_nm="삼성전자",
                    ccld_qty=60, ccld_uv=250_000, ccld_amt=60 * 250_000,
                    ccld_dt="", ccld_tm="", buy_sell_tp="2",
                ),
            ]

    trade_date = date.today().strftime("%Y-%m-%d")
    reconcile_result = await reconcile_trade_ledger(_EodKiwoom(), temp_storage, trade_date)

    assert reconcile_result == {"checked": 2, "missing_orders": 0, "upserted_qty": 0}

    rows_after = await temp_storage.get_kr_stock_trades(stk_cd="005930")
    assert len(rows_after) == 2  # nothing re-appended
    assert sum(r["executed_quantity"] for r in rows_after) == 160  # stays 160, never 220


async def test_execute_order_buy_split_records_one_row_per_part(temp_storage):
    """BUY counterpart, exercised through the REAL `_execute_order` body
    (only `order_agent.execute_order` is stubbed) — unlike
    test_f3_fill_tracking.py's split-registration tests, which stub
    `_execute_order` itself and so never reach its ledger-write branch."""
    coord = _active_coordinator()
    parts = [
        OrderResult(
            order_id="SPLIT-BUY-A", ticker="005930", side=OrderSide.BUY,
            requested_quantity=100, filled_quantity=100, avg_price=250_000,
            status="filled",
        ),
        OrderResult(
            order_id="SPLIT-BUY-B", ticker="005930", side=OrderSide.BUY,
            requested_quantity=100, filled_quantity=75, avg_price=250_000,
            status="partial",
        ),
    ]
    result = _split_result(parts, total_quantity=200, side=OrderSide.BUY)

    async def _exec(order):
        return result

    coord.order_agent.execute_order = _exec

    order = OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.BUY,
        quantity=200,
        price=250_000,
        session_id="sess-split-buy",
    )
    await coord._execute_order(order)
    await _flush()

    rows = await temp_storage.get_kr_stock_trades(stk_cd="005930")
    assert len(rows) == 2
    by_order_id = {r["order_id"]: r for r in rows}
    assert by_order_id["SPLIT-BUY-A"]["quantity"] == 100
    assert by_order_id["SPLIT-BUY-A"]["executed_quantity"] == 100
    assert by_order_id["SPLIT-BUY-A"]["status"] == "completed"
    assert by_order_id["SPLIT-BUY-B"]["quantity"] == 100
    assert by_order_id["SPLIT-BUY-B"]["executed_quantity"] == 75
    assert by_order_id["SPLIT-BUY-B"]["status"] == "partial"
    assert sum(r["executed_quantity"] for r in rows) == 175


async def test_apply_sell_fill_split_skips_zero_filled_parts(temp_storage):
    """A part that placed but filled 0 (still pending at the broker) must
    not get a ledger row yet — only parts with filled_quantity > 0 record;
    the zero-fill part is picked up later by the fill tracker/poll path."""
    coord = _active_coordinator()
    order = OrderRequest(
        ticker="005930", side=OrderSide.SELL, quantity=200, price=250_000,
        session_id="sess-split-zero",
    )
    parts = [
        OrderResult(
            order_id="SPLIT-Z-A", ticker="005930", side=OrderSide.SELL,
            requested_quantity=100, filled_quantity=40, avg_price=250_000,
            status="partial",
        ),
        OrderResult(
            order_id="SPLIT-Z-B", ticker="005930", side=OrderSide.SELL,
            requested_quantity=100, filled_quantity=0, avg_price=0,
            status="pending",
        ),
    ]
    result = _split_result(parts, total_quantity=200, side=OrderSide.SELL)

    coord._apply_sell_fill("005930", result.filled_quantity, order=order, result=result)
    await _flush()

    rows = await temp_storage.get_kr_stock_trades(stk_cd="005930")
    assert len(rows) == 1
    assert rows[0]["order_id"] == "SPLIT-Z-A"
    assert rows[0]["executed_quantity"] == 40

