"""
Korean Stock Market Data Endpoints

Endpoints for fetching market data:
- GET /stocks - Popular stocks list
- POST /stocks/search - Search stocks
- GET /ticker/{stk_cd} - Current ticker
- GET /candles/{stk_cd} - OHLCV data
- GET /orderbook/{stk_cd} - Order book
"""

import random
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas.kr_stocks import (
    KRStockCandleData,
    KRStockCandlesResponse,
    KRStockInfo,
    KRStockListResponse,
    KRStockOrderbookResponse,
    KRStockOrderbookUnit,
    KRStockSearchRequest,
    KRStockTickerResponse,
)
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from .constants import (
    CACHE_TTL_SECONDS,
    KOREAN_STOCKS,
    POPULAR_STOCKS,
    get_cached_popular_stocks,
    get_stocks_cache_time,
    set_cached_popular_stocks,
)

logger = structlog.get_logger()
router = APIRouter()


@router.get("/stocks", response_model=KRStockListResponse)
async def get_stocks():
    """
    Get list of popular Korean stocks.

    Returns a curated list of popular Korean stocks for quick selection.
    For full stock search, use the search endpoint.

    Returns:
        List of popular Korean stocks
    """
    cached_stocks = get_cached_popular_stocks()
    cache_time = get_stocks_cache_time()

    # Check cache
    now = datetime.now(timezone.utc)
    if cached_stocks and cache_time:
        cache_age = (now - cache_time).total_seconds()
        if cache_age < CACHE_TTL_SECONDS:
            return KRStockListResponse(
                stocks=cached_stocks, total=len(cached_stocks)
            )

    # Fetch current prices for popular stocks
    client = await get_shared_kiwoom_client_async()
    stocks = []

    try:
        for stk_cd, stk_nm in POPULAR_STOCKS:
            try:
                info = await client.get_stock_info(stk_cd)
                stocks.append(
                    KRStockInfo(
                        stk_cd=stk_cd,
                        stk_nm=info.stk_nm if info else stk_nm,
                        cur_prc=info.cur_prc if info else 0,
                        prdy_ctrt=info.prdy_ctrt if info else 0.0,
                        prdy_vrss=info.prdy_vrss if info else 0,
                        trde_qty=info.acml_vol if info else 0,
                        trde_prica=info.acml_tr_pbmn if info else 0,
                    )
                )
            except Exception as e:
                logger.warning(
                    "failed_to_fetch_stock_info", stk_cd=stk_cd, error=str(e)
                )
                stocks.append(
                    KRStockInfo(
                        stk_cd=stk_cd,
                        stk_nm=stk_nm,
                        cur_prc=0,
                        prdy_ctrt=0.0,
                        prdy_vrss=0,
                        trde_qty=0,
                        trde_prica=0,
                    )
                )

        set_cached_popular_stocks(stocks, now)
        return KRStockListResponse(stocks=stocks, total=len(stocks))

    except Exception as e:
        logger.error("get_stocks_failed", error=str(e))
        # Return cached data if available
        if cached_stocks:
            return KRStockListResponse(
                stocks=cached_stocks, total=len(cached_stocks)
            )
        # Return static list without prices
        stocks = [
            KRStockInfo(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                cur_prc=0,
                prdy_ctrt=0.0,
                prdy_vrss=0,
                trde_qty=0,
                trde_prica=0,
            )
            for stk_cd, stk_nm in POPULAR_STOCKS
        ]
        return KRStockListResponse(stocks=stocks, total=len(stocks))


