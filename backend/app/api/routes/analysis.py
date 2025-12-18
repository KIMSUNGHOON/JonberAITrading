"""
Analysis API Routes

Endpoints for starting and monitoring trading analysis sessions.
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from agents.graph.state import create_initial_state
from agents.graph.trading_graph import get_trading_graph
from app.api.schemas.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStatusResponse,
    AnalysisSummary,
    SessionListItem,
    SessionListResponse,
    TradeProposalResponse,
)

logger = structlog.get_logger()
router = APIRouter()

# In-memory session store
# TODO: Use SQLite storage service for persistence
active_sessions: dict[str, dict] = {}


# -------------------------------------------
# Session Management
# -------------------------------------------


def get_session(session_id: str) -> dict:
    """Get session or raise 404."""
    session = active_sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )
    return session


# -------------------------------------------
# Analysis Endpoints
# -------------------------------------------


@router.post("/start", response_model=AnalysisResponse)
async def start_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a new trading analysis session.

    The analysis runs in the background. Use the returned session_id
    to track progress via `/status/{session_id}` or WebSocket.

    Args:
        request: Analysis request with ticker and optional query

    Returns:
        Session ID and initial status
    """
    session_id = str(uuid.uuid4())
    ticker = request.ticker.upper()

    logger.info(
        "analysis_session_started",
        session_id=session_id,
        ticker=ticker,
    )

    # Initialize state
    initial_state = create_initial_state(ticker, request.query)

    # Create session record
    active_sessions[session_id] = {
        "session_id": session_id,
        "ticker": ticker,
        "status": "running",
        "state": initial_state,
        "created_at": datetime.utcnow(),
        "error": None,
    }

    # Run analysis in background
    background_tasks.add_task(
        run_analysis_task,
        session_id,
        initial_state,
    )

    return AnalysisResponse(
        session_id=session_id,
        ticker=ticker,
        status="started",
        message="Analysis started. Connect to WebSocket for live updates.",
    )


async def run_analysis_task(session_id: str, initial_state: dict):
    """
    Background task to run the analysis graph.

    Runs until the approval interrupt point.
    """
    graph = get_trading_graph()
    session = active_sessions.get(session_id)

    if not session:
        logger.error("session_not_found_in_task", session_id=session_id)
        return

    try:
        config = {"configurable": {"thread_id": session_id}}

        # Run until interrupt (approval node)
        async for event in graph.astream(initial_state, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    # Update session state
                    if isinstance(node_output, dict):
                        session["state"].update(node_output)
                    session["last_node"] = node_name

                    logger.debug(
                        "graph_node_completed",
                        session_id=session_id,
                        node=node_name,
                    )

        # Check if we hit the approval interrupt
        state = session["state"]
        if state.get("awaiting_approval"):
            session["status"] = "awaiting_approval"
            logger.info(
                "analysis_awaiting_approval",
                session_id=session_id,
                ticker=session["ticker"],
            )
        else:
            session["status"] = "completed"

    except Exception as e:
        logger.error(
            "analysis_task_failed",
            session_id=session_id,
            error=str(e),
        )
        session["status"] = "error"
        session["error"] = str(e)


@router.get("/status/{session_id}", response_model=AnalysisStatusResponse)
async def get_analysis_status(session_id: str):
    """
    Get the current status of an analysis session.

    Args:
        session_id: Session identifier

    Returns:
        Full status including analyses and trade proposal
    """
    session = get_session(session_id)
    state = session["state"]

    # Build analyses summary
    analyses = []
    for key in ["technical_analysis", "fundamental_analysis", "sentiment_analysis", "risk_assessment"]:
        analysis = state.get(key)
        if analysis:
            analyses.append(
                AnalysisSummary(
                    agent_type=analysis.agent_type,
                    signal=analysis.signal.value if hasattr(analysis.signal, "value") else str(analysis.signal),
                    confidence=analysis.confidence,
                    summary=analysis.summary[:300] if analysis.summary else "",
                    key_factors=analysis.key_factors[:5] if analysis.key_factors else [],
                )
            )

    # Build trade proposal response
    trade_proposal = None
    proposal = state.get("trade_proposal")
    if proposal:
        trade_proposal = TradeProposalResponse(
            id=proposal.id,
            ticker=proposal.ticker,
            action=proposal.action.value if hasattr(proposal.action, "value") else proposal.action,
            quantity=proposal.quantity,
            entry_price=proposal.entry_price,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
            risk_score=proposal.risk_score,
            position_size_pct=proposal.position_size_pct,
            rationale=proposal.rationale[:1000] if proposal.rationale else "",
            bull_case=proposal.bull_case[:500] if proposal.bull_case else "",
            bear_case=proposal.bear_case[:500] if proposal.bear_case else "",
            created_at=proposal.created_at,
        )

    return AnalysisStatusResponse(
        session_id=session_id,
        ticker=session["ticker"],
        status=session["status"],
        current_stage=state.get("current_stage", {}).value if hasattr(state.get("current_stage"), "value") else str(state.get("current_stage")),
        awaiting_approval=state.get("awaiting_approval", False),
        trade_proposal=trade_proposal,
        analyses=analyses,
        reasoning_log=state.get("reasoning_log", [])[-20:],  # Last 20 entries
        error=session.get("error"),
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    status_filter: Optional[str] = None,
    limit: int = 50,
):
    """
    List all analysis sessions.

    Args:
        status_filter: Optional filter by status
        limit: Maximum number of sessions to return

    Returns:
        List of sessions with basic info
    """
    sessions = []

    for session_id, session in active_sessions.items():
        if status_filter and session["status"] != status_filter:
            continue

        sessions.append(
            SessionListItem(
                session_id=session_id,
                ticker=session["ticker"],
                status=session["status"],
                created_at=session.get("created_at"),
            )
        )

        if len(sessions) >= limit:
            break

    # Sort by created_at descending
    sessions.sort(key=lambda s: s.created_at or datetime.min, reverse=True)

    return SessionListResponse(
        sessions=sessions,
        total=len(active_sessions),
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Delete an analysis session.

    Args:
        session_id: Session identifier

    Returns:
        Confirmation message
    """
    if session_id not in active_sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    del active_sessions[session_id]

    logger.info("session_deleted", session_id=session_id)

    return {"message": f"Session {session_id} deleted"}


# -------------------------------------------
# Export session store for other modules
# -------------------------------------------

def get_active_sessions() -> dict:
    """Get reference to active sessions (for WebSocket, approval routes)."""
    return active_sessions
