"""
Coin Market Data Endpoints

Endpoints for fetching market data:
- GET /markets - Market list
- POST /markets/search - Search markets
- GET /ticker/{market} - Single ticker
- GET /tickers - Multiple tickers
- GET /candles/{market} - OHLCV data
- GET /orderbook/{market} - Order book
"""

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas.coin import (
    CandleData,
    CandleListResponse,
    MarketInfo,
    MarketListResponse,
    MarketSearchRequest,
    OrderbookResponse,
    OrderbookUnit,
    TickerListResponse,
    TickerResponse,
)
from .constants import (
    CACHE_TTL_SECONDS,
    get_cached_markets,
    get_markets_cache_time,
    set_cached_markets,
)
from .helpers import get_upbit_client, ticker_to_response

logger = structlog.get_logger()
router = APIRouter()


@router.get("/markets", response_model=MarketListResponse)
async def get_markets(
    quote_currency: Optional[str] = Query(
        default="KRW",
        description="Quote currency filter (KRW, BTC, USDT)",
    ),
    include_warning: bool = Query(
        default=False,
        description="Include markets with warnings",
    ),
):
    """
    Get list of available cryptocurrency markets.

    Args:
        quote_currency: Filter by quote currency (default: KRW)
        include_warning: Whether to include markets with warnings

    Returns:
        List of markets with Korean/English names
    """
    cached_markets = get_cached_markets()
    cache_time = get_markets_cache_time()

    # Check cache
    now = datetime.now(timezone.utc)
    if cached_markets and cache_time:
        cache_age = (now - cache_time).total_seconds()
        if cache_age < CACHE_TTL_SECONDS:
            filtered = cached_markets
            if quote_currency:
                filtered = [
                    m for m in filtered if m.market.startswith(f"{quote_currency}-")
                ]
            if not include_warning:
                filtered = [m for m in filtered if not m.market_warning]
            return MarketListResponse(markets=filtered, total=len(filtered))

    # Fetch from API
    async with get_upbit_client() as client:
        try:
            markets = await client.get_markets(is_details=True)

            new_cached = [
                MarketInfo(
                    market=m.market,
                    korean_name=m.korean_name,
                    english_name=m.english_name,
                    market_warning=m.market_warning,
                )
                for m in markets
            ]
            set_cached_markets(new_cached, now)

            # Apply filters
            filtered = new_cached
            if quote_currency:
                filtered = [
                    m for m in filtered if m.market.startswith(f"{quote_currency}-")
                ]
            if not include_warning:
                filtered = [m for m in filtered if not m.market_warning]

            return MarketListResponse(markets=filtered, total=len(filtered))

        except Exception as e:
            logger.error("get_markets_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch markets: {str(e)}",
            )


@router.post("/markets/search", response_model=MarketListResponse)
async def search_markets(request: MarketSearchRequest):
    """
    Search markets by Korean/English name or market code.

    Args:
        request: Search query and limit

    Returns:
        Matching markets
    """
    cached_markets = get_cached_markets()

    # Ensure cache is populated
    if not cached_markets:
        await get_markets(quote_currency=None, include_warning=True)
        cached_markets = get_cached_markets()

    query = request.query.lower()
    matches = []

    for market in cached_markets:
        if (
            query in market.market.lower()
            or query in market.korean_name.lower()
            or query in market.english_name.lower()
        ):
            matches.append(market)
            if len(matches) >= request.limit:
                break

    return MarketListResponse(markets=matches, total=len(matches))


@router.get("/ticker/{market}", response_model=TickerResponse)
async def get_ticker(market: str):
    """
    Get current ticker for a market.

    Args:
        market: Market code (e.g., KRW-BTC)

    Returns:
        Current price and 24h stats
    """
    market = market.upper()

    async with get_upbit_client() as client:
        try:
            tickers = await client.get_ticker([market])
            if not tickers:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Market {market} not found",
                )

            return ticker_to_response(tickers[0])

        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_ticker_failed", market=market, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch ticker: {str(e)}",
            )


