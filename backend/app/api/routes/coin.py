"""
Coin Analysis API Routes

Endpoints for Upbit cryptocurrency market data and analysis.
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.api.schemas.coin import (
    CandleData,
    CandleListResponse,
    CoinAnalysisRequest,
    CoinAnalysisResponse,
    CoinAnalysisStatusResponse,
    CoinAnalysisSummary,
    CoinTradeProposalResponse,
    MarketInfo,
    MarketListResponse,
    MarketSearchRequest,
    OrderbookResponse,
    OrderbookUnit,
    TickerListResponse,
    TickerResponse,
)
from app.config import settings
from services.upbit import UpbitClient

logger = structlog.get_logger()
router = APIRouter()

# In-memory session store for coin analysis
# TODO: Merge with stock session store or use unified storage
coin_sessions: dict[str, dict] = {}

# Cached market list
_cached_markets: list[MarketInfo] = []
_markets_cache_time: Optional[datetime] = None
CACHE_TTL_SECONDS = 300  # 5 minutes


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def get_upbit_client() -> UpbitClient:
    """Get Upbit client instance."""
    return UpbitClient(
        access_key=getattr(settings, "UPBIT_ACCESS_KEY", None),
        secret_key=getattr(settings, "UPBIT_SECRET_KEY", None),
    )


def get_coin_session(session_id: str) -> dict:
    """Get session or raise 404."""
    session = coin_sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coin session {session_id} not found",
        )
    return session


# -------------------------------------------
# Market Data Endpoints
# -------------------------------------------


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
    global _cached_markets, _markets_cache_time

    # Check cache
    now = datetime.utcnow()
    if _cached_markets and _markets_cache_time:
        cache_age = (now - _markets_cache_time).total_seconds()
        if cache_age < CACHE_TTL_SECONDS:
            filtered = _cached_markets
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

            _cached_markets = [
                MarketInfo(
                    market=m.market,
                    korean_name=m.korean_name,
                    english_name=m.english_name,
                    market_warning=m.market_warning,
                )
                for m in markets
            ]
            _markets_cache_time = now

            # Apply filters
            filtered = _cached_markets
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
    # Ensure cache is populated
    if not _cached_markets:
        await get_markets(quote_currency=None, include_warning=True)

    query = request.query.lower()
    matches = []

    for market in _cached_markets:
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

            t = tickers[0]
            return TickerResponse(
                market=t.market,
                trade_price=t.trade_price,
                change=t.change,
                change_rate=t.signed_change_rate * 100,
                change_price=t.signed_change_price,
                high_price=t.high_price,
                low_price=t.low_price,
                trade_volume=t.acc_trade_volume_24h,
                acc_trade_price_24h=t.acc_trade_price_24h,
                timestamp=datetime.utcnow(),
            )

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

    This batch endpoint reduces API calls and avoids rate limiting.
    Upbit allows querying multiple markets in one request.

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

            ticker_responses = [
                TickerResponse(
                    market=t.market,
                    trade_price=t.trade_price,
                    change=t.change,
                    change_rate=t.signed_change_rate * 100,
                    change_price=t.signed_change_price,
                    high_price=t.high_price,
                    low_price=t.low_price,
                    trade_volume=t.acc_trade_volume_24h,
                    acc_trade_price_24h=t.acc_trade_price_24h,
                    timestamp=datetime.utcnow(),
                )
                for t in tickers
            ]

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
        description="Candle interval (1s, 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M). Note: 1s only available for last 3 months.",
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

    Note:
        Second candles (1s) are only available for the most recent 3 months.
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
                timestamp=datetime.utcnow(),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_orderbook_failed", market=market, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch orderbook: {str(e)}",
            )


# -------------------------------------------
# Analysis Endpoints
# -------------------------------------------


@router.post("/analysis/start", response_model=CoinAnalysisResponse)
async def start_coin_analysis(
    request: CoinAnalysisRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a new coin analysis session.

    The analysis runs in the background. Use the returned session_id
    to track progress via `/status/{session_id}` or WebSocket.

    Args:
        request: Analysis request with market code

    Returns:
        Session ID and initial status
    """
    session_id = str(uuid.uuid4())
    market = request.market.upper()

    logger.info(
        "coin_analysis_started",
        session_id=session_id,
        market=market,
    )

    # Get market info for Korean name
    korean_name = None
    if _cached_markets:
        market_info = next((m for m in _cached_markets if m.market == market), None)
        if market_info:
            korean_name = market_info.korean_name

    # Create session record
    coin_sessions[session_id] = {
        "session_id": session_id,
        "market": market,
        "korean_name": korean_name,
        "status": "running",
        "state": {
            "market": market,
            "korean_name": korean_name,
            "query": request.query,
            "reasoning_log": [],
            "current_stage": "initializing",
        },
        "created_at": datetime.utcnow(),
        "error": None,
    }

    # Run analysis in background
    background_tasks.add_task(
        run_coin_analysis_task,
        session_id,
    )

    return CoinAnalysisResponse(
        session_id=session_id,
        market=market,
        status="started",
        message="Coin analysis started. Connect to WebSocket for live updates.",
    )


