"""
Kiwoom WebSocket Client

Real-time data streaming from Kiwoom Securities via WebSocket.
Supports order execution, balance, tick, and orderbook subscriptions.

Real-time API Types:
  00: 주문체결 (계좌) - Order Execution
  04: 잔고 (계좌) - Balance Update
  0A: 주식기세 - Stock Mood
  0B: 주식체결 - Stock Tick
  0C: 주식우선호가 - Best Bid/Ask
  0D: 주식호가잔량 - Orderbook
  0E: 주식시간외호가 - After-hours Quote
  0F: 주식당일거래원 - Daily Broker
  0G: ETF NAV
  0H: 주식예상체결 - Expected Trade
  0J: 업종지수 - Sector Index
  1h: VI발동/해제 - VI Trigger
"""

import asyncio
import json
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

import structlog
import websockets
from pydantic import BaseModel, Field
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = structlog.get_logger()


# -------------------------------------------
# Real-time Data Types
# -------------------------------------------


class RealTimeType(str, Enum):
    """Kiwoom Real-time data type codes."""

    ORDER_EXECUTION = "00"  # 주문체결
    BALANCE = "04"  # 잔고
    STOCK_MOOD = "0A"  # 주식기세
    STOCK_TICK = "0B"  # 주식체결
    BEST_QUOTE = "0C"  # 주식우선호가
    ORDERBOOK = "0D"  # 주식호가잔량
    AFTER_HOURS_QUOTE = "0E"  # 주식시간외호가
    DAILY_BROKER = "0F"  # 주식당일거래원
    ETF_NAV = "0G"  # ETF NAV
    EXPECTED_TRADE = "0H"  # 주식예상체결
    SECTOR_INDEX = "0J"  # 업종지수
    VI_TRIGGER = "1h"  # VI발동/해제


class TradeDirection(str, Enum):
    """Trade direction."""

    BUY = "2"  # 매수
    SELL = "1"  # 매도


class VIType(str, Enum):
    """VI (Volatility Interruption) type."""

    STATIC_TRIGGER = "1"  # 정적VI 발동
    DYNAMIC_TRIGGER = "2"  # 동적VI 발동
    STATIC_RELEASE = "3"  # 정적VI 해제
    DYNAMIC_RELEASE = "4"  # 동적VI 해제


# -------------------------------------------
# WebSocket Response Models
# -------------------------------------------


class OrderExecutionData(BaseModel):
    """주문체결 데이터 (00)"""

    type: str = Field(default="order_execution")
    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(default="", description="종목명")
    ord_no: str = Field(..., description="주문번호")
    org_ord_no: Optional[str] = Field(None, description="원주문번호")
    ord_qty: int = Field(..., description="주문수량")
    ord_prc: int = Field(..., description="주문가격")
    ccld_qty: int = Field(default=0, description="체결수량")
    ccld_prc: int = Field(default=0, description="체결가격")
    rmn_qty: int = Field(default=0, description="미체결수량")
    ord_tp: str = Field(..., description="주문구분 (매수/매도)")
    ccld_tm: str = Field(default="", description="체결시간")
    timestamp: datetime = Field(default_factory=datetime.now)


class BalanceData(BaseModel):
    """잔고 데이터 (04)"""

    type: str = Field(default="balance")
    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(default="", description="종목명")
    hldg_qty: int = Field(..., description="보유수량")
    ord_psbl_qty: int = Field(default=0, description="주문가능수량")
    avg_buy_prc: int = Field(..., description="평균매입가")
    cur_prc: int = Field(..., description="현재가")
    evlu_amt: int = Field(default=0, description="평가금액")
    evlu_pfls_amt: int = Field(default=0, description="평가손익")
    evlu_pfls_rt: float = Field(default=0.0, description="평가손익률")
    timestamp: datetime = Field(default_factory=datetime.now)


class StockTickData(BaseModel):
    """주식체결 데이터 (0B)"""

    type: str = Field(default="tick")
    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(default="", description="종목명")
    cur_prc: int = Field(..., description="현재가")
    prdy_vrss: int = Field(default=0, description="전일대비")
    prdy_ctrt: float = Field(default=0.0, description="전일대비율")
    acml_vol: int = Field(default=0, description="누적거래량")
    acml_tr_pbmn: int = Field(default=0, description="누적거래대금")
    ccld_qty: int = Field(default=0, description="체결수량")
    ccld_tm: str = Field(default="", description="체결시간")
    ask_bid: str = Field(default="", description="매수/매도 구분")
    strt_prc: int = Field(default=0, description="시가")
    high_prc: int = Field(default=0, description="고가")
    low_prc: int = Field(default=0, description="저가")
    timestamp: datetime = Field(default_factory=datetime.now)