@router.get("/tickers", response_model=TickerListResponse)
async def get_tickers(
    markets: str = Query(
        ...,
        description="Comma-separated market codes (e.g., KRW-BTC,KRW-ETH,KRW-XRP)",
    ),
):
    """
    Get current tickers for multiple markets in a single request.

    Args:
        markets: Comma-separated market codes (max ~100 markets)

    Returns:
        List of ticker data for all requested markets
    """
    market_list = [m.strip().upper() for m in markets.split(",") if m.strip()]

    if not market_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one market code is required",
        )

    if len(market_list) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 markets per request",
        )

    async with get_upbit_client() as client:
        try:
            tickers = await client.get_ticker(market_list)

            ticker_responses = [ticker_to_response(t) for t in tickers]

            return TickerListResponse(
                tickers=ticker_responses,
                total=len(ticker_responses),
            )

        except Exception as e:
            logger.error("get_tickers_failed", markets=markets, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch tickers: {str(e)}",
            )


@router.get("/candles/{market}", response_model=CandleListResponse)
async def get_candles(
    market: str,
    interval: str = Query(
        default="1d",
        description="Candle interval (1s, 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M)",
    ),
    count: int = Query(
        default=100,
        ge=1,
        le=200,
        description="Number of candles",
    ),
):
    """
    Get candle (OHLCV) data for a market.

    Args:
        market: Market code
        interval: Candle interval
        count: Number of candles (max 200)

    Returns:
        List of candles (newest first)
    """
    market = market.upper()

    # Map interval to API params
    interval_map = {
        "1s": ("seconds", None),
        "1m": ("minutes", 1),
        "3m": ("minutes", 3),
        "5m": ("minutes", 5),
        "10m": ("minutes", 10),
        "15m": ("minutes", 15),
        "30m": ("minutes", 30),
        "1h": ("minutes", 60),
        "4h": ("minutes", 240),
        "1d": ("days", None),
        "1w": ("weeks", None),
        "1M": ("months", None),
    }

    if interval not in interval_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid interval: {interval}. Supported: {list(interval_map.keys())}",
        )

    candle_type, unit = interval_map[interval]

    async with get_upbit_client() as client:
        try:
            if candle_type == "seconds":
                candles = await client.get_candles_seconds(market=market, count=count)
            elif candle_type == "minutes":
                candles = await client.get_candles_minutes(
                    market=market, unit=unit, count=count
                )
            elif candle_type == "days":
                candles = await client.get_candles_days(market=market, count=count)
            elif candle_type == "weeks":
                candles = await client.get_candles_weeks(market=market, count=count)
            else:  # months
                candles = await client.get_candles_months(market=market, count=count)

            return CandleListResponse(
                market=market,
                interval=interval,
                candles=[
                    CandleData(
                        datetime=c.candle_date_time_kst,
                        open=c.opening_price,
                        high=c.high_price,
                        low=c.low_price,
                        close=c.trade_price,
                        volume=c.candle_acc_trade_volume,
                    )
                    for c in candles
                ],
            )

        except Exception as e:
            logger.error(
                "get_candles_failed", market=market, interval=interval, error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch candles: {str(e)}",
            )


@router.get("/orderbook/{market}", response_model=OrderbookResponse)
async def get_orderbook(market: str):
    """
    Get orderbook for a market.

    Args:
        market: Market code

    Returns:
        Bid/ask orderbook with totals
    """
    market = market.upper()

    async with get_upbit_client() as client:
        try:
            orderbooks = await client.get_orderbook([market])
            if not orderbooks:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Market {market} not found",
                )

            ob = orderbooks[0]
            bid_ask_ratio = (
                ob.total_bid_size / ob.total_ask_size if ob.total_ask_size > 0 else 0
            )

            return OrderbookResponse(
                market=ob.market,
                total_ask_size=ob.total_ask_size,
                total_bid_size=ob.total_bid_size,
                bid_ask_ratio=bid_ask_ratio,
                asks=[
                    OrderbookUnit(price=u.ask_price, size=u.ask_size)
                    for u in ob.orderbook_units
                ],
                bids=[
                    OrderbookUnit(price=u.bid_price, size=u.bid_size)
                    for u in ob.orderbook_units
                ],
                timestamp=datetime.now(timezone.utc),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_orderbook_failed", market=market, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch orderbook: {str(e)}",
            )
