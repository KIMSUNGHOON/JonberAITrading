"""
Upbit WebSocket Client

Real-time data streaming from Upbit exchange via WebSocket.
Supports ticker, trade, and orderbook subscriptions.
"""

import asyncio
import json
import uuid
from enum import Enum
from typing import Any, Callable, Optional

import structlog
import websockets
from pydantic import BaseModel, ConfigDict, Field
from websockets.exceptions import ConnectionClosed, WebSocketException

logger = structlog.get_logger()


# -------------------------------------------
# WebSocket Data Types
# -------------------------------------------


class StreamType(str, Enum):
    """Stream type indicator."""

    SNAPSHOT = "SNAPSHOT"
    REALTIME = "REALTIME"


class ChangeDirection(str, Enum):
    """Price change direction."""

    RISE = "RISE"
    EVEN = "EVEN"
    FALL = "FALL"


class AskBid(str, Enum):
    """Trade side."""

    ASK = "ASK"  # Sell
    BID = "BID"  # Buy


# -------------------------------------------
# WebSocket Response Models
# -------------------------------------------


class WebSocketTicker(BaseModel):
    """Real-time ticker data from WebSocket."""

    type: str = Field(default="ticker")
    code: str = Field(..., description="마켓 코드 (예: KRW-BTC)")
    opening_price: float = Field(..., description="시가")
    high_price: float = Field(..., description="고가")
    low_price: float = Field(..., description="저가")
    trade_price: float = Field(..., description="현재가")
    prev_closing_price: float = Field(..., description="전일 종가")
    change: ChangeDirection = Field(..., description="전일 대비")
    change_price: float = Field(..., description="변화액")
    signed_change_price: float = Field(..., description="부호 있는 변화액")
    change_rate: float = Field(..., description="변화율")
    signed_change_rate: float = Field(..., description="부호 있는 변화율")
    trade_volume: float = Field(..., description="최근 거래량")
    acc_trade_volume: float = Field(..., description="누적 거래량 (UTC 0시 기준)")
    acc_trade_volume_24h: float = Field(..., description="24시간 누적 거래량")
    acc_trade_price: float = Field(..., description="누적 거래대금 (UTC 0시 기준)")
    acc_trade_price_24h: float = Field(..., description="24시간 누적 거래대금")
    trade_date: str = Field(..., alias="trade_date", description="최근 거래 일자 (yyyyMMdd)")
    trade_time: str = Field(..., alias="trade_time", description="최근 거래 시각 (HHmmss)")
    trade_timestamp: int = Field(..., description="체결 타임스탬프 (ms)")
    ask_bid: AskBid = Field(..., description="매수/매도 구분")
    acc_ask_volume: float = Field(..., description="누적 매도량")
    acc_bid_volume: float = Field(..., description="누적 매수량")
    highest_52_week_price: float = Field(..., description="52주 최고가")
    highest_52_week_date: str = Field(..., description="52주 최고가 달성일")
    lowest_52_week_price: float = Field(..., description="52주 최저가")
    lowest_52_week_date: str = Field(..., description="52주 최저가 달성일")
    market_state: str = Field(..., description="거래 상태")
    timestamp: int = Field(..., description="타임스탬프 (ms)")
    stream_type: StreamType = Field(..., description="스트림 타입")

    model_config = ConfigDict(populate_by_name=True)


class WebSocketTrade(BaseModel):
    """Real-time trade data from WebSocket."""

    type: str = Field(default="trade")
    code: str = Field(..., description="마켓 코드")
    trade_price: float = Field(..., description="체결 가격")
    trade_volume: float = Field(..., description="체결량")
    ask_bid: AskBid = Field(..., description="매수/매도 구분")
    prev_closing_price: float = Field(..., description="전일 종가")
    change: ChangeDirection = Field(..., description="전일 대비")
    change_price: float = Field(..., description="변화량")
    trade_date: str = Field(..., description="체결 일자 (yyyy-MM-dd)")
    trade_time: str = Field(..., alias="trade_time", description="체결 시각 (HH:mm:ss)")
    trade_timestamp: int = Field(..., description="체결 타임스탬프 (ms)")
    timestamp: int = Field(..., description="타임스탬프 (ms)")
    sequential_id: int = Field(..., description="체결 번호")
    best_ask_price: Optional[float] = Field(None, description="최우선 매도호가")
    best_ask_size: Optional[float] = Field(None, description="최우선 매도잔량")
    best_bid_price: Optional[float] = Field(None, description="최우선 매수호가")
    best_bid_size: Optional[float] = Field(None, description="최우선 매수잔량")
    stream_type: StreamType = Field(..., description="스트림 타입")

    model_config = ConfigDict(populate_by_name=True)


