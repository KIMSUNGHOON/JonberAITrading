"""
Unified Analysis Routes

Provides a single entry point for all market type analyses:
- /api/v1/unified-analysis/start - Start analysis for any market type
- /api/v1/unified-analysis/status/{session_id} - Get status
- /api/v1/unified-analysis/cancel/{session_id} - Cancel analysis
- /api/v1/unified-analysis/sessions - List all sessions

This module routes requests to the appropriate analysis graph based on market_type.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.api.schemas.analysis_unified import (
    MarketType,
    UnifiedAnalysisRequest,
    UnifiedAnalysisResponse,
    UnifiedAnalysisStatusResponse,
    UnifiedAnalysisSummary,
    UnifiedSessionListResponse,
    UnifiedTradeProposal,
)
from app.core.analysis_limiter import acquire_analysis_slot, release_analysis_slot
from services.session_manager import get_session_manager, MarketType as SessionMarketType

logger = structlog.get_logger()
router = APIRouter()


# =============================================================================
# Helper Functions
# =============================================================================


def _get_session_market_type(market_type: MarketType) -> SessionMarketType:
    """Convert API market type to session market type."""
    mapping = {
        "stock": SessionMarketType.STOCK,
        "kr_stock": SessionMarketType.KIWOOM,
        "coin": SessionMarketType.COIN,
    }
    return mapping.get(market_type, SessionMarketType.STOCK)


async def _run_analysis_task(
    session_id: str,
    market_type: MarketType,
    ticker: str,
    name: Optional[str],
    query: Optional[str],
) -> None:
    """
    Background task to run analysis.

    Routes to the appropriate graph based on market_type.
    """
    session_manager = await get_session_manager()

    try:
        # Update status to running
        await session_manager.update_session(
            session_id,
            status="running",
            current_stage="data_collection",
        )

        # Import the appropriate graph
        if market_type == "kr_stock":
            from agents.graph.kr_stock_graph import get_kr_stock_trading_graph

            graph = get_kr_stock_trading_graph()
            initial_state = {
                "stk_cd": ticker,
                "stk_nm": name or ticker,
                "user_query": query or f"{name or ticker} 분석해주세요",
                "messages": [],
                "reasoning_log": [],
            }
        elif market_type == "coin":
            from agents.graph.coin_graph import get_coin_trading_graph

            graph = get_coin_trading_graph()
            initial_state = {
                "market": ticker,
                "korean_name": name,
                "user_query": query or f"{ticker} 분석해주세요",
                "messages": [],
                "reasoning_log": [],
            }
        else:
            # Default stock graph
            from agents.graph.trading_graph import get_trading_graph

            graph = get_trading_graph()
            initial_state = {
                "ticker": ticker,
                "query": query or f"Analyze {ticker}",
                "messages": [],
                "reasoning_log": [],
            }

        # Run the graph
        config = {"configurable": {"thread_id": session_id}}
        result = None

        async for event in graph.astream(initial_state, config=config):
            # Extract state updates
            for node_name, node_output in event.items():
                if isinstance(node_output, dict):
                    # Update session with current stage
                    current_stage = node_output.get("current_stage")
                    if current_stage:
                        await session_manager.update_session(
                            session_id,
                            current_stage=str(current_stage),
                        )

                    # Update reasoning log
                    reasoning_log = node_output.get("reasoning_log", [])
                    if reasoning_log:
                        await session_manager.update_session(
                            session_id,
                            reasoning_log=reasoning_log,
                        )

                    result = node_output

        # Process final result
        if result:
            analyses = []

            # Extract technical analysis
            tech = result.get("technical_analysis")
            if tech:
                analyses.append(
                    UnifiedAnalysisSummary(
                        type="technical",
                        signal=tech.get("signal", "HOLD"),
                        confidence=tech.get("confidence", 0.5),
                        summary=tech.get("summary", ""),
                        key_factors=tech.get("key_factors", []),
                    ).model_dump()
                )

            # Extract fundamental analysis
            fund = result.get("fundamental_analysis")
            if fund:
                analyses.append(
                    UnifiedAnalysisSummary(
                        type="fundamental",
                        signal=fund.get("signal", "HOLD"),
                        confidence=fund.get("confidence", 0.5),
                        summary=fund.get("summary", ""),
                        key_factors=fund.get("key_factors", []),
                    ).model_dump()
                )

            # Extract sentiment analysis
            sent = result.get("sentiment_analysis")
            if sent:
                analyses.append(
                    UnifiedAnalysisSummary(
                        type="sentiment",
                        signal=sent.get("signal", "HOLD"),
                        confidence=sent.get("confidence", 0.5),
                        summary=sent.get("summary", ""),
                        key_factors=sent.get("key_factors", []),
                    ).model_dump()
                )

            # Extract trade proposal
            proposal = result.get("trade_proposal")
            trade_proposal = None
            if proposal:
                trade_proposal = UnifiedTradeProposal(
                    action=proposal.get("action", "HOLD"),
                    confidence=proposal.get("confidence", 0.5),
                    target_price=proposal.get("target_price"),
                    stop_loss=proposal.get("stop_loss"),
                    take_profit=proposal.get("take_profit"),
                    position_size=proposal.get("position_size"),
                    reasoning=proposal.get("reasoning", ""),
                ).model_dump()

            # Update session with final results
            await session_manager.update_session(
                session_id,
                status="completed",
                current_stage="complete",
                analyses=analyses,
                trade_proposal=trade_proposal,
                reasoning_log=result.get("reasoning_log", []),
            )
        else:
            await session_manager.update_session(
                session_id,
                status="completed",
                current_stage="complete",
            )

    except Exception as e:
        logger.error(
            "unified_analysis_failed",
            session_id=session_id,
            market_type=market_type,
            ticker=ticker,
            error=str(e),
        )
        await session_manager.update_session(
            session_id,
            status="failed",
            error=str(e),
        )

    finally:
        release_analysis_slot()


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/start", response_model=UnifiedAnalysisResponse)
async def start_unified_analysis(
    request: UnifiedAnalysisRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a unified analysis for any market type.

    This endpoint routes to the appropriate analysis graph based on market_type:
    - stock: US/international stocks
    - kr_stock: Korean stocks (Kiwoom)
    - coin: Cryptocurrency (Upbit)

    Returns a session_id that can be used to track progress.
    """
    # Check slot availability
    if not acquire_analysis_slot():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="분석 슬롯이 모두 사용 중입니다. 잠시 후 다시 시도해주세요.",
        )

    # Generate session ID
    session_id = f"unified-{request.market_type}-{uuid.uuid4().hex[:8]}"

    # Create session
    session_manager = await get_session_manager()
    session_market_type = _get_session_market_type(request.market_type)

    await session_manager.create_session(
        session_id=session_id,
        market_type=session_market_type,
        ticker=request.ticker,
        display_name=request.name or request.ticker,
        initial_data={
            "market_type": request.market_type,
            "ticker": request.ticker,
            "name": request.name,
            "query": request.query,
            "status": "pending",
            "current_stage": "initializing",
            "analyses": [],
            "reasoning_log": [],
        },
    )

    # Start background analysis
    background_tasks.add_task(
        _run_analysis_task,
        session_id,
        request.market_type,
        request.ticker,
        request.name,
        request.query,
    )

    logger.info(
        "unified_analysis_started",
        session_id=session_id,
        market_type=request.market_type,
        ticker=request.ticker,
    )

    return UnifiedAnalysisResponse(
        session_id=session_id,
        market_type=request.market_type,
        ticker=request.ticker,
        status="pending",
        message=f"{request.market_type} 분석을 시작합니다: {request.ticker}",
    )


