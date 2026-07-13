"""P1-1: services.trading.trade_log — record_trade_fill core + fire-and-forget
wrapper.

`record_trade_fill_async` is the single write path every fill choke point
(coordinator._execute_order / _apply_sell_fill / _poll_tracked_fills, and the
LangGraph execution node) funnels through — a storage failure here must never
raise, since recording a trade must never break the trading flow.
`record_trade_fill` is the fire-and-forget wrapper actually called from those
choke points; `wait_for_pending_trade_fill_writes` lets tests flush it
deterministically instead of racing the event loop.
"""

from unittest.mock import MagicMock

import pytest

import services.storage_service as ss
from services.trading import trade_log

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _kwargs(**overrides) -> dict:
    base = dict(
        stk_cd="005930",
        side="buy",
        order_type="limit",
        price=70000,
        quantity=10,
        executed_quantity=10,
        status="completed",
        stk_nm="삼성전자",
        session_id="sess-1",
        order_id="ORD1",
    )
    base.update(overrides)
    return base


async def test_record_trade_fill_async_writes_expected_row(temp_storage):
    await trade_log.record_trade_fill_async(**_kwargs())

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["stk_cd"] == "005930"
    assert row["side"] == "buy"
    assert row["order_type"] == "limit"
    assert row["price"] == 70000
    assert row["quantity"] == 10
    assert row["executed_quantity"] == 10
    assert row["total_krw"] == 700000  # derived: price * executed_quantity
    assert row["status"] == "completed"
    assert row["order_id"] == "ORD1"
    assert row["session_id"] == "sess-1"


async def test_record_trade_fill_async_respects_explicit_total_krw_and_fee(
    temp_storage,
):
    await trade_log.record_trade_fill_async(**_kwargs(total_krw=699_500, fee=500))

    rows = await temp_storage.get_kr_stock_trades()
    assert rows[0]["total_krw"] == 699_500
    assert rows[0]["fee"] == 500


async def test_record_trade_fill_async_never_raises_on_storage_failure(monkeypatch):
    async def _boom():
        raise RuntimeError("db boom")

    monkeypatch.setattr(ss, "get_storage_service", _boom)

    # Must swallow the failure — a recording failure can never break the
    # caller's trading flow.
    await trade_log.record_trade_fill_async(**_kwargs())


async def test_record_trade_fill_schedules_background_task_and_writes(temp_storage):
    trade_log.record_trade_fill(**_kwargs(stk_cd="000660"))
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_stock_trades(stk_cd="000660")
    assert len(rows) == 1


async def test_record_trade_fill_without_running_loop_logs_and_does_not_raise(
    monkeypatch,
):
    monkeypatch.setattr(
        trade_log.asyncio,
        "get_running_loop",
        MagicMock(side_effect=RuntimeError("no running loop")),
    )

    # Must not raise even without an event loop to schedule onto.
    trade_log.record_trade_fill(**_kwargs())
