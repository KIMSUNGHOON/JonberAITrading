"""P1-1 wiring: kr_stock_execution_node records the confirmed fill for
/trades via services.trading.trade_log.record_trade_fill.

Uses the REAL trade_log module backed by an isolated temp-SQLite storage
(not mocked) to prove the end-to-end write — unlike
test_kr_execution_fill_confirm.py / test_hitl_execution_routing.py, which
neutralize trade_log entirely (via an autouse fixture) to keep their own,
unrelated assertions free of real storage I/O.

Fixture pattern follows test_kr_execution_fill_confirm.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.storage_service as ss
from agents.graph.kr_stock_nodes.execution import kr_stock_execution_node
from services.kiwoom.models import FilledOrder, OrderResponse
from services.trading import trade_log

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


async def _no_sleep(_seconds):
    return None


class _FakeKiwoomClient:
    def __init__(self, filled_orders, ord_no="ORD1"):
        self._filled_orders = filled_orders
        self._ord_no = ord_no

    async def place_buy_order(self, stk_cd, qty, price=None, order_type=None):
        return OrderResponse(ord_no=self._ord_no, return_code=0, return_msg="정상")

    async def place_sell_order(self, stk_cd, qty, price=None, order_type=None):
        return OrderResponse(ord_no=self._ord_no, return_code=0, return_msg="정상")

    async def get_filled_orders(
        self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True
    ):
        return list(self._filled_orders)


def _filled(ord_no, qty, price, buy_sell_tp="매수"):
    return FilledOrder(
        ord_no=ord_no,
        stk_cd="005930",
        stk_nm="삼성전자",
        ccld_qty=qty,
        ccld_uv=price,
        ccld_amt=qty * price,
        ccld_dt="",
        ccld_tm="",
        buy_sell_tp=buy_sell_tp,
    )


def _state(action="BUY", quantity=10, entry_price=70000, existing_position=None):
    return {
        "approval_status": "approved",
        "trade_proposal": {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "action": action,
            "entry_price": entry_price,
            "quantity": quantity,
            "stop_loss": 66500,
            "take_profit": 77000,
            "risk_score": 0.6,
        },
        "existing_position": existing_position,
        "reasoning_log": [],
        "session_id": "sess-graph-1",
    }


def _mock_coordinator():
    coordinator = MagicMock()
    coordinator.fill_tracker = MagicMock()
    coordinator._schedule_persist = MagicMock()
    coordinator.risk_params = MagicMock()
    return coordinator


async def test_buy_full_fill_records_trade(monkeypatch, temp_storage):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient([_filled("ORD1", 10, 70000)])
    coordinator = _mock_coordinator()

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ), patch(
        "services.trading.position_registration.register_fill_as_position",
        new_callable=AsyncMock,
    ):
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "completed"
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["stk_cd"] == "005930"
    assert row["stk_nm"] == "삼성전자"
    assert row["side"] == "buy"
    assert row["order_type"] == "limit"
    assert row["price"] == 70000
    assert row["quantity"] == 10
    assert row["executed_quantity"] == 10
    assert row["status"] == "completed"
    assert row["order_id"] == "ORD1"
    assert row["session_id"] == "sess-graph-1"


async def test_sell_partial_fill_records_partial_trade(monkeypatch, temp_storage):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(
        [_filled("ORD2", 12, 71000, buy_sell_tp="매도")], ord_no="ORD2"
    )
    coordinator = _mock_coordinator()
    existing = {
        "quantity": 100,
        "entry_price": 65000,
        "stop_loss": 60000,
        "take_profit": 75000,
    }

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ):
        result = await kr_stock_execution_node(
            _state(
                action="REDUCE",
                quantity=30,
                entry_price=71000,
                existing_position=existing,
            )
        )

    assert result["execution_status"] == "completed"
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["side"] == "sell"
    assert row["price"] == 71000
    assert row["quantity"] == 30
    assert row["executed_quantity"] == 12
    assert row["status"] == "partial"
    assert row["order_id"] == "ORD2"


async def test_zero_fill_records_nothing(monkeypatch, temp_storage):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient([])
    coordinator = _mock_coordinator()

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ):
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "placed_pending_fill"
    await trade_log.wait_for_pending_trade_fill_writes()

    assert await temp_storage.get_kr_stock_trades() == []
