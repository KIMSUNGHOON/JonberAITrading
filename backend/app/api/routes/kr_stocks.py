"""
Korean Stock (Kiwoom) Analysis API Routes

Endpoints for Kiwoom Securities Korean stock market data and analysis.
Follows the same patterns as coin.py for consistency.
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.api.schemas.kr_stocks import (
    KRStockAccountResponse,
    KRStockAnalysisRequest,
    KRStockAnalysisResponse,
    KRStockAnalysisStatusResponse,
    KRStockAnalysisSummary,
    KRStockCandleData,
    KRStockCandlesResponse,
    KRStockCashBalance,
    KRStockHolding,
    KRStockInfo,
    KRStockListResponse,
    KRStockOrderbookResponse,
    KRStockOrderbookUnit,
    KRStockOrderCancelResponse,
    KRStockOrderListResponse,
    KRStockOrderRequest,
    KRStockOrderResponse,
    KRStockPosition,
    KRStockPositionListResponse,
    KRStockSearchRequest,
    KRStockTickerResponse,
    KRStockTradeListResponse,
    KRStockTradeProposalResponse,
    KRStockTradeRecord,
    KiwoomApiKeyRequest,
    KiwoomApiKeyResponse,
    KiwoomApiKeyStatus,
    KiwoomValidationResponse,
)
from app.config import settings
from app.api.routes.settings import (
    get_kiwoom_app_key,
    get_kiwoom_secret_key,
    get_kiwoom_account,
    get_kiwoom_is_mock,
)
from app.core.kiwoom_singleton import (
    get_shared_kiwoom_client,
    get_shared_kiwoom_client_async,
    invalidate_kiwoom_client,
)
from app.core.analysis_limiter import (
    acquire_analysis_slot,
    release_analysis_slot,
    get_active_analysis_count,
    MAX_CONCURRENT_ANALYSES,
)

logger = structlog.get_logger()
router = APIRouter()

# In-memory session store for Korean stock analysis
kr_stock_sessions: dict[str, dict] = {}

# Cached stock list (popular stocks for quick access)
_cached_popular_stocks: list[KRStockInfo] = []
_stocks_cache_time: Optional[datetime] = None
CACHE_TTL_SECONDS = 300  # 5 minutes

# Note: KiwoomClient singleton is now managed in app.core.kiwoom_singleton

# Korean stocks list (KOSPI/KOSDAQ major stocks)
# Extended list for better search functionality
KOREAN_STOCKS = [
    # 시가총액 상위 (KOSPI)
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("005380", "현대차"),
    ("051910", "LG화학"),
    ("006400", "삼성SDI"),
    ("035720", "카카오"),
    ("068270", "셀트리온"),
    ("028260", "삼성물산"),
    ("105560", "KB금융"),
    ("005490", "POSCO홀딩스"),
    ("055550", "신한지주"),
    ("003670", "포스코퓨처엠"),
    ("000270", "기아"),
    ("012330", "현대모비스"),
    ("066570", "LG전자"),
    ("003550", "LG"),
    ("096770", "SK이노베이션"),
    ("086790", "하나금융지주"),
    ("032830", "삼성생명"),
    ("015760", "한국전력"),
    ("033780", "KT&G"),
    ("034730", "SK"),
    ("017670", "SK텔레콤"),
    ("018260", "삼성에스디에스"),
    ("000810", "삼성화재"),
    ("030200", "KT"),
    ("316140", "우리금융지주"),
    ("009150", "삼성전기"),
    ("010950", "S-Oil"),
    ("036570", "엔씨소프트"),
    ("090430", "아모레퍼시픽"),
    ("011170", "롯데케미칼"),
    ("034020", "두산에너빌리티"),
    ("024110", "기업은행"),
    ("009540", "한국조선해양"),
    ("032640", "LG유플러스"),
    ("010130", "고려아연"),
    ("021240", "코웨이"),
    ("047050", "포스코인터내셔널"),
    ("003490", "대한항공"),
    ("009830", "한화솔루션"),
    ("088350", "한화생명"),
    ("010620", "현대미포조선"),
    ("000100", "유한양행"),
    ("326030", "SK바이오팜"),
    ("011200", "HMM"),
    ("329180", "현대중공업"),
    ("267250", "HD현대"),
    ("004020", "현대제철"),
    # 추가 인기 종목
    ("352820", "하이브"),
    ("003410", "쌍용C&E"),
    ("002790", "아모레G"),
    ("000720", "현대건설"),
    ("047810", "한국항공우주"),
    ("010140", "삼성중공업"),
    ("051900", "LG생활건강"),
    ("011780", "금호석유"),
    ("034220", "LG디스플레이"),
    ("001450", "현대해상"),
    ("004370", "농심"),
    ("139480", "이마트"),
    ("007070", "GS리테일"),
    ("004990", "롯데지주"),
    ("003230", "삼양식품"),
    ("097950", "CJ제일제당"),
    ("009240", "한샘"),
    ("035250", "강원랜드"),
    ("000880", "한화"),
    ("161390", "한국타이어앤테크놀로지"),
    # KOSDAQ 인기 종목
    ("247540", "에코프로비엠"),
    ("086520", "에코프로"),
    ("041510", "에스엠"),
    ("035900", "JYP Ent."),
    ("122870", "와이지엔터테인먼트"),
    ("263750", "펄어비스"),
    ("293490", "카카오게임즈"),
    ("112040", "위메이드"),
    ("251270", "넷마블"),
    ("053800", "안랩"),
    ("145020", "휴젤"),
    ("028300", "HLB"),
    ("196170", "알테오젠"),
    ("091990", "셀트리온헬스케어"),
    ("068760", "셀트리온제약"),
    ("357780", "솔브레인"),
    ("036830", "솔브레인홀딩스"),
    ("000120", "CJ대한통운"),
    ("078930", "GS"),
    ("034730", "SK"),
    ("006360", "GS건설"),
    ("069960", "현대백화점"),
    ("004170", "신세계"),
    ("001040", "CJ"),
    ("272210", "한화시스템"),
    ("042700", "한미반도체"),
    ("336260", "두산퓨얼셀"),
    ("298050", "효성첨단소재"),
    ("241560", "두산밥캣"),
]

# Popular Korean stocks for default list (subset for quick access)
POPULAR_STOCKS = KOREAN_STOCKS[:10]


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def get_kr_stock_session(session_id: str) -> dict:
    """Get session or raise 404."""
    session = kr_stock_sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Korean stock session {session_id} not found",
        )
    return session


def _check_kiwoom_api_keys():
    """Check if Kiwoom API keys are configured (runtime or env)."""
    app_key = get_kiwoom_app_key()
    secret_key = get_kiwoom_secret_key()

    if not app_key or not secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kiwoom API keys not configured. Please configure in Settings.",
        )


# -------------------------------------------
# Market Data Endpoints
# -------------------------------------------


@router.get("/stocks", response_model=KRStockListResponse)
async def get_stocks():
    """
    Get list of popular Korean stocks.

    Returns a curated list of popular Korean stocks for quick selection.
    For full stock search, use the search endpoint.

    Returns:
        List of popular Korean stocks
    """
    global _cached_popular_stocks, _stocks_cache_time

    # Check cache
    now = datetime.utcnow()
    if _cached_popular_stocks and _stocks_cache_time:
        cache_age = (now - _stocks_cache_time).total_seconds()
        if cache_age < CACHE_TTL_SECONDS:
            return KRStockListResponse(
                stocks=_cached_popular_stocks, total=len(_cached_popular_stocks)
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

        _cached_popular_stocks = stocks
        _stocks_cache_time = now

        return KRStockListResponse(stocks=stocks, total=len(stocks))

    except Exception as e:
        logger.error("get_stocks_failed", error=str(e))
        # Return cached data if available
        if _cached_popular_stocks:
            return KRStockListResponse(
                stocks=_cached_popular_stocks, total=len(_cached_popular_stocks)
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

    for stock in _cached_popular_stocks:
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
            timestamp=datetime.utcnow(),
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
        # ChartData uses: dt, open_prc, high_prc, low_prc, clos_prc, acml_vol, acml_tr_pbmn
        # KRStockCandleData uses: stck_bsop_date, stck_oprc, stck_hgpr, stck_lwpr, stck_clpr, acml_vol, acml_tr_pbmn
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
        # Fallback to mock data when API fails (e.g., no credentials configured)
        return _generate_mock_candles(stk_cd, count)


def _generate_mock_candles(stk_cd: str, count: int = 60) -> KRStockCandlesResponse:
    """
    Generate mock candle data for testing/demo when API is unavailable.

    Uses consistent pseudo-random values based on stock code for reproducibility.
    """
    import random
    from datetime import datetime, timedelta

    # Use stock code as seed for consistent mock data
    seed = sum(ord(c) for c in stk_cd)
    random.seed(seed)

    # Get stock name from KOREAN_STOCKS list
    stk_nm = None
    for code, name in KOREAN_STOCKS:
        if code == stk_cd:
            stk_nm = name
            break

    # Generate base price based on stock (major stocks like Samsung have higher prices)
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
        change_pct = (random.random() - 0.48) * 0.03  # -1.5% to +1.5%
        volatility = price * 0.02

        open_prc = int(price)
        close_prc = int(price * (1 + change_pct))
        high_prc = int(max(open_prc, close_prc) + random.random() * volatility * 0.5)
        low_prc = int(min(open_prc, close_prc) - random.random() * volatility * 0.5)

        # Ensure high >= low
        if high_prc < low_prc:
            high_prc, low_prc = low_prc, high_prc

        # Random volume
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

    # Return newest first (most recent at index 0)
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
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_orderbook_failed", stk_cd=stk_cd, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to fetch orderbook: {str(e)}",
        )


# -------------------------------------------
# Analysis Endpoints
# -------------------------------------------


@router.post("/analysis/start", response_model=KRStockAnalysisResponse)
async def start_kr_stock_analysis(
    request: KRStockAnalysisRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a new Korean stock analysis session.

    The analysis runs in the background using Kiwoom market data and LLM agents.
    Use the returned session_id to track progress via `/status/{session_id}` or WebSocket.

    Args:
        request: Analysis request with stock code

    Returns:
        Session ID and initial status
    """
    session_id = str(uuid.uuid4())
    stk_cd = request.stk_cd

    logger.info(
        "kr_stock_analysis_started",
        session_id=session_id,
        stk_cd=stk_cd,
    )

    # Get stock name
    stk_nm = None
    client = await get_shared_kiwoom_client_async()
    try:
        info = await client.get_stock_info(stk_cd)
        if info:
            stk_nm = info.stk_nm
    except Exception as e:
        logger.warning("failed_to_get_stock_name", stk_cd=stk_cd, error=str(e))

    # Create session record
    kr_stock_sessions[session_id] = {
        "session_id": session_id,
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "status": "running",
        "state": {
            "stk_cd": stk_cd,
            "stk_nm": stk_nm,
            "query": request.query,
            "reasoning_log": [],
            "current_stage": "data_collection",  # Match frontend WorkflowProgress stage IDs
        },
        "created_at": datetime.utcnow(),
        "error": None,
    }

    # Run analysis in background
    background_tasks.add_task(
        run_kr_stock_analysis_task,
        session_id,
    )

    return KRStockAnalysisResponse(
        session_id=session_id,
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        status="started",
        message="한국주식 분석이 시작되었습니다. WebSocket으로 실시간 업데이트를 받을 수 있습니다.",
    )


