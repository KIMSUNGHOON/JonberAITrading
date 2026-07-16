"""
Korean Stock Analysis Endpoints

Endpoints for stock analysis:
- POST /analysis/start - Start analysis
- GET /analysis/status/{session_id} - Get analysis status
- POST /analysis/cancel/{session_id} - Cancel analysis
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

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
from app.config import get_settings
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from app.api.routes._autonomy_injector import maybe_schedule_auto_approve
from services.session_manager import (
    MarketType,
    SessionStatus,
    commit_session_status,
    get_session_manager,
    mirror_session_status,
)
from .constants import kr_stock_sessions

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
    stk_cd = request.stk_cd
    session_id = str(uuid.uuid4())

    # P2-3: SM direct-write conversion. The old two-step dance -- a
    # find_active_kr_session() dedup READ, followed (with no intervening
    # await, per the P4-T1 TOCTOU fix) by a synchronous legacy-dict
    # placeholder WRITE -- is replaced by a SINGLE atomic call that holds the
    # SessionManager's own lock across the whole check-then-create window.
    # This must run before any network round-trip (stock_info/balance below):
    # those awaits are exactly the gap two near-simultaneous starts for the
    # SAME stk_cd could otherwise both slip through.
    initial_state = {
        "stk_cd": stk_cd,
        "stk_nm": None,
        "query": request.query,
        "reasoning_log": [],
        "current_stage": "data_collection",
        "position_exists": False,
    }

    try:
        session_manager = await get_session_manager()
        created, existing = await session_manager.create_session_if_no_active(
            session_id,
            MarketType.KIWOOM,
            stk_cd,
            stk_cd,  # display_name placeholder -- refined below once stk_nm resolves
            stk_cd=stk_cd,
            stk_nm=None,
            state=initial_state,
        )
    except Exception as e:
        # P1-5 fail-fast semantics preserved: with C-only reads a session the
        # registry never even attempted to reserve is invisible everywhere --
        # there is no legacy dict left to degrade to.
        logger.error(
            "session_manager_create_failed_failfast",
            session_id=session_id,
            stk_cd=stk_cd,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="session registry unavailable — retry",
        )

    if existing is not None:
        existing_status = (
            existing.status.value
            if isinstance(existing.status, SessionStatus)
            else existing.status
        )
        logger.info(
            "kr_stock_analysis_dedup_hit",
            existing_session_id=existing.session_id,
            stk_cd=stk_cd,
            existing_status=existing_status,
        )
        return KRStockAnalysisResponse(
            session_id=existing.session_id,
            stk_cd=existing.stk_cd or stk_cd,
            stk_nm=existing.stk_nm,
            status=existing_status,
            message="이미 진행중인 분석 세션이 있습니다 — 기존 세션을 재사용합니다.",
            duplicate=True,
            # P4 Task 2: best-effort, no extra broker call — reuse whatever
            # this in-flight session already recorded (either the fresh-start
            # check below, if it ran for this same session, or the graph's
            # own data_collection node once it completes). A dedup hit is
            # meant to return immediately without paying for a second
            # network round-trip (see test_kr_start_dedup_does_not_call_kiwoom_client).
            position_exists=bool((existing.state or {}).get("position_exists", False)),
        )

    logger.info(
        "kr_stock_analysis_started",
        session_id=session_id,
        stk_cd=stk_cd,
    )

    # Get stock name + position (awaited network calls). Wrapped so that an
    # unexpected failure resolving the kiwoom client itself — as opposed to
    # the inner best-effort lookups below, which already degrade to
    # None/False on failure without raising — cleans up the just-reserved SM
    # session instead of leaving a stranded "running" session that would
    # permanently block future analysis of this ticker.
    stk_nm = None
    position_exists = False
    try:
        client = await get_shared_kiwoom_client_async()

        try:
            info = await client.get_stock_info(stk_cd)
            if info:
                stk_nm = info.stk_nm
        except Exception as e:
            logger.warning("failed_to_get_stock_name", stk_cd=stk_cd, error=str(e))

        # P4 Task 2: surface whether stk_cd is already held, from the SAME
        # broker-balance source /positions and Operations '보유' read (kt00004,
        # get_account_balance()) — so this flag can never disagree with what
        # those surfaces show as held. Best-effort: any failure (client
        # unavailable, API error) degrades to False rather than failing the
        # analysis-start request — a position-awareness hint must never block
        # starting the analysis itself.
        try:
            balance = await client.get_account_balance()
            position_exists = any(h.stk_cd == stk_cd for h in balance.holdings)
        except Exception as e:
            logger.warning("kr_position_exists_check_failed", stk_cd=stk_cd, error=str(e))
    except Exception:
        await session_manager.remove_session(session_id)
        raise

    # Finalize the reservation now that the lookups above have resolved.
    # `created` is the SAME AnalysisSession instance the SessionManager holds
    # in `_sessions` (create_session_if_no_active returns the live object, not
    # a copy) — stk_nm/display_name are AnalysisSession FIELDS (not part of
    # `state`; to_legacy_dict()'s "stk_nm" reads self.stk_nm, which is what
    # the status endpoint and this response both surface), so they are set
    # directly here. The state-dict fields go through update_state(), whose
    # _save_session() call also persists this field mutation as part of the
    # same row write.
    created.stk_nm = stk_nm
    created.display_name = stk_nm or stk_cd
    await session_manager.update_state(
        session_id, {"stk_nm": stk_nm, "position_exists": position_exists}
    )

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
        position_exists=position_exists,
    )


async def _finalize_awaiting_transition(session_id: str) -> None:
    """
    Awaiting-critical write-through (P1, spec §P1): the AWAITING_APPROVAL
    transition MUST land in the SessionManager -- with C-only reads a session
    whose transition never reached the SM is an invisible interrupt (parked
    graph nobody can see or approve). One retry, then fail closed: the
    session becomes ERROR and no auto-approve is scheduled.

    P2-3: SM-only -- there is no legacy dict left to keep in sync. The
    caller (run_kr_stock_analysis_task) holds no session dict of its own
    either; this function re-fetches the SM row itself for the reasoning-log
    append and for the legacy-shaped dict maybe_schedule_auto_approve expects.
    """
    last_error: Optional[Exception] = None
    for _attempt in range(2):
        try:
            await commit_session_status(session_id, SessionStatus.AWAITING_APPROVAL)
            last_error = None
            break
        except Exception as e:  # noqa: BLE001 -- any SM failure fails closed below
            last_error = e

    if last_error is None:
        logger.info("kr_stock_analysis_awaiting_approval", session_id=session_id)
        # Outside the retry loop on purpose (see comment above) -- any
        # exception here propagates to the caller unchanged (run_kr_stock_
        # analysis_task's own outer except marks the session error, same end
        # state, without corrupting the SM status this function just
        # correctly committed).
        sm = await get_session_manager()
        sm_session = await sm.get_session(session_id)
        # sm_session.state is shared BY REFERENCE with the SessionManager's
        # copy (to_legacy_dict() does not deep-copy state) -- any state
        # mutation the injector makes (auto_approve_at, reasoning_log, ...)
        # reaches the real SM row directly. This is a known seam (its
        # "status" key is a point-in-time snapshot, not live) accepted until
        # P2-6 gives the injector a proper SM-native session handle.
        legacy_session = sm_session.to_legacy_dict() if sm_session is not None else {
            "session_id": session_id,
            "status": "awaiting_approval",
            "state": {},
        }
        await maybe_schedule_auto_approve(session_id, "kiwoom", legacy_session)
        return

    logger.critical(
        "awaiting_writethrough_failclosed",
        session_id=session_id,
        error=str(last_error),
    )
    # Best-effort: land ERROR (+ an explanatory reasoning-log entry) in the
    # SM directly. Any failure here is swallowed -- this branch is already
    # the fail-closed path; a second failure just means the reconcile pass
    # repairs a stale AWAITING row on restart instead.
    try:
        sm = await get_session_manager()
        sm_session = await sm.get_session(session_id)
        if sm_session is not None:
            reasoning_log = sm_session.state.get("reasoning_log", []) + [
                "[Error] 승인대기 상태를 영속 저장소에 기록하지 못해 세션을 안전 종료했습니다."
            ]
            await sm.update_state(
                session_id,
                {"awaiting_approval": False, "reasoning_log": reasoning_log},
            )
    except Exception as e:  # noqa: BLE001 -- best-effort, never escalate
        logger.warning(
            "awaiting_writethrough_failclosed_state_update_failed",
            session_id=session_id,
            error=str(e),
        )
    await mirror_session_status(
        session_id,
        SessionStatus.ERROR,
        error=f"awaiting transition write-through failed: {last_error}",
    )


async def run_kr_stock_analysis_task(session_id: str):
    """
    Background task to run Korean stock analysis using LangGraph workflow.

    Runs the kr_stock trading graph through all analysis stages until
    it reaches the approval interrupt point.

    P2-3: the SessionManager's AnalysisSession IS the working state object --
    `sm_session` is fetched once and held for the life of this task.
    SessionManager.get_session()/update_state()/update_status() never replace
    the stored object, only mutate it in place (same dict/attribute
    references), so `sm_session.status`/`sm_session.state` stay LIVE: a
    concurrent cancel (which calls update_status/update_state on the same
    session_id) is visible here without re-fetching.
    """
    from agents.graph.kr_stock_graph import get_kr_stock_trading_graph
    from agents.graph.kr_stock_state import create_kr_stock_initial_state

    sm = await get_session_manager()
    sm_session = await sm.get_session(session_id)
    if sm_session is None:
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
        # Cancel-during-slot-wait: the terminal cancelled status wins.
        if sm_session.status != SessionStatus.CANCELLED:
            await sm.update_status(session_id, SessionStatus.ERROR, error="Analysis timeout")
        return

    try:
        stk_cd = sm_session.stk_cd
        stk_nm = sm_session.stk_nm

        # Get the trading graph
        graph = get_kr_stock_trading_graph()

        # Create initial state. session_id must be threaded into the graph
        # state — nodes read it (e.g. the WATCH branch stamps it on the
        # watch-list entry); leaving it None silently broke those consumers.
        initial_state = create_kr_stock_initial_state(
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            user_query=sm_session.state.get("query"),
            session_id=session_id,
        )

        config = {"configurable": {"thread_id": session_id}}

        # Run until interrupt (approval node)
        async for event in graph.astream(initial_state, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    # SM direct write (P2-3): one call updates state AND
                    # fires the WebSocket push notification -- no legacy dict
                    # to keep in sync anymore.
                    if isinstance(node_output, dict):
                        await sm.update_state(session_id, node_output, last_node=node_name)

                    logger.debug(
                        "kr_stock_graph_node_completed",
                        session_id=session_id,
                        node=node_name,
                    )

        # Check if we hit the approval interrupt
        state = sm_session.state
        if sm_session.status == SessionStatus.CANCELLED:
            # User cancelled mid-run (the graph kept streaming) — the terminal
            # cancelled status must not be overwritten by this final write.
            pass
        elif state.get("awaiting_approval"):
            # P1-5: write-through -- fails closed to ERROR if the SM commit
            # doesn't land, instead of silently mirroring best-effort.
            await _finalize_awaiting_transition(session_id)
        elif state.get("error"):
            await sm.update_status(session_id, SessionStatus.ERROR, error=state.get("error"))
        else:
            await sm.update_status(session_id, SessionStatus.COMPLETED)

    except Exception as e:
        logger.error(
            "kr_stock_analysis_failed",
            session_id=session_id,
            error=str(e),
        )
        try:
            reasoning_log = sm_session.state.get("reasoning_log", []) + [
                f"[Error] 분석 실패: {str(e)}"
            ]
            await sm.update_state(session_id, {"reasoning_log": reasoning_log})
        except Exception as log_err:  # noqa: BLE001 -- never let logging mask the real failure
            logger.warning(
                "kr_stock_analysis_failure_log_mirror_failed",
                session_id=session_id,
                error=str(log_err),
            )
        # Cancel-mid-run: the terminal cancelled status wins over the error write.
        if sm_session.status != SessionStatus.CANCELLED:
            await sm.update_status(session_id, SessionStatus.ERROR, error=str(e))
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
    # P1-3 (session-SSOT): the SessionManager is the ONLY read source when
    # SESSION_SSOT_READS is on (default). The legacy-first + SM-fallback path
    # survives solely as the kill-switch fallback until P2 removes legacy
    # writes entirely — see app/api/routes/approval.py and websocket.py for
    # the same switch.
    if get_settings().SESSION_SSOT_READS:
        session_manager = await get_session_manager()
        session = await session_manager.get_session_dict(session_id)
    else:
        session = kr_stock_sessions.get(session_id)
        if session is None:
            # Legacy dict miss: `kr_stock_sessions` is a plain in-process dict —
            # every restart wipes it. Sessions that were running/awaiting_approval
            # at shutdown are reloaded into the SessionManager at startup (see
            # SessionManager._load_active_sessions) and may since have completed
            # via the resume/approval flow; fall back to its persisted copy so
            # this session's analyses/trade_proposal are still servable instead
            # of a bare 404.
            session_manager = await get_session_manager()
            session = await session_manager.get_session_dict(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Korean stock session {session_id} not found",
        )
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
        position_exists=state.get("position_exists", False),
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
    # I3: local import — approval.py is imported at kr_stocks-package init
    # time (__init__.py -> .analysis, this module), and approval.py itself
    # imports get_kr_stock_sessions from this package at module level. A
    # module-level import of approval here would close a real import cycle
    # (approval -> kr_stocks -> analysis -> approval, partially-initialized).
    # Deferred import breaks the cycle; by request time approval.py is always
    # fully loaded.
    from app.api.routes.approval import _session_decision_lock

    # Route this cancel through the SAME per-session lock /decide uses, so it
    # serializes against a concurrent reject/approve on the same session_id
    # instead of racing it directly against the SM.
    # Pre-fix: an in-flight reject -> re-analysis holds no lock at all here,
    # so a cancel arriving mid-resume could mirror CANCELLED and then have the
    # reject's own final-status mirror silently overwrite it afterwards.
    async with _session_decision_lock(session_id):
        sm = await get_session_manager()
        sm_session = await sm.get_session(session_id)
        if sm_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Korean stock session {session_id} not found",
            )

        # I4: refuse a cancel of an already-settled session. completed/error
        # both mean the session already ran to its real outcome (trade
        # executed, or a run that already failed) — flipping that back to
        # CANCELLED after the fact would misreport it. "cancelled" is folded
        # into the same 409 (pre-existing behavior, previously a 400): a
        # repeat-cancel is a no-op with nothing left to do, so it is refused
        # the same way rather than silently re-mirroring CANCELLED again.
        if sm_session.status in (
            SessionStatus.COMPLETED,
            SessionStatus.ERROR,
            SessionStatus.CANCELLED,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"세션이 이미 {sm_session.status.value} 상태입니다 — 취소 불가",
            )

        # P2-3: SM direct-write -- there is no legacy dict left to mutate
        # locally first, so this is fail-loud (P1-5 pattern): one retry, then
        # a 503 instead of a silently-swallowed "mirror_failed" 200. A
        # zombie-resurrection guard still applies (live-confirmed 2x
        # pre-P2-3): if this write never lands, the SM row stays
        # AWAITING_APPROVAL with awaiting_approval still True — a restart
        # would then resurrect this cancelled session as a visible-but-
        # unapprovable zombie (approve → 400 "Session is not awaiting
        # approval"). Fail loud instead of risking that silently.
        reasoning_log = sm_session.state.get("reasoning_log", []) + [
            "[System] 사용자가 분석을 취소했습니다"
        ]

        last_error: Optional[Exception] = None
        for _attempt in range(2):
            try:
                await sm.update_status(session_id, SessionStatus.CANCELLED)
                await sm.update_state(
                    session_id,
                    {
                        "awaiting_approval": False,
                        "approval_status": "cancelled",
                        "reasoning_log": reasoning_log,
                    },
                )
                last_error = None
                break
            except Exception as e:
                last_error = e

        if last_error is not None:
            logger.error(
                "kr_stock_analysis_cancel_failed",
                session_id=session_id,
                error=str(last_error),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="cancel could not be persisted — retry",
            )

        logger.info("kr_stock_analysis_cancelled", session_id=session_id)

        return {
            "message": f"세션 {session_id}이 취소되었습니다",
            "mirror_failed": False,
        }
