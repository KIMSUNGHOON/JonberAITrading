"""
HITL Approval API Routes

Endpoints for human-in-the-loop trade approval workflow.
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, status

from agents.graph.coin_trading_graph import get_coin_trading_graph
from agents.graph.kr_stock_graph import get_kr_stock_trading_graph
from agents.graph.trading_graph import get_trading_graph
from app.api.routes.analysis import get_active_sessions
from app.api.routes.coin import get_coin_sessions
from app.api.routes.kr_stocks import get_kr_stock_sessions
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
    # Search all session types: US stock, coin, and Korean stock
    stock_sessions = get_active_sessions()
    coin_sessions = get_coin_sessions()
    kr_stock_sessions = get_kr_stock_sessions()
    session = stock_sessions.get(request.session_id) or coin_sessions.get(request.session_id) or kr_stock_sessions.get(request.session_id)

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

    # Apply modifications if provided (proposal is now a dict)
    if request.decision == "modified" and request.modifications:
        proposal = state.get("trade_proposal")
        if proposal:
            for key, value in request.modifications.items():
                if key in proposal:
                    proposal[key] = value
                    logger.debug(
                        "proposal_modified",
                        session_id=request.session_id,
                        field=key,
                        value=value,
                    )

    # Resume graph execution - select appropriate graph based on session type
    if request.session_id in kr_stock_sessions:
        graph = get_kr_stock_trading_graph()
    elif request.session_id in coin_sessions:
        graph = get_coin_trading_graph()
    else:
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
        elif request.decision == "rejected":
            # Re-analysis requested - session continues running
            session["status"] = "running"
            execution_status = "re_analyzing"
        elif request.decision == "cancelled":
            # User cancelled the workflow
            session["status"] = "cancelled"
            execution_status = "cancelled"
        else:
            # modified
            session["status"] = "completed"
            execution_status = state.get("execution_status", "completed")

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
        message = "Trade rejected. Re-analyzing with your feedback..."
    elif request.decision == "cancelled":
        message = "Analysis cancelled by user."
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
    # Combine all session types: US stock, coin, and Korean stock
    stock_sessions = get_active_sessions()
    coin_sessions = get_coin_sessions()
    kr_stock_sessions = get_kr_stock_sessions()
    all_sessions = {**stock_sessions, **coin_sessions, **kr_stock_sessions}
    pending = []

    for session_id, session in all_sessions.items():
        state = session["state"]

        if not state.get("awaiting_approval"):
            continue

        proposal = state.get("trade_proposal")
        if not proposal:
            continue

        # Build analyses summary (analyses are now dicts)
        analyses_summary = PendingProposalSummary(
            technical=_get_analysis_summary(state.get("technical_analysis")),
            fundamental=_get_analysis_summary(state.get("fundamental_analysis")),
            sentiment=_get_analysis_summary(state.get("sentiment_analysis")),
            risk=_get_analysis_summary(state.get("risk_assessment")),
        )

        # Handle proposal as dict
        action = proposal.get("action", "HOLD")
        rationale = proposal.get("rationale", "")

        # Get ticker/market/stk_cd - each session type uses different keys
        ticker = session.get("ticker") or session.get("market") or session.get("stk_cd", "UNKNOWN")

        pending.append(
            PendingApprovalItem(
                session_id=session_id,
                ticker=ticker,
                action=str(action),
                quantity=proposal.get("quantity", 0),
                risk_score=proposal.get("risk_score", 0.5),
                rationale_preview=rationale[:200] if rationale else "",
                analyses_summary=analyses_summary,
                created_at=proposal.get("created_at"),
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
    # Search all session types: US stock, coin, and Korean stock
    stock_sessions = get_active_sessions()
    coin_sessions = get_coin_sessions()
    kr_stock_sessions = get_kr_stock_sessions()
    session = stock_sessions.get(session_id) or coin_sessions.get(session_id) or kr_stock_sessions.get(session_id)

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

    # Handle proposal as dict
    action = proposal.get("action", "HOLD") if proposal else "HOLD"

    # Get ticker/market/stk_cd - each session type uses different keys
    ticker = session.get("ticker") or session.get("market") or session.get("stk_cd", "UNKNOWN")

    return {
        "session_id": session_id,
        "ticker": ticker,
        "trade_proposal": {
            "id": proposal.get("id", ""),
            "action": str(action),
            "quantity": proposal.get("quantity", 0),
            "entry_price": proposal.get("entry_price"),
            "stop_loss": proposal.get("stop_loss"),
            "take_profit": proposal.get("take_profit"),
            "risk_score": proposal.get("risk_score", 0.5),
            "position_size_pct": proposal.get("position_size_pct", 5.0),
            "rationale": proposal.get("rationale", ""),
            "bull_case": proposal.get("bull_case", ""),
            "bear_case": proposal.get("bear_case", ""),
        } if proposal else None,
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
    """Get brief summary from analysis result (now a dict)."""
    if not analysis:
        return None

    signal = analysis.get("signal", "hold")
    confidence = analysis.get("confidence", 0.5)
    summary = analysis.get("summary", "")

    return f"{signal} ({confidence:.0%}): {summary[:100]}"


def _format_analysis(analysis) -> dict | None:
    """Format analysis for API response (now a dict)."""
    if not analysis:
        return None

    reasoning = analysis.get("reasoning", "")

    return {
        "agent_type": analysis.get("agent_type", "unknown"),
        "signal": str(analysis.get("signal", "hold")),
        "confidence": analysis.get("confidence", 0.5),
        "summary": analysis.get("summary", ""),
        "key_factors": analysis.get("key_factors", []),
        "signals": analysis.get("signals", {}),
        "reasoning": reasoning[:1000] if reasoning else "",
    }