async def run_kr_stock_analysis_task(session_id: str):
    """
    Background task to run Korean stock analysis using LangGraph workflow.

    Runs the kr_stock trading graph through all analysis stages until
    it reaches the approval interrupt point.
    """
    from agents.graph.kr_stock_graph import get_kr_stock_trading_graph
    from agents.graph.kr_stock_state import create_kr_stock_initial_state

    session = kr_stock_sessions.get(session_id)
    if not session:
        logger.error("kr_stock_session_not_found", session_id=session_id)
        return

    # Acquire analysis slot (limits concurrent analyses)
    slot_acquired = await acquire_analysis_slot(timeout=60.0)
    if not slot_acquired:
        logger.warning(
            "kr_stock_analysis_slot_timeout",
            session_id=session_id,
            active_count=get_active_analysis_count(),
        )
        session["status"] = "error"
        session["error"] = "Analysis timeout"
        return

    try:
        stk_cd = session["stk_cd"]
        stk_nm = session.get("stk_nm")

        # Get the trading graph
        graph = get_kr_stock_trading_graph()

        # Create initial state
        initial_state = create_kr_stock_initial_state(
            stk_cd=stk_cd,
            stk_nm=stk_nm,
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
                        "kr_stock_graph_node_completed",
                        session_id=session_id,
                        node=node_name,
                    )

        # Check if we hit the approval interrupt
        state = session["state"]
        if state.get("awaiting_approval"):
            session["status"] = "awaiting_approval"
            logger.info(
                "kr_stock_analysis_awaiting_approval",
                session_id=session_id,
                stk_cd=stk_cd,
            )
        elif state.get("error"):
            session["status"] = "error"
            session["error"] = state.get("error")
        else:
            session["status"] = "completed"

    except Exception as e:
        logger.error(
            "kr_stock_analysis_failed",
            session_id=session_id,
            error=str(e),
        )
        session["status"] = "error"
        session["error"] = str(e)
        session["state"]["reasoning_log"] = session["state"].get("reasoning_log", []) + [
            f"[Error] 분석 실패: {str(e)}"
        ]
    finally:
        # Always release the analysis slot
        release_analysis_slot()