class OrderbookData(BaseModel):
    """주식호가잔량 데이터 (0D)"""

    type: str = Field(default="orderbook")
    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(default="", description="종목명")
    sell_hoga_1: int = Field(default=0, description="매도호가1")
    sell_hoga_qty_1: int = Field(default=0, description="매도호가수량1")
    sell_hoga_2: int = Field(default=0, description="매도호가2")
    sell_hoga_qty_2: int = Field(default=0, description="매도호가수량2")
    sell_hoga_3: int = Field(default=0, description="매도호가3")
    sell_hoga_qty_3: int = Field(default=0, description="매도호가수량3")
    sell_hoga_4: int = Field(default=0, description="매도호가4")
    sell_hoga_qty_4: int = Field(default=0, description="매도호가수량4")
    sell_hoga_5: int = Field(default=0, description="매도호가5")
    sell_hoga_qty_5: int = Field(default=0, description="매도호가수량5")
    buy_hoga_1: int = Field(default=0, description="매수호가1")
    buy_hoga_qty_1: int = Field(default=0, description="매수호가수량1")
    buy_hoga_2: int = Field(default=0, description="매수호가2")
    buy_hoga_qty_2: int = Field(default=0, description="매수호가수량2")
    buy_hoga_3: int = Field(default=0, description="매수호가3")
    buy_hoga_qty_3: int = Field(default=0, description="매수호가수량3")
    buy_hoga_4: int = Field(default=0, description="매수호가4")
    buy_hoga_qty_4: int = Field(default=0, description="매수호가수량4")
    buy_hoga_5: int = Field(default=0, description="매수호가5")
    buy_hoga_qty_5: int = Field(default=0, description="매수호가수량5")
    tot_sell_qty: int = Field(default=0, description="총매도잔량")
    tot_buy_qty: int = Field(default=0, description="총매수잔량")
    timestamp: datetime = Field(default_factory=datetime.now)


class VITriggerData(BaseModel):
    """VI발동/해제 데이터 (1h)"""

    type: str = Field(default="vi")
    stk_cd: str = Field(..., description="종목코드")
    stk_nm: str = Field(default="", description="종목명")
    vi_type: VIType = Field(..., description="VI 유형")
    vi_prc: int = Field(default=0, description="VI 발동가격")
    vi_std_prc: int = Field(default=0, description="VI 기준가격")
    vi_tm: str = Field(default="", description="VI 시간")
    timestamp: datetime = Field(default_factory=datetime.now)


# -------------------------------------------
# Callback Types
# -------------------------------------------

OrderExecutionCallback = Callable[[OrderExecutionData], None]
BalanceCallback = Callable[[BalanceData], None]
TickCallback = Callable[[StockTickData], None]
OrderbookCallback = Callable[[OrderbookData], None]
VICallback = Callable[[VITriggerData], None]
ErrorCallback = Callable[[Exception], None]


# -------------------------------------------
# WebSocket Client
# -------------------------------------------


