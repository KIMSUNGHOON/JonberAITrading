"""
Coin Analysis Endpoints

Endpoints for coin analysis:
- POST /analysis/start - Start analysis
- GET /analysis/status/{session_id} - Get analysis status
- POST /analysis/cancel/{session_id} - Cancel analysis
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.schemas.coin import (
    CoinAnalysisRequest,
    CoinAnalysisResponse,
    CoinAnalysisStatusResponse,
    CoinAnalysisSummary,
    CoinTradeProposalResponse,
)
from app.config import get_settings
from app.core.analysis_limiter import (
    acquire_analysis_slot,
    get_active_analysis_count,
    release_analysis_slot,
)
from app.api.routes._autonomy_injector import maybe_schedule_auto_approve
from services.session_manager import (
    MarketType,
    SessionStatus,
    commit_session_status,
    get_session_manager,
    mirror_session_status,
)
from .constants import get_cached_markets
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
    market = request.market.upper()
    session_id = str(uuid.uuid4())

    # Get market info for Korean name -- a plain in-process cache lookup
    # (get_cached_markets/set_cached_markets are populated by /markets, no
    # network round-trip here), so it is safe to resolve BEFORE the atomic
    # reservation below (unlike KR's stk_nm, which needs an actual Kiwoom
    # API call and is therefore resolved AFTER reservation instead).
    korean_name = None
    cached_markets = get_cached_markets()
    if cached_markets:
        market_info = next((m for m in cached_markets if m.market == market), None)
        if market_info:
            korean_name = market_info.korean_name

    # P2-4: SM direct-write conversion (coin's counterpart to P2-3's KR
    # change). The old two-step dance -- a find_active_coin_session() dedup
    # READ, followed by a synchronous legacy-dict placeholder WRITE -- is
    # replaced by a SINGLE atomic call that holds the SessionManager's own
    # lock across the whole check-then-create window. This must run before
    # any network round-trip (the storage position lookup below): that await
    # is exactly the gap two near-simultaneous starts for the SAME market
    # could otherwise both slip through.
    initial_state = {
        "market": market,
        "korean_name": korean_name,
        "query": request.query,
        "reasoning_log": [],
        "current_stage": "data_collection",
        "position_exists": False,
    }

    try:
        session_manager = await get_session_manager()
        created, existing = await session_manager.create_session_if_no_active(
            session_id,
            MarketType.COIN,
            market,
            korean_name or market,
            market=market,
            korean_name=korean_name,
            state=initial_state,
        )
    except Exception as e:
        # P1-5 fail-fast semantics preserved: with C-only reads a session the
        # registry never even attempted to reserve is invisible everywhere --
        # there is no legacy dict left to degrade to.
        logger.error(
            "session_manager_create_failed_failfast",
            session_id=session_id,
            market=market,
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
            "coin_analysis_dedup_hit",
            existing_session_id=existing.session_id,
            market=market,
            existing_status=existing_status,
        )
        return CoinAnalysisResponse(
            session_id=existing.session_id,
            market=existing.market or market,
            status=existing_status,
            message="이미 진행중인 분석 세션이 있습니다 — 기존 세션을 재사용합니다.",
            duplicate=True,
            # P4 Task 2: best-effort, no extra storage lookup — reuse
            # whatever this in-flight session already recorded, mirroring
            # the KR dedup path's reasoning (a dedup hit returns immediately,
            # without paying for a second lookup).
            position_exists=bool((existing.state or {}).get("position_exists", False)),
        )

    logger.info(
        "coin_analysis_started",
        session_id=session_id,
        market=market,
    )

    # P4 Task 2: surface whether this market is already held, from the SAME
    # storage-backed source /positions reads (storage.get_coin_position) —
    # so this flag can never disagree with what that surface shows as held.
    # Best-effort: get_coin_position already degrades to None internally on
    # a storage error, so this can never fail the analysis-start request.
    position_exists = False
    try:
        from services.storage_service import get_storage_service

        storage = await get_storage_service()
        position = await storage.get_coin_position(market)
        position_exists = bool(position) and float(position.get("quantity", 0)) > 0
    except Exception as e:
        logger.warning("coin_position_exists_check_failed", market=market, error=str(e))

    # Finalize the reservation now that the storage lookup above has
    # resolved. `created` is the SAME AnalysisSession instance the
    # SessionManager holds in `_sessions` (create_session_if_no_active
    # returns the live object, not a copy).
    await session_manager.update_state(session_id, {"position_exists": position_exists})

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
        position_exists=position_exists,
    )


async def _finalize_awaiting_transition(session_id: str) -> None:
    """
    Awaiting-critical write-through (P1, spec §P1): the AWAITING_APPROVAL
    transition MUST land in the SessionManager -- with C-only reads a session
    whose transition never reached the SM is an invisible interrupt (parked
    graph nobody can see or approve). One retry, then fail closed: the
    session becomes ERROR and no auto-approve is scheduled.

    P2-4: SM-only -- there is no legacy dict left to keep in sync. The
    caller (run_coin_analysis_task) holds no session dict of its own either;
    this function re-fetches the SM row itself for the reasoning-log append
    and for the legacy-shaped dict maybe_schedule_auto_approve expects.
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
        logger.info("coin_analysis_awaiting_approval", session_id=session_id)
        # Outside the retry loop on purpose (see comment above) -- any
        # exception here propagates to the caller unchanged (run_coin_
        # analysis_task's own outer except marks the session error, same end
        # state, without corrupting the SM status this function just
        # correctly committed).
        sm = await get_session_manager()
        sm_session = await sm.get_session(session_id)
        # sm_session.state is shared BY REFERENCE with the SessionManager's
        # copy (to_legacy_dict() does not deep-copy state) -- any state
        # mutation the injector makes (auto_approve_at, reasoning_log, ...)
        # reaches the real SM row directly. Same known seam as the kr_stocks
        # counterpart (its "status" key is a point-in-time snapshot, not
        # live) accepted until P2-6 gives the injector a proper SM-native
        # session handle.
        legacy_session = sm_session.to_legacy_dict() if sm_session is not None else {
            "session_id": session_id,
            "status": "awaiting_approval",
            "state": {},
        }
        await maybe_schedule_auto_approve(session_id, "coin", legacy_session)
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
                "[Error] Failed to persist awaiting-approval state -- session safely terminated."
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