@router.get(
    "/analysis/status/{session_id}", response_model=KRStockAnalysisStatusResponse
)
async def get_kr_stock_analysis_status(session_id: str):
    """
    Get the current status of a Korean stock analysis session.

    Args:
        session_id: Session identifier

    Returns:
        Full status including market data and trade proposal
    """
    session = get_kr_stock_session(session_id)
    state = session["state"]

    # Build trade proposal response
    trade_proposal = None
    proposal = state.get("trade_proposal")
    if proposal:
        trade_proposal = KRStockTradeProposalResponse(
            id=proposal.get("id", ""),
            stk_cd=proposal.get("stk_cd", ""),
            stk_nm=proposal.get("stk_nm"),
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

    # Build analyses
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
                KRStockAnalysisSummary(
                    agent_type=analysis.get("agent_type", key),
                    signal=analysis.get("signal", "hold"),
                    confidence=analysis.get("confidence", 0.5),
                    summary=analysis.get("summary", "")[:300],
                    key_factors=analysis.get("key_factors", [])[:5],
                )
            )

    return KRStockAnalysisStatusResponse(
        session_id=session_id,
        stk_cd=session["stk_cd"],
        stk_nm=session.get("stk_nm"),
        status=session["status"],
        current_stage=state.get("current_stage"),
        awaiting_approval=state.get("awaiting_approval", False),
        trade_proposal=trade_proposal,
        analyses=analyses,
        reasoning_log=state.get("reasoning_log", [])[-20:],
        error=session.get("error"),
    )


