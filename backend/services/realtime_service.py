"""
Real-time Data Service

Manages Upbit WebSocket connection and broadcasts real-time
market data to connected frontend clients.

This service acts as a bridge between:
- Upbit WebSocket (data source)
- Frontend WebSocket clients (data consumers)
"""

import asyncio
from typing import Callable, Optional

import structlog

from services.upbit import (
    UpbitWebSocketClient,
    WebSocketOrderbook,
    WebSocketTicker,
    WebSocketTrade,
)

logger = structlog.get_logger()


# -------------------------------------------
# Singleton Service Instance
# -------------------------------------------

_realtime_service: Optional["RealtimeService"] = None


async def get_realtime_service() -> "RealtimeService":
    """Get or create the singleton realtime service instance."""
    global _realtime_service
    if _realtime_service is None:
        _realtime_service = RealtimeService()
        # Auto-start the service when first accessed
        await _realtime_service.start()
    return _realtime_service


async def close_realtime_service() -> None:
    """Close the realtime service and clean up resources."""
    global _realtime_service
    if _realtime_service is not None:
        await _realtime_service.stop()
        _realtime_service = None
        logger.info("realtime_service_closed")


# -------------------------------------------
# Callback Types
# -------------------------------------------

TickerBroadcastCallback = Callable[[dict], None]
TradeBroadcastCallback = Callable[[dict], None]


# -------------------------------------------
# Realtime Service
# -------------------------------------------


