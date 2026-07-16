"""
HITL Approval API Routes

Endpoints for human-in-the-loop trade approval workflow.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

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
from app.config import get_settings
from app.dependencies import get_trading_coordinator
from services.session_manager import (
    MarketType,
    SessionStatus,
    commit_session_state,
    commit_session_status,
    get_session_manager,
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


class _SmSessionView:
    """Minimal dict-style live view over an AnalysisSession, for callers
    (the autonomy injector) that still expect ``session["state"]`` /
    ``session.get("status")`` access.

    P2-5 (session-SSOT): unlike ``sm_session.to_legacy_dict()``, which
    snapshots "status" as a plain string at call time, this wraps the LIVE
    AnalysisSession object -- ``.get("status")`` re-reads ``sm_session.status``
    on every access, so a decision recorded by another caller (e.g. a manual
    cancel arriving during the autonomy injector's 60s grace window) is
    visible immediately instead of frozen at scheduling time. ``state`` is
    the SessionManager's own dict (already live/shared), so mutations
    through it reach the SM row directly, same as the pre-P2-5
    to_legacy_dict() shape.

    Scoped to exactly what ``_autonomy_injector.py`` reads today
    (``session["state"]``, ``session.get("status")``); migrating the
    injector itself to a native SM handle is P2-6's job.
    """

    def __init__(self, sm_session):
        self._sm_session = sm_session

    def __getitem__(self, key):
        if key == "state":
            return self._sm_session.state
        if key == "status":
            return self._sm_session.status.value
        return getattr(self._sm_session, key)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, AttributeError):
            return default


async def submit_decision(
    session_id: str,
    decision: str,
    feedback: str | None = None,
    modifications: dict | None = None,
    actor: str = "user",
    expected_proposal_id: str | None = None,
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

    expected_proposal_id (system actor only, CRITICAL/F4b): the autonomy
    injector's grace-window timer already checks the proposal id BEFORE
    calling this function, but that check runs OUTSIDE the per-session lock.
    A reject -> re-analysis cycle can replace state["trade_proposal"] with a
    NEW id in the window between that outside check and the timer actually
    acquiring the lock here — see _submit_decision_locked, which re-validates
    the pin AFTER the lock is held, closing that TOCTOU race. Never passed
    (stays None) for actor='user'.
    """
    async with _session_decision_lock(session_id):
        return await _submit_decision_locked(
            session_id, decision, feedback, modifications, actor, expected_proposal_id
        )


async def _submit_decision_locked(
    session_id: str,
    decision: str,
    feedback: str | None = None,
    modifications: dict | None = None,
    actor: str = "user",
    expected_proposal_id: str | None = None,
):
    # P2-5 (session-SSOT): the SessionManager (SM / "C") is now the SOLE
    # session store for /decide -- no legacy in-memory dict ("B") merged
    # lookup, no restart-recovery adoption fallback (that helper function
    # was deleted by this task). By the time P2-3/P2-4 landed, the KR/coin
    # producers had already stopped writing to B on the awaiting-approval
    # path, so B was empty on every single call here and this function
    # silently fell through to the SM-backed fallback every time anyway --
    # going SM-only just makes that the one and only path instead of a
    # fallback.
    sm = await get_session_manager()
    sm_session = await sm.get_session(session_id)

    if sm_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # Live reference, not a to_legacy_dict() snapshot: sm.get_session()
    # returns the exact AnalysisSession object the SessionManager holds in
    # its own _sessions dict, so mutating `state` here (or calling
    # sm.update_state / commit_session_state) reaches the real SM row
    # directly -- there is no separate copy left to fall out of sync.
    # sm_session.status is read live throughout this function for the same
    # reason: any commit_session_status/mirror_session_status call (here or
    # from a concurrent caller sharing this same object) mutates
    # sm_session.status in place.
    state = sm_session.state

    # CRITICAL (F4b t1): re-validate the pinned proposal id INSIDE the lock.
    # The injector's outside pre-check (see _autonomy_injector) can pass,
    # then a reject -> re-analysis replaces state["trade_proposal"] with a
    # NEW id before this stale timer actually acquires the per-session lock.
    # Without this check, that timer would approve a proposal the user never
    # saw. Scoped to actor=='system' only -- user decisions never pin an id
    # and this must never affect the user-facing /decide route.
    if actor == "system" and expected_proposal_id is not None:
        current_proposal_id = (state.get("trade_proposal") or {}).get("id")
        if current_proposal_id != expected_proposal_id:
            logger.info(
                "auto_approve_stood_down_inside_lock",
                session_id=session_id,
                scheduled_for=expected_proposal_id,
                current=current_proposal_id,
                reason="proposal_changed",
            )
            return {"status": "stood_down", "reason": "proposal_changed"}

        # F4b IMPORTANT-1 (belt-and-braces): the pin above only catches a
        # REPLACED proposal (reject -> re-analysis). A route that flips the
        # SM status without replacing the proposal or clearing
        # state["awaiting_approval"] (the coin cancel route's bug, fixed
        # alongside this -- see coin/analysis.py cancel route) would sail
        # through the pin check unchanged and fall into the live approve
        # path below, executing an order and overwriting the cancelled
        # status. Checking sm_session.status here closes the whole class for
        # BOTH markets against ANY status-only mutation, present or future,
        # not just the one bug this audit found.
        if sm_session.status != SessionStatus.AWAITING_APPROVAL:
            logger.info(
                "auto_approve_stood_down_inside_lock",
                session_id=session_id,
                scheduled_for=expected_proposal_id,
                session_status=sm_session.status.value,
                reason="not_awaiting",
            )
            return {"status": "stood_down", "reason": "not_awaiting"}

    # General restart-adoption-equivalent guard: state["awaiting_approval"]
    # can be stale-True even though the SM's own status has already moved
    # past AWAITING_APPROVAL -- e.g. a cancel/other-terminal path that flips
    # sm_session.status without clearing state (the "coin cancel route" bug
    # F4b IMPORTANT-1 fixed above, present or future). Pre-P2-5, this exact
    # shape was refused by the (now-deleted) restart-recovery adoption
    # helper's own gate (actor-agnostic, ran for every /decide call since B
    # was always empty) -- deleting that function does not remove the need
    # for the check,
    # since resuming the graph off a stale True flag here would replay a
    # decision against a session the SM already considers settled. Placed
    # AFTER the F4b block above so a matching system-actor pin still gets
    # F4b's graceful stand-down dict instead of this hard 404 -- by the time
    # we reach here, either F4b already returned (actor=='system' with a
    # matching id) or this is the actor-agnostic fallback (chiefly the
    # user-facing /decide route, which never pins an id).
    if state.get("awaiting_approval") and sm_session.status != SessionStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    if not state.get("awaiting_approval"):
        if decision == "cancelled":
            # Masquerade guard (P0-4): if this session's last recorded
            # decision was "approved", awaiting_approval=False does NOT mean
            # "safely settled" the way it does for a plain
            # stale-flag/reject/cancel zombie below -- it can also mean
            # approve resumed the graph, the execution node placed a broker
            # order, and the process died (or a concurrent cancel raced in)
            # before the final status commit at the end of the resume ran.
            # In that window a real broker position may already exist.
            # Returning 200 "cancelled" here would tell the user a possibly-
            # executed trade was cleanly cancelled. Refuse instead -- no
            # state mutation, no status mirror -- and make the caller
            # confirm the actual fill before treating it as dead.
            if state.get("approval_status") == "approved":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="실행 중일 수 있어 취소 불가 — 체결 확인 필요",
                )
            # I4 (F4b T4 extension): a session already TERMINAL (completed or
            # error) has already run to its real outcome -- regardless of
            # which decision got it there (approved AND modified both leave
            # sm_session.status == COMPLETED; a re-analysis that blew up
            # leaves ERROR). A late cancel arriving after that (e.g. from a
            # reloaded tab, or racing the I3 lock) must not flip a settled
            # outcome back to CANCELLED -- that would misreport an executed
            # trade as never-happened, or erase a genuine failure record.
            # Checked after the narrower approved-branch above (which has
            # its own, more specific "확인 필요" message for the maybe-
            # mid-flight shape); this one is a plain "already done" refusal.
            # cancelled itself is intentionally NOT included here --
            # re-cancelling an already-cancelled session is a harmless
            # idempotent no-op, handled by the zombie-tolerance branch
            # below.
            if sm_session.status in (SessionStatus.COMPLETED, SessionStatus.ERROR):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="이미 처리됨 — 취소 불가",
                )
            # Cancel-zombie tolerance: the operations board lists a session
            # as actionable off the SM row (sm_session.status ==
            # AWAITING_APPROVAL -- checked above), but
            # state["awaiting_approval"] can be stale/False (reject ->
            # re-analysis cycles and mirror races desync the flag from the
            # sm truth). Approve/reject/modified must stay fail-closed
            # (strictness pinned above/below), but cancel executes nothing
            # -- there is no unsafe resume to guard against -- so it must
            # always succeed. This is a pure termination mark: no graph
            # resume.
            state["approval_status"] = "cancelled"
            state["awaiting_approval"] = False
            state.pop("auto_approve_at", None)
            await mirror_session_status(session_id, SessionStatus.CANCELLED)
            logger.info(
                "approval_cancel_stale_flag_tolerated",
                session_id=session_id,
            )
            return ApprovalResponse(
                session_id=session_id,
                decision=decision,
                status=SessionStatus.CANCELLED.value,
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

    # P1-5 review fix (Important A): commit-first ordering. The decision is
    # committed to the SM BEFORE it is treated as applied -- previously a
    # separate legacy-dict copy was mutated first, so a failed commit left
    # the session wedged: the local copy already said "decided" while the SM
    # still showed AWAITING_APPROVAL (the SM never heard), and a retry hit
    # the "not awaiting approval" 400 instead of being cleanly retryable.
    # P2-5: `state` IS sm_session.state (the SM's own live dict), so
    # commit_session_state's update_state call is the ONLY write needed
    # here -- there is no separate local copy left to re-apply
    # decision_updates to afterward (the old "B mutation" block is gone).
    # Modifications are computed against a COPY of the proposal so the
    # commit is the single point where state["trade_proposal"] actually
    # changes.
    updated_proposal = None
    if decision == "modified" and state.get("trade_proposal"):
        updated_proposal = dict(state["trade_proposal"])
        if modifications:
            for key, value in modifications.items():
                if key in updated_proposal:
                    updated_proposal[key] = value

    decision_updates = {
        "approval_status": decision,
        "user_feedback": feedback,
        "awaiting_approval": False,
        "approval_actor": actor,
        # A decision voids any pending autonomous-approval countdown (R3).
        "auto_approve_at": None,
    }
    if updated_proposal is not None:
        decision_updates["trade_proposal"] = updated_proposal

    try:
        await commit_session_state(session_id, decision_updates)
    except Exception as e:
        logger.critical(
            "approval_decision_writethrough_failed",
            session_id=session_id,
            decision=decision,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="approval state could not be persisted — retry",
        )

    # Resume graph execution - select appropriate graph based on session type.
    #
    # P2 (spec §P2, review CRITICAL): market discrimination must come from the
    # SM record's market_type, NOT legacy-dict (B) membership. sm_session was
    # already fetched above and is guaranteed non-None (the 404 branch
    # returned earlier otherwise) -- fail-closed (no B-membership fallback,
    # no guessing) for any market_type this branch doesn't recognize.
    if sm_session.market_type not in (MarketType.KIWOOM, MarketType.COIN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown session market — refusing to resume",
        )
    if sm_session.market_type == MarketType.KIWOOM:
        graph = get_kr_stock_trading_graph()
        market = "kiwoom"
    else:
        graph = get_coin_trading_graph()
        market = "coin"
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
        # Continue from the interrupt (decision already applied to graph
        # state). `state` IS sm_session.state (live), so sm.update_state is
        # the single write per node: it applies node_output to state,
        # flushes to SQLite (sync for critical keys, debounced otherwise),
        # and notifies WS subscribers all in one call (P2-5: replaces the
        # old `state.update(node_output)` + `mirror_session_state(...)`
        # pair -- there is no separate local copy left to update first).
        async for event in graph.astream(None, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    state_updates = node_output if isinstance(node_output, dict) else {}
                    await sm.update_state(session_id, state_updates, last_node=node_name)

        # Track allocation result for response message
        allocation_rationale = None

        # Update session status based on decision
        if decision == "approved":
            final_status = SessionStatus.COMPLETED
            execution_status = state.get("execution_status", "completed")

            # Connect to auto-trading system
            proposal = state.get("trade_proposal")
            if proposal:
                try:
                    coordinator = await get_trading_coordinator()

                    # Ticker/display-name: sourced from the SM row's own
                    # market-specific fields (only one of stk_cd/market is
                    # populated depending on market_type; korean_name covers
                    # the coin shape stk_nm never had).
                    ticker = sm_session.stk_cd or sm_session.ticker or sm_session.market
                    stock_name = sm_session.stk_nm or sm_session.korean_name

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
            # either the approval interrupt (new proposal awaiting) or the
            # end.
            new_proposal_awaiting = bool(
                state.get("awaiting_approval") and not state.get("approval_status")
            )
            if new_proposal_awaiting:
                # 재분석이 새 제안으로 다시 인터럽트에 도달 — status를 producer
                # 경로와 동일하게 정합시키고 injector를 재암한다 (B3; 기존
                # 제안 ID 피닝이 이중 승인을 방지). 게이트 deny/hitl이면
                # maybe_schedule_auto_approve가 아무것도 쓰지 않는다(plain HITL).
                #
                # P1-5 review fix (Important B): commit-first ordering --
                # commit_session_status(AWAITING_APPROVAL) must land (1
                # retry) BEFORE the timer is scheduled. The pre-fix code
                # scheduled the 60s auto-approve timer unconditionally,
                # ahead of the shared final-status commit far below -- if
                # THAT commit then failed, the timer was already armed
                # against an SM row that never learned about this
                # transition: a live violation of the core invariant ("SM
                # 기록 실패 시 schedule 절대 금지"), since a brief SM
                # recovery could let the timer fire an autonomous order for
                # a transition nobody could see. market already resolved
                # from sm_session.market_type at the graph-selection site
                # above -- reused here, no re-derivation.
                last_error: Optional[Exception] = None
                for _attempt in range(2):
                    try:
                        await commit_session_status(session_id, SessionStatus.AWAITING_APPROVAL)
                        last_error = None
                        break
                    except Exception as e:
                        last_error = e
                if last_error is not None:
                    logger.critical(
                        "approval_rearm_writethrough_failed",
                        session_id=session_id,
                        error=str(last_error),
                    )
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="approval state could not be persisted — retry",
                    )

                final_status = SessionStatus.AWAITING_APPROVAL
                execution_status = "awaiting_approval"
                # P2-5: the injector's `session` argument is no longer a
                # to_legacy_dict() snapshot (its "status" key would freeze
                # at schedule time) -- _SmSessionView is a thin live
                # dict-style proxy over sm_session so _autonomy_injector's
                # existing session["state"] / session.get("status") reads
                # always see the current SM state/status, including any
                # decision made by another caller during the grace window.
                # Migrating the injector itself to a native SM handle is
                # P2-6's job; this is the narrowest fix that keeps
                # /decide's own call site honest in the meantime.
                await maybe_schedule_auto_approve(session_id, market, _SmSessionView(sm_session))
            else:
                final_status = SessionStatus.RUNNING
                execution_status = "re_analyzing"
        elif decision == "cancelled":
            # User cancelled the workflow
            final_status = SessionStatus.CANCELLED
            execution_status = "cancelled"
        else:
            # modified
            final_status = SessionStatus.COMPLETED
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
            final_status = SessionStatus.CANCELLED
            execution_status = "cancelled"

        # Commit the final status to the SessionManager (completed/running/
        # cancelled). P1-5: write-through -- for a decision that may already
        # have executed a broker order (approved/modified), a silently
        # swallowed commit failure here would leave the SM showing a stale
        # AWAITING_APPROVAL status for a session that is actually done.
        try:
            await commit_session_status(session_id, final_status)
        except Exception as e:
            logger.critical(
                "approval_final_status_writethrough_failed",
                session_id=session_id,
                status=final_status.value,
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="approval state could not be persisted — retry",
            )

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
            final_status=final_status.value,
            execution_status=execution_status,
        )

        # Send notifications (Telegram + WebSocket)
        proposal = state.get("trade_proposal", {})
        ticker = sm_session.stk_cd or sm_session.ticker or sm_session.market or ""
        stock_name = sm_session.stk_nm or sm_session.korean_name or ticker
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
                    # I5: honest wording keyed off the graph's real
                    # execution_status (set above at the top of this
                    # decision=='approved' branch) instead of the previous
                    # "queued" substring check on allocation_rationale, which
                    # never actually matched anything allocation_rationale
                    # produces (it always reads "... executed via trading
                    # graph (<status>)") -- so BUY/SELL always fell through to
                    # broadcast_trade_executed/send_trade_executed even when
                    # the order only placed and never confirmed a fill, or
                    # outright failed. Never claim a fill that didn't happen.
                    if execution_status == "placed_pending_fill":
                        order_response = state.get("order_response") or {}
                        ord_no = order_response.get("ord_no")
                        await broadcast_trade_queued(
                            ticker=ticker,
                            stock_name=stock_name,
                            action=action,
                            quantity=proposal.get("quantity", 0),
                            price=proposal.get("entry_price", 0),
                            expected_execution=(
                                f"접수, 체결 대기 (주문번호: {ord_no})"
                                if ord_no
                                else "접수, 체결 대기"
                            ),
                            session_id=session_id,
                        )
                    elif execution_status == "failed":
                        await broadcast_trade_rejected(
                            ticker=ticker,
                            stock_name=stock_name,
                            reason=state.get("error") or "주문 실행 실패",
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
                    # BUY/SELL actions: honest wording keyed off execution_status
                    # (see the matching WS branch above for why -- same
                    # "queued" dead-check replaced).
                    elif action in ("BUY", "SELL"):
                        if execution_status == "placed_pending_fill":
                            order_response = state.get("order_response") or {}
                            await telegram.send_trade_pending(
                                ticker=ticker,
                                stock_name=stock_name,
                                action=action,
                                quantity=proposal.get("quantity", 0),
                                ord_no=order_response.get("ord_no"),
                            )
                        elif execution_status == "failed":
                            await telegram.send_trade_rejected(
                                ticker=ticker,
                                stock_name=stock_name,
                                reason=state.get("error") or "주문 실행 실패",
                            )
                        else:
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

    except HTTPException:
        # P1-5: a deliberate fail-loud raise (SM write-through failures
        # above) must propagate with its own status/detail -- the generic
        # handler below must not rewrap it into a 500.
        raise
    except Exception as e:
        logger.error(
            "approval_processing_failed",
            session_id=session_id,
            error=str(e),
        )
        await mirror_session_status(session_id, SessionStatus.ERROR, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process approval: {str(e)}",
        )

    # Build response message
    if decision == "approved":
        if allocation_rationale and "watch list" in allocation_rationale.lower():
            message = f"{allocation_rationale}"
        # I5: honest wording off the real execution_status -- replaces a
        # "queued" substring check that never matched (allocation_rationale
        # never contains that word), which meant this always fell through to
        # "executed successfully" regardless of whether the order filled.
        elif execution_status == "placed_pending_fill":
            message = "Trade approved and order placed — fill pending confirmation."
        elif execution_status == "failed":
            message = "Trade approved but execution failed."
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
        status=final_status.value,
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
    # P1 (session-SSOT): SESSION_SSOT_READS=True (default) reads the
    # SessionManager exclusively. False = legacy dict merge (pre-P1
    # behavior) -- kill switch only, valid until P2 removes legacy writes.
    if get_settings().SESSION_SSOT_READS:
        sm = await get_session_manager()
        sm_sessions = await sm.get_all_sessions()
        all_sessions = {
            sid: s.to_legacy_dict() for sid, s in sm_sessions.items()
        }
    else:
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
    # P1 (session-SSOT): SM-only lookup (no legacy-dict fallback) when the
    # flag is on -- see list_pending_approvals above for the same switch.
    if get_settings().SESSION_SSOT_READS:
        sm = await get_session_manager()
        session = await sm.get_session_dict(session_id)
    else:
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