@router.post("/analysis/cancel/{session_id}")
async def cancel_kr_stock_analysis(session_id: str):
    """
    Cancel a Korean stock analysis session.

    Args:
        session_id: Session identifier

    Returns:
        Confirmation message
    """
    session = get_kr_stock_session(session_id)

    if session["status"] in ["completed", "cancelled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"세션이 이미 {session['status']} 상태입니다",
        )

    session["status"] = "cancelled"
    session["state"]["reasoning_log"].append("[System] 사용자가 분석을 취소했습니다")

    logger.info("kr_stock_analysis_cancelled", session_id=session_id)

    return {"message": f"세션 {session_id}이 취소되었습니다"}


# -------------------------------------------
# Account & Order Endpoints
# -------------------------------------------


@router.get("/accounts", response_model=KRStockAccountResponse)
async def get_accounts():
    """
    Get account information including cash balance and holdings.

    Requires Kiwoom API keys to be configured.

    Returns:
        Account balances and stock holdings
    """
    _check_kiwoom_api_keys()

    client = await get_shared_kiwoom_client_async()

    try:
        # Get cash balance
        cash_balance = await client.get_cash_balance()

        # Get account balance (holdings)
        account_balance = await client.get_account_balance()

        # Map CashBalance model attributes to schema
        cash = KRStockCashBalance(
            deposit=cash_balance.dnca_tot_amt,
            orderable_amount=cash_balance.ord_psbl_amt,
            withdrawable_amount=cash_balance.sttl_psbk_amt,
        )

        # Map Holding model attributes to schema
        holdings = [
            KRStockHolding(
                stk_cd=h.stk_cd,
                stk_nm=h.stk_nm,
                quantity=h.hldg_qty,
                avg_buy_price=h.avg_buy_prc,
                current_price=h.cur_prc,
                eval_amount=h.evlu_amt,
                profit_loss=h.evlu_pfls_amt,
                profit_loss_rate=h.evlu_pfls_rt,
            )
            for h in account_balance.holdings
        ]

        # Calculate stock evaluation from individual holdings (not from account_balance.evlu_amt)
        # account_balance.evlu_amt may include cash, so we sum up holdings' evlu_amt directly
        stock_eval_amount = sum(h.evlu_amt for h in account_balance.holdings)

        return KRStockAccountResponse(
            cash=cash,
            holdings=holdings,
            total_eval_amount=stock_eval_amount,
            total_profit_loss=account_balance.evlu_pfls_amt,
            total_profit_loss_rate=account_balance.evlu_pfls_rt,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_accounts_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"계좌 조회 실패: {str(e)}",
        )


