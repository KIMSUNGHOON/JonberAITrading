"""
HITL Approval API Routes

Endpoints for human-in-the-loop trade approval workflow.
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, status

from agents.graph.trading_graph import get_trading_graph
from app.api.routes.analysis import get_active_sessions
from app.api.schemas.approval import (
    ApprovalRequest,
    ApprovalResponse,
    PendingApprovalItem,
    PendingApprovalsResponse,
    PendingProposalSummary,
)

logger = structlog.get_logger()
router = APIRouter()


# -------------------------------------------
# Approval Endpoints
# -------------------------------------------


@router.post("/decide", response_model=ApprovalResponse)
async def submit_approval(request: ApprovalRequest):
    """
    Submit approval decision for a pending trade proposal.

    This resumes the LangGraph workflow from the approval interrupt.

    Args:
        request: Approval decision with session_id and decision

    Returns:
        Updated status after decision is processed
    """
    active_sessions = get_active_sessions()
    session = active_sessions.get(request.session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {request.session_id} not found",
        )

    state = session["state"]

    if not state.get("awaiting_approval"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not awaiting approval",
        )

    logger.info(
        "approval_submitted",
        session_id=request.session_id,
        decision=request.decision,
        has_feedback=bool(request.feedback),
    )

    # Update state with approval decision
    state["approval_status"] = request.decision
    state["user_feedback"] = request.feedback
    state["awaiting_approval"] = False

    # Apply modifications if provided
    if request.decision == "modified" and request.modifications:
        proposal = state.get("trade_proposal")
        if proposal:
            for key, value in request.modifications.items():
                if hasattr(proposal, key):
                    setattr(proposal, key, value)
                    logger.debug(
                        "proposal_modified",
                        session_id=request.session_id,
                        field=key,
                        value=value,
                    )

    # Resume graph execution
    graph = get_trading_graph()
    config = {"configurable": {"thread_id": request.session_id}}

    execution_status = None

    try:
        # Continue from interrupt with updated state
        async for event in graph.astream(None, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    if isinstance(node_output, dict):
                        state.update(node_output)
                    session["last_node"] = node_name

        # Update session status based on decision
        if request.decision == "approved":
            session["status"] = "completed"
            execution_status = state.get("execution_status", "completed")
        else:
            session["status"] = "cancelled"
            execution_status = "cancelled"

        logger.info(
            "approval_processed",
            session_id=request.session_id,
            final_status=session["status"],
            execution_status=execution_status,
        )

    except Exception as e:
        logger.error(
            "approval_processing_failed",
            session_id=request.session_id,
            error=str(e),
        )
        session["status"] = "error"
        session["error"] = str(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process approval: {str(e)}",
        )

    # Build response message
    if request.decision == "approved":
        message = "Trade approved and executed successfully."
    elif request.decision == "rejected":
        message = "Trade rejected. No action taken."
    else:  # modified
        message = "Trade modified and executed with changes."

    return ApprovalResponse(
        session_id=request.session_id,
        decision=request.decision,
        status=session["status"],
        message=message,
        execution_status=execution_status,
    )


@router.get("/pending", response_model=PendingApprovalsResponse)
async def list_pending_approvals():
    """
    List all sessions awaiting approval.

    Returns:
        List of pending approvals with trade proposal details
    """
    active_sessions = get_active_sessions()
    pending = []

    for session_id, session in active_sessions.items():
        state = session["state"]

        if not state.get("awaiting_approval"):
            continue

        proposal = state.get("trade_proposal")
        if not proposal:
            continue

        # Build analyses summary
        analyses_summary = PendingProposalSummary(
            technical=_get_analysis_summary(state.get("technical_analysis")),
            fundamental=_get_analysis_summary(state.get("fundamental_analysis")),
            sentiment=_get_analysis_summary(state.get("sentiment_analysis")),
            risk=_get_analysis_summary(state.get("risk_assessment")),
        )

        pending.append(
            PendingApprovalItem(
                session_id=session_id,
                ticker=session["ticker"],
                action=proposal.action.value if hasattr(proposal.action, "value") else proposal.action,
                quantity=proposal.quantity,
                risk_score=proposal.risk_score,
                rationale_preview=proposal.rationale[:200] if proposal.rationale else "",
                analyses_summary=analyses_summary,
                created_at=proposal.created_at,
            )
        )

    # Sort by created_at (oldest first - FIFO)
    pending.sort(key=lambda p: p.created_at)

    return PendingApprovalsResponse(
        pending_approvals=pending,
        total=len(pending),
    )


@router.get("/pending/{session_id}")
async def get_pending_approval(session_id: str):
    """
    Get detailed information about a pending approval.

    Args:
        session_id: Session identifier

    Returns:
        Detailed trade proposal and analyses
    """
    active_sessions = get_active_sessions()
    session = active_sessions.get(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    state = session["state"]

    if not state.get("awaiting_approval"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not awaiting approval",
        )

    proposal = state.get("trade_proposal")

    return {
        "session_id": session_id,
        "ticker": session["ticker"],
        "trade_proposal": {
            "id": proposal.id,
            "action": proposal.action.value if hasattr(proposal.action, "value") else proposal.action,
            "quantity": proposal.quantity,
            "entry_price": proposal.entry_price,
            "stop_loss": proposal.stop_loss,
            "take_profit": proposal.take_profit,
            "risk_score": proposal.risk_score,
            "position_size_pct": proposal.position_size_pct,
            "rationale": proposal.rationale,
            "bull_case": proposal.bull_case,
            "bear_case": proposal.bear_case,
        },
        "analyses": {
            "technical": _format_analysis(state.get("technical_analysis")),
            "fundamental": _format_analysis(state.get("fundamental_analysis")),
            "sentiment": _format_analysis(state.get("sentiment_analysis")),
            "risk": _format_analysis(state.get("risk_assessment")),
        },
        "synthesis": state.get("synthesis"),
        "reasoning_log": state.get("reasoning_log", []),
    }


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def _get_analysis_summary(analysis) -> str | None:
    """Get brief summary from analysis result."""
    if not analysis:
        return None

    signal = analysis.signal.value if hasattr(analysis.signal, "value") else str(analysis.signal)
    confidence = f"{analysis.confidence:.0%}"
    summary = analysis.summary[:100] if analysis.summary else ""

    return f"{signal} ({confidence}): {summary}"


def _format_analysis(analysis) -> dict | None:
    """Format analysis for API response."""
    if not analysis:
        return None

    return {
        "agent_type": analysis.agent_type,
        "signal": analysis.signal.value if hasattr(analysis.signal, "value") else str(analysis.signal),
        "confidence": analysis.confidence,
        "summary": analysis.summary,
        "key_factors": analysis.key_factors,
        "signals": analysis.signals,
        "reasoning": analysis.reasoning[:1000] if analysis.reasoning else "",
    }
