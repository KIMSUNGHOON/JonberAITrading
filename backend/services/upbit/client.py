"""
Upbit API Client

Async HTTP client for Upbit cryptocurrency exchange API.
Supports both QUOTATION (public) and EXCHANGE (authenticated) APIs.
"""

import asyncio
from typing import Optional

import httpx
import structlog

from .auth import generate_authorization_header
from .models import (
    Account,
    Candle,
    CoinAnalysisData,
    DayCandle,
    Market,
    MinuteCandle,
    Order,
    Orderbook,
    Ticker,
    Trade,
)

logger = structlog.get_logger()


class UpbitAPIError(Exception):
    """Upbit API error with status code and message."""

    def __init__(self, status_code: int, message: str, error_code: Optional[str] = None):
        self.status_code = status_code
        self.message = message
        self.error_code = error_code
        super().__init__(f"[{status_code}] {error_code}: {message}")


class UpbitClient:
    """
    Async Upbit API Client.

    Supports:
    - QUOTATION API (no auth): Market data, candles, orderbook, trades
    - EXCHANGE API (auth required): Accounts, orders

    Rate Limits:
    - Orders: 8/sec, 200/min
    - Others: 30/sec, 900/min
    """

    BASE_URL = "https://api.upbit.com/v1"

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize Upbit client.

        Args:
            access_key: API access key (required for EXCHANGE API)
            secret_key: API secret key (required for EXCHANGE API)
            timeout: Request timeout in seconds
        """
        self.access_key = access_key
        self.secret_key = secret_key
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ============================================================
    # QUOTATION API (No Authentication Required)
    # ============================================================

    async def get_markets(self, is_details: bool = False) -> list[Market]:
        """
        Get all available markets.

        Args:
            is_details: Include detailed market info

        Returns:
            List of Market objects
        """
        params = {"isDetails": str(is_details).lower()}
        response = await self._request("GET", "/market/all", params=params)
        return [Market(**m) for m in response]

    async def get_ticker(self, markets: list[str]) -> list[Ticker]:
        """
        Get current ticker for markets.

        Args:
            markets: List of market codes (e.g., ["KRW-BTC", "KRW-ETH"])

        Returns:
            List of Ticker objects
        """
        params = {"markets": ",".join(markets)}
        response = await self._request("GET", "/ticker", params=params)
        return [Ticker(**t) for t in response]

    async def get_candles_minutes(
        self,
        market: str,
        unit: int = 1,
        count: int = 200,
        to: Optional[str] = None,
    ) -> list[MinuteCandle]:
        """
        Get minute candles.

        Args:
            market: Market code (e.g., "KRW-BTC")
            unit: Candle unit (1, 3, 5, 10, 15, 30, 60, 240)
            count: Number of candles (max 200)
            to: Last candle time (ISO 8601)

        Returns:
            List of MinuteCandle objects (newest first)
        """
        if unit not in [1, 3, 5, 10, 15, 30, 60, 240]:
            raise ValueError(f"Invalid unit: {unit}. Must be 1, 3, 5, 10, 15, 30, 60, or 240")

        params = {"market": market, "count": min(count, 200)}
        if to:
            params["to"] = to

        response = await self._request("GET", f"/candles/minutes/{unit}", params=params)
        # Note: Upbit API already includes 'unit' in the response, no need to add it
        return [MinuteCandle(**c) for c in response]

    async def get_candles_days(
        self,
        market: str,
        count: int = 200,
        to: Optional[str] = None,
        converting_price_unit: Optional[str] = None,
    ) -> list[DayCandle]:
        """
        Get daily candles.

        Args:
            market: Market code
            count: Number of candles (max 200)
            to: Last candle date (yyyy-MM-dd or yyyy-MM-dd'T'HH:mm:ss)
            converting_price_unit: Price conversion currency (e.g., "KRW")

        Returns:
            List of DayCandle objects (newest first)
        """
        params = {"market": market, "count": min(count, 200)}
        if to:
            params["to"] = to
        if converting_price_unit:
            params["convertingPriceUnit"] = converting_price_unit

        response = await self._request("GET", "/candles/days", params=params)
        return [DayCandle(**c) for c in response]

    async def get_candles_weeks(
        self,
        market: str,
        count: int = 200,
        to: Optional[str] = None,
    ) -> list[Candle]:
        """Get weekly candles."""
        params = {"market": market, "count": min(count, 200)}
        if to:
            params["to"] = to

        response = await self._request("GET", "/candles/weeks", params=params)
        return [Candle(**c) for c in response]

    async def get_candles_months(
        self,
        market: str,
        count: int = 200,
        to: Optional[str] = None,
    ) -> list[Candle]:
        """Get monthly candles."""
        params = {"market": market, "count": min(count, 200)}
        if to:
            params["to"] = to

        response = await self._request("GET", "/candles/months", params=params)
        return [Candle(**c) for c in response]

    async def get_candles_seconds(
        self,
        market: str,
        count: int = 200,
        to: Optional[str] = None,
    ) -> list[Candle]:
        """
        Get second candles.

        Note: Second candle API only provides data for up to the most recent 3 months.
        If you request data outside of this retention period, the API will return
        an empty array or fewer items than requested.

        Args:
            market: Market code (e.g., "KRW-BTC")
            count: Number of candles (max 200, default 1)
            to: End time of the query period (ISO 8601 format)
                If omitted, the most recent candle is returned.

        Returns:
            List of Candle objects (newest first)
        """
        params = {"market": market, "count": min(count, 200)}
        if to:
            params["to"] = to

        response = await self._request("GET", "/candles/seconds", params=params)
        return [Candle(**c) for c in response]

    async def get_orderbook(self, markets: list[str]) -> list[Orderbook]:
        """
        Get orderbook for markets.

        Args:
            markets: List of market codes

        Returns:
            List of Orderbook objects
        """
        params = {"markets": ",".join(markets)}
        response = await self._request("GET", "/orderbook", params=params)
        return [Orderbook(**o) for o in response]

    async def get_trades(
        self,
        market: str,
        count: int = 100,
        to: Optional[str] = None,
        cursor: Optional[str] = None,
        days_ago: Optional[int] = None,
    ) -> list[Trade]:
        """
        Get recent trades.

        Args:
            market: Market code
            count: Number of trades (max 500)
            to: Last trade time (HH:mm:ss or HH:mm:ss.sss)
            cursor: Pagination cursor
            days_ago: Past days (0-7, 0=today)

        Returns:
            List of Trade objects
        """
        params = {"market": market, "count": min(count, 500)}
        if to:
            params["to"] = to
        if cursor:
            params["cursor"] = cursor
        if days_ago is not None:
            params["daysAgo"] = days_ago

        response = await self._request("GET", "/trades/ticks", params=params)
        return [Trade(**t) for t in response]

    # ============================================================
    # EXCHANGE API (Authentication Required)
    # ============================================================

    async def get_accounts(self) -> list[Account]:
        """
        Get all account balances.

        Returns:
            List of Account objects
        """
        response = await self._request("GET", "/accounts", auth=True)
        return [Account(**a) for a in response]

    async def get_order(self, uuid: str) -> Order:
        """
        Get order by UUID.

        Args:
            uuid: Order UUID

        Returns:
            Order object
        """
        params = {"uuid": uuid}
        response = await self._request("GET", "/order", params=params, auth=True)
        return Order(**response)

    async def get_orders(
        self,
        market: Optional[str] = None,
        state: str = "wait",
        states: Optional[list[str]] = None,
        page: int = 1,
        limit: int = 100,
        order_by: str = "desc",
    ) -> list[Order]:
        """
        Get orders list.

        Args:
            market: Market code (optional)
            state: Order state (wait, watch, done, cancel)
            states: Multiple states
            page: Page number
            limit: Results per page (max 100)
            order_by: Sort order (asc, desc)

        Returns:
            List of Order objects
        """
        params = {
            "state": state,
            "page": page,
            "limit": min(limit, 100),
            "order_by": order_by,
        }
        if market:
            params["market"] = market
        if states:
            params["states[]"] = states

        response = await self._request("GET", "/orders", params=params, auth=True)
        return [Order(**o) for o in response]

    async def place_order(
        self,
        market: str,
        side: str,
        volume: Optional[float] = None,
        price: Optional[float] = None,
        ord_type: str = "limit",
    ) -> Order:
        """
        Place a new order.

        Args:
            market: Market code (e.g., "KRW-BTC")
            side: "bid" (buy) or "ask" (sell)
            volume: Order quantity (required for limit/market sell)
            price: Order price (required for limit/market buy)
            ord_type: Order type
                - "limit": Limit order (price & volume required)
                - "price": Market buy (price = total KRW amount)
                - "market": Market sell (volume required)

        Returns:
            Created Order object
        """
        if side not in ["bid", "ask"]:
            raise ValueError("side must be 'bid' or 'ask'")
        if ord_type not in ["limit", "price", "market"]:
            raise ValueError("ord_type must be 'limit', 'price', or 'market'")

        data = {
            "market": market,
            "side": side,
            "ord_type": ord_type,
        }

        if volume is not None:
            data["volume"] = str(volume)
        if price is not None:
            data["price"] = str(price)

        response = await self._request("POST", "/orders", data=data, auth=True)
        return Order(**response)

    async def cancel_order(self, uuid: str) -> Order:
        """
        Cancel an order.

        Args:
            uuid: Order UUID

        Returns:
            Cancelled Order object
        """
        params = {"uuid": uuid}
        response = await self._request("DELETE", "/order", params=params, auth=True)
        return Order(**response)

    # ============================================================
    # High-Level Methods for Analysis
    # ============================================================

    async def get_analysis_data(
        self,
        market: str,
        candle_count: int = 100,
        trade_count: int = 50,
    ) -> CoinAnalysisData:
        """
        Get aggregated data for AI analysis.

        Fetches ticker, orderbook, candles, and trades in parallel.

        Args:
            market: Market code (e.g., "KRW-BTC")
            candle_count: Number of daily candles to fetch
            trade_count: Number of recent trades to fetch

        Returns:
            CoinAnalysisData with all relevant data
        """
        # Fetch all data in parallel
        ticker_task = self.get_ticker([market])
        orderbook_task = self.get_orderbook([market])
        candles_task = self.get_candles_days(market, count=candle_count)
        trades_task = self.get_trades(market, count=trade_count)
        markets_task = self.get_markets()

        results = await asyncio.gather(
            ticker_task,
            orderbook_task,
            candles_task,
            trades_task,
            markets_task,
            return_exceptions=True,
        )

        ticker_data, orderbook_data, candles_data, trades_data, markets_data = results

        # Handle any errors
        for result in results:
            if isinstance(result, Exception):
                raise result

        ticker = ticker_data[0]
        orderbook = orderbook_data[0]

        # Find market info
        market_info = next((m for m in markets_data if m.market == market), None)
        korean_name = market_info.korean_name if market_info else market
        english_name = market_info.english_name if market_info else market

        # Calculate bid/ask ratio
        bid_ask_ratio = (
            orderbook.total_bid_size / orderbook.total_ask_size
            if orderbook.total_ask_size > 0
            else 0
        )

        return CoinAnalysisData(
            market=market,
            korean_name=korean_name,
            english_name=english_name,
            current_price=ticker.trade_price,
            change_rate_24h=ticker.signed_change_rate * 100,
            change_price_24h=ticker.signed_change_price,
            volume_24h=ticker.acc_trade_volume_24h,
            trade_value_24h=ticker.acc_trade_price_24h,
            high_24h=ticker.high_price,
            low_24h=ticker.low_price,
            high_52w=ticker.highest_52_week_price,
            low_52w=ticker.lowest_52_week_price,
            bid_ask_ratio=bid_ask_ratio,
            total_bid_size=orderbook.total_bid_size,
            total_ask_size=orderbook.total_ask_size,
            candles=[
                {
                    "date": c.candle_date_time_kst,
                    "open": c.opening_price,
                    "high": c.high_price,
                    "low": c.low_price,
                    "close": c.trade_price,
                    "volume": c.candle_acc_trade_volume,
                }
                for c in candles_data
            ],
            recent_trades=[
                {
                    "time": t.trade_time_utc,
                    "price": t.trade_price,
                    "volume": t.trade_volume,
                    "side": t.ask_bid,
                }
                for t in trades_data
            ],
        )

    # ============================================================
    # Internal Methods
    # ============================================================

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        auth: bool = False,
    ) -> dict | list:
        """
        Make HTTP request to Upbit API.

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request body (for POST)
            auth: Whether to include authentication

        Returns:
            JSON response
        """
        headers = {}

        if auth:
            if not self.access_key or not self.secret_key:
                raise ValueError("API keys required for authenticated requests")

            # Generate auth header with query params or body
            query = params or data
            headers = generate_authorization_header(
                self.access_key,
                self.secret_key,
                query,
            )

        try:
            response = await self._client.request(
                method=method,
                url=endpoint,
                params=params,
                json=data if method == "POST" else None,
                headers=headers,
            )

            # Check for errors
            if response.status_code >= 400:
                error_data = response.json() if response.text else {}
                error = error_data.get("error", {})
                raise UpbitAPIError(
                    status_code=response.status_code,
                    message=error.get("message", response.text),
                    error_code=error.get("name"),
                )

            return response.json()

        except httpx.HTTPError as e:
            logger.error("upbit_api_error", error=str(e), endpoint=endpoint)
            raise UpbitAPIError(
                status_code=500,
                message=f"HTTP error: {str(e)}",
            )