@router.get("/orders", response_model=KRStockOrderListResponse)
async def get_orders(
    stk_cd: Optional[str] = Query(
        default=None,
        description="Filter by stock code",
    ),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status (pending, partial, completed, cancelled)",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of orders to return",
    ),
):
    """
    Get list of orders.

    Requires Kiwoom API keys to be configured.

    Args:
        stk_cd: Filter by stock code
        status_filter: Filter by order status
        limit: Maximum number of orders (default 50)

    Returns:
        List of orders
    """
    _check_kiwoom_api_keys()

    client = await get_shared_kiwoom_client_async()

    try:
        # Use get_pending_orders for pending/partial orders
        pending_orders = await client.get_pending_orders()

        orders = []
        for order in pending_orders[:limit]:
            # Apply stock code filter
            if stk_cd and order.stk_cd != stk_cd:
                continue

            # Determine order status
            order_status = "pending"
            if order.ccld_qty > 0 and order.rmn_qty > 0:
                order_status = "partial"
            elif order.rmn_qty == 0:
                order_status = "completed"

            # Apply status filter
            if status_filter and order_status != status_filter:
                continue

            # Determine side from buy_sell_tp (1: buy, 2: sell)
            side = "buy" if order.buy_sell_tp in ["1", "01", "매수"] else "sell"

            # Parse datetime from ord_dt + ord_tm
            try:
                created_at = datetime.strptime(
                    f"{order.ord_dt}{order.ord_tm}",
                    "%Y%m%d%H%M%S"
                )
            except (ValueError, TypeError):
                created_at = datetime.utcnow()

            orders.append(
                KRStockOrderResponse(
                    order_id=order.ord_no,
                    stk_cd=order.stk_cd,
                    stk_nm=order.stk_nm,
                    side=side,
                    ord_type="limit",  # Pending orders are typically limit orders
                    price=order.ord_uv,
                    quantity=order.ord_qty,
                    executed_quantity=order.ccld_qty,
                    remaining_quantity=order.rmn_qty,
                    status=order_status,
                    created_at=created_at,
                )
            )

        return KRStockOrderListResponse(orders=orders, total=len(orders))

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_orders_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"주문 조회 실패: {str(e)}",
        )


@router.post("/orders", response_model=KRStockOrderResponse)
async def create_order(request: KRStockOrderRequest):
    """
    Create a new order.

    Requires Kiwoom API keys to be configured.

    Order types:
    - limit: Limit order (지정가) - requires price
    - market: Market order (시장가)

    Args:
        request: Order request

    Returns:
        Created order details
    """
    _check_kiwoom_api_keys()

    # Validate order parameters
    if request.ord_type == "limit" and not request.price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="지정가 주문은 가격이 필요합니다",
        )

    # Check trading mode
    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)

    if is_mock:
        logger.info(
            "mock_trade_order",
            stk_cd=request.stk_cd,
            side=request.side,
            ord_type=request.ord_type,
            price=request.price,
            quantity=request.quantity,
        )
        # Return simulated order for mock trading
        return KRStockOrderResponse(
            order_id=f"mock-{uuid.uuid4()}",
            stk_cd=request.stk_cd,
            stk_nm=None,
            side=request.side,
            ord_type=request.ord_type,
            price=request.price,
            quantity=request.quantity,
            executed_quantity=request.quantity if request.ord_type == "market" else 0,
            remaining_quantity=0 if request.ord_type == "market" else request.quantity,
            status="completed" if request.ord_type == "market" else "pending",
            created_at=datetime.utcnow(),
        )

    # Live trading
    client = await get_shared_kiwoom_client_async()

    try:
        from services.kiwoom import OrderRequest as KiwoomOrderRequest, OrderType

        order_type = OrderType.BUY if request.side == "buy" else OrderType.SELL
        if request.ord_type == "market":
            order_type = (
                OrderType.MARKET_BUY
                if request.side == "buy"
                else OrderType.MARKET_SELL
            )

        kiwoom_request = KiwoomOrderRequest(
            stk_cd=request.stk_cd,
            order_type=order_type,
            quantity=request.quantity,
            price=request.price or 0,
        )

        order = await client.place_order(kiwoom_request)

        logger.info(
            "order_created",
            order_id=order.order_id,
            stk_cd=request.stk_cd,
            side=request.side,
        )

        return KRStockOrderResponse(
            order_id=order.order_id,
            stk_cd=request.stk_cd,
            stk_nm=order.stk_nm if hasattr(order, "stk_nm") else None,
            side=request.side,
            ord_type=request.ord_type,
            price=request.price,
            quantity=request.quantity,
            executed_quantity=0,
            remaining_quantity=request.quantity,
            status="pending",
            created_at=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "create_order_failed",
            stk_cd=request.stk_cd,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"주문 생성 실패: {str(e)}",
        )


