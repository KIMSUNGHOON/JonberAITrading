"""
Korean Stock Analysis Endpoints

Endpoints for stock analysis:
- POST /analysis/start - Start analysis
- GET /analysis/status/{session_id} - Get analysis status
- POST /analysis/cancel/{session_id} - Cancel analysis
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.schemas.kr_stocks import (
    KRStockAnalysisRequest,
    KRStockAnalysisResponse,
    KRStockAnalysisStatusResponse,
    KRStockAnalysisSummary,
    KRStockTradeProposalResponse,
)
from app.core.analysis_limiter import (
    acquire_analysis_slot,
    get_active_analysis_count,
    release_analysis_slot,
)
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from .constants import kr_stock_sessions
from .helpers import get_kr_stock_session

logger = structlog.get_logger()
router = APIRouter()


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
            "current_stage": "data_collection",
        },
        "created_at": datetime.now(timezone.utc),
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
            else proposal.get("created_at", datetime.now(timezone.utc)),
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
