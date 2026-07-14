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
from app.api.routes._autonomy_injector import maybe_schedule_auto_approve
from services.session_manager import (
    MarketType,
    SessionStatus,
    get_session_manager,
    mirror_session_state,
    mirror_session_status,
)
from .constants import coin_sessions, get_cached_markets
from .helpers import find_active_coin_session, get_coin_session

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

    # P4 dedup: refuse to spawn a second concurrent analysis for a market
    # that already has one in progress (RUNNING/AWAITING_APPROVAL) — reuse
    # the existing session instead of minting a new one. Completed/error/
    # cancelled sessions never block; only a truly in-flight run does, so
    # re-analysis after a prior run finished is always allowed.
    existing = await find_active_coin_session(market)
    if existing is not None:
        logger.info(
            "coin_analysis_dedup_hit",
            existing_session_id=existing["session_id"],
            market=market,
            existing_status=existing.get("status"),
        )
        return CoinAnalysisResponse(
            session_id=existing["session_id"],
            market=existing.get("market") or market,
            status=existing.get("status", "running"),
            message="이미 진행중인 분석 세션이 있습니다 — 기존 세션을 재사용합니다.",
            duplicate=True,
        )

    session_id = str(uuid.uuid4())

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

    # Create session record (legacy dict = read path for REST/WS)
    initial_state = {
        "market": market,
        "korean_name": korean_name,
        "query": request.query,
        "reasoning_log": [],
        "current_stage": "data_collection",
    }
    coin_sessions[session_id] = {
        "session_id": session_id,
        "market": market,
        "korean_name": korean_name,
        "status": "running",
        "state": initial_state,
        "created_at": datetime.now(timezone.utc),
        "error": None,
    }

    # Also register in the SessionManager so its pub/sub can push updates to
    # the session WebSocket. Best-effort: on failure the session degrades to
    # the WS poll fallback, never a 500.
    try:
        session_manager = await get_session_manager()
        await session_manager.create_session(
            session_id=session_id,
            market_type=MarketType.COIN,
            ticker=market,
            display_name=korean_name or market,
            market=market,
            korean_name=korean_name,
            state={**initial_state, "reasoning_log": []},
        )
    except Exception as e:
        logger.warning(
            "sm_session_registration_failed",
            session_id=session_id,
            error=str(e),
        )

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
        # Cancel-during-slot-wait: the terminal cancelled status wins.
        if session["status"] != "cancelled":
            session["status"] = "error"
            session["error"] = "분석 대기열이 가득 찼습니다. 잠시 후 다시 시도해주세요."
            session["state"]["reasoning_log"].append(
                "[Error] 동시 분석 한도 초과 - 잠시 후 다시 시도해주세요."
            )
            update_session_status(session_id, "error", session["error"])
            await mirror_session_status(session_id, SessionStatus.ERROR, error=session["error"])
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
                    # Update session state with node output (legacy dict FIRST so
                    # a pub/sub wake-up always reads a fresh snapshot, then the sm
                    # mirror fires the WebSocket push notification)
                    if isinstance(node_output, dict):
                        session["state"].update(node_output)
                        await mirror_session_state(session_id, node_output, last_node=node_name)
                    session["last_node"] = node_name

                    logger.debug(
                        "coin_graph_node_completed",
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
            session["status"] = "awaiting_approval"
            update_session_status(session_id, "awaiting_approval")
            await mirror_session_status(session_id, SessionStatus.AWAITING_APPROVAL)
            logger.info(
                "coin_analysis_awaiting_approval",
                session_id=session_id,
                market=market,
            )
            # R3: in autonomous mode (gate-checked) this schedules a 60s-grace
            # auto-approval; in HITL mode (or any gate deny) it is a no-op.
            await maybe_schedule_auto_approve(session_id, "coin", session)
        elif state.get("error"):
            session["status"] = "error"
            session["error"] = state.get("error")
            update_session_status(session_id, "error", session["error"])
            await mirror_session_status(session_id, SessionStatus.ERROR, error=session["error"])
        else:
            session["status"] = "completed"
            update_session_status(session_id, "completed")
            await mirror_session_status(session_id, SessionStatus.COMPLETED)

    except Exception as e:
        logger.error(
            "coin_analysis_failed",
            session_id=session_id,
            error=str(e),
        )
        session["state"]["reasoning_log"] = session["state"].get("reasoning_log", []) + [
            f"[Error] Analysis failed: {str(e)}"
        ]
        # Cancel-mid-run: the terminal cancelled status wins over the error write.
        if session["status"] != "cancelled":
            session["status"] = "error"
            session["error"] = str(e)
            update_session_status(session_id, "error", str(e))
            await mirror_session_status(session_id, SessionStatus.ERROR, error=str(e))

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
        session = get_coin_session(session_id)

        # I4: refuse a cancel of an already-settled session. completed/error
        # both mean the session already ran to its real outcome; "cancelled"
        # is folded into the same 409 (pre-existing behavior, previously a
        # 400) since a repeat-cancel has nothing left to do.
        if session["status"] in ("completed", "error", "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Session already {session['status']} — cancel refused",
            )

        session["status"] = "cancelled"
        # F4b IMPORTANT-1: mirror the kr_stocks cancel route's state-clearing.
        # Without this, awaiting_approval stays True and approval_status stays
        # None/absent after this cancel — a stale system auto-approve racing
        # in through the injector's grace-window timer (see
        # _autonomy_injector._auto_approve_after_grace) checks the proposal-id
        # pin (unaffected by a cancel, which never replaces the proposal) but
        # NOT session["status"], so it falls straight through
        # submit_decision's stale-flag checks into the live approve path:
        # order placed, this cancelled status silently overwritten with
        # "completed". Clearing both flags here makes the session look
        # correctly "not awaiting" the same way kr_stocks does, and
        # approval._submit_decision_locked's inside-lock guard (belt-and-
        # braces) now also stands down on session["status"] alone.
        session["state"]["awaiting_approval"] = False
        session["state"]["approval_status"] = "cancelled"
        session["state"]["reasoning_log"].append("[System] Analysis cancelled by user")

        # Mirror to sm — the notify wakes the WebSocket, which re-reads the fresh
        # legacy snapshot (cancelled status + the appended log entry).
        await mirror_session_status(session_id, SessionStatus.CANCELLED)
        await mirror_session_state(
            session_id,
            {"awaiting_approval": False, "approval_status": "cancelled"},
        )

        logger.info("coin_analysis_cancelled", session_id=session_id)

        return {"message": f"Session {session_id} cancelled"}