class RealtimeService:
    """
    Real-time market data service.

    Manages:
    - Upbit WebSocket connection lifecycle
    - Market subscriptions per client
    - Data broadcasting to frontend clients

    Usage:
        service = await get_realtime_service()
        await service.start()

        # Subscribe to markets
        service.subscribe_ticker(["KRW-BTC", "KRW-ETH"], callback)

        # Later, unsubscribe
        service.unsubscribe_ticker(["KRW-BTC"], callback)
    """

    def __init__(self):
        self._upbit_ws: Optional[UpbitWebSocketClient] = None
        self._running = False
        self._run_task: Optional[asyncio.Task] = None

        # Track subscriptions per callback
        # ticker_callbacks[market] = set of callbacks
        self._ticker_callbacks: dict[str, set[TickerBroadcastCallback]] = {}
        self._trade_callbacks: dict[str, set[TradeBroadcastCallback]] = {}

        # Latest data cache (for new subscribers)
        self._latest_tickers: dict[str, dict] = {}
        self._latest_trades: dict[str, dict] = {}

    async def start(self) -> None:
        """Start the realtime service and connect to Upbit WebSocket."""
        if self._running:
            logger.warning("realtime_service_already_running")
            return

        self._running = True
        self._upbit_ws = UpbitWebSocketClient(
            reconnect=True,
            max_reconnect_attempts=0,  # Infinite reconnect
        )

        # Register internal callbacks
        self._upbit_ws.on_ticker(self._handle_ticker)
        self._upbit_ws.on_trade(self._handle_trade)
        self._upbit_ws.on_error(self._handle_error)

        try:
            await self._upbit_ws.connect()
            self._run_task = asyncio.create_task(self._run_websocket())
            logger.info("realtime_service_started")
        except Exception as e:
            logger.error("realtime_service_start_failed", error=str(e))
            self._running = False
            raise

    async def stop(self) -> None:
        """Stop the realtime service."""
        self._running = False

        if self._run_task:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            self._run_task = None

        if self._upbit_ws:
            await self._upbit_ws.disconnect()
            self._upbit_ws = None

        logger.info("realtime_service_stopped")

    async def _run_websocket(self) -> None:
        """Run the WebSocket receive loop."""
        if self._upbit_ws:
            try:
                await self._upbit_ws.run()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("realtime_websocket_error", error=str(e))

    # -------------------------------------------
    # Subscription Management
    # -------------------------------------------

    async def subscribe_ticker(
        self,
        markets: list[str],
        callback: TickerBroadcastCallback,
    ) -> None:
        """
        Subscribe to ticker updates for specified markets.

        Args:
            markets: List of market codes (e.g., ["KRW-BTC"])
            callback: Function to call with ticker data
        """
        new_markets = []

        for market in markets:
            market = market.upper()
            if market not in self._ticker_callbacks:
                self._ticker_callbacks[market] = set()
                new_markets.append(market)

            self._ticker_callbacks[market].add(callback)

            # Send cached data immediately if available
            if market in self._latest_tickers:
                try:
                    callback(self._latest_tickers[market])
                except Exception as e:
                    logger.warning("ticker_callback_error", error=str(e))

        # Subscribe to new markets on Upbit WebSocket
        if new_markets and self._upbit_ws:
            await self._upbit_ws.subscribe_ticker(new_markets)
            logger.debug("ticker_subscribed", markets=new_markets)

    async def unsubscribe_ticker(
        self,
        markets: list[str],
        callback: TickerBroadcastCallback,
    ) -> None:
        """
        Unsubscribe from ticker updates.

        Args:
            markets: List of market codes
            callback: Callback to remove
        """
        removed_markets = []

        for market in markets:
            market = market.upper()
            if market in self._ticker_callbacks:
                self._ticker_callbacks[market].discard(callback)

                # If no more callbacks for this market, unsubscribe
                if not self._ticker_callbacks[market]:
                    del self._ticker_callbacks[market]
                    removed_markets.append(market)

        if removed_markets and self._upbit_ws:
            await self._upbit_ws.unsubscribe_ticker(removed_markets)
            logger.debug("ticker_unsubscribed", markets=removed_markets)

    async def subscribe_trade(
        self,
        markets: list[str],
        callback: TradeBroadcastCallback,
    ) -> None:
        """Subscribe to trade updates for specified markets."""
        new_markets = []

        for market in markets:
            market = market.upper()
            if market not in self._trade_callbacks:
                self._trade_callbacks[market] = set()
                new_markets.append(market)

            self._trade_callbacks[market].add(callback)

        if new_markets and self._upbit_ws:
            await self._upbit_ws.subscribe_trade(new_markets)
            logger.debug("trade_subscribed", markets=new_markets)

    async def unsubscribe_trade(
        self,
        markets: list[str],
        callback: TradeBroadcastCallback,
    ) -> None:
        """Unsubscribe from trade updates."""
        removed_markets = []

        for market in markets:
            market = market.upper()
            if market in self._trade_callbacks:
                self._trade_callbacks[market].discard(callback)

                if not self._trade_callbacks[market]:
                    del self._trade_callbacks[market]
                    removed_markets.append(market)

        if removed_markets and self._upbit_ws:
            await self._upbit_ws.unsubscribe_trade(removed_markets)
            logger.debug("trade_unsubscribed", markets=removed_markets)

    async def unsubscribe_all(self, callback: TickerBroadcastCallback) -> None:
        """
        Unsubscribe a callback from all markets.

        Useful for cleanup when a client disconnects.
        """
        # Collect all markets this callback is subscribed to
        ticker_markets = [
            market
            for market, callbacks in self._ticker_callbacks.items()
            if callback in callbacks
        ]
        trade_markets = [
            market
            for market, callbacks in self._trade_callbacks.items()
            if callback in callbacks
        ]

        if ticker_markets:
            await self.unsubscribe_ticker(ticker_markets, callback)
        if trade_markets:
            await self.unsubscribe_trade(trade_markets, callback)

    # -------------------------------------------
    # Data Handlers
    # -------------------------------------------

    def _handle_ticker(self, ticker: WebSocketTicker) -> None:
        """Handle incoming ticker data from Upbit WebSocket."""
        market = ticker.code

        # Convert to dict for serialization
        ticker_data = {
            "type": "ticker",
            "market": market,
            "trade_price": ticker.trade_price,
            "change": ticker.change.value,
            "change_rate": ticker.signed_change_rate * 100,
            "change_price": ticker.signed_change_price,
            "high_price": ticker.high_price,
            "low_price": ticker.low_price,
            "acc_trade_volume_24h": ticker.acc_trade_volume_24h,
            "acc_trade_price_24h": ticker.acc_trade_price_24h,
            "trade_timestamp": ticker.trade_timestamp,
            "stream_type": ticker.stream_type.value,
        }

        # Cache latest data
        self._latest_tickers[market] = ticker_data

        # Broadcast to subscribers
        callbacks = self._ticker_callbacks.get(market, set())
        for callback in callbacks.copy():
            try:
                callback(ticker_data)
            except Exception as e:
                logger.warning(
                    "ticker_broadcast_error",
                    market=market,
                    error=str(e),
                )

    def _handle_trade(self, trade: WebSocketTrade) -> None:
        """Handle incoming trade data from Upbit WebSocket."""
        market = trade.code

        trade_data = {
            "type": "trade",
            "market": market,
            "trade_price": trade.trade_price,
            "trade_volume": trade.trade_volume,
            "ask_bid": trade.ask_bid.value,
            "trade_timestamp": trade.trade_timestamp,
            "sequential_id": trade.sequential_id,
            "stream_type": trade.stream_type.value,
        }

        # Cache latest data
        self._latest_trades[market] = trade_data

        # Broadcast to subscribers
        callbacks = self._trade_callbacks.get(market, set())
        for callback in callbacks.copy():
            try:
                callback(trade_data)
            except Exception as e:
                logger.warning(
                    "trade_broadcast_error",
                    market=market,
                    error=str(e),
                )

    def _handle_error(self, error: Exception) -> None:
        """Handle WebSocket errors."""
        logger.error("upbit_websocket_error", error=str(error))

    # -------------------------------------------
    # Utility Methods
    # -------------------------------------------

    def get_latest_ticker(self, market: str) -> Optional[dict]:
        """Get the latest cached ticker for a market."""
        return self._latest_tickers.get(market.upper())

    def get_subscribed_markets(self) -> dict[str, int]:
        """Get count of subscribers per market."""
        return {
            market: len(callbacks)
            for market, callbacks in self._ticker_callbacks.items()
        }

    @property
    def is_running(self) -> bool:
        """Check if the service is running."""
        return self._running

    @property
    def is_connected(self) -> bool:
        """Check if connected to Upbit WebSocket."""
        return self._upbit_ws is not None and self._upbit_ws.is_connected
