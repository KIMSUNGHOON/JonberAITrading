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
    mirror_session_state,
    mirror_session_status,
)
from .constants import kr_stock_sessions
from .helpers import find_active_kr_session, get_kr_stock_session

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

    # P4 dedup: refuse to spawn a second concurrent analysis for a stk_cd
    # that already has one in progress (RUNNING/AWAITING_APPROVAL) — reuse
    # the existing session instead of minting a new one. Completed/error/
    # cancelled sessions never block; only a truly in-flight run does, so
    # re-analysis after a prior run finished is always allowed.
    existing = await find_active_kr_session(stk_cd)
    if existing is not None:
        logger.info(
            "kr_stock_analysis_dedup_hit",
            existing_session_id=existing["session_id"],
            stk_cd=stk_cd,
            existing_status=existing.get("status"),
        )
        return KRStockAnalysisResponse(
            session_id=existing["session_id"],
            stk_cd=existing.get("stk_cd") or stk_cd,
            stk_nm=existing.get("stk_nm"),
            status=existing.get("status", "running"),
            message="이미 진행중인 분석 세션이 있습니다 — 기존 세션을 재사용합니다.",
            duplicate=True,
            # P4 Task 2: best-effort, no extra broker call — reuse whatever
            # this in-flight session already recorded (either the fresh-start
            # check below, if it ran for this same session, or the graph's
            # own data_collection node once it completes). A dedup hit is
            # meant to return immediately without paying for a second
            # network round-trip (see test_kr_start_dedup_does_not_call_kiwoom_client).
            position_exists=bool((existing.get("state") or {}).get("position_exists", False)),
        )

    session_id = str(uuid.uuid4())

    logger.info(
        "kr_stock_analysis_started",
        session_id=session_id,
        stk_cd=stk_cd,
    )

    # P4-T1 TOCTOU fix: reserve the session synchronously, right here — no
    # `await` between this write and the `find_active_kr_session` check
    # above — BEFORE the kiwoom name/position lookups below. Those lookups
    # are awaited network round-trips; without this reservation, two
    # near-simultaneous starts for the SAME stk_cd could both pass the dedup
    # check above before either recorded a session (two graph runs for one
    # ticker). `find_active_kr_session` matches on stk_cd + status in
    # {"running", "awaiting_approval"}, which this placeholder already
    # satisfies, so a concurrent request now dedups onto it immediately.
    # stk_nm/position_exists are filled in below once the lookups return.
    kr_stock_sessions[session_id] = {
        "session_id": session_id,
        "stk_cd": stk_cd,
        "stk_nm": None,
        "status": "running",
        "state": {
            "stk_cd": stk_cd,
            "stk_nm": None,
            "query": request.query,
            "reasoning_log": [],
            "current_stage": "data_collection",
            "position_exists": False,
        },
        "created_at": datetime.now(timezone.utc),
        "error": None,
    }

    # Get stock name + position (awaited network calls). Wrapped so that an
    # unexpected failure resolving the kiwoom client itself — as opposed to
    # the inner best-effort lookups below, which already degrade to
    # None/False on failure without raising — cleans up the placeholder just
    # reserved above instead of leaving a stranded "running" session that
    # would permanently block future analysis of this ticker.
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
        kr_stock_sessions.pop(session_id, None)
        raise

    # Finalize session record (legacy dict = read path for REST/WS) now that
    # the lookups above have resolved.
    initial_state = {
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "query": request.query,
        "reasoning_log": [],
        "current_stage": "data_collection",
        "position_exists": position_exists,
    }
    kr_stock_sessions[session_id].update(
        {
            "stk_nm": stk_nm,
            "state": initial_state,
        }
    )

    # Also register in the SessionManager so its pub/sub can push updates to
    # the session WebSocket. The sm keeps an independent state copy — the
    # producer mirrors every write (legacy first, then sm). Best-effort: on
    # failure the session degrades to the WS poll fallback, never a 500.
    try:
        session_manager = await get_session_manager()
        await session_manager.create_session(
            session_id=session_id,
            market_type=MarketType.KIWOOM,
            ticker=stk_cd,
            display_name=stk_nm or stk_cd,
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            state={**initial_state, "reasoning_log": []},
        )
    except Exception as e:
        # P1: with C-only reads a session that failed SM registration is
        # invisible everywhere -- fail fast instead of running blind. No
        # analysis slot was acquired yet at this point (that happens inside
        # run_kr_stock_analysis_task, which this failure prevents from ever
        # being scheduled), so there is nothing to release here.
        logger.error(
            "session_manager_create_failed_failfast",
            session_id=session_id,
            error=str(e),
        )
        kr_stock_sessions[session_id]["status"] = "error"
        kr_stock_sessions[session_id]["error"] = f"session registry create failed: {e}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"session registry create failed: {e}",
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