@router.get("/status/{session_id}", response_model=UnifiedAnalysisStatusResponse)
async def get_unified_analysis_status(session_id: str):
    """
    Get the status of a unified analysis session.

    Returns current progress, analyses, and trade proposal if completed.
    """
    session_manager = await get_session_manager()
    session = await session_manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"세션을 찾을 수 없습니다: {session_id}",
        )

    data = session.get("data", {})

    return UnifiedAnalysisStatusResponse(
        session_id=session_id,
        market_type=data.get("market_type", "stock"),
        ticker=data.get("ticker", ""),
        name=data.get("name"),
        status=data.get("status", "unknown"),
        analyses=data.get("analyses", []),
        trade_proposal=data.get("trade_proposal"),
        current_stage=data.get("current_stage"),
        reasoning_log=data.get("reasoning_log", []),
        created_at=session.get("created_at"),
        updated_at=session.get("updated_at"),
        metadata=data.get("metadata", {}),
        error=data.get("error"),
    )


@router.post("/cancel/{session_id}")
async def cancel_unified_analysis(session_id: str):
    """
    Cancel a running unified analysis session.

    Only sessions in 'pending' or 'running' status can be cancelled.
    """
    session_manager = await get_session_manager()
    session = await session_manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"세션을 찾을 수 없습니다: {session_id}",
        )

    data = session.get("data", {})
    current_status = data.get("status")

    if current_status not in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"취소할 수 없는 상태입니다: {current_status}",
        )

    await session_manager.update_session(
        session_id,
        status="cancelled",
        current_stage="cancelled",
    )

    release_analysis_slot()

    logger.info("unified_analysis_cancelled", session_id=session_id)

    return {
        "session_id": session_id,
        "status": "cancelled",
        "message": "분석이 취소되었습니다.",
    }