@router.delete("/orders/{order_id}", response_model=KRStockOrderCancelResponse)
async def cancel_order(order_id: str):
    """
    Cancel an order.

    Requires Kiwoom API keys to be configured.
    Only orders in 'pending' or 'partial' status can be cancelled.

    Args:
        order_id: Order ID to cancel

    Returns:
        Cancelled order details
    """
    _check_kiwoom_api_keys()

    # Check for mock trading
    if order_id.startswith("mock-"):
        logger.info("mock_trade_cancel", order_id=order_id)
        return KRStockOrderCancelResponse(
            order_id=order_id,
            stk_cd="000000",
            status="cancelled",
            cancelled_quantity=0,
        )

    client = await get_shared_kiwoom_client_async()

    try:
        result = await client.cancel_order(order_id)

        logger.info("order_cancelled", order_id=order_id)

        return KRStockOrderCancelResponse(
            order_id=order_id,
            stk_cd=result.stk_cd if hasattr(result, "stk_cd") else "000000",
            status="cancelled",
            cancelled_quantity=result.cancelled_quantity
            if hasattr(result, "cancelled_quantity")
            else 0,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("cancel_order_failed", order_id=order_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"주문 취소 실패: {str(e)}",
        )


# -------------------------------------------
# Position Endpoints
# -------------------------------------------


@router.get("/positions", response_model=KRStockPositionListResponse)
async def get_positions():
    """
    Get all open positions with real-time P&L.

    Returns:
        List of positions with portfolio summary
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()

    # Try to get positions from storage first
    try:
        positions_data = await storage.get_kr_stock_positions()
    except AttributeError:
        # If method doesn't exist yet, return empty
        positions_data = []

    if not positions_data:
        return KRStockPositionListResponse(
            positions=[],
            total_value_krw=0,
            total_pnl=0,
            total_pnl_pct=0,
        )

    # Get current prices
    client = await get_shared_kiwoom_client_async()
    price_map = {}

    try:
        for p in positions_data:
            try:
                info = await client.get_stock_info(p["stk_cd"])
                if info:
                    price_map[p["stk_cd"]] = info.cur_prc
            except Exception:
                pass
    except Exception as e:
        logger.warning("failed_to_fetch_prices_for_positions", error=str(e))

    positions = []
    total_value = 0
    total_pnl = 0
    total_cost = 0

    for p in positions_data:
        stk_cd = p["stk_cd"]
        quantity = p["quantity"]
        avg_entry = p["avg_entry_price"]
        current_price = price_map.get(stk_cd, avg_entry)

        position_value = quantity * current_price
        position_cost = quantity * avg_entry
        unrealized_pnl = position_value - position_cost
        unrealized_pnl_pct = (
            (unrealized_pnl / position_cost * 100) if position_cost > 0 else 0
        )

        total_value += position_value
        total_cost += position_cost
        total_pnl += unrealized_pnl

        positions.append(
            KRStockPosition(
                stk_cd=stk_cd,
                stk_nm=p["stk_nm"],
                quantity=quantity,
                avg_entry_price=avg_entry,
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                stop_loss=p.get("stop_loss"),
                take_profit=p.get("take_profit"),
                session_id=p.get("session_id"),
                created_at=p["created_at"],
            )
        )

    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return KRStockPositionListResponse(
        positions=positions,
        total_value_krw=int(total_value),
        total_pnl=int(total_pnl),
        total_pnl_pct=total_pnl_pct,
    )


@router.get("/positions/{stk_cd}", response_model=KRStockPosition)
async def get_position(stk_cd: str):
    """
    Get a single position by stock code with real-time P&L.

    Args:
        stk_cd: Stock code

    Returns:
        Position details with current P&L
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()

    try:
        position = await storage.get_kr_stock_position(stk_cd)
    except AttributeError:
        position = None

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{stk_cd} 포지션을 찾을 수 없습니다",
        )

    # Get current price
    current_price = position["avg_entry_price"]
    client = await get_shared_kiwoom_client_async()

    try:
        info = await client.get_stock_info(stk_cd)
        if info:
            current_price = info.cur_prc
    except Exception as e:
        logger.warning("failed_to_fetch_ticker", stk_cd=stk_cd, error=str(e))

    quantity = position["quantity"]
    avg_entry = position["avg_entry_price"]
    position_value = quantity * current_price
    position_cost = quantity * avg_entry
    unrealized_pnl = position_value - position_cost
    unrealized_pnl_pct = (
        (unrealized_pnl / position_cost * 100) if position_cost > 0 else 0
    )

    return KRStockPosition(
        stk_cd=stk_cd,
        stk_nm=position["stk_nm"],
        quantity=quantity,
        avg_entry_price=avg_entry,
        current_price=current_price,
        unrealized_pnl=int(unrealized_pnl),
        unrealized_pnl_pct=unrealized_pnl_pct,
        stop_loss=position.get("stop_loss"),
        take_profit=position.get("take_profit"),
        session_id=position.get("session_id"),
        created_at=position["created_at"],
    )


