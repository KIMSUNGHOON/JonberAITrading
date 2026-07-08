"""P5 S1: OrderAgent Kiwoom execution must dispatch place_buy_order/place_sell_order
and parse the returned OrderResponse.

Pre-fix, _execute_kiwoom_order called a nonexistent self.kiwoom.place_order(...) and
dict-parsed response.get('rt_cd') — so every approved KR BUY/SELL AttributeError'd and
was silently rejected. Mock-only (spec'd client): never touches a live broker.
"""

from unittest.mock import AsyncMock, MagicMock

from services.trading.order_agent import OrderAgent
from services.trading.models import OrderRequest, OrderSide, OrderType
from services.kiwoom.client import KiwoomClient
from services.kiwoom.models import OrderResponse, OrderType as KiwoomOrderType


def _mock_kiwoom(ord_no="0001093", return_code=0, return_msg="정상"):
    client = MagicMock(spec=KiwoomClient)
    resp = OrderResponse(ord_no=ord_no, return_code=return_code, return_msg=return_msg)
    client.place_buy_order = AsyncMock(return_value=resp)
    client.place_sell_order = AsyncMock(return_value=resp)
    return client


async def test_buy_dispatches_place_buy_order_and_fills():
    client = _mock_kiwoom(ord_no="B123")
    agent = OrderAgent(kiwoom_client=client)
    order = OrderRequest(ticker="005930", side=OrderSide.BUY, quantity=10,
                         price=70000, order_type=OrderType.LIMIT)
    result = await agent._execute_kiwoom_order("oid1", order)
    client.place_buy_order.assert_awaited_once()
    client.place_sell_order.assert_not_awaited()
    kwargs = client.place_buy_order.await_args.kwargs
    assert kwargs["stk_cd"] == "005930"
    assert kwargs["qty"] == 10
    assert kwargs["order_type"] == KiwoomOrderType.LIMIT
    assert result.status == "filled"
    assert result.order_id == "B123"


async def test_sell_dispatches_place_sell_order():
    client = _mock_kiwoom()
    agent = OrderAgent(kiwoom_client=client)
    order = OrderRequest(ticker="005930", side=OrderSide.SELL, quantity=5,
                         price=71000, order_type=OrderType.LIMIT)
    result = await agent._execute_kiwoom_order("oid2", order)
    client.place_sell_order.assert_awaited_once()
    client.place_buy_order.assert_not_awaited()
    assert result.status == "filled"


async def test_market_order_sends_none_price_and_market_type():
    client = _mock_kiwoom()
    agent = OrderAgent(kiwoom_client=client)
    order = OrderRequest(ticker="005930", side=OrderSide.BUY, quantity=3,
                         order_type=OrderType.MARKET)  # no price
    await agent._execute_kiwoom_order("oid3", order)
    kwargs = client.place_buy_order.await_args.kwargs
    assert kwargs["price"] is None
    assert kwargs["order_type"] == KiwoomOrderType.MARKET


async def test_nonzero_return_code_is_rejected():
    client = _mock_kiwoom(return_code=1, return_msg="주문거부")
    agent = OrderAgent(kiwoom_client=client)
    order = OrderRequest(ticker="005930", side=OrderSide.BUY, quantity=2,
                         price=70000, order_type=OrderType.LIMIT)
    result = await agent._execute_kiwoom_order("oid4", order)
    assert result.status == "rejected"
    assert result.message == "주문거부"
