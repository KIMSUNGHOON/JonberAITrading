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
from app.core.analysis_limiter import (
    acquire_analysis_slot,
    release_analysis_slot,
    register_session,
    update_session_status,
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
    Uses semaphore to limit concurrent analyses.
    """
    graph = get_trading_graph()
    session = active_sessions.get(session_id)

    if not session:
        logger.error("session_not_found_in_task", session_id=session_id)
        return

    # Acquire analysis slot (with timeout)
    slot_acquired = await acquire_analysis_slot(timeout=60.0)
    if not slot_acquired:
        session["status"] = "error"
        session["error"] = "Analysis queue is full. Please try again later."
        session["state"]["reasoning_log"] = session["state"].get("reasoning_log", []) + [
            "[Error] Concurrent analysis limit reached - please try again later."
        ]
        update_session_status(session_id, "error", session["error"])
        logger.warning(
            "analysis_slot_timeout",
            session_id=session_id,
        )
        return

    try:
        # Register with unified session tracker
        register_session(
            session_id=session_id,
            market_type="stock",
            ticker=session["ticker"],
            display_name=session["ticker"],
        )

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
            update_session_status(session_id, "awaiting_approval")
            logger.info(
                "analysis_awaiting_approval",
                session_id=session_id,
                ticker=session["ticker"],
            )
        else:
            session["status"] = "completed"
            update_session_status(session_id, "completed")

    except Exception as e:
        logger.error(
            "analysis_task_failed",
            session_id=session_id,
            error=str(e),
        )
        session["status"] = "error"
        session["error"] = str(e)
        update_session_status(session_id, "error", str(e))

    finally:
        # Always release the analysis slot
        release_analysis_slot()
        logger.debug(
            "analysis_slot_released",
            session_id=session_id,
        )


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

    # Build analyses summary (analyses are now dicts from model_dump())
    analyses = []
    for key in ["technical_analysis", "fundamental_analysis", "sentiment_analysis", "risk_assessment"]:
        analysis = state.get(key)
        if analysis:
            signal = analysis.get("signal", "hold")
            # Handle both enum value and string
            if hasattr(signal, "value"):
                signal = signal.value
            summary = analysis.get("summary", "")
            key_factors = analysis.get("key_factors", [])
            analyses.append(
                AnalysisSummary(
                    agent_type=analysis.get("agent_type", key),
                    signal=str(signal),
                    confidence=analysis.get("confidence", 0.5),
                    summary=summary[:300] if summary else "",
                    key_factors=key_factors[:5] if key_factors else [],
                )
            )

    # Build trade proposal response (proposal is now a dict from model_dump())
    trade_proposal = None
    proposal = state.get("trade_proposal")
    if proposal:
        action = proposal.get("action", "HOLD")
        # Handle both enum value and string
        if hasattr(action, "value"):
            action = action.value
        rationale = proposal.get("rationale", "")
        bull_case = proposal.get("bull_case", "")
        bear_case = proposal.get("bear_case", "")
        trade_proposal = TradeProposalResponse(
            id=proposal.get("id", ""),
            ticker=proposal.get("ticker", ""),
            action=str(action),
            quantity=proposal.get("quantity", 0),
            entry_price=proposal.get("entry_price"),
            stop_loss=proposal.get("stop_loss"),
            take_profit=proposal.get("take_profit"),
            risk_score=proposal.get("risk_score", 0.5),
            position_size_pct=proposal.get("position_size_pct", 5.0),
            rationale=rationale[:1000] if rationale else "",
            bull_case=bull_case[:500] if bull_case else "",
            bear_case=bear_case[:500] if bear_case else "",
            created_at=proposal.get("created_at"),
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


# -------------------------------------------
# Translation Endpoint
# -------------------------------------------

from pydantic import BaseModel
from agents.llm_provider import get_llm_provider
from langchain_core.messages import SystemMessage, HumanMessage


class TranslationRequest(BaseModel):
    """Translation request model."""
    text: str
    target_language: str = "en"  # "en" for English, "ko" for Korean


class TranslationResponse(BaseModel):
    """Translation response model."""
    original: str
    translated: str
    target_language: str


@router.post("/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    """
    Translate text between Korean and English using LLM.

    Args:
        request: Translation request with text and target language

    Returns:
        Original and translated text
    """
    try:
        llm = get_llm_provider()

        if request.target_language == "en":
            prompt = "Translate the following Korean text to English. Only output the translation, nothing else."
        else:
            prompt = "Translate the following English text to Korean. Only output the translation, nothing else."

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=request.text),
        ]

        translated = await llm.generate(messages)

        return TranslationResponse(
            original=request.text,
            translated=translated.strip(),
            target_language=request.target_language,
        )

    except Exception as e:
        logger.error("translation_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation failed: {str(e)}",
        )
