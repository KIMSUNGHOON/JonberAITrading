"""P1-7: Batch KR ticker endpoint — POST /kr_stocks/tickers.

Before this, panels fanned out one GET /ticker/{stk_cd} request per symbol
(P0-T4 stopgap in WatchlistPanel) which strains the shared ~1.4 req/s
Kiwoom rate limiter and leaves prices stale. This endpoint reuses the
same single-quote data path (KiwoomClient.get_stock_info — same 3s TTL
cache, same shared rate limiter) but collapses N requests into one.

Direct-call style (no TestClient), matching test_kr_order_execution.py /
test_kr_trades.py conventions.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routes.kr_stocks import tickers as tickers_mod
from app.api.schemas.kr_stocks import KRStockTickerBatchRequest
from services.kiwoom.models import StockBasicInfo


def _info(stk_cd="005930", stk_nm="삼성전자", cur_prc=71000, prdy_ctrt=1.23):
    return StockBasicInfo(
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        cur_prc=cur_prc,
        prdy_vrss=500,
        prdy_ctrt=prdy_ctrt,
        acml_vol=1000,
        acml_tr_pbmn=71000000,
        strt_prc=70500,
        high_prc=71200,
        low_prc=70200,
    )


@patch("app.api.routes.kr_stocks.tickers.get_shared_kiwoom_client_async")
async def test_batch_returns_snapshots_for_all_valid_codes(mock_client_get):
    client = MagicMock()
    client.get_stock_info = AsyncMock(
        side_effect=lambda stk_cd: _info(stk_cd=stk_cd, stk_nm="X" + stk_cd)
    )
    mock_client_get.return_value = client

    resp = await tickers_mod.get_tickers(
        KRStockTickerBatchRequest(codes=["005930", "000660"])
    )

    assert resp.total == 2
    assert set(resp.tickers.keys()) == {"005930", "000660"}
    assert resp.tickers["005930"].cur_prc == 71000
    assert resp.tickers["005930"].stk_nm == "X005930"
    assert resp.tickers["000660"].cur_prc == 71000
    assert client.get_stock_info.await_count == 2


@patch("app.api.routes.kr_stocks.tickers.get_shared_kiwoom_client_async")
async def test_batch_degrades_failing_code_to_null_not_fabricated(mock_client_get):
    client = MagicMock()

    async def _side_effect(stk_cd):
        if stk_cd == "000660":
            raise RuntimeError("kiwoom rate limit")
        return _info(stk_cd=stk_cd)

    client.get_stock_info = AsyncMock(side_effect=_side_effect)
    mock_client_get.return_value = client

    resp = await tickers_mod.get_tickers(
        KRStockTickerBatchRequest(codes=["005930", "000660"])
    )

    assert resp.total == 1
    assert resp.tickers["005930"] is not None
    assert resp.tickers["005930"].cur_prc == 71000
    # Failing code is present but null — honest degrade, never fabricated.
    assert resp.tickers["000660"] is None


@patch("app.api.routes.kr_stocks.tickers.get_shared_kiwoom_client_async")
async def test_batch_unknown_code_format_degrades_to_null(mock_client_get):
    client = MagicMock()
    client.get_stock_info = AsyncMock(return_value=_info())
    mock_client_get.return_value = client

    resp = await tickers_mod.get_tickers(KRStockTickerBatchRequest(codes=["notacode"]))

    assert resp.total == 0
    assert resp.tickers["notacode"] is None
    # Invalid-format codes never even reach the client / rate limiter.
    client.get_stock_info.assert_not_awaited()


@patch("app.api.routes.kr_stocks.tickers.get_shared_kiwoom_client_async")
async def test_batch_rejects_over_max_size(mock_client_get):
    client = MagicMock()
    client.get_stock_info = AsyncMock(return_value=_info())
    mock_client_get.return_value = client

    codes = [str(100000 + i) for i in range(tickers_mod.MAX_BATCH_SIZE + 1)]

    with pytest.raises(HTTPException) as exc_info:
        await tickers_mod.get_tickers(KRStockTickerBatchRequest(codes=codes))

    assert exc_info.value.status_code == 400
    mock_client_get.assert_not_called()


@patch("app.api.routes.kr_stocks.tickers.get_shared_kiwoom_client_async")
async def test_batch_rejects_empty_codes(mock_client_get):
    with pytest.raises(HTTPException) as exc_info:
        await tickers_mod.get_tickers(KRStockTickerBatchRequest(codes=[]))

    assert exc_info.value.status_code == 400
    mock_client_get.assert_not_called()


@patch("app.api.routes.kr_stocks.tickers.get_shared_kiwoom_client_async")
async def test_batch_dedupes_repeated_codes_into_single_fetch(mock_client_get):
    client = MagicMock()
    client.get_stock_info = AsyncMock(return_value=_info())
    mock_client_get.return_value = client

    resp = await tickers_mod.get_tickers(
        KRStockTickerBatchRequest(codes=["005930", "005930", "005930"])
    )

    assert resp.total == 1
    assert client.get_stock_info.await_count == 1


@patch("app.api.routes.kr_stocks.tickers.get_shared_kiwoom_client_async")
async def test_batch_reuses_client_cache_path_not_bespoke_fetch(mock_client_get):
    """The batch route must call the SAME client.get_stock_info used by the
    single-quote route (which already honors the 3s TTL cache + shared rate
    limiter) — not some parallel fetch path that bypasses either."""
    client = MagicMock()
    client.get_stock_info = AsyncMock(return_value=_info())
    mock_client_get.return_value = client

    await tickers_mod.get_tickers(KRStockTickerBatchRequest(codes=["005930"]))

    client.get_stock_info.assert_awaited_once_with("005930")