class KiwoomWebSocketClient:
    """
    Kiwoom WebSocket Client for real-time market data.

    Features:
    - Auto-reconnect with exponential backoff
    - Multiple stock subscription
    - Callback-based data delivery
    - Support for tick, orderbook, order execution, and balance streams

    Usage:
        client = KiwoomWebSocketClient(
            base_url="wss://mockapi.kiwoom.com",
            token="your_token"
        )
        client.on_tick(callback_function)
        await client.connect()
        await client.subscribe_tick(["005930", "000660"])
        await client.run()
    """

    def __init__(
        self,
        base_url: str = "wss://mockapi.kiwoom.com",
        token: Optional[str] = None,
        reconnect: bool = True,
        max_reconnect_attempts: int = 10,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
    ):
        """
        Initialize WebSocket client.

        Args:
            base_url: WebSocket base URL (wss://mockapi.kiwoom.com or wss://api.kiwoom.com)
            token: OAuth access token (required for account data)
            reconnect: Enable auto-reconnection
            max_reconnect_attempts: Maximum reconnection attempts (0 = infinite)
            reconnect_delay: Initial delay between reconnection attempts
            max_reconnect_delay: Maximum delay between reconnection attempts
        """
        self._base_url = base_url.replace("https://", "wss://")
        self._ws_url = f"{self._base_url}/api/dostk/websocket"
        self._token = token

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect = reconnect
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._reconnect_attempts = 0

        # Subscriptions by type
        self._subscribed_ticks: set[str] = set()
        self._subscribed_orderbooks: set[str] = set()
        self._subscribed_order_execution: bool = False
        self._subscribed_balance: bool = False
        self._subscribed_vi: set[str] = set()

        # Callbacks
        self._tick_callbacks: list[TickCallback] = []
        self._orderbook_callbacks: list[OrderbookCallback] = []
        self._order_execution_callbacks: list[OrderExecutionCallback] = []
        self._balance_callbacks: list[BalanceCallback] = []
        self._vi_callbacks: list[VICallback] = []
        self._error_callbacks: list[ErrorCallback] = []

        # Receive task
        self._receive_task: Optional[asyncio.Task] = None

    def set_token(self, token: str) -> None:
        """Update access token."""
        self._token = token

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        try:
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
            }
            if self._token:
                headers["authorization"] = f"Bearer {self._token}"

            self._ws = await websockets.connect(
                self._ws_url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=10,
            )
            self._reconnect_attempts = 0
            logger.info("kiwoom_websocket_connected", url=self._ws_url)

            # Re-subscribe to all markets
            await self._resubscribe()

        except Exception as e:
            logger.error("kiwoom_websocket_connect_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None
            logger.info("kiwoom_websocket_disconnected")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    # -------------------------------------------
    # Subscription Methods
    # -------------------------------------------

    async def subscribe_tick(self, stock_codes: list[str]) -> None:
        """
        Subscribe to tick (체결) updates for specified stocks.

        Args:
            stock_codes: List of stock codes (e.g., ["005930", "000660"])
        """
        self._subscribed_ticks.update(stock_codes)
        await self._send_subscription(RealTimeType.STOCK_TICK, list(self._subscribed_ticks))

    async def subscribe_orderbook(self, stock_codes: list[str]) -> None:
        """
        Subscribe to orderbook (호가) updates for specified stocks.

        Args:
            stock_codes: List of stock codes
        """
        self._subscribed_orderbooks.update(stock_codes)
        await self._send_subscription(RealTimeType.ORDERBOOK, list(self._subscribed_orderbooks))

    async def subscribe_order_execution(self) -> None:
        """
        Subscribe to order execution (주문체결) updates.
        Requires authentication.
        """
        if not self._token:
            raise ValueError("Token required for order execution subscription")
        self._subscribed_order_execution = True
        await self._send_subscription(RealTimeType.ORDER_EXECUTION, [])

    async def subscribe_balance(self) -> None:
        """
        Subscribe to balance (잔고) updates.
        Requires authentication.
        """
        if not self._token:
            raise ValueError("Token required for balance subscription")
        self._subscribed_balance = True
        await self._send_subscription(RealTimeType.BALANCE, [])

    async def subscribe_vi(self, stock_codes: list[str]) -> None:
        """
        Subscribe to VI (변동성완화장치) trigger updates.

        Args:
            stock_codes: List of stock codes
        """
        self._subscribed_vi.update(stock_codes)
        await self._send_subscription(RealTimeType.VI_TRIGGER, list(self._subscribed_vi))

    async def unsubscribe_tick(self, stock_codes: list[str]) -> None:
        """Unsubscribe from tick updates."""
        self._subscribed_ticks.difference_update(stock_codes)
        await self._send_unsubscription(RealTimeType.STOCK_TICK, stock_codes)

    async def unsubscribe_orderbook(self, stock_codes: list[str]) -> None:
        """Unsubscribe from orderbook updates."""
        self._subscribed_orderbooks.difference_update(stock_codes)
        await self._send_unsubscription(RealTimeType.ORDERBOOK, stock_codes)

    async def unsubscribe_order_execution(self) -> None:
        """Unsubscribe from order execution updates."""
        self._subscribed_order_execution = False
        await self._send_unsubscription(RealTimeType.ORDER_EXECUTION, [])

    async def unsubscribe_balance(self) -> None:
        """Unsubscribe from balance updates."""
        self._subscribed_balance = False
        await self._send_unsubscription(RealTimeType.BALANCE, [])

    async def _send_subscription(self, rt_type: RealTimeType, stock_codes: list[str]) -> None:
        """Send subscription request."""
        if not self._ws:
            return

        # Kiwoom WebSocket subscription format
        message = {
            "header": {
                "tr_type": "1",  # 1: 등록, 2: 해제
                "rq_type": rt_type.value,
            },
            "body": {
                "stk_cds": stock_codes,
            }
        }

        await self._ws.send(json.dumps(message))
        logger.debug(
            "kiwoom_websocket_subscribed",
            type=rt_type.value,
            stocks=len(stock_codes),
        )

    async def _send_unsubscription(self, rt_type: RealTimeType, stock_codes: list[str]) -> None:
        """Send unsubscription request."""
        if not self._ws:
            return

        message = {
            "header": {
                "tr_type": "2",  # 2: 해제
                "rq_type": rt_type.value,
            },
            "body": {
                "stk_cds": stock_codes,
            }
        }

        await self._ws.send(json.dumps(message))
        logger.debug(
            "kiwoom_websocket_unsubscribed",
            type=rt_type.value,
            stocks=len(stock_codes),
        )

    async def _resubscribe(self) -> None:
        """Re-subscribe to all after reconnection."""
        if self._subscribed_ticks:
            await self._send_subscription(RealTimeType.STOCK_TICK, list(self._subscribed_ticks))
        if self._subscribed_orderbooks:
            await self._send_subscription(RealTimeType.ORDERBOOK, list(self._subscribed_orderbooks))
        if self._subscribed_order_execution:
            await self._send_subscription(RealTimeType.ORDER_EXECUTION, [])
        if self._subscribed_balance:
            await self._send_subscription(RealTimeType.BALANCE, [])
        if self._subscribed_vi:
            await self._send_subscription(RealTimeType.VI_TRIGGER, list(self._subscribed_vi))

    # -------------------------------------------
    # Callback Registration
    # -------------------------------------------

    def on_tick(self, callback: TickCallback) -> None:
        """Register tick callback."""
        self._tick_callbacks.append(callback)

    def on_orderbook(self, callback: OrderbookCallback) -> None:
        """Register orderbook callback."""
        self._orderbook_callbacks.append(callback)

    def on_order_execution(self, callback: OrderExecutionCallback) -> None:
        """Register order execution callback."""
        self._order_execution_callbacks.append(callback)

    def on_balance(self, callback: BalanceCallback) -> None:
        """Register balance callback."""
        self._balance_callbacks.append(callback)

    def on_vi(self, callback: VICallback) -> None:
        """Register VI trigger callback."""
        self._vi_callbacks.append(callback)

    def on_error(self, callback: ErrorCallback) -> None:
        """Register error callback."""
        self._error_callbacks.append(callback)

    # -------------------------------------------
    # Message Handling
    # -------------------------------------------

    async def run(self) -> None:
        """
        Start receiving and processing messages.
        Blocks until disconnect() is called or connection fails.
        """
        self._running = True
        self._receive_task = asyncio.current_task()

        while self._running:
            try:
                await self._receive_loop()
            except ConnectionClosed as e:
                logger.warning("kiwoom_websocket_closed", code=e.code, reason=e.reason)
                if self._running and self._reconnect:
                    await self._handle_reconnect()
                else:
                    break
            except WebSocketException as e:
                logger.error("kiwoom_websocket_error", error=str(e))
                self._notify_error(e)
                if self._running and self._reconnect:
                    await self._handle_reconnect()
                else:
                    break
            except asyncio.CancelledError:
                break

    async def _receive_loop(self) -> None:
        """Receive and process messages from WebSocket."""
        if not self._ws:
            raise WebSocketException("Not connected")

        async for message in self._ws:
            if not self._running:
                break

            try:
                data = json.loads(message)
                await self._process_message(data)
            except json.JSONDecodeError as e:
                logger.warning("kiwoom_websocket_invalid_json", error=str(e))

    async def _process_message(self, data: dict[str, Any]) -> None:
        """Process incoming WebSocket message."""
        header = data.get("header", {})
        body = data.get("body", data)  # Some messages may not have header/body structure
        msg_type = header.get("rq_type", data.get("rq_type", ""))

        try:
            if msg_type == RealTimeType.STOCK_TICK.value:
                tick = self._parse_tick_data(body)
                await self._invoke_callbacks(self._tick_callbacks, tick)

            elif msg_type == RealTimeType.ORDERBOOK.value:
                orderbook = self._parse_orderbook_data(body)
                await self._invoke_callbacks(self._orderbook_callbacks, orderbook)

            elif msg_type == RealTimeType.ORDER_EXECUTION.value:
                execution = self._parse_order_execution_data(body)
                await self._invoke_callbacks(self._order_execution_callbacks, execution)

            elif msg_type == RealTimeType.BALANCE.value:
                balance = self._parse_balance_data(body)
                await self._invoke_callbacks(self._balance_callbacks, balance)

            elif msg_type == RealTimeType.VI_TRIGGER.value:
                vi = self._parse_vi_data(body)
                await self._invoke_callbacks(self._vi_callbacks, vi)

        except Exception as e:
            logger.error("kiwoom_websocket_process_error", type=msg_type, error=str(e))

    async def _invoke_callbacks(self, callbacks: list, data: Any) -> None:
        """Invoke all callbacks for the given data."""
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error("kiwoom_callback_error", error=str(e))

    def _parse_tick_data(self, body: dict) -> StockTickData:
        """Parse tick data from WebSocket message."""
        return StockTickData(
            stk_cd=body.get("stk_cd", ""),
            stk_nm=body.get("stk_nm", ""),
            cur_prc=self._parse_int(body.get("cur_prc", 0)),
            prdy_vrss=self._parse_int(body.get("prdy_vrss", 0)),
            prdy_ctrt=self._parse_float(body.get("prdy_ctrt", 0)),
            acml_vol=self._parse_int(body.get("acml_vol", 0)),
            acml_tr_pbmn=self._parse_int(body.get("acml_tr_pbmn", 0)),
            ccld_qty=self._parse_int(body.get("ccld_qty", 0)),
            ccld_tm=body.get("ccld_tm", ""),
            ask_bid=body.get("ask_bid", ""),
            strt_prc=self._parse_int(body.get("strt_prc", 0)),
            high_prc=self._parse_int(body.get("high_prc", 0)),
            low_prc=self._parse_int(body.get("low_prc", 0)),
        )

    def _parse_orderbook_data(self, body: dict) -> OrderbookData:
        """Parse orderbook data from WebSocket message."""
        return OrderbookData(
            stk_cd=body.get("stk_cd", ""),
            stk_nm=body.get("stk_nm", ""),
            sell_hoga_1=self._parse_int(body.get("sell_hoga_1", 0)),
            sell_hoga_qty_1=self._parse_int(body.get("sell_hoga_qty_1", 0)),
            sell_hoga_2=self._parse_int(body.get("sell_hoga_2", 0)),
            sell_hoga_qty_2=self._parse_int(body.get("sell_hoga_qty_2", 0)),
            sell_hoga_3=self._parse_int(body.get("sell_hoga_3", 0)),
            sell_hoga_qty_3=self._parse_int(body.get("sell_hoga_qty_3", 0)),
            sell_hoga_4=self._parse_int(body.get("sell_hoga_4", 0)),
            sell_hoga_qty_4=self._parse_int(body.get("sell_hoga_qty_4", 0)),
            sell_hoga_5=self._parse_int(body.get("sell_hoga_5", 0)),
            sell_hoga_qty_5=self._parse_int(body.get("sell_hoga_qty_5", 0)),
            buy_hoga_1=self._parse_int(body.get("buy_hoga_1", 0)),
            buy_hoga_qty_1=self._parse_int(body.get("buy_hoga_qty_1", 0)),
            buy_hoga_2=self._parse_int(body.get("buy_hoga_2", 0)),
            buy_hoga_qty_2=self._parse_int(body.get("buy_hoga_qty_2", 0)),
            buy_hoga_3=self._parse_int(body.get("buy_hoga_3", 0)),
            buy_hoga_qty_3=self._parse_int(body.get("buy_hoga_qty_3", 0)),
            buy_hoga_4=self._parse_int(body.get("buy_hoga_4", 0)),
            buy_hoga_qty_4=self._parse_int(body.get("buy_hoga_qty_4", 0)),
            buy_hoga_5=self._parse_int(body.get("buy_hoga_5", 0)),
            buy_hoga_qty_5=self._parse_int(body.get("buy_hoga_qty_5", 0)),
            tot_sell_qty=self._parse_int(body.get("tot_sell_qty", 0)),
            tot_buy_qty=self._parse_int(body.get("tot_buy_qty", 0)),
        )

    def _parse_order_execution_data(self, body: dict) -> OrderExecutionData:
        """Parse order execution data from WebSocket message."""
        return OrderExecutionData(
            stk_cd=body.get("stk_cd", ""),
            stk_nm=body.get("stk_nm", ""),
            ord_no=body.get("ord_no", ""),
            org_ord_no=body.get("org_ord_no"),
            ord_qty=self._parse_int(body.get("ord_qty", 0)),
            ord_prc=self._parse_int(body.get("ord_prc", 0)),
            ccld_qty=self._parse_int(body.get("ccld_qty", 0)),
            ccld_prc=self._parse_int(body.get("ccld_prc", 0)),
            rmn_qty=self._parse_int(body.get("rmn_qty", 0)),
            ord_tp=body.get("ord_tp", ""),
            ccld_tm=body.get("ccld_tm", ""),
        )

    def _parse_balance_data(self, body: dict) -> BalanceData:
        """Parse balance data from WebSocket message."""
        return BalanceData(
            stk_cd=body.get("stk_cd", ""),
            stk_nm=body.get("stk_nm", ""),
            hldg_qty=self._parse_int(body.get("hldg_qty", 0)),
            ord_psbl_qty=self._parse_int(body.get("ord_psbl_qty", 0)),
            avg_buy_prc=self._parse_int(body.get("avg_buy_prc", 0)),
            cur_prc=self._parse_int(body.get("cur_prc", 0)),
            evlu_amt=self._parse_int(body.get("evlu_amt", 0)),
            evlu_pfls_amt=self._parse_int(body.get("evlu_pfls_amt", 0)),
            evlu_pfls_rt=self._parse_float(body.get("evlu_pfls_rt", 0)),
        )

    def _parse_vi_data(self, body: dict) -> VITriggerData:
        """Parse VI trigger data from WebSocket message."""
        return VITriggerData(
            stk_cd=body.get("stk_cd", ""),
            stk_nm=body.get("stk_nm", ""),
            vi_type=VIType(body.get("vi_type", "1")),
            vi_prc=self._parse_int(body.get("vi_prc", 0)),
            vi_std_prc=self._parse_int(body.get("vi_std_prc", 0)),
            vi_tm=body.get("vi_tm", ""),
        )

    @staticmethod
    def _parse_int(value: Any) -> int:
        """Parse integer value from various formats."""
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        try:
            return int(str(value).replace(",", "").replace("+", "").replace("-", "") or "0")
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_float(value: Any) -> float:
        """Parse float value from various formats."""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).replace(",", "").replace("+", "") or "0")
        except (ValueError, TypeError):
            return 0.0

    async def _handle_reconnect(self) -> None:
        """Handle reconnection with exponential backoff."""
        self._reconnect_attempts += 1

        if (
            self._max_reconnect_attempts > 0
            and self._reconnect_attempts > self._max_reconnect_attempts
        ):
            logger.error(
                "kiwoom_websocket_max_reconnect_exceeded",
                attempts=self._reconnect_attempts,
            )
            self._running = False
            return

        delay = min(
            self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
            self._max_reconnect_delay,
        )

        logger.info(
            "kiwoom_websocket_reconnecting",
            attempt=self._reconnect_attempts,
            delay=delay,
        )

        await asyncio.sleep(delay)

        try:
            await self.connect()
        except Exception as e:
            logger.error("kiwoom_websocket_reconnect_failed", error=str(e))
            self._notify_error(e)

    def _notify_error(self, error: Exception) -> None:
        """Notify error callbacks."""
        for callback in self._error_callbacks:
            try:
                callback(error)
            except Exception as e:
                logger.error("kiwoom_error_callback_error", error=str(e))

    # -------------------------------------------
    # Properties
    # -------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and self._ws.open

    @property
    def subscribed_stocks(self) -> dict[str, set[str]]:
        """Get all subscribed stocks by type."""
        return {
            "tick": self._subscribed_ticks.copy(),
            "orderbook": self._subscribed_orderbooks.copy(),
            "vi": self._subscribed_vi.copy(),
        }

    @property
    def subscribed_account_streams(self) -> dict[str, bool]:
        """Get subscribed account streams."""
        return {
            "order_execution": self._subscribed_order_execution,
            "balance": self._subscribed_balance,
        }
