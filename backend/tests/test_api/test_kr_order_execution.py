"""P5 S5a: KR REST order routes' LIVE branch must dispatch place_buy_order /
place_sell_order and parse OrderResponse.

Pre-fix, orders.create_order and positions.close_position used nonexistent
OrderType.BUY/SELL/MARKET_SELL + a nonexistent client.place_order(request), so the
live branch AttributeError'd -> HTTP 503. Mock-only: the Kiwoom client is mocked and
KIWOOM_IS_MOCK is patched purely to reach the live code branch — no real broker call.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routes.kr_stocks import orders as orders_mod
from app.api.routes.kr_stocks import positions as positions_mod
from app.api.schemas.kr_stocks import KRStockOrderRequest
from services.kiwoom.models import OrderResponse, OrderType as KiwoomOrderType


def _resp(ord_no="L1", rc=0):
    return OrderResponse(ord_no=ord_no, return_code=rc, return_msg="정상")


@patch("app.api.routes.kr_stocks.orders.check_kiwoom_api_keys")
@patch("app.api.routes.kr_stocks.orders.get_shared_kiwoom_client_async")
async def test_create_order_live_buy_dispatches_place_buy_order(mock_client_get, _chk):
    client = MagicMock()
    client.place_buy_order = AsyncMock(return_value=_resp("B1"))
    client.place_sell_order = AsyncMock(return_value=_resp())
    mock_client_get.return_value = client
    req = KRStockOrderRequest(stk_cd="005930", side="buy", ord_type="limit", price=70000, quantity=10)
    with patch.object(orders_mod.settings, "KIWOOM_IS_MOCK", False):
        resp = await orders_mod.create_order(req)
    client.place_buy_order.assert_awaited_once()
    client.place_sell_order.assert_not_awaited()
    assert client.place_buy_order.await_args.kwargs["order_type"] == KiwoomOrderType.LIMIT
    assert resp.order_id == "B1"


@patch("app.api.routes.kr_stocks.orders.check_kiwoom_api_keys")
@patch("app.api.routes.kr_stocks.orders.get_shared_kiwoom_client_async")
async def test_create_order_live_market_sell_dispatches_place_sell_order(mock_client_get, _chk):
    client = MagicMock()
    client.place_buy_order = AsyncMock(return_value=_resp())
    client.place_sell_order = AsyncMock(return_value=_resp("S1"))
    mock_client_get.return_value = client
    req = KRStockOrderRequest(stk_cd="005930", side="sell", ord_type="market", quantity=5)
    with patch.object(orders_mod.settings, "KIWOOM_IS_MOCK", False):
        resp = await orders_mod.create_order(req)
    client.place_sell_order.assert_awaited_once()
    kwargs = client.place_sell_order.await_args.kwargs
    assert kwargs["order_type"] == KiwoomOrderType.MARKET
    assert kwargs["price"] is None  # market order sends no price
    assert resp.order_id == "S1"


@patch("app.api.routes.kr_stocks.orders.check_kiwoom_api_keys")
@patch("app.api.routes.kr_stocks.orders.get_shared_kiwoom_client_async")
async def test_create_order_mock_mode_never_touches_client(mock_client_get, _chk):
    # Frozen default (KIWOOM_IS_MOCK True): returns a simulated order, no client call.
    req = KRStockOrderRequest(stk_cd="005930", side="buy", ord_type="market", quantity=1)
    with patch.object(orders_mod.settings, "KIWOOM_IS_MOCK", True):
        resp = await orders_mod.create_order(req)
    mock_client_get.assert_not_called()
    assert resp.order_id.startswith("mock-")


@patch("services.storage_service.get_storage_service")
@patch("app.api.routes.kr_stocks.positions.check_kiwoom_api_keys")
@patch("app.api.routes.kr_stocks.positions.get_shared_kiwoom_client_async")
async def test_close_position_live_dispatches_market_sell(mock_client_get, _chk, mock_storage_get):
    client = MagicMock()
    client.place_sell_order = AsyncMock(return_value=_resp("C1"))
    mock_client_get.return_value = client
    storage = MagicMock()
    storage.get_kr_stock_position = AsyncMock(
        return_value={"quantity": 10, "stk_nm": "삼성전자", "avg_entry_price": 70000}
    )
    storage.delete_kr_stock_position = AsyncMock()
    mock_storage_get.return_value = storage
    with patch.object(positions_mod.settings, "KIWOOM_IS_MOCK", False):
        resp = await positions_mod.close_position("005930")
    client.place_sell_order.assert_awaited_once()
    kwargs = client.place_sell_order.await_args.kwargs
    assert kwargs["order_type"] == KiwoomOrderType.MARKET
    assert kwargs["qty"] == 10
    assert resp.order_id == "C1"