class WebSocketOrderbook(BaseModel):
    """Real-time orderbook data from WebSocket."""

    type: str = Field(default="orderbook")
    code: str = Field(..., description="마켓 코드")
    total_ask_size: float = Field(..., description="호가 매도 총 잔량")
    total_bid_size: float = Field(..., description="호가 매수 총 잔량")
    orderbook_units: list[dict] = Field(..., description="호가 목록")
    timestamp: int = Field(..., description="타임스탬프 (ms)")
    stream_type: StreamType = Field(..., description="스트림 타입")


# -------------------------------------------
# Callback Types
# -------------------------------------------

TickerCallback = Callable[[WebSocketTicker], None]
TradeCallback = Callable[[WebSocketTrade], None]
OrderbookCallback = Callable[[WebSocketOrderbook], None]
ErrorCallback = Callable[[Exception], None]


# -------------------------------------------
# WebSocket Client
# -------------------------------------------


class UpbitWebSocketClient:
    """
    Upbit WebSocket Client for real-time market data.

    Features:
    - Auto-reconnect with exponential backoff
    - Multiple market subscription
    - Callback-based data delivery
    - Support for ticker, trade, and orderbook streams

    Usage:
        async with UpbitWebSocketClient() as client:
            client.on_ticker(callback_function)
            await client.subscribe_ticker(["KRW-BTC", "KRW-ETH"])
            await client.run()
    """

    WSS_URL = "wss://api.upbit.com/websocket/v1"

    def __init__(
        self,
        reconnect: bool = True,
        max_reconnect_attempts: int = 10,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
    ):
        """
        Initialize WebSocket client.

        Args:
            reconnect: Enable auto-reconnection
            max_reconnect_attempts: Maximum reconnection attempts (0 = infinite)
            reconnect_delay: Initial delay between reconnection attempts
            max_reconnect_delay: Maximum delay between reconnection attempts
        """
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect = reconnect
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._reconnect_attempts = 0

        # Subscriptions
        self._subscribed_tickers: set[str] = set()
        self._subscribed_trades: set[str] = set()
        self._subscribed_orderbooks: set[str] = set()

        # Callbacks
        self._ticker_callbacks: list[TickerCallback] = []
        self._trade_callbacks: list[TradeCallback] = []
        self._orderbook_callbacks: list[OrderbookCallback] = []
        self._error_callbacks: list[ErrorCallback] = []

        # Receive task
        self._receive_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        try:
            self._ws = await websockets.connect(
                self.WSS_URL,
                ping_interval=30,
                ping_timeout=10,
            )
            self._reconnect_attempts = 0
            logger.info("upbit_websocket_connected", url=self.WSS_URL)

            # Re-subscribe to all markets
            await self._resubscribe()

        except Exception as e:
            logger.error("upbit_websocket_connect_failed", error=str(e))
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
            logger.info("upbit_websocket_disconnected")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    # -------------------------------------------
    # Subscription Methods
    # -------------------------------------------

    async def subscribe_ticker(self, markets: list[str]) -> None:
        """
        Subscribe to ticker updates for specified markets.

        Args:
            markets: List of market codes (e.g., ["KRW-BTC", "KRW-ETH"])
        """
        self._subscribed_tickers.update(markets)
        await self._send_subscription()

    async def subscribe_trade(self, markets: list[str]) -> None:
        """
        Subscribe to trade updates for specified markets.

        Args:
            markets: List of market codes
        """
        self._subscribed_trades.update(markets)
        await self._send_subscription()

    async def subscribe_orderbook(self, markets: list[str]) -> None:
        """
        Subscribe to orderbook updates for specified markets.

        Args:
            markets: List of market codes
        """
        self._subscribed_orderbooks.update(markets)
        await self._send_subscription()

    async def unsubscribe_ticker(self, markets: list[str]) -> None:
        """Unsubscribe from ticker updates."""
        self._subscribed_tickers.difference_update(markets)
        await self._send_subscription()

    async def unsubscribe_trade(self, markets: list[str]) -> None:
        """Unsubscribe from trade updates."""
        self._subscribed_trades.difference_update(markets)
        await self._send_subscription()

    async def unsubscribe_orderbook(self, markets: list[str]) -> None:
        """Unsubscribe from orderbook updates."""
        self._subscribed_orderbooks.difference_update(markets)
        await self._send_subscription()

    async def _send_subscription(self) -> None:
        """Send subscription message to WebSocket."""
        if not self._ws:
            return

        # Build subscription message
        subscription = [{"ticket": str(uuid.uuid4())}]

        if self._subscribed_tickers:
            subscription.append({
                "type": "ticker",
                "codes": list(self._subscribed_tickers),
            })

        if self._subscribed_trades:
            subscription.append({
                "type": "trade",
                "codes": list(self._subscribed_trades),
            })

        if self._subscribed_orderbooks:
            subscription.append({
                "type": "orderbook",
                "codes": list(self._subscribed_orderbooks),
            })

        # Add format
        subscription.append({"format": "DEFAULT"})

        message = json.dumps(subscription)
        await self._ws.send(message)

        logger.debug(
            "upbit_websocket_subscribed",
            tickers=len(self._subscribed_tickers),
            trades=len(self._subscribed_trades),
            orderbooks=len(self._subscribed_orderbooks),
        )

    async def _resubscribe(self) -> None:
        """Re-subscribe to all markets after reconnection."""
        if (
            self._subscribed_tickers
            or self._subscribed_trades
            or self._subscribed_orderbooks
        ):
            await self._send_subscription()

    # -------------------------------------------
    # Callback Registration
    # -------------------------------------------

    def on_ticker(self, callback: TickerCallback) -> None:
        """Register ticker callback."""
        self._ticker_callbacks.append(callback)

    def on_trade(self, callback: TradeCallback) -> None:
        """Register trade callback."""
        self._trade_callbacks.append(callback)

    def on_orderbook(self, callback: OrderbookCallback) -> None:
        """Register orderbook callback."""
        self._orderbook_callbacks.append(callback)

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
                logger.warning("upbit_websocket_closed", code=e.code, reason=e.reason)
                if self._running and self._reconnect:
                    await self._handle_reconnect()
                else:
                    break
            except WebSocketException as e:
                logger.error("upbit_websocket_error", error=str(e))
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
                logger.warning("upbit_websocket_invalid_json", error=str(e))

    async def _process_message(self, data: dict[str, Any]) -> None:
        """Process incoming WebSocket message."""
        msg_type = data.get("type")

        try:
            if msg_type == "ticker":
                ticker = WebSocketTicker(**data)
                for callback in self._ticker_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(ticker)
                        else:
                            callback(ticker)
                    except Exception as e:
                        logger.error("ticker_callback_error", error=str(e))

            elif msg_type == "trade":
                trade = WebSocketTrade(**data)
                for callback in self._trade_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(trade)
                        else:
                            callback(trade)
                    except Exception as e:
                        logger.error("trade_callback_error", error=str(e))

            elif msg_type == "orderbook":
                orderbook = WebSocketOrderbook(**data)
                for callback in self._orderbook_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(orderbook)
                        else:
                            callback(orderbook)
                    except Exception as e:
                        logger.error("orderbook_callback_error", error=str(e))

        except Exception as e:
            logger.error("upbit_websocket_process_error", type=msg_type, error=str(e))

    async def _handle_reconnect(self) -> None:
        """Handle reconnection with exponential backoff."""
        self._reconnect_attempts += 1

        if (
            self._max_reconnect_attempts > 0
            and self._reconnect_attempts > self._max_reconnect_attempts
        ):
            logger.error(
                "upbit_websocket_max_reconnect_exceeded",
                attempts=self._reconnect_attempts,
            )
            self._running = False
            return

        delay = min(
            self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
            self._max_reconnect_delay,
        )

        logger.info(
            "upbit_websocket_reconnecting",
            attempt=self._reconnect_attempts,
            delay=delay,
        )

        await asyncio.sleep(delay)

        try:
            await self.connect()
        except Exception as e:
            logger.error("upbit_websocket_reconnect_failed", error=str(e))
            self._notify_error(e)

    def _notify_error(self, error: Exception) -> None:
        """Notify error callbacks."""
        for callback in self._error_callbacks:
            try:
                callback(error)
            except Exception as e:
                logger.error("error_callback_error", error=str(e))

    # -------------------------------------------
    # Properties
    # -------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and self._ws.open

    @property
    def subscribed_markets(self) -> dict[str, set[str]]:
        """Get all subscribed markets by type."""
        return {
            "ticker": self._subscribed_tickers.copy(),
            "trade": self._subscribed_trades.copy(),
            "orderbook": self._subscribed_orderbooks.copy(),
        }