@router.post("/stocks/search", response_model=KRStockListResponse)
async def search_stocks(request: KRStockSearchRequest):
    """
    Search Korean stocks by code or name.

    Args:
        request: Search query and limit

    Returns:
        Matching stocks
    """
    query = request.query.strip()
    cached_stocks = get_cached_popular_stocks()

    # If query looks like a stock code (6 digits), fetch directly
    if query.isdigit() and len(query) == 6:
        client = await get_shared_kiwoom_client_async()
        try:
            info = await client.get_stock_info(query)
            if info:
                return KRStockListResponse(
                    stocks=[
                        KRStockInfo(
                            stk_cd=query,
                            stk_nm=info.stk_nm,
                            cur_prc=info.cur_prc,
                            prdy_ctrt=info.prdy_ctrt,
                            prdy_vrss=info.prdy_vrss,
                            trde_qty=info.acml_vol,
                            trde_prica=info.acml_tr_pbmn,
                        )
                    ],
                    total=1,
                )
        except Exception as e:
            logger.warning("stock_search_failed", query=query, error=str(e))

    # Search in cached popular stocks first
    query_lower = query.lower()
    matches = []
    matched_codes = set()

    for stock in cached_stocks:
        if query_lower in stock.stk_cd.lower() or query_lower in stock.stk_nm.lower():
            matches.append(stock)
            matched_codes.add(stock.stk_cd)
            if len(matches) >= request.limit:
                break

    # Search in extended KOREAN_STOCKS list
    if len(matches) < request.limit:
        for stk_cd, stk_nm in KOREAN_STOCKS:
            if stk_cd in matched_codes:
                continue
            if query_lower in stk_cd.lower() or query_lower in stk_nm.lower():
                matches.append(
                    KRStockInfo(
                        stk_cd=stk_cd,
                        stk_nm=stk_nm,
                        cur_prc=0,
                        prdy_ctrt=0.0,
                        prdy_vrss=0,
                        trde_qty=0,
                        trde_prica=0,
                    )
                )
                matched_codes.add(stk_cd)
                if len(matches) >= request.limit:
                    break

    return KRStockListResponse(stocks=matches, total=len(matches))


@router.get("/ticker/{stk_cd}", response_model=KRStockTickerResponse)
async def get_ticker(stk_cd: str):
    """
    Get current ticker for a Korean stock.

    Args:
        stk_cd: Stock code (e.g., 005930)

    Returns:
        Current price and stats
    """
    if len(stk_cd) != 6 or not stk_cd.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock code must be 6 digits",
        )

    client = await get_shared_kiwoom_client_async()

    try:
        info = await client.get_stock_info(stk_cd)

        if not info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Stock {stk_cd} not found",
            )

        return KRStockTickerResponse(
            stk_cd=stk_cd,
            stk_nm=info.stk_nm,
            cur_prc=info.cur_prc,
            prdy_vrss=info.prdy_vrss,
            prdy_ctrt=info.prdy_ctrt,
            opng_prc=info.strt_prc,
            high_prc=info.high_prc,
            low_prc=info.low_prc,
            trde_qty=info.acml_vol,
            trde_prica=info.acml_tr_pbmn,
            per=info.per,
            pbr=info.pbr,
            eps=info.eps,
            bps=info.bps,
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_ticker_failed", stk_cd=stk_cd, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to fetch ticker: {str(e)}",
        )


