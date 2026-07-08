"""P5 S5b: broker-agnostic ExecutionService + Kiwoom/Upbit adapters.

Verifies the single execution path maps a uniform place_order(side, qty, price,
order_type) onto each broker's native call, and normalizes the response to
ExecutionResult. Mock-only: broker clients are mocked, no real order.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.execution import (
    ExecutionService,
    KiwoomExecutionAdapter,
    UpbitExecutionAdapter,
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


# ---- Upbit adapter ----

async def test_upbit_adapter_buy_limit_maps_to_bid():
    client = MagicMock()
    order = MagicMock(uuid="U1", state="wait")
    client.place_order = AsyncMock(return_value=order)
    result = await UpbitExecutionAdapter(client).place(
        ticker="KRW-BTC", side=ExecutionSide.BUY, qty=0.1, price=90_000_000, order_type=ExecutionOrderType.LIMIT
    )
    kwargs = client.place_order.await_args.kwargs
    assert kwargs["market"] == "KRW-BTC"
    assert kwargs["side"] == "bid"
    assert kwargs["ord_type"] == "limit"
    assert result.success is True
    assert result.order_id == "U1"


async def test_upbit_adapter_market_buy_uses_price_ord_type():
    client = MagicMock()
    client.place_order = AsyncMock(return_value=MagicMock(uuid="U2", state="wait"))
    await UpbitExecutionAdapter(client).place(
        ticker="KRW-BTC", side=ExecutionSide.BUY, qty=None, price=100000, order_type=ExecutionOrderType.MARKET
    )
    assert client.place_order.await_args.kwargs["ord_type"] == "price"
    assert client.place_order.await_args.kwargs["side"] == "bid"


async def test_upbit_adapter_market_sell_uses_market_ord_type():
    client = MagicMock()
    client.place_order = AsyncMock(return_value=MagicMock(uuid="U3", state="done"))
    await UpbitExecutionAdapter(client).place(
        ticker="KRW-BTC", side=ExecutionSide.SELL, qty=0.1, order_type=ExecutionOrderType.MARKET
    )
    assert client.place_order.await_args.kwargs["ord_type"] == "market"
    assert client.place_order.await_args.kwargs["side"] == "ask"


# ---- Service routing ----

async def test_service_routes_by_market():
    kr_client = MagicMock()
    kr_client.place_buy_order = AsyncMock(return_value=OrderResponse(ord_no="K", return_code=0, return_msg=""))
    up_client = MagicMock()
    up_client.place_order = AsyncMock(return_value=MagicMock(uuid="U", state="wait"))
    service = ExecutionService(
        kr_stock=KiwoomExecutionAdapter(kr_client),
        coin=UpbitExecutionAdapter(up_client),
    )
    r_kr = await service.place_order(
        market=MarketKind.KR_STOCK, ticker="005930", side=ExecutionSide.BUY, qty=1, price=100
    )
    r_coin = await service.place_order(
        market=MarketKind.COIN, ticker="KRW-BTC", side=ExecutionSide.BUY, qty=0.1, price=90_000_000
    )
    assert r_kr.order_id == "K"
    assert r_coin.order_id == "U"
    kr_client.place_buy_order.assert_awaited_once()
    up_client.place_order.assert_awaited_once()


async def test_service_unknown_market_raises():
    service = ExecutionService(kr_stock=KiwoomExecutionAdapter(MagicMock()))
    with pytest.raises(ValueError):
        await service.place_order(
            market=MarketKind.COIN, ticker="KRW-BTC", side=ExecutionSide.BUY, qty=1
        )