async def _finalize_awaiting_transition(session_id: str, session: dict) -> None:
    """
    Awaiting-critical write-through (P1, spec §P1): the AWAITING_APPROVAL
    transition MUST land in the SessionManager -- with C-only reads a session
    whose transition never reached the SM is an invisible interrupt (parked
    graph nobody can see or approve). One retry, then fail closed: the session
    becomes ERROR in BOTH stores and no auto-approve is scheduled.
    """
    last_error: Optional[Exception] = None
    for _attempt in range(2):
        try:
            await commit_session_status(session_id, SessionStatus.AWAITING_APPROVAL)
            session["status"] = "awaiting_approval"
            logger.info("kr_stock_analysis_awaiting_approval", session_id=session_id)
            await maybe_schedule_auto_approve(session_id, "kiwoom", session)
            return
        except Exception as e:  # noqa: BLE001 -- any SM failure fails closed below
            last_error = e

    session["status"] = "error"
    session["error"] = f"awaiting transition write-through failed: {last_error}"
    session["state"]["awaiting_approval"] = False
    session["state"]["reasoning_log"] = session["state"].get("reasoning_log", []) + [
        "[Error] 승인대기 상태를 영속 저장소에 기록하지 못해 세션을 안전 종료했습니다."
    ]
    logger.critical(
        "awaiting_writethrough_failclosed",
        session_id=session_id,
        error=str(last_error),
    )
    # Best-effort: try to land the ERROR in the SM too (same failure likely,
    # but the reconcile pass will repair a stale AWAITING row on restart).
    await mirror_session_status(session_id, SessionStatus.ERROR, error=session["error"])


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
        # Cancel-during-slot-wait: the terminal cancelled status wins.
        if session["status"] != "cancelled":
            session["status"] = "error"
            session["error"] = "Analysis timeout"
            await mirror_session_status(session_id, SessionStatus.ERROR, error="Analysis timeout")
        return

    try:
        stk_cd = session["stk_cd"]
        stk_nm = session.get("stk_nm")

        # Get the trading graph
        graph = get_kr_stock_trading_graph()

        # Create initial state. session_id must be threaded into the graph
        # state — nodes read it (e.g. the WATCH branch stamps it on the
        # watch-list entry); leaving it None silently broke those consumers.
        initial_state = create_kr_stock_initial_state(
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            user_query=session["state"].get("query"),
            session_id=session_id,
        )

        config = {"configurable": {"thread_id": session_id}}

        # Run until interrupt (approval node)
        async for event in graph.astream(initial_state, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    # Update session state with node output (legacy dict FIRST so
                    # a pub/sub wake-up always reads a fresh snapshot, then the sm
                    # mirror fires the WebSocket push notification)
                    if isinstance(node_output, dict):
                        session["state"].update(node_output)
                        await mirror_session_state(session_id, node_output, last_node=node_name)
                    session["last_node"] = node_name

                    logger.debug(
                        "kr_stock_graph_node_completed",
                        session_id=session_id,
                        node=node_name,
                    )

        # Check if we hit the approval interrupt
        state = session["state"]
        if session["status"] == "cancelled":
            # User cancelled mid-run (the graph kept streaming) — the terminal
            # cancelled status must not be overwritten by this final write.
            pass
        elif state.get("awaiting_approval"):
            # P1-5: write-through -- fails closed to ERROR (both stores) if the
            # SM commit doesn't land, instead of silently mirroring best-effort.
            await _finalize_awaiting_transition(session_id, session)
        elif state.get("error"):
            session["status"] = "error"
            session["error"] = state.get("error")
            await mirror_session_status(session_id, SessionStatus.ERROR, error=state.get("error"))
        else:
            session["status"] = "completed"
            await mirror_session_status(session_id, SessionStatus.COMPLETED)

    except Exception as e:
        logger.error(
            "kr_stock_analysis_failed",
            session_id=session_id,
            error=str(e),
        )
        session["state"]["reasoning_log"] = session["state"].get("reasoning_log", []) + [
            f"[Error] 분석 실패: {str(e)}"
        ]
        # Cancel-mid-run: the terminal cancelled status wins over the error write.
        if session["status"] != "cancelled":
            session["status"] = "error"
            session["error"] = str(e)
            await mirror_session_status(session_id, SessionStatus.ERROR, error=str(e))
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
    # instead of racing it directly against the legacy dict + sm mirror.
    # Pre-fix: an in-flight reject -> re-analysis holds no lock at all here,
    # so a cancel arriving mid-resume could mirror CANCELLED and then have the
    # reject's own final-status mirror silently overwrite it afterwards.
    async with _session_decision_lock(session_id):
        session = get_kr_stock_session(session_id)

        # I4: refuse a cancel of an already-settled session. completed/error
        # both mean the session already ran to its real outcome (trade
        # executed, or a run that already failed) — flipping that back to
        # CANCELLED after the fact would misreport it. "cancelled" is folded
        # into the same 409 (pre-existing behavior, previously a 400): a
        # repeat-cancel is a no-op with nothing left to do, so it is refused
        # the same way rather than silently re-mirroring CANCELLED again.
        if session["status"] in ("completed", "error", "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"세션이 이미 {session['status']} 상태입니다 — 취소 불가",
            )

        session["status"] = "cancelled"
        session["state"]["awaiting_approval"] = False
        session["state"]["approval_status"] = "cancelled"
        session["state"]["reasoning_log"].append("[System] 사용자가 분석을 취소했습니다")

        # Mirror to sm — the notify wakes the WebSocket, which re-reads the fresh
        # legacy snapshot (cancelled status + the appended log entry).
        #
        # Zombie-resurrection guard (live-confirmed 2x): the sm's AnalysisSession.state
        # is an INDEPENDENT copy of the legacy dict (made at registration time, see
        # start_kr_stock_analysis), so clearing awaiting_approval on `session["state"]`
        # above does NOT touch the sm/SQLite side. If the mirror below silently fails,
        # the sm row stays AWAITING_APPROVAL with awaiting_approval still True — a
        # restart then resurrects this cancelled session as a visible-but-unapprovable
        # zombie (approve → 400 "Session is not awaiting approval"). Do not swallow
        # that failure: log it loudly and tell the caller via `mirror_failed`.
        # P1-5: one retry before surfacing mirror_failed -- a transient SQLite
        # hiccup should not zombie-resurrect this session on restart if a
        # single retry would have landed the write.
        mirror_failed = False
        last_error: Optional[Exception] = None
        for _attempt in range(2):
            try:
                manager = await get_session_manager()
                await manager.update_status(session_id, SessionStatus.CANCELLED)
                await manager.update_state(
                    session_id,
                    {"awaiting_approval": False, "approval_status": "cancelled"},
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
        if last_error is not None:
            mirror_failed = True
            logger.error(
                "kr_stock_analysis_cancel_mirror_failed",
                session_id=session_id,
                error=str(last_error),
            )

        logger.info("kr_stock_analysis_cancelled", session_id=session_id)

        return {
            "message": f"세션 {session_id}이 취소되었습니다",
            "mirror_failed": mirror_failed,
        }
