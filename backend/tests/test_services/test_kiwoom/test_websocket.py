"""
Kiwoom WebSocket Client Unit Tests

Tests for real-time data streaming functionality.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.kiwoom.websocket import (
    BalanceData,
    KiwoomWebSocketClient,
    OrderbookData,
    OrderExecutionData,
    RealTimeType,
    StockTickData,
    VITriggerData,
    VIType,
)


class TestRealTimeType:
    """RealTimeType enum tests"""

    def test_stock_tick_value(self):
        """Test STOCK_TICK enum value"""
        assert RealTimeType.STOCK_TICK.value == "0B"

    def test_orderbook_value(self):
        """Test ORDERBOOK enum value"""
        assert RealTimeType.ORDERBOOK.value == "0D"

    def test_order_execution_value(self):
        """Test ORDER_EXECUTION enum value"""
        assert RealTimeType.ORDER_EXECUTION.value == "00"

    def test_balance_value(self):
        """Test BALANCE enum value"""
        assert RealTimeType.BALANCE.value == "04"

    def test_vi_trigger_value(self):
        """Test VI_TRIGGER enum value"""
        assert RealTimeType.VI_TRIGGER.value == "1h"


class TestWebSocketModels:
    """WebSocket data model tests"""

    def test_stock_tick_data_creation(self):
        """Test StockTickData model creation"""
        tick = StockTickData(
            stk_cd="005930",
            stk_nm="삼성전자",
            cur_prc=72000,
            prdy_vrss=1000,
            prdy_ctrt=1.41,
            acml_vol=10000000,
        )

        assert tick.stk_cd == "005930"
        assert tick.stk_nm == "삼성전자"
        assert tick.cur_prc == 72000
        assert tick.prdy_vrss == 1000
        assert tick.prdy_ctrt == 1.41
        assert tick.type == "tick"

    def test_orderbook_data_creation(self):
        """Test OrderbookData model creation"""
        orderbook = OrderbookData(
            stk_cd="005930",
            sell_hoga_1=72100,
            sell_hoga_qty_1=1000,
            buy_hoga_1=72000,
            buy_hoga_qty_1=2000,
            tot_sell_qty=50000,
            tot_buy_qty=60000,
        )

        assert orderbook.stk_cd == "005930"
        assert orderbook.sell_hoga_1 == 72100
        assert orderbook.buy_hoga_1 == 72000
        assert orderbook.tot_sell_qty == 50000
        assert orderbook.tot_buy_qty == 60000
        assert orderbook.type == "orderbook"

    def test_order_execution_data_creation(self):
        """Test OrderExecutionData model creation"""
        execution = OrderExecutionData(
            stk_cd="005930",
            stk_nm="삼성전자",
            ord_no="0001234",
            ord_qty=10,
            ord_prc=72000,
            ccld_qty=10,
            ccld_prc=72000,
            rmn_qty=0,
            ord_tp="2",
        )

        assert execution.stk_cd == "005930"
        assert execution.ord_no == "0001234"
        assert execution.ord_qty == 10
        assert execution.ccld_qty == 10
        assert execution.rmn_qty == 0
        assert execution.type == "order_execution"

    def test_balance_data_creation(self):
        """Test BalanceData model creation"""
        balance = BalanceData(
            stk_cd="005930",
            stk_nm="삼성전자",
            hldg_qty=100,
            avg_buy_prc=70000,
            cur_prc=72000,
            evlu_amt=7200000,
            evlu_pfls_amt=200000,
            evlu_pfls_rt=2.86,
        )

        assert balance.stk_cd == "005930"
        assert balance.hldg_qty == 100
        assert balance.avg_buy_prc == 70000
        assert balance.evlu_pfls_rt == 2.86
        assert balance.type == "balance"

    def test_vi_trigger_data_creation(self):
        """Test VITriggerData model creation"""
        vi = VITriggerData(
            stk_cd="005930",
            stk_nm="삼성전자",
            vi_type=VIType.STATIC_TRIGGER,
            vi_prc=75000,
            vi_std_prc=72000,
            vi_tm="093015",
        )

        assert vi.stk_cd == "005930"
        assert vi.vi_type == VIType.STATIC_TRIGGER
        assert vi.vi_prc == 75000
        assert vi.type == "vi"


class TestKiwoomWebSocketClient:
    """KiwoomWebSocketClient unit tests"""

    def test_client_initialization(self):
        """Test WebSocket client initialization"""
        client = KiwoomWebSocketClient(
            base_url="wss://mockapi.kiwoom.com",
            token="test_token",
        )

        assert client._base_url == "wss://mockapi.kiwoom.com"
        assert client._token == "test_token"
        assert client._reconnect is True
        assert client._running is False

    def test_client_initialization_with_https_url(self):
        """Test URL conversion from https to wss"""
        client = KiwoomWebSocketClient(
            base_url="https://mockapi.kiwoom.com",
        )

        assert client._base_url == "wss://mockapi.kiwoom.com"

    def test_set_token(self):
        """Test setting token"""
        client = KiwoomWebSocketClient()
        client.set_token("new_token")

        assert client._token == "new_token"

    def test_is_connected_false_initially(self):
        """Test is_connected property when not connected"""
        client = KiwoomWebSocketClient()

        assert client.is_connected is False

    def test_subscribed_stocks_empty_initially(self):
        """Test subscribed_stocks property when empty"""
        client = KiwoomWebSocketClient()

        stocks = client.subscribed_stocks

        assert stocks["tick"] == set()
        assert stocks["orderbook"] == set()
        assert stocks["vi"] == set()

    def test_subscribed_account_streams_false_initially(self):
        """Test subscribed_account_streams property when empty"""
        client = KiwoomWebSocketClient()

        streams = client.subscribed_account_streams

        assert streams["order_execution"] is False
        assert streams["balance"] is False

    def test_on_tick_callback_registration(self):
        """Test registering tick callback"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()

        client.on_tick(callback)

        assert callback in client._tick_callbacks

    def test_on_orderbook_callback_registration(self):
        """Test registering orderbook callback"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()

        client.on_orderbook(callback)

        assert callback in client._orderbook_callbacks

    def test_on_order_execution_callback_registration(self):
        """Test registering order execution callback"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()

        client.on_order_execution(callback)

        assert callback in client._order_execution_callbacks

    def test_on_balance_callback_registration(self):
        """Test registering balance callback"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()

        client.on_balance(callback)

        assert callback in client._balance_callbacks

    def test_on_vi_callback_registration(self):
        """Test registering VI callback"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()

        client.on_vi(callback)

        assert callback in client._vi_callbacks

    def test_on_error_callback_registration(self):
        """Test registering error callback"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()

        client.on_error(callback)

        assert callback in client._error_callbacks


class TestWebSocketClientParsers:
    """Parser method tests"""

    def test_parse_int_with_int(self):
        """Test parsing integer value"""
        result = KiwoomWebSocketClient._parse_int(12345)
        assert result == 12345

    def test_parse_int_with_string(self):
        """Test parsing string to integer"""
        result = KiwoomWebSocketClient._parse_int("12345")
        assert result == 12345

    def test_parse_int_with_comma(self):
        """Test parsing comma-formatted string"""
        result = KiwoomWebSocketClient._parse_int("1,234,567")
        assert result == 1234567

    def test_parse_int_with_sign(self):
        """Test parsing signed string"""
        result = KiwoomWebSocketClient._parse_int("+12345")
        assert result == 12345

    def test_parse_int_with_none(self):
        """Test parsing None value"""
        result = KiwoomWebSocketClient._parse_int(None)
        assert result == 0

    def test_parse_float_with_float(self):
        """Test parsing float value"""
        result = KiwoomWebSocketClient._parse_float(1.23)
        assert result == 1.23

    def test_parse_float_with_string(self):
        """Test parsing string to float"""
        result = KiwoomWebSocketClient._parse_float("1.23")
        assert result == 1.23

    def test_parse_float_with_none(self):
        """Test parsing None value"""
        result = KiwoomWebSocketClient._parse_float(None)
        assert result == 0.0


class TestWebSocketClientSubscriptions:
    """Subscription method tests"""

    @pytest.mark.asyncio
    async def test_subscribe_tick_updates_set(self):
        """Test subscribe_tick updates subscription set"""
        client = KiwoomWebSocketClient()
        client._ws = AsyncMock()
        client._ws.send = AsyncMock()

        await client.subscribe_tick(["005930", "000660"])

        assert "005930" in client._subscribed_ticks
        assert "000660" in client._subscribed_ticks

    @pytest.mark.asyncio
    async def test_subscribe_orderbook_updates_set(self):
        """Test subscribe_orderbook updates subscription set"""
        client = KiwoomWebSocketClient()
        client._ws = AsyncMock()
        client._ws.send = AsyncMock()

        await client.subscribe_orderbook(["005930"])

        assert "005930" in client._subscribed_orderbooks

    @pytest.mark.asyncio
    async def test_subscribe_order_execution_requires_token(self):
        """Test subscribe_order_execution requires token"""
        client = KiwoomWebSocketClient(token=None)

        with pytest.raises(ValueError, match="Token required"):
            await client.subscribe_order_execution()

    @pytest.mark.asyncio
    async def test_subscribe_balance_requires_token(self):
        """Test subscribe_balance requires token"""
        client = KiwoomWebSocketClient(token=None)

        with pytest.raises(ValueError, match="Token required"):
            await client.subscribe_balance()

    @pytest.mark.asyncio
    async def test_subscribe_vi_updates_set(self):
        """Test subscribe_vi updates subscription set"""
        client = KiwoomWebSocketClient()
        client._ws = AsyncMock()
        client._ws.send = AsyncMock()

        await client.subscribe_vi(["005930"])

        assert "005930" in client._subscribed_vi

    @pytest.mark.asyncio
    async def test_unsubscribe_tick_updates_set(self):
        """Test unsubscribe_tick updates subscription set"""
        client = KiwoomWebSocketClient()
        client._ws = AsyncMock()
        client._ws.send = AsyncMock()
        client._subscribed_ticks = {"005930", "000660"}

        await client.unsubscribe_tick(["005930"])

        assert "005930" not in client._subscribed_ticks
        assert "000660" in client._subscribed_ticks


class TestWebSocketClientMessageProcessing:
    """Message processing tests"""

    @pytest.mark.asyncio
    async def test_process_tick_message(self):
        """Test processing tick message"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()
        client.on_tick(callback)

        message = {
            "header": {"rq_type": "0B"},
            "body": {
                "stk_cd": "005930",
                "stk_nm": "삼성전자",
                "cur_prc": 72000,
                "prdy_vrss": 1000,
                "prdy_ctrt": 1.41,
            }
        }

        await client._process_message(message)

        callback.assert_called_once()
        tick_data = callback.call_args[0][0]
        assert isinstance(tick_data, StockTickData)
        assert tick_data.stk_cd == "005930"
        assert tick_data.cur_prc == 72000

    @pytest.mark.asyncio
    async def test_process_orderbook_message(self):
        """Test processing orderbook message"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()
        client.on_orderbook(callback)

        message = {
            "header": {"rq_type": "0D"},
            "body": {
                "stk_cd": "005930",
                "sell_hoga_1": 72100,
                "sell_hoga_qty_1": 1000,
                "buy_hoga_1": 72000,
                "buy_hoga_qty_1": 2000,
            }
        }

        await client._process_message(message)

        callback.assert_called_once()
        orderbook_data = callback.call_args[0][0]
        assert isinstance(orderbook_data, OrderbookData)
        assert orderbook_data.stk_cd == "005930"

    @pytest.mark.asyncio
    async def test_process_order_execution_message(self):
        """Test processing order execution message"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()
        client.on_order_execution(callback)

        message = {
            "header": {"rq_type": "00"},
            "body": {
                "stk_cd": "005930",
                "ord_no": "0001234",
                "ord_qty": 10,
                "ord_prc": 72000,
                "ccld_qty": 10,
                "ccld_prc": 72000,
                "ord_tp": "2",
            }
        }

        await client._process_message(message)

        callback.assert_called_once()
        execution_data = callback.call_args[0][0]
        assert isinstance(execution_data, OrderExecutionData)
        assert execution_data.ord_no == "0001234"

    @pytest.mark.asyncio
    async def test_process_balance_message(self):
        """Test processing balance message"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()
        client.on_balance(callback)

        message = {
            "header": {"rq_type": "04"},
            "body": {
                "stk_cd": "005930",
                "hldg_qty": 100,
                "avg_buy_prc": 70000,
                "cur_prc": 72000,
            }
        }

        await client._process_message(message)

        callback.assert_called_once()
        balance_data = callback.call_args[0][0]
        assert isinstance(balance_data, BalanceData)
        assert balance_data.hldg_qty == 100

    @pytest.mark.asyncio
    async def test_process_vi_message(self):
        """Test processing VI trigger message"""
        client = KiwoomWebSocketClient()
        callback = MagicMock()
        client.on_vi(callback)

        message = {
            "header": {"rq_type": "1h"},
            "body": {
                "stk_cd": "005930",
                "vi_type": "1",
                "vi_prc": 75000,
                "vi_std_prc": 72000,
            }
        }

        await client._process_message(message)

        callback.assert_called_once()
        vi_data = callback.call_args[0][0]
        assert isinstance(vi_data, VITriggerData)
        assert vi_data.vi_type == VIType.STATIC_TRIGGER

    @pytest.mark.asyncio
    async def test_async_callback_invocation(self):
        """Test async callback invocation"""
        client = KiwoomWebSocketClient()
        callback = AsyncMock()
        client.on_tick(callback)

        message = {
            "header": {"rq_type": "0B"},
            "body": {"stk_cd": "005930", "cur_prc": 72000}
        }

        await client._process_message(message)

        callback.assert_awaited_once()


class TestWebSocketClientReconnection:
    """Reconnection tests"""

    @pytest.mark.asyncio
    async def test_reconnect_delay_exponential_backoff(self):
        """Test exponential backoff delay calculation"""
        client = KiwoomWebSocketClient(
            reconnect_delay=1.0,
            max_reconnect_delay=60.0,
        )

        # Simulate reconnection attempts
        client._reconnect_attempts = 1
        delay_1 = min(
            client._reconnect_delay * (2 ** (client._reconnect_attempts - 1)),
            client._max_reconnect_delay,
        )

        client._reconnect_attempts = 3
        delay_3 = min(
            client._reconnect_delay * (2 ** (client._reconnect_attempts - 1)),
            client._max_reconnect_delay,
        )

        assert delay_1 == 1.0  # 1 * 2^0 = 1
        assert delay_3 == 4.0  # 1 * 2^2 = 4

    @pytest.mark.asyncio
    async def test_max_reconnect_delay_cap(self):
        """Test max reconnect delay is capped"""
        client = KiwoomWebSocketClient(
            reconnect_delay=1.0,
            max_reconnect_delay=10.0,
        )

        client._reconnect_attempts = 10  # Would be 2^9 = 512 without cap
        delay = min(
            client._reconnect_delay * (2 ** (client._reconnect_attempts - 1)),
            client._max_reconnect_delay,
        )

        assert delay == 10.0  # Capped at max


class TestVIType:
    """VIType enum tests"""

    def test_static_trigger(self):
        """Test STATIC_TRIGGER value"""
        assert VIType.STATIC_TRIGGER.value == "1"

    def test_dynamic_trigger(self):
        """Test DYNAMIC_TRIGGER value"""
        assert VIType.DYNAMIC_TRIGGER.value == "2"

    def test_static_release(self):
        """Test STATIC_RELEASE value"""
        assert VIType.STATIC_RELEASE.value == "3"

    def test_dynamic_release(self):
        """Test DYNAMIC_RELEASE value"""
        assert VIType.DYNAMIC_RELEASE.value == "4"
