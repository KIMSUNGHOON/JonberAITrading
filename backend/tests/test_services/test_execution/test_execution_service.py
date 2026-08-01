"""P5 S5b: broker-agnostic ExecutionService + Kiwoom adapter.

Verifies the single execution path maps a uniform place_order(side, qty, price,
order_type) onto each broker's native call, and normalizes the response to
ExecutionResult. Mock-only: broker clients are mocked, no real order.

(2026-08-01 Upbit 제거: Upbit 어댑터·`MarketKind.COIN` 경로 테스트는
services/execution/adapters.py의 UpbitExecutionAdapter와 함께 제거했다 —
UpbitClient가 더 이상 존재하지 않아 프로덕션에서 도달 불가능했고, 이 테스트들은
MagicMock으로만 그린을 유지하고 있었다.)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.execution import (
    ExecutionService,
    KiwoomExecutionAdapter,
    ExecutionSide,
    ExecutionOrderType,
    MarketKind,
)
from services.kiwoom.models import OrderResponse, OrderType as KiwoomOrderType


# ---- Kiwoom adapter ----

async def test_kiwoom_adapter_buy_limit_maps_to_place_buy_order():
    client = MagicMock()
    client.place_buy_order = AsyncMock(return_value=OrderResponse(ord_no="K1", return_code=0, return_msg="정상"))
    client.place_sell_order = AsyncMock(return_value=OrderResponse(ord_no="", return_code=0, return_msg=""))
    result = await KiwoomExecutionAdapter(client).place(
        ticker="005930", side=ExecutionSide.BUY, qty=10, price=70000, order_type=ExecutionOrderType.LIMIT
    )
    client.place_buy_order.assert_awaited_once()
    client.place_sell_order.assert_not_awaited()
    kwargs = client.place_buy_order.await_args.kwargs
    assert kwargs["stk_cd"] == "005930"
    assert kwargs["qty"] == 10
    assert kwargs["price"] == 70000
    assert kwargs["order_type"] == KiwoomOrderType.LIMIT
    assert result.success is True
    assert result.order_id == "K1"
    assert result.status == "pending"


async def test_kiwoom_adapter_market_sell_sends_no_price():
    client = MagicMock()
    client.place_sell_order = AsyncMock(return_value=OrderResponse(ord_no="K2", return_code=0, return_msg=""))
    result = await KiwoomExecutionAdapter(client).place(
        ticker="005930", side=ExecutionSide.SELL, qty=5, order_type=ExecutionOrderType.MARKET
    )
    kwargs = client.place_sell_order.await_args.kwargs
    assert kwargs["price"] is None
    assert kwargs["order_type"] == KiwoomOrderType.MARKET
    assert result.order_id == "K2"


async def test_kiwoom_adapter_rejected_on_nonzero_return_code():
    client = MagicMock()
    client.place_buy_order = AsyncMock(return_value=OrderResponse(ord_no="", return_code=1, return_msg="거부"))
    result = await KiwoomExecutionAdapter(client).place(
        ticker="005930", side=ExecutionSide.BUY, qty=1, price=100, order_type=ExecutionOrderType.LIMIT
    )
    assert result.success is False
    assert result.status == "rejected"
    assert result.message == "거부"


# ---- Service routing ----

async def test_service_routes_by_market():
    kr_client = MagicMock()
    kr_client.place_buy_order = AsyncMock(return_value=OrderResponse(ord_no="K", return_code=0, return_msg=""))
    service = ExecutionService(kr_stock=KiwoomExecutionAdapter(kr_client))
    r_kr = await service.place_order(
        market=MarketKind.KR_STOCK, ticker="005930", side=ExecutionSide.BUY, qty=1, price=100
    )
    assert r_kr.order_id == "K"
    kr_client.place_buy_order.assert_awaited_once()


async def test_service_raises_when_no_adapter_registered_for_market():
    # Renamed from test_service_unknown_market_raises (리뷰 지적): with
    # MarketKind down to one member there is no "unknown market" left to
    # construct — this now exercises the same ValueError path via an
    # unregistered adapter (kr_stock omitted) instead.
    service = ExecutionService()
    with pytest.raises(ValueError):
        await service.place_order(
            market=MarketKind.KR_STOCK, ticker="005930", side=ExecutionSide.BUY, qty=1
        )
