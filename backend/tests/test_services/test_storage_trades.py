"""P1-1: kr_stock_trades storage round-trip.

The 거래내역(/trades) tab was a permanent empty shell — StorageService had no
get_kr_stock_trades/get_kr_stock_trades_count methods at all (the route
masked the missing methods as an empty list via `except AttributeError`).
These tests pin the real storage methods against an isolated SQLite (same
temp-db pattern as test_r5_p1_execution_reliability.py's `temp_storage`
fixture).
"""

from datetime import datetime

import pytest
import pytest_asyncio

import services.storage_service as ss

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def temp_storage(tmp_path):
    """Isolated SQLite storage — no need to touch the module singleton here
    since these tests call the instance's methods directly."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    yield storage


def _trade(**overrides) -> dict:
    record = {
        "id": "t1",
        "session_id": "sess-1",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "side": "buy",
        "order_type": "limit",
        "price": 70000,
        "quantity": 10,
        "executed_quantity": 10,
        "fee": 0,
        "total_krw": 700000,
        "status": "completed",
        "order_id": "ORD1",
        "created_at": datetime(2026, 7, 14, 9, 5, 0),
    }
    record.update(overrides)
    return record


async def test_add_and_get_single_trade_round_trips(temp_storage):
    ok = await temp_storage.add_kr_stock_trade(_trade())
    assert ok is True

    fetched = await temp_storage.get_kr_stock_trade("t1")
    assert fetched is not None
    assert fetched["stk_cd"] == "005930"
    assert fetched["stk_nm"] == "삼성전자"
    assert fetched["side"] == "buy"
    assert fetched["order_type"] == "limit"
    assert fetched["price"] == 70000
    assert fetched["quantity"] == 10
    assert fetched["executed_quantity"] == 10
    assert fetched["total_krw"] == 700000
    assert fetched["status"] == "completed"
    assert fetched["order_id"] == "ORD1"
    assert fetched["session_id"] == "sess-1"


async def test_get_trade_missing_returns_none(temp_storage):
    assert await temp_storage.get_kr_stock_trade("nope") is None


async def test_list_trades_ordered_newest_first(temp_storage):
    await temp_storage.add_kr_stock_trade(
        _trade(id="t1", created_at=datetime(2026, 7, 14, 9, 0, 0))
    )
    await temp_storage.add_kr_stock_trade(
        _trade(id="t2", created_at=datetime(2026, 7, 14, 9, 5, 0))
    )
    await temp_storage.add_kr_stock_trade(
        _trade(id="t3", created_at=datetime(2026, 7, 14, 9, 10, 0))
    )

    trades = await temp_storage.get_kr_stock_trades(limit=20, offset=0)
    assert [t["id"] for t in trades] == ["t3", "t2", "t1"]


async def test_list_trades_filters_by_stk_cd(temp_storage):
    await temp_storage.add_kr_stock_trade(_trade(id="t1", stk_cd="005930"))
    await temp_storage.add_kr_stock_trade(_trade(id="t2", stk_cd="000660"))

    trades = await temp_storage.get_kr_stock_trades(stk_cd="000660")
    assert [t["id"] for t in trades] == ["t2"]


async def test_list_trades_pagination(temp_storage):
    for i in range(5):
        await temp_storage.add_kr_stock_trade(
            _trade(id=f"t{i}", created_at=datetime(2026, 7, 14, 9, i, 0))
        )

    page1 = await temp_storage.get_kr_stock_trades(limit=2, offset=0)
    page2 = await temp_storage.get_kr_stock_trades(limit=2, offset=2)
    assert [t["id"] for t in page1] == ["t4", "t3"]
    assert [t["id"] for t in page2] == ["t2", "t1"]


async def test_get_trades_count_total_and_filtered(temp_storage):
    await temp_storage.add_kr_stock_trade(_trade(id="t1", stk_cd="005930"))
    await temp_storage.add_kr_stock_trade(_trade(id="t2", stk_cd="005930"))
    await temp_storage.add_kr_stock_trade(_trade(id="t3", stk_cd="000660"))

    assert await temp_storage.get_kr_stock_trades_count() == 3
    assert await temp_storage.get_kr_stock_trades_count(stk_cd="005930") == 2
    assert await temp_storage.get_kr_stock_trades_count(stk_cd="999999") == 0


async def test_optional_fields_default_sensibly(temp_storage):
    minimal = _trade(id="t-min")
    del minimal["session_id"]
    del minimal["stk_nm"]
    del minimal["order_id"]
    del minimal["fee"]

    ok = await temp_storage.add_kr_stock_trade(minimal)
    assert ok is True

    fetched = await temp_storage.get_kr_stock_trade("t-min")
    assert fetched["session_id"] is None
    assert fetched["stk_nm"] is None
    assert fetched["order_id"] is None
    assert fetched["fee"] == 0


async def test_empty_table_returns_empty_list_and_zero_count(temp_storage):
    assert await temp_storage.get_kr_stock_trades() == []
    assert await temp_storage.get_kr_stock_trades_count() == 0
