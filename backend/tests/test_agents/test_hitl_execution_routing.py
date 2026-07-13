"""P5 S2 characterization: HITL resume routing + the (now-reachable) execute node.

approval.py now injects the decision INTO the graph checkpoint (astream(update)
instead of astream(None)), so should_continue_*_execution actually sees
approval_status on resume and the position-aware, mock-gated execute node fires.
These lock the routing contract + that the execute node is mock-safe for every action.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.graph.kr_stock_nodes.execution import (
    should_continue_kr_stock_execution,
    kr_stock_execution_node,
)
from agents.graph.coin_nodes import should_continue_coin_execution
from services.kiwoom.models import FilledOrder, OrderResponse

ROUTERS = [
    should_continue_kr_stock_execution,
    should_continue_coin_execution,
]


@pytest.mark.parametrize("router", ROUTERS)
def test_approved_routes_to_execute(router):
    assert router({"approval_status": "approved"}) == "execute"


@pytest.mark.parametrize("router", ROUTERS)
def test_rejected_routes_to_re_analyze(router):
    assert router({"approval_status": "rejected"}) == "re_analyze"


@pytest.mark.parametrize("router", ROUTERS)
@pytest.mark.parametrize("status", [None, "cancelled", "modified"])
def test_non_execute_statuses_route_to_end(router, status):
    assert router({"approval_status": status}) == "end"


@patch("services.trading.position_registration.register_fill_as_position", new_callable=AsyncMock)
@patch("app.dependencies.get_trading_coordinator")
@patch("agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async")
async def test_kr_execute_approved_buy_places_mock_order(
    mock_get_client, mock_get_coordinator, mock_register
):
    # The execute node now confirms the ACTUAL fill (ka10076) instead of
    # assuming placement==fill — the fake client must report a real fill for
    # this to reach "completed" (see test_kr_execution_fill_confirm.py for
    # the 0/partial/exception fill-confirmation branches).
    client = MagicMock()
    client.place_buy_order = AsyncMock(
        return_value=OrderResponse(ord_no="X1", return_code=0, return_msg="정상")
    )
    client.get_filled_orders = AsyncMock(
        return_value=[
            FilledOrder(
                ord_no="X1", stk_cd="005930", stk_nm="삼성전자",
                ccld_qty=10, ccld_uv=70000, ccld_amt=700000,
                ccld_dt="", ccld_tm="", buy_sell_tp="매수",
            )
        ]
    )
    mock_get_client.return_value = client
    # A mocked coordinator — this test isn't exercising coordinator wiring
    # (that's test_kr_execution_fill_confirm.py's job), just guarding against
    # the real global singleton being touched.
    mock_get_coordinator.return_value = MagicMock()
    state = {
        "approval_status": "approved",
        "trade_proposal": {"stk_cd": "005930", "stk_nm": "삼성전자", "action": "BUY",
                           "entry_price": 70000, "quantity": 10},
        "reasoning_log": [],
    }
    result = await kr_stock_execution_node(state)
    client.place_buy_order.assert_awaited_once()
    assert result["execution_status"] == "completed"


@patch("agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async")
async def test_kr_execute_not_approved_skips_broker(mock_get_client):
    state = {
        "approval_status": "rejected",
        "trade_proposal": {"action": "BUY"},
        "reasoning_log": [],
    }
    result = await kr_stock_execution_node(state)
    assert result["execution_status"] == "cancelled"
    mock_get_client.assert_not_called()  # never reaches the broker


@patch("agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async")
async def test_kr_execute_watch_places_no_order(mock_get_client):
    state = {
        "approval_status": "approved",
        "trade_proposal": {"stk_cd": "005930", "stk_nm": "삼성전자", "action": "WATCH",
                           "entry_price": 70000, "quantity": 0},
        "reasoning_log": [],
    }
    result = await kr_stock_execution_node(state)
    assert result["execution_status"] == "completed"
    mock_get_client.assert_not_called()  # no-trade action never places an order
