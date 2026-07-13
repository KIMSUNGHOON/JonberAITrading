"""
HITL Approval API Routes

Endpoints for human-in-the-loop trade approval workflow.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, status

from agents.graph.coin_trading_graph import get_coin_trading_graph
from agents.graph.kr_stock_graph import get_kr_stock_trading_graph
from app.api.routes._autonomy_injector import maybe_schedule_auto_approve
from app.api.routes.coin import get_coin_sessions
from app.api.routes.kr_stocks import get_kr_stock_sessions
from app.api.schemas.approval import (
    ApprovalRequest,
    ApprovalResponse,
    PendingApprovalItem,
    PendingApprovalsResponse,
    PendingProposalSummary,
)
from app.dependencies import get_trading_coordinator
from services.session_manager import (
    MarketType,
    SessionStatus,
    get_session_manager,
    mirror_session_state,
    mirror_session_status,
)
from services.telegram import get_telegram_notifier
from app.api.routes.websocket import (
    broadcast_trade_executed,
    broadcast_trade_queued,
    broadcast_trade_rejected,
    broadcast_watch_added,
)

logger = structlog.get_logger()
router = APIRouter()


# -------------------------------------------
# Approval Endpoints
# -------------------------------------------

# Per-session decision serialization. submit_decision clears
# state["awaiting_approval"] at its START but only mirrors the final SM status
# at its END — during a long resume (e.g. a reject-triggered re-analysis) the
# session still lists as awaiting on the operations board (which reads the SM
# status), so a second decision could arrive mid-flight (e.g. a cancel from a
# reloaded tab; the FE double-submit guard is client-local). Un-serialized,
# that cancel returned 200 "cancelled" via the zombie-cancel branch, and the
# ORIGINAL in-flight call then finished and overwrote the SM mirror with
# "running"/"completed" — silently orphaning the cancel (or executing a trade
# the user was told was cancelled). The lock makes the second caller wait and
# observe the true post-resume state. Lock entries are refcount-pruned on
# release so the dict stays bounded by in-flight sessions, not total sessions.
_decision_locks: dict[str, asyncio.Lock] = {}
_decision_lock_refs: dict[str, int] = {}


@asynccontextmanager
async def _session_decision_lock(session_id: str):
    lock = _decision_locks.setdefault(session_id, asyncio.Lock())
    _decision_lock_refs[session_id] = _decision_lock_refs.get(session_id, 0) + 1
    try:
        async with lock:
            yield
    finally:
        # Safe prune: refcount covers holders AND waiters — it only reaches 0
        # when nobody else holds a reference to this lock, so popping it can
        # never strand a waiter on a discarded lock (a later caller simply
        # creates a fresh one). No await between release and this decrement,
        # so no interleaving window.
        remaining = _decision_lock_refs[session_id] - 1
        if remaining:
            _decision_lock_refs[session_id] = remaining
        else:
            del _decision_lock_refs[session_id]
            _decision_locks.pop(session_id, None)


async def submit_decision(
    session_id: str,
    decision: str,
    feedback: str | None = None,
    modifications: dict | None = None,
    actor: str = "user",
):
    """
    Apply an approval decision and resume the LangGraph workflow from the
    approval interrupt.

    Extracted from the /decide route (R3) so the autonomy injector can submit
    decisions programmatically with actor='system'. Raises the same
    HTTPExceptions as the route; the route is a thin wrapper (actor='user').

    Decisions for the same session are serialized by a per-session lock (see
    _decision_locks above). The autonomy injector calls this only from a
    detached asyncio task after its grace sleep — never from within this call
    chain — so the lock cannot deadlock.
    """
    async with _session_decision_lock(session_id):
        return await _submit_decision_locked(
            session_id, decision, feedback, modifications, actor
        )


async def _submit_decision_locked(
    session_id: str,
    decision: str,
    feedback: str | None = None,
    modifications: dict | None = None,
    actor: str = "user",
):
    # Search all session types: coin and Korean stock
    coin_sessions = get_coin_sessions()
    kr_stock_sessions = get_kr_stock_sessions()
    session = coin_sessions.get(session_id) or kr_stock_sessions.get(session_id)

    if not session:
        # These legacy dicts are process-local and empty after a restart. The
        # session_manager SQLite row (and the LangGraph checkpoint, keyed by
        # thread_id=session_id) both survive a restart — fall back to sm and
        # re-adopt a legacy-shaped session into the correct dict so the rest
        # of this function, and any subsequent lookups, work unchanged.
        session = await _adopt_session_from_manager(
            session_id, coin_sessions, kr_stock_sessions
        )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    state = session["state"]

    if not state.get("awaiting_approval"):
        if decision == "cancelled":
            # Cancel-zombie tolerance: the operations board lists a session as
            # actionable off the session_manager row (sm.status ==
            # AWAITING_APPROVAL — checked above, in _adopt_session_from_manager,
            # or already true for a legacy-dict hit), but state["awaiting_approval"]
            # can be stale/False (reject -> re-analysis cycles and mirror races
            # desync the flag from the sm truth). Approve/reject/modified must
            # stay fail-closed (strictness pinned below), but cancel executes
            # nothing — there is no unsafe resume to guard against — so it must
            # always succeed for a session found by EITHER truth. This is a pure
            # termination mark: no graph resume, no legacy-dict (re-)registration.
            state["approval_status"] = "cancelled"
            state["awaiting_approval"] = False
            state.pop("auto_approve_at", None)
            session["status"] = "cancelled"
            await mirror_session_status(session_id, SessionStatus.CANCELLED)
            logger.info(
                "approval_cancel_stale_flag_tolerated",
                session_id=session_id,
            )
            return ApprovalResponse(
                session_id=session_id,
                decision=decision,
                status=session["status"],
                message="Analysis cancelled by user.",
                execution_status="cancelled",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not awaiting approval",
        )

    # Log state BEFORE approval to verify analysis results exist
    logger.info(
        "approval_state_before",
        session_id=session_id,
        decision=decision,
        has_technical=state.get("technical_analysis") is not None,
        has_fundamental=state.get("fundamental_analysis") is not None,
        has_sentiment=state.get("sentiment_analysis") is not None,
        has_risk=state.get("risk_assessment") is not None,
        state_keys=list(state.keys()),
    )

    # Update state with approval decision
    state["approval_status"] = decision
    state["user_feedback"] = feedback
    state["awaiting_approval"] = False
    state["approval_actor"] = actor
    # A decision voids any pending autonomous-approval countdown (R3).
    state.pop("auto_approve_at", None)

    # Apply modifications if provided (proposal is now a dict)
    if decision == "modified" and modifications:
        proposal = state.get("trade_proposal")
        if proposal:
            for key, value in modifications.items():
                if key in proposal:
                    proposal[key] = value
                    logger.debug(
                        "proposal_modified",
                        session_id=session_id,
                        field=key,
                        value=value,
                    )

    # Mirror the decision into the SessionManager (best-effort, no-op for
    # sessions not tracked there). Without this, sm-tracked sessions stay
    # AWAITING_APPROVAL forever (never TTL-cleaned) and the session WebSocket's
    # sm fallback would replay the already-decided proposal after a restart.
    decision_updates = {
        "approval_status": decision,
        "user_feedback": feedback,
        "awaiting_approval": False,
        "approval_actor": actor,
        "auto_approve_at": None,
    }
    if decision == "modified" and state.get("trade_proposal"):
        decision_updates["trade_proposal"] = state["trade_proposal"]
    await mirror_session_state(session_id, decision_updates)

    # Resume graph execution - select appropriate graph based on session type
    if session_id in kr_stock_sessions:
        graph = get_kr_stock_trading_graph()
    else:
        graph = get_coin_trading_graph()
    config = {"configurable": {"thread_id": session_id}}

    execution_status = None

    # Inject the human decision INTO the persisted graph checkpoint, THEN resume
    # with astream(None). Passing the dict to astream() instead RESTARTS the graph
    # from its entry node (re-running the whole analysis) rather than resuming from
    # the approval interrupt — so aupdate_state + astream(None) is the correct
    # LangGraph resume, and it also lets should_continue_*_execution see
    # approval_status (the old astream(None)-without-update routed to 'end').
    resume_update = {
        "approval_status": decision,
        "user_feedback": feedback,
        "awaiting_approval": False,
        "approval_actor": actor,
    }

    try:
        await graph.aupdate_state(config, resume_update)
        # Continue from the interrupt (decision already applied to graph state)
        async for event in graph.astream(None, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    if isinstance(node_output, dict):
                        state.update(node_output)
                        # Legacy first, then sm mirror (fires the WS push notify)
                        await mirror_session_state(
                            session_id, node_output, last_node=node_name
                        )
                    session["last_node"] = node_name

        # Track allocation result for response message
        allocation_rationale = None

        # Update session status based on decision
        if decision == "approved":
            session["status"] = "completed"
            execution_status = state.get("execution_status", "completed")

            # Connect to auto-trading system
            proposal = state.get("trade_proposal")
            if proposal:
                try:
                    coordinator = await get_trading_coordinator()

                    # Get ticker and stock name from session
                    ticker = session.get("stk_cd") or session.get("ticker") or session.get("market")
                    stock_name = session.get("stk_nm") or session.get("stock_name")

                    # Extract proposal data
                    action = proposal.get("action", "HOLD")

                    # Handle WATCH action - add to watch list
                    if action == "WATCH" and ticker:
                        # Get analysis data for watch list
                        technical = state.get("technical_analysis", {})
                        risk = state.get("risk_assessment", {})
                        synthesis = state.get("synthesis", {})

                        coordinator.add_to_watch_list(
                            session_id=session_id,
                            ticker=ticker,
                            stock_name=stock_name,
                            signal=technical.get("signal", "hold"),
                            confidence=technical.get("confidence", 0.5),
                            current_price=proposal.get("entry_price", 0),
                            target_entry_price=proposal.get("entry_price"),
                            stop_loss=proposal.get("stop_loss"),
                            take_profit=proposal.get("take_profit"),
                            analysis_summary=synthesis.get("summary", proposal.get("rationale", ""))[:500],
                            key_factors=technical.get("key_factors", [])[:5],
                            risk_score=int(risk.get("risk_score", 5)),
                        )

                        logger.info(
                            "watch_list_added",
                            session_id=session_id,
                            ticker=ticker,
                            stock_name=stock_name,
                        )
                        allocation_rationale = f"Added {stock_name or ticker} to Watch List"

                    # Handle BUY/SELL/ADD/REDUCE - the graph execution node is the
                    # SOLE executor: should_continue_*_execution -> "execute" already
                    # placed the order above (mock-gated by KIWOOM_IS_MOCK / Upbit
                    # paper mode). The coordinator is intentionally NOT called here to
                    # avoid double execution.
                    elif action in ("BUY", "SELL", "ADD", "REDUCE") and ticker:
                        exec_status = state.get("execution_status", "completed")
                        allocation_rationale = (
                            f"{action} executed via trading graph ({exec_status})"
                        )

                        logger.info(
                            "graph_execution_result",
                            session_id=session_id,
                            ticker=ticker,
                            action=action,
                            execution_status=exec_status,
                        )

                except Exception as e:
                    logger.error(
                        "auto_trading_connection_failed",
                        session_id=session_id,
                        error=str(e),
                    )
                    # Don't fail the approval, just log the error

        elif decision == "rejected":
            # Re-analysis requested. The resume above ran the graph back to
            # either the approval interrupt (new proposal awaiting) or the end.
            new_proposal_awaiting = bool(
                state.get("awaiting_approval") and not state.get("approval_status")
            )
            if new_proposal_awaiting:
                # 재분석이 새 제안으로 다시 인터럽트에 도달 — status를 producer
                # 경로와 동일하게 정합시키고 injector를 재암한다 (B3; 기존
                # 제안 ID 피닝이 이중 승인을 방지). 게이트 deny/hitl이면
                # maybe_schedule_auto_approve가 아무것도 쓰지 않는다(plain HITL).
                session["status"] = "awaiting_approval"
                execution_status = "awaiting_approval"
                market = "kiwoom" if session_id in kr_stock_sessions else "coin"
                await maybe_schedule_auto_approve(session_id, market, session)
            else:
                session["status"] = "running"
                execution_status = "re_analyzing"
        elif decision == "cancelled":
            # User cancelled the workflow
            session["status"] = "cancelled"
            execution_status = "cancelled"
        else:
            # modified
            session["status"] = "completed"
            execution_status = state.get("execution_status", "completed")

        # Belt-and-braces on top of the per-session lock (which serializes
        # decisions within this process): if approval_status was flipped to
        # "cancelled" underneath the resume (direct state mutation from another
        # worker sharing this state dict), preserve the cancel instead of
        # overwriting the final status with running/completed.
        if decision != "cancelled" and state.get("approval_status") == "cancelled":
            logger.warning(
                "approval_final_status_preserves_concurrent_cancel",
                session_id=session_id,
                decision=decision,
            )
            session["status"] = "cancelled"
            execution_status = "cancelled"

        # Mirror the final status to the SessionManager (completed/running/cancelled)
        await mirror_session_status(session_id, session["status"])

        # Log state AFTER approval to verify analysis results are preserved
        logger.info(
            "approval_state_after",
            session_id=session_id,
            has_technical=state.get("technical_analysis") is not None,
            has_fundamental=state.get("fundamental_analysis") is not None,
            has_sentiment=state.get("sentiment_analysis") is not None,
            has_risk=state.get("risk_assessment") is not None,
            execution_status=execution_status,
        )

        logger.info(
            "approval_processed",
            session_id=session_id,
            final_status=session["status"],
            execution_status=execution_status,
        )

        # Send notifications (Telegram + WebSocket)
        proposal = state.get("trade_proposal", {})
        ticker = session.get("stk_cd") or session.get("ticker") or session.get("market", "")
        stock_name = session.get("stk_nm") or session.get("stock_name", ticker)
        action = proposal.get("action", "BUY")

        # WebSocket broadcast for real-time UI updates
        try:
            if decision == "approved":
                if action == "WATCH":
                    technical = state.get("technical_analysis", {})
                    await broadcast_watch_added(
                        ticker=ticker,
                        stock_name=stock_name,
                        signal=technical.get("signal", "hold"),
                        confidence=technical.get("confidence", 0.5),
                        current_price=proposal.get("entry_price", 0),
                        session_id=session_id,
                    )
                elif action in ("BUY", "SELL"):
                    # Check if trade was queued or executed immediately
                    if allocation_rationale and "queued" in allocation_rationale.lower():
                        await broadcast_trade_queued(
                            ticker=ticker,
                            stock_name=stock_name,
                            action=action,
                            quantity=proposal.get("quantity", 0),
                            price=proposal.get("entry_price", 0),
                            session_id=session_id,
                        )
                    else:
                        await broadcast_trade_executed(
                            ticker=ticker,
                            stock_name=stock_name,
                            action=action,
                            quantity=proposal.get("quantity", 0),
                            price=proposal.get("entry_price", 0),
                            total_amount=proposal.get("quantity", 0) * proposal.get("entry_price", 0),
                            session_id=session_id,
                        )
            elif decision == "rejected":
                await broadcast_trade_rejected(
                    ticker=ticker,
                    stock_name=stock_name,
                    reason=feedback,
                    session_id=session_id,
                )
        except Exception as we:
            logger.warning("websocket_broadcast_failed", error=str(we))

        # Telegram notification
        try:
            telegram = await get_telegram_notifier()
            if telegram.is_ready:
                if decision == "approved":
                    # WATCH action sends watch list notification
                    if action == "WATCH":
                        technical = state.get("technical_analysis", {})
                        risk = state.get("risk_assessment", {})
                        await telegram.send_watch_list_added(
                            ticker=ticker,
                            stock_name=stock_name,
                            signal=technical.get("signal", "hold"),
                            confidence=technical.get("confidence", 0.5),
                            current_price=int(proposal.get("entry_price", 0)),
                            target_price=int(proposal.get("entry_price", 0)) if proposal.get("entry_price") else None,
                            risk_score=int(risk.get("risk_score", 5)),
                        )
                    # BUY/SELL actions send trade executed notification
                    elif action in ("BUY", "SELL"):
                        await telegram.send_trade_executed(
                            ticker=ticker,
                            stock_name=stock_name,
                            action=action,
                            quantity=proposal.get("quantity", 0),
                            price=proposal.get("entry_price", 0),
                            total_amount=proposal.get("quantity", 0) * proposal.get("entry_price", 0),
                        )
                elif decision == "rejected":
                    await telegram.send_trade_rejected(
                        ticker=ticker,
                        stock_name=stock_name,
                        reason=feedback or "User rejected the proposal",
                    )
        except Exception as te:
            logger.warning("telegram_notification_failed", error=str(te))

    except Exception as e:
        logger.error(
            "approval_processing_failed",
            session_id=session_id,
            error=str(e),
        )
        session["status"] = "error"
        session["error"] = str(e)
        await mirror_session_status(session_id, "error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process approval: {str(e)}",
        )

    # Build response message
    if decision == "approved":
        if allocation_rationale and "watch list" in allocation_rationale.lower():
            message = f"{allocation_rationale}"
        elif allocation_rationale and "queued" in allocation_rationale.lower():
            message = f"Trade approved. {allocation_rationale}"
        else:
            message = "Trade approved and executed successfully."
    elif decision == "rejected":
        message = "Trade rejected. Re-analyzing with your feedback..."
    elif decision == "cancelled":
        message = "Analysis cancelled by user."
    else:  # modified
        message = "Trade modified and executed with changes."

    return ApprovalResponse(
        session_id=session_id,
        decision=decision,
        status=session["status"],
        message=message,
        execution_status=execution_status,
    )



@router.post("/decide", response_model=ApprovalResponse)
async def submit_approval(request: ApprovalRequest):
    """HITL decide endpoint — thin wrapper over submit_decision (actor='user')."""
    return await submit_decision(
        request.session_id,
        request.decision,
        feedback=request.feedback,
        modifications=request.modifications,
        actor="user",
    )

@router.get("/pending", response_model=PendingApprovalsResponse)
async def list_pending_approvals():
    """
    List all sessions awaiting approval.

    Returns:
        List of pending approvals with trade proposal details
    """
    # Combine all session types: coin and Korean stock
    coin_sessions = get_coin_sessions()
    kr_stock_sessions = get_kr_stock_sessions()
    all_sessions = {**coin_sessions, **kr_stock_sessions}
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
    # Search all session types: coin and Korean stock
    coin_sessions = get_coin_sessions()
    kr_stock_sessions = get_kr_stock_sessions()
    session = coin_sessions.get(session_id) or kr_stock_sessions.get(session_id)

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


async def _adopt_session_from_manager(
    session_id: str,
    coin_sessions: dict,
    kr_stock_sessions: dict,
) -> dict | None:
    """Re-adopt a session that survived a restart via session_manager.

    The legacy in-memory dicts (coin/kr_stock) are process-local and lost on
    restart, but the SessionManager's SQLite-backed row survives (as does the
    LangGraph checkpoint keyed by thread_id=session_id — see P6 durable
    persistence). On a legacy-dict miss, look the session up there and, if
    found, convert it to the legacy-compatible shape (AnalysisSession.state
    is shared by reference, so subsequent mutations here also reach the sm
    row) and register it into the correct dict so the rest of submit_decision
    — and any later lookups — work unchanged.

    Fail-closed, validated BEFORE any registration (no zombie entries on
    failed probes):
    - only sm status == AWAITING_APPROVAL is adoptable. A settled session
      (cancelled/completed/error/running) returns None so the caller 404s —
      even if its state dict still says awaiting_approval=True (the cancel
      path clears status but not state; if the CANCELLED mirror write failed
      silently the row could survive the restart load filter, and adopting it
      would let an approve resume a proposal the user already vetoed).
    - only KIWOOM (kr stock) and COIN market types are adopted; anything else
      returns None so the caller 404s.
    - the state-level awaiting_approval check runs before registration too: a
      status=AWAITING_APPROVAL row whose state says it is NOT awaiting (mirror
      lag) is returned WITHOUT being registered, so the caller 400s and the
      legacy dict stays clean.
    """
    try:
        manager = await get_session_manager()
        sm_session = await manager.get_session(session_id)
    except Exception as e:
        logger.warning(
            "sm_session_adopt_lookup_failed",
            session_id=session_id,
            error=str(e),
        )
        return None

    if sm_session is None:
        return None

    if sm_session.status != SessionStatus.AWAITING_APPROVAL:
        logger.warning(
            "sm_session_adopt_refused_not_awaiting_status",
            session_id=session_id,
            sm_status=str(sm_session.status),
        )
        return None

    if sm_session.market_type == MarketType.KIWOOM:
        target_dict = kr_stock_sessions
    elif sm_session.market_type == MarketType.COIN:
        target_dict = coin_sessions
    else:
        logger.warning(
            "sm_session_adopt_unsupported_market_type",
            session_id=session_id,
            market_type=str(sm_session.market_type),
        )
        return None

    legacy_session = sm_session.to_legacy_dict()

    # State-level awaiting check BEFORE registering: return unregistered so
    # the caller's own awaiting check raises 400 without leaving a zombie
    # entry in the legacy dict.
    if not legacy_session["state"].get("awaiting_approval"):
        logger.warning(
            "sm_session_adopt_refused_state_not_awaiting",
            session_id=session_id,
        )
        return legacy_session

    target_dict[session_id] = legacy_session

    logger.info(
        "sm_session_adopted",
        session_id=session_id,
        market_type=str(sm_session.market_type),
    )
    return legacy_session


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
        "reasoning": reasoning if reasoning else "",  # Removed truncation
    }