@router.get("/candles/{stk_cd}", response_model=KRStockCandlesResponse)
async def get_candles(
    stk_cd: str,
    count: int = Query(
        default=60,
        ge=1,
        le=100,
        description="Number of candles (max 100)",
    ),
):
    """
    Get daily candle (OHLCV) data for a Korean stock.

    Args:
        stk_cd: Stock code
        count: Number of candles (max 100)

    Returns:
        List of daily candles (newest first)
    """
    if len(stk_cd) != 6 or not stk_cd.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock code must be 6 digits",
        )

    client = await get_shared_kiwoom_client_async()

    try:
        # get_daily_chart returns list[ChartData], not an object with .candles
        chart_data_list = await client.get_daily_chart(stk_cd)

        if not chart_data_list:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No chart data for stock {stk_cd}",
            )

        # Limit to requested count
        chart_data_list = chart_data_list[:count]

        # Get stock name
        info = await client.get_stock_info(stk_cd)
        stk_nm = info.stk_nm if info else None

        # Map ChartData fields to KRStockCandleData fields
        candles = [
            KRStockCandleData(
                stck_bsop_date=c.dt,
                stck_oprc=c.open_prc,
                stck_hgpr=c.high_prc,
                stck_lwpr=c.low_prc,
                stck_clpr=c.clos_prc,
                acml_vol=c.acml_vol,
                acml_tr_pbmn=c.acml_tr_pbmn or 0,
            )
            for c in chart_data_list
        ]

        return KRStockCandlesResponse(
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            candles=candles,
            period="D",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("get_candles_api_failed_using_mock", stk_cd=stk_cd, error=str(e))
        # Fallback to mock data when API fails
        return _generate_mock_candles(stk_cd, count)


def _generate_mock_candles(stk_cd: str, count: int = 60) -> KRStockCandlesResponse:
    """
    Generate mock candle data for testing/demo when API is unavailable.

    Uses consistent pseudo-random values based on stock code for reproducibility.
    """
    # Use stock code as seed for consistent mock data
    seed = sum(ord(c) for c in stk_cd)
    random.seed(seed)

    # Get stock name from KOREAN_STOCKS list
    stk_nm = None
    for code, name in KOREAN_STOCKS:
        if code == stk_cd:
            stk_nm = name
            break

    # Generate base price based on stock
    base_price = 50000 + (seed % 100) * 1000
    price = base_price

    candles = []
    today = datetime.now()

    for i in range(count - 1, -1, -1):
        dt = today - timedelta(days=i)
        date_str = dt.strftime("%Y%m%d")

        # Skip weekends
        if dt.weekday() >= 5:
            continue

        # Random walk for price
        change_pct = (random.random() - 0.48) * 0.03
        volatility = price * 0.02

        open_prc = int(price)
        close_prc = int(price * (1 + change_pct))
        high_prc = int(max(open_prc, close_prc) + random.random() * volatility * 0.5)
        low_prc = int(min(open_prc, close_prc) - random.random() * volatility * 0.5)

        if high_prc < low_prc:
            high_prc, low_prc = low_prc, high_prc

        acml_vol = int(500000 + random.random() * 2000000)
        acml_tr_pbmn = int(close_prc * acml_vol)

        candles.append(KRStockCandleData(
            stck_bsop_date=date_str,
            stck_oprc=open_prc,
            stck_hgpr=high_prc,
            stck_lwpr=low_prc,
            stck_clpr=close_prc,
            acml_vol=acml_vol,
            acml_tr_pbmn=acml_tr_pbmn,
        ))

        price = close_prc

    # Return newest first
    candles.reverse()

    logger.info("mock_candles_generated", stk_cd=stk_cd, count=len(candles))

    return KRStockCandlesResponse(
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        candles=candles[:count],
        period="D",
    )


@router.get("/orderbook/{stk_cd}", response_model=KRStockOrderbookResponse)
async def get_orderbook(stk_cd: str):
    """
    Get orderbook for a Korean stock.

    Args:
        stk_cd: Stock code

    Returns:
        Bid/ask orderbook with totals
    """
    if len(stk_cd) != 6 or not stk_cd.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock code must be 6 digits",
        )

    client = await get_shared_kiwoom_client_async()

    try:
        orderbook = await client.get_orderbook(stk_cd)

        if not orderbook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No orderbook for stock {stk_cd}",
            )

        # Get stock name
        info = await client.get_stock_info(stk_cd)
        stk_nm = info.stk_nm if info else None

        asks = [
            KRStockOrderbookUnit(
                price=ask.price,
                volume=ask.volume,
                change_rate=ask.change_rate if hasattr(ask, "change_rate") else None,
            )
            for ask in orderbook.asks
        ]

        bids = [
            KRStockOrderbookUnit(
                price=bid.price,
                volume=bid.volume,
                change_rate=bid.change_rate if hasattr(bid, "change_rate") else None,
            )
            for bid in orderbook.bids
        ]

        return KRStockOrderbookResponse(
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            asks=asks,
            bids=bids,
            total_ask_volume=orderbook.total_ask_volume,
            total_bid_volume=orderbook.total_bid_volume,
            bid_ask_ratio=orderbook.bid_ask_ratio,
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_orderbook_failed", stk_cd=stk_cd, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to fetch orderbook: {str(e)}",
        )