async def run_coin_analysis_task(session_id: str):
    """
    Background task to run coin analysis using LangGraph workflow.

    P2-4: the SessionManager's AnalysisSession IS the working state object --
    `sm_session` is fetched once and held for the life of this task.
    SessionManager.get_session()/update_state()/update_status() never replace
    the stored object, only mutate it in place (same dict/attribute
    references), so `sm_session.status`/`sm_session.state` stay LIVE: a
    concurrent cancel (which calls update_status/update_state on the same
    session_id) is visible here without re-fetching.
    """
    from agents.graph.coin_trading_graph import get_coin_trading_graph
    from agents.graph.coin_state import create_coin_initial_state

    sm = await get_session_manager()
    sm_session = await sm.get_session(session_id)
    if sm_session is None:
        logger.error("coin_session_not_found", session_id=session_id)
        return

    # Acquire analysis slot (with timeout)
    slot_acquired = await acquire_analysis_slot(timeout=60.0)
    if not slot_acquired:
        logger.warning(
            "coin_analysis_slot_timeout",
            session_id=session_id,
            active_count=get_active_analysis_count(),
        )
        # Cancel-during-slot-wait: the terminal cancelled status wins.
        if sm_session.status != SessionStatus.CANCELLED:
            await sm.update_status(
                session_id,
                SessionStatus.ERROR,
                error="분석 대기열이 가득 찼습니다. 잠시 후 다시 시도해주세요.",
            )
        return

    try:
        market = sm_session.market
        korean_name = sm_session.korean_name

        # Get the coin trading graph
        graph = get_coin_trading_graph()

        # Create initial state
        initial_state = create_coin_initial_state(
            market=market,
            korean_name=korean_name,
            user_query=sm_session.state.get("query"),
        )

        config = {"configurable": {"thread_id": session_id}}

        # Run until interrupt (approval node)
        async for event in graph.astream(initial_state, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    # SM direct write (P2-4): one call updates state AND
                    # fires the WebSocket push notification -- no legacy dict
                    # to keep in sync anymore.
                    if isinstance(node_output, dict):
                        await sm.update_state(session_id, node_output, last_node=node_name)

                    logger.debug(
                        "coin_graph_node_completed",
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
            "coin_analysis_failed",
            session_id=session_id,
            error=str(e),
        )
        try:
            reasoning_log = sm_session.state.get("reasoning_log", []) + [
                f"[Error] Analysis failed: {str(e)}"
            ]
            await sm.update_state(session_id, {"reasoning_log": reasoning_log})
        except Exception as log_err:  # noqa: BLE001 -- never let logging mask the real failure
            logger.warning(
                "coin_analysis_failure_log_mirror_failed",
                session_id=session_id,
                error=str(log_err),
            )
        # Cancel-mid-run: the terminal cancelled status wins over the error write.
        if sm_session.status != SessionStatus.CANCELLED:
            await sm.update_status(session_id, SessionStatus.ERROR, error=str(e))

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
    # P1-3 (session-SSOT): the SessionManager is the ONLY read source when
    # SESSION_SSOT_READS is on (default) — this is coin's first restart-tolerant
    # read path (previously `get_coin_session` read the legacy in-process dict
    # alone, so a session that survived a restart into the SM would 404 here).
    # The legacy-only path survives solely as the kill-switch fallback until
    # P2 removes legacy writes entirely — see app/api/routes/approval.py and
    # websocket.py for the same switch.
    if get_settings().SESSION_SSOT_READS:
        session_manager = await get_session_manager()
        session = await session_manager.get_session_dict(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Coin session {session_id} not found",
            )
    else:
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
        position_exists=state.get("position_exists", False),
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
    # I3: local import — approval.py is imported at coin-package init time
    # (__init__.py -> .analysis, this module), and approval.py itself imports
    # get_coin_sessions from this package at module level. A module-level
    # import of approval here would close a real import cycle (approval ->
    # coin -> analysis -> approval, partially-initialized). Deferred import
    # breaks the cycle; by request time approval.py is always fully loaded.
    from app.api.routes.approval import _session_decision_lock

    # Route this cancel through the SAME per-session lock /decide uses, so it
    # serializes against a concurrent reject/approve on the same session_id
    # (see the kr_stocks analog for the full defect writeup).
    async with _session_decision_lock(session_id):
        sm = await get_session_manager()
        sm_session = await sm.get_session(session_id)
        if sm_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Coin session {session_id} not found",
            )

        # I4: refuse a cancel of an already-settled session. completed/error
        # both mean the session already ran to its real outcome; "cancelled"
        # is folded into the same 409 (pre-existing behavior, previously a
        # 400) since a repeat-cancel has nothing left to do.
        if sm_session.status in (
            SessionStatus.COMPLETED,
            SessionStatus.ERROR,
            SessionStatus.CANCELLED,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Session already {sm_session.status.value} — cancel refused",
            )

        # P2-4: SM direct-write -- there is no legacy dict left to mutate
        # locally first, so this is fail-loud (P1-5 pattern): one retry, then
        # a 503 instead of a silently-swallowed "mirror_failed" 200. A
        # zombie-resurrection guard still applies (see kr_stocks cancel route
        # for the full writeup): if this write never lands, the SM row stays
        # AWAITING_APPROVAL with awaiting_approval still True -- a restart
        # would then resurrect this cancelled session as a visible-but-
        # unapprovable zombie. F4b IMPORTANT-1: clearing both awaiting_approval
        # and approval_status here is what prevents a stale system
        # auto-approve racing in through the injector's grace-window timer
        # from sailing through submit_decision's stale-flag checks and
        # silently overwriting this cancelled status with "completed".
        reasoning_log = sm_session.state.get("reasoning_log", []) + [
            "[System] Analysis cancelled by user"
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
                "coin_analysis_cancel_failed",
                session_id=session_id,
                error=str(last_error),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="cancel could not be persisted — retry",
            )

        logger.info("coin_analysis_cancelled", session_id=session_id)

        return {"message": f"Session {session_id} cancelled", "mirror_failed": False}
