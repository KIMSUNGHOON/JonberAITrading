"""P1-1: /trades route — real storage methods, no more AttributeError masking.

Before this fix, StorageService had no get_kr_stock_trades /
get_kr_stock_trades_count / get_kr_stock_trade methods at all; the route
caught the resulting AttributeError and silently returned an empty list (or
404) — the 거래내역 tab was a permanent empty shell no matter how many trades
executed. These tests prove records written to storage actually come back
out through the route, and that a real storage failure now surfaces honestly
instead of being masked.

Direct-call style (no TestClient), matching test_kr_order_execution.py.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routes.kr_stocks import trades as trades_mod


def _row(**overrides) -> dict:
    row = {
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
    row.update(overrides)
    return row


@patch("services.storage_service.get_storage_service")
async def test_get_trades_returns_recorded_rows(mock_get_storage):
    storage = MagicMock()
    storage.get_kr_stock_trades = AsyncMock(return_value=[_row()])
    storage.get_kr_stock_trades_count = AsyncMock(return_value=1)
    mock_get_storage.return_value = storage

    resp = await trades_mod.get_trades(stk_cd=None, page=1, limit=20)

    assert resp.total == 1
    assert len(resp.trades) == 1
    assert resp.trades[0].id == "t1"
    assert resp.trades[0].stk_cd == "005930"
    assert resp.trades[0].side == "buy"
    assert resp.trades[0].quantity == 10
    assert resp.trades[0].executed_quantity == 10


@patch("services.storage_service.get_storage_service")
async def test_get_trades_empty_when_nothing_recorded(mock_get_storage):
    storage = MagicMock()
    storage.get_kr_stock_trades = AsyncMock(return_value=[])
    storage.get_kr_stock_trades_count = AsyncMock(return_value=0)
    mock_get_storage.return_value = storage

    resp = await trades_mod.get_trades(stk_cd=None, page=1, limit=20)

    assert resp.trades == []
    assert resp.total == 0


@patch("services.storage_service.get_storage_service")
async def test_get_trades_passes_pagination_and_filter_through(mock_get_storage):
    storage = MagicMock()
    storage.get_kr_stock_trades = AsyncMock(return_value=[])
    storage.get_kr_stock_trades_count = AsyncMock(return_value=0)
    mock_get_storage.return_value = storage

    await trades_mod.get_trades(stk_cd="005930", page=3, limit=10)

    storage.get_kr_stock_trades.assert_awaited_once_with(
        stk_cd="005930", limit=10, offset=20
    )
    storage.get_kr_stock_trades_count.assert_awaited_once_with(stk_cd="005930")


@patch("services.storage_service.get_storage_service")
async def test_get_trades_real_failure_is_no_longer_masked(mock_get_storage):
    """Pre-fix: a missing storage method raised AttributeError, caught and
    silently turned into an empty list. Now that the methods exist, ANY
    failure (e.g. a genuine storage error) must propagate honestly instead
    of being swallowed."""
    storage = MagicMock()
    storage.get_kr_stock_trades = AsyncMock(side_effect=RuntimeError("db down"))
    mock_get_storage.return_value = storage

    with pytest.raises(RuntimeError):
        await trades_mod.get_trades(stk_cd=None, page=1, limit=20)


@patch("services.storage_service.get_storage_service")
async def test_get_trade_by_id_returns_record(mock_get_storage):
    storage = MagicMock()
    storage.get_kr_stock_trade = AsyncMock(return_value=_row())
    mock_get_storage.return_value = storage

    resp = await trades_mod.get_trade("t1")

    assert resp.id == "t1"
    assert resp.stk_cd == "005930"


@patch("services.storage_service.get_storage_service")
async def test_get_trade_by_id_missing_returns_404(mock_get_storage):
    storage = MagicMock()
    storage.get_kr_stock_trade = AsyncMock(return_value=None)
    mock_get_storage.return_value = storage

    with pytest.raises(HTTPException) as exc_info:
        await trades_mod.get_trade("nope")

    assert exc_info.value.status_code == 404