async def run_coin_analysis_task(session_id: str):
    """
    Background task to run coin analysis using LangGraph workflow.

    Runs the coin trading graph through all analysis stages until
    it reaches the approval interrupt point.
    """
    from agents.graph.coin_trading_graph import get_coin_trading_graph
    from agents.graph.coin_state import create_coin_initial_state

    session = coin_sessions.get(session_id)
    if not session:
        logger.error("coin_session_not_found", session_id=session_id)
        return

    try:
        market = session["market"]
        korean_name = session.get("korean_name")

        # Get the coin trading graph
        graph = get_coin_trading_graph()

        # Create initial state
        initial_state = create_coin_initial_state(
            market=market,
            korean_name=korean_name,
            user_query=session["state"].get("query"),
        )

        config = {"configurable": {"thread_id": session_id}}

        # Run until interrupt (approval node)
        async for event in graph.astream(initial_state, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    # Update session state with node output
                    if isinstance(node_output, dict):
                        session["state"].update(node_output)
                    session["last_node"] = node_name

                    logger.debug(
                        "coin_graph_node_completed",
                        session_id=session_id,
                        node=node_name,
                    )

        # Check if we hit the approval interrupt
        state = session["state"]
        if state.get("awaiting_approval"):
            session["status"] = "awaiting_approval"
            logger.info(
                "coin_analysis_awaiting_approval",
                session_id=session_id,
                market=market,
            )
        elif state.get("error"):
            session["status"] = "error"
            session["error"] = state.get("error")
        else:
            session["status"] = "completed"

    except Exception as e:
        logger.error(
            "coin_analysis_failed",
            session_id=session_id,
            error=str(e),
        )
        session["status"] = "error"
        session["error"] = str(e)
        session["state"]["reasoning_log"] = session["state"].get("reasoning_log", []) + [
            f"[Error] Analysis failed: {str(e)}"
        ]


@router.get("/analysis/status/{session_id}", response_model=CoinAnalysisStatusResponse)
async def get_coin_analysis_status(session_id: str):
    """
    Get the current status of a coin analysis session.

    Args:
        session_id: Session identifier

    Returns:
        Full status including market data and trade proposal
    """
    session = get_coin_session(session_id)
    state = session["state"]

    # Build trade proposal response
    trade_proposal = None
    proposal = state.get("trade_proposal")
    if proposal:
        trade_proposal = CoinTradeProposalResponse(
            id=proposal.get("id", ""),
            market=proposal.get("market", ""),
            korean_name=proposal.get("korean_name"),
            action=proposal.get("action", "HOLD"),
            quantity=proposal.get("quantity", 0),
            entry_price=proposal.get("entry_price"),
            stop_loss=proposal.get("stop_loss"),
            take_profit=proposal.get("take_profit"),
            risk_score=proposal.get("risk_score", 0.5),
            position_size_pct=proposal.get("position_size_pct", 5.0),
            rationale=proposal.get("rationale", ""),
            bull_case=proposal.get("bull_case", ""),
            bear_case=proposal.get("bear_case", ""),
            created_at=datetime.fromisoformat(proposal["created_at"])
            if isinstance(proposal.get("created_at"), str)
            else proposal.get("created_at", datetime.utcnow()),
        )

    # Build analyses (placeholder for now)
    analyses = []
    for key in [
        "technical_analysis",
        "fundamental_analysis",
        "sentiment_analysis",
        "risk_assessment",
    ]:
        analysis = state.get(key)
        if analysis:
            analyses.append(
                CoinAnalysisSummary(
                    agent_type=analysis.get("agent_type", key),
                    signal=analysis.get("signal", "hold"),
                    confidence=analysis.get("confidence", 0.5),
                    summary=analysis.get("summary", "")[:300],
                    key_factors=analysis.get("key_factors", [])[:5],
                )
            )

    return CoinAnalysisStatusResponse(
        session_id=session_id,
        market=session["market"],
        korean_name=session.get("korean_name"),
        status=session["status"],
        current_stage=state.get("current_stage"),
        awaiting_approval=state.get("awaiting_approval", False),
        trade_proposal=trade_proposal,
        analyses=analyses,
        reasoning_log=state.get("reasoning_log", [])[-20:],
        error=session.get("error"),
    )


@router.post("/analysis/cancel/{session_id}")
async def cancel_coin_analysis(session_id: str):
    """
    Cancel a coin analysis session.

    Args:
        session_id: Session identifier

    Returns:
        Confirmation message
    """
    session = get_coin_session(session_id)

    if session["status"] in ["completed", "cancelled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session already {session['status']}",
        )

    session["status"] = "cancelled"
    session["state"]["reasoning_log"].append("[System] Analysis cancelled by user")

    logger.info("coin_analysis_cancelled", session_id=session_id)

    return {"message": f"Session {session_id} cancelled"}


# -------------------------------------------
# Export session store
# -------------------------------------------


def get_coin_sessions() -> dict:
    """Get reference to coin sessions (for WebSocket, approval routes)."""
    return coin_sessions