@router.get("/sessions", response_model=UnifiedSessionListResponse)
async def list_unified_sessions(
    market_type: Optional[MarketType] = Query(
        default=None,
        description="Filter by market type",
    ),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status (pending, running, completed, failed, cancelled)",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of sessions to return",
    ),
):
    """
    List unified analysis sessions.

    Supports filtering by market_type and status.
    """
    session_manager = await get_session_manager()

    # Get all sessions
    all_sessions = []
    by_market_type = {"stock": 0, "kr_stock": 0, "coin": 0}

    # Get sessions by type
    session_market_types = []
    if market_type:
        session_market_types = [_get_session_market_type(market_type)]
    else:
        session_market_types = [SessionMarketType.STOCK, SessionMarketType.KIWOOM, SessionMarketType.COIN]

    for smt in session_market_types:
        sessions = await session_manager.list_sessions(smt)

        for session in sessions:
            data = session.get("data", {})
            mt = data.get("market_type", "stock")
            session_status = data.get("status", "unknown")

            # Count by market type
            if mt in by_market_type:
                by_market_type[mt] += 1

            # Apply status filter
            if status_filter and session_status != status_filter:
                continue

            all_sessions.append(
                UnifiedAnalysisStatusResponse(
                    session_id=session.get("session_id", ""),
                    market_type=mt,
                    ticker=data.get("ticker", ""),
                    name=data.get("name"),
                    status=session_status,
                    analyses=data.get("analyses", []),
                    trade_proposal=data.get("trade_proposal"),
                    current_stage=data.get("current_stage"),
                    reasoning_log=data.get("reasoning_log", []),
                    created_at=session.get("created_at"),
                    updated_at=session.get("updated_at"),
                    metadata=data.get("metadata", {}),
                    error=data.get("error"),
                )
            )

    # Apply limit
    all_sessions = all_sessions[:limit]

    return UnifiedSessionListResponse(
        sessions=all_sessions,
        total=len(all_sessions),
        by_market_type=by_market_type,
    )


@router.delete("/sessions/{session_id}")
async def delete_unified_session(session_id: str):
    """
    Delete a unified analysis session.

    Removes the session from storage.
    """
    session_manager = await get_session_manager()
    session = await session_manager.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"세션을 찾을 수 없습니다: {session_id}",
        )

    await session_manager.delete_session(session_id)

    logger.info("unified_session_deleted", session_id=session_id)

    return {
        "session_id": session_id,
        "deleted": True,
        "message": "세션이 삭제되었습니다.",
    }