@router.post("/positions/{stk_cd}/close", response_model=KRStockOrderResponse)
async def close_position(stk_cd: str):
    """
    Close a position by selling all holdings at market price.

    Args:
        stk_cd: Stock code to close

    Returns:
        Order response from the sell order
    """
    from services.storage_service import get_storage_service

    _check_kiwoom_api_keys()

    storage = await get_storage_service()

    try:
        position = await storage.get_kr_stock_position(stk_cd)
    except AttributeError:
        position = None

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{stk_cd} 포지션을 찾을 수 없습니다",
        )

    quantity = position["quantity"]
    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{stk_cd} 포지션 수량이 0입니다",
        )

    # Check trading mode
    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)

    if is_mock:
        logger.info(
            "mock_trade_close_position",
            stk_cd=stk_cd,
            quantity=quantity,
        )

        # Get current price
        client = await get_shared_kiwoom_client_async()
        current_price = position["avg_entry_price"]
        try:
            info = await client.get_stock_info(stk_cd)
            if info:
                current_price = info.cur_prc
        except Exception:
            pass

        # Delete position
        try:
            await storage.delete_kr_stock_position(stk_cd)
        except AttributeError:
            pass

        return KRStockOrderResponse(
            order_id=f"mock-close-{uuid.uuid4()}",
            stk_cd=stk_cd,
            stk_nm=position["stk_nm"],
            side="sell",
            ord_type="market",
            price=current_price,
            quantity=quantity,
            executed_quantity=quantity,
            remaining_quantity=0,
            status="completed",
            created_at=datetime.utcnow(),
        )

    # Live trading
    client = await get_shared_kiwoom_client_async()

    try:
        from services.kiwoom import OrderRequest as KiwoomOrderRequest, OrderType

        kiwoom_request = KiwoomOrderRequest(
            stk_cd=stk_cd,
            order_type=OrderType.MARKET_SELL,
            quantity=quantity,
            price=0,
        )

        order = await client.place_order(kiwoom_request)

        # Delete position on success
        try:
            await storage.delete_kr_stock_position(stk_cd)
        except AttributeError:
            pass

        logger.info("position_closed", stk_cd=stk_cd, order_id=order.order_id)

        return KRStockOrderResponse(
            order_id=order.order_id,
            stk_cd=stk_cd,
            stk_nm=position["stk_nm"],
            side="sell",
            ord_type="market",
            price=None,
            quantity=quantity,
            executed_quantity=0,
            remaining_quantity=quantity,
            status="pending",
            created_at=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("close_position_failed", stk_cd=stk_cd, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"포지션 청산 실패: {str(e)}",
        )


# -------------------------------------------
# Trade History Endpoints
# -------------------------------------------


@router.get("/trades", response_model=KRStockTradeListResponse)
async def get_trades(
    stk_cd: Optional[str] = Query(default=None, description="Filter by stock code"),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """
    Get trade history with pagination.

    Args:
        stk_cd: Filter by stock code (optional)
        page: Page number (1-indexed)
        limit: Results per page (max 100)

    Returns:
        Paginated list of trade records
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    offset = (page - 1) * limit

    try:
        trades_data = await storage.get_kr_stock_trades(
            stk_cd=stk_cd,
            limit=limit,
            offset=offset,
        )
        total = await storage.get_kr_stock_trades_count(stk_cd=stk_cd)
    except AttributeError:
        trades_data = []
        total = 0

    trades = [
        KRStockTradeRecord(
            id=t["id"],
            session_id=t.get("session_id"),
            stk_cd=t["stk_cd"],
            stk_nm=t.get("stk_nm"),
            side=t["side"],
            order_type=t["order_type"],
            price=t["price"],
            quantity=t["quantity"],
            executed_quantity=t["executed_quantity"],
            fee=t.get("fee", 0),
            total_krw=t["total_krw"],
            status=t["status"],
            order_id=t.get("order_id"),
            created_at=t["created_at"],
        )
        for t in trades_data
    ]

    return KRStockTradeListResponse(
        trades=trades,
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/trades/{trade_id}", response_model=KRStockTradeRecord)
async def get_trade(trade_id: str):
    """
    Get a single trade by ID.

    Args:
        trade_id: Trade ID

    Returns:
        Trade record details
    """
    from services.storage_service import get_storage_service

    storage = await get_storage_service()

    try:
        trade = await storage.get_kr_stock_trade(trade_id)
    except AttributeError:
        trade = None

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"거래 {trade_id}를 찾을 수 없습니다",
        )

    return KRStockTradeRecord(
        id=trade["id"],
        session_id=trade.get("session_id"),
        stk_cd=trade["stk_cd"],
        stk_nm=trade.get("stk_nm"),
        side=trade["side"],
        order_type=trade["order_type"],
        price=trade["price"],
        quantity=trade["quantity"],
        executed_quantity=trade["executed_quantity"],
        fee=trade.get("fee", 0),
        total_krw=trade["total_krw"],
        status=trade["status"],
        order_id=trade.get("order_id"),
        created_at=trade["created_at"],
    )


# -------------------------------------------
# Settings Endpoints
# -------------------------------------------


@router.get("/settings/status", response_model=KiwoomApiKeyStatus)
async def get_kiwoom_api_status():
    """
    Get current Kiwoom API configuration status.

    Returns:
        Configuration status including whether keys are set
    """
    app_key = getattr(settings, "KIWOOM_APP_KEY", None)
    account = getattr(settings, "KIWOOM_ACCOUNT_NUMBER", None)
    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)

    is_configured = bool(app_key and account)

    # Mask account number for display
    account_masked = None
    if account:
        if len(account) > 4:
            account_masked = account[:4] + "*" * (len(account) - 4)
        else:
            account_masked = "****"

    return KiwoomApiKeyStatus(
        is_configured=is_configured,
        account_masked=account_masked,
        trading_mode="paper" if is_mock else "live",
        is_valid=None,  # Would need to validate with API
        last_validated=None,
    )


@router.post("/settings/update", response_model=KiwoomApiKeyResponse)
async def update_kiwoom_api_keys(request: KiwoomApiKeyRequest):
    """
    Update Kiwoom API keys.

    Note: In production, this would persist to secure storage.
    Currently updates in-memory settings only.

    Args:
        request: API key update request

    Returns:
        Update result with new status
    """
    # In a real implementation, this would:
    # 1. Validate the keys with Kiwoom API
    # 2. Store securely (env file, secrets manager, etc.)
    # For now, just update the settings object

    try:
        settings.KIWOOM_APP_KEY = request.app_key
        settings.KIWOOM_APP_SECRET = request.app_secret
        settings.KIWOOM_ACCOUNT_NUMBER = request.account_number
        settings.KIWOOM_IS_MOCK = request.is_mock

        logger.info(
            "kiwoom_api_keys_updated",
            account=request.account_number[:4] + "****",
            is_mock=request.is_mock,
        )

        return KiwoomApiKeyResponse(
            success=True,
            message="Kiwoom API 설정이 업데이트되었습니다",
            status=KiwoomApiKeyStatus(
                is_configured=True,
                account_masked=request.account_number[:4] + "****",
                trading_mode="paper" if request.is_mock else "live",
                is_valid=None,
                last_validated=None,
            ),
        )

    except Exception as e:
        logger.error("update_kiwoom_keys_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"설정 업데이트 실패: {str(e)}",
        )


@router.post("/settings/validate", response_model=KiwoomValidationResponse)
async def validate_kiwoom_api_keys():
    """
    Validate Kiwoom API keys by making a test request.

    Returns:
        Validation result
    """
    _check_kiwoom_api_keys()

    client = await get_shared_kiwoom_client_async()

    try:
        # Try to get cash balance as a test
        balance = await client.get_cash_balance()

        return KiwoomValidationResponse(
            is_valid=True,
            message="API 키가 유효합니다",
            account_info={
                "deposit": balance.dnca_tot_amt,
                "orderable_amount": balance.ord_psbl_amt,
            },
        )

    except Exception as e:
        logger.error("validate_kiwoom_keys_failed", error=str(e))
        return KiwoomValidationResponse(
            is_valid=False,
            message=f"API 키 검증 실패: {str(e)}",
            account_info=None,
        )


@router.delete("/settings/clear")
async def clear_kiwoom_api_keys():
    """
    Clear Kiwoom API keys from settings.

    Returns:
        Confirmation message
    """
    try:
        settings.KIWOOM_APP_KEY = None
        settings.KIWOOM_APP_SECRET = None
        settings.KIWOOM_ACCOUNT_NUMBER = None

        logger.info("kiwoom_api_keys_cleared")

        return {"message": "Kiwoom API 설정이 삭제되었습니다"}

    except Exception as e:
        logger.error("clear_kiwoom_keys_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"설정 삭제 실패: {str(e)}",
        )


# -------------------------------------------
# Export session store
# -------------------------------------------


def get_kr_stock_sessions() -> dict:
    """Get reference to Korean stock sessions (for WebSocket, approval routes)."""
    return kr_stock_sessions
