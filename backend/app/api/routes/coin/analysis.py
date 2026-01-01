"""
Coin Analysis Endpoints

Endpoints for coin analysis:
- POST /analysis/start - Start analysis
- GET /analysis/status/{session_id} - Get analysis status
- POST /analysis/cancel/{session_id} - Cancel analysis
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.schemas.coin import (
    CoinAnalysisRequest,
    CoinAnalysisResponse,
    CoinAnalysisStatusResponse,
    CoinAnalysisSummary,
    CoinTradeProposalResponse,
)
from app.core.analysis_limiter import (
    acquire_analysis_slot,
    register_session,
    release_analysis_slot,
    update_session_status,
)
from .constants import coin_sessions, get_cached_markets
from .helpers import get_coin_session

logger = structlog.get_logger()
router = APIRouter()


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
    cached_markets = get_cached_markets()
    if cached_markets:
        market_info = next((m for m in cached_markets if m.market == market), None)
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
            "current_stage": "data_collection",
        },
        "created_at": datetime.now(timezone.utc),
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
    """
    from agents.graph.coin_trading_graph import get_coin_trading_graph
    from agents.graph.coin_state import create_coin_initial_state

    session = coin_sessions.get(session_id)
    if not session:
        logger.error("coin_session_not_found", session_id=session_id)
        return

    # Acquire analysis slot (with timeout)
    slot_acquired = await acquire_analysis_slot(timeout=60.0)
    if not slot_acquired:
        session["status"] = "error"
        session["error"] = "분석 대기열이 가득 찼습니다. 잠시 후 다시 시도해주세요."
        session["state"]["reasoning_log"].append(
            "[Error] 동시 분석 한도 초과 - 잠시 후 다시 시도해주세요."
        )
        update_session_status(session_id, "error", session["error"])
        logger.warning(
            "coin_analysis_slot_timeout",
            session_id=session_id,
        )
        return

    try:
        market = session["market"]
        korean_name = session.get("korean_name")

        # Register with unified session tracker
        register_session(
            session_id=session_id,
            market_type="coin",
            ticker=market,
            display_name=korean_name,
        )

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
            update_session_status(session_id, "awaiting_approval")
            logger.info(
                "coin_analysis_awaiting_approval",
                session_id=session_id,
                market=market,
            )
        elif state.get("error"):
            session["status"] = "error"
            session["error"] = state.get("error")
            update_session_status(session_id, "error", session["error"])
        else:
            session["status"] = "completed"
            update_session_status(session_id, "completed")

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
        update_session_status(session_id, "error", str(e))

    finally:
        # Always release the analysis slot
        release_analysis_slot()
        logger.debug(
            "coin_analysis_slot_released",
            session_id=session_id,
        )


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
