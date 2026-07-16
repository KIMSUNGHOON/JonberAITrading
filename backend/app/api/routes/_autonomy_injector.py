"""
Auto-approve Injector (R3)

When an analysis session reaches awaiting_approval and the shared autonomy
gate allows, this module announces the pending autonomous approval
(auto_approve_at countdown + reasoning entry + best-effort Telegram), waits
the grace window, RE-checks (the session must still be awaiting AND the gate
must still be green), then submits the decision through the extracted
submit_decision with actor='system'.

Invariants:
- The graph/interrupt is untouched — this is Design A: the decision is
  injected through the exact same resume path a human uses.
- Manual decisions always win: any decision during the grace window makes the
  injector stand down silently (and submit_decision's awaiting check makes
  the race idempotent).
- FAIL-CLOSED: gate pre-check deny → nothing is written, the session stays
  plain HITL; any exception → the session stays awaiting_approval and the
  normal HITL flow owns it.

Spec: docs/superpowers/specs/2026-07-11-r3-autonomous-hitl-mode-design.md §2.4
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog

from app.config import get_settings
from services.autonomy import check_autonomy
from services.session_manager import (
    MarketType,
    SessionStatus,
    get_session_manager,
    mirror_session_state,
)

logger = structlog.get_logger()

# Fixed 60s grace window (user decision). Module constant so tests can patch it.
AUTONOMY_GRACE_SECONDS = 60.0


def _proposal_fields(session: dict) -> dict:
    proposal = session.get("state", {}).get("trade_proposal") or {}
    action = proposal.get("action", "HOLD")
    if hasattr(action, "value"):
        action = action.value
    return {
        "action": str(action).upper(),
        "quantity": proposal.get("quantity"),
        "entry_price": proposal.get("entry_price"),
    }


async def maybe_schedule_auto_approve(session_id: str, market: str, session: dict) -> None:
    """Called by a producer right after it set awaiting_approval (+ mirrors).

    Pre-checks the gate; if allowed, announces the countdown and schedules the
    grace task. A deny here writes NOTHING — the session is ordinary HITL.
    """
    try:
        fields = _proposal_fields(session)
        decision = await check_autonomy(market, **fields)
        if not decision.allowed:
            logger.info(
                "auto_approve_not_scheduled",
                session_id=session_id,
                market=market,
                check=decision.check,
                reason=decision.reason,
            )
            return

        auto_approve_at = (
            datetime.now(timezone.utc) + timedelta(seconds=AUTONOMY_GRACE_SECONDS)
        ).isoformat()
        grace_secs = int(AUTONOMY_GRACE_SECONDS)

        # Legacy first (the WS read path), then the sm mirror (fires the push).
        state = session["state"]
        state["auto_approve_at"] = auto_approve_at
        state["reasoning_log"] = state.get("reasoning_log", []) + [
            f"[System] {grace_secs}초 후 자율 승인 예정 — REJECT로 거부 가능"
        ]
        await mirror_session_state(
            session_id,
            {"auto_approve_at": auto_approve_at, "reasoning_log": state["reasoning_log"]},
        )

        await _notify_pending(session_id, market, fields, grace_secs)

        # Pin the proposal identity: the grace task may only approve the exact
        # proposal it announced. A reject→re-analyze cycle mutates the SAME
        # session dict in place and can re-arm awaiting_approval with a NEW
        # proposal — without this pin the stale timer could approve a proposal
        # the user never saw (and with zero grace).
        proposal_id = (session["state"].get("trade_proposal") or {}).get("id")

        asyncio.create_task(
            _auto_approve_after_grace(session_id, market, session, proposal_id)
        )
        logger.info(
            "auto_approve_scheduled",
            session_id=session_id,
            market=market,
            auto_approve_at=auto_approve_at,
        )
    except Exception as e:
        # Fail-closed: scheduling problems leave the session plain HITL.
        logger.error("auto_approve_schedule_failed", session_id=session_id, error=str(e))


async def _clear_countdown(session_id: str, session: dict) -> None:
    """Remove a no-longer-valid auto_approve_at from state + the sm mirror so
    late-joining WS clients and restart recovery never see a stale countdown."""
    session["state"].pop("auto_approve_at", None)
    await mirror_session_state(session_id, {"auto_approve_at": None})


async def _auto_approve_after_grace(
    session_id: str, market: str, session: dict, proposal_id: str | None
) -> None:
    try:
        await asyncio.sleep(AUTONOMY_GRACE_SECONDS)

        state = session["state"]

        # Manual decisions during the grace always win. approval_status is set
        # the moment ANY decision is recorded — it also guards the brief
        # mid-reject window where the resuming graph re-emits
        # awaiting_approval=True before re_analyze clears it.
        if (
            session.get("status") != "awaiting_approval"
            or not state.get("awaiting_approval")
            or state.get("approval_status")
        ):
            logger.info("auto_approve_stood_down_manual", session_id=session_id)
            return

        # Only the exact proposal we announced may be approved. A re-analysis
        # produced a NEW proposal → this timer is stale; the fresh awaiting
        # state gets its own injector run (or plain HITL).
        current_id = (state.get("trade_proposal") or {}).get("id")
        if proposal_id is None or current_id != proposal_id:
            logger.info(
                "auto_approve_stood_down_proposal_changed",
                session_id=session_id,
                scheduled_for=proposal_id,
                current=current_id,
            )
            await _clear_countdown(session_id, session)
            return

        # Re-check the gate — the mode may have been flipped or a limit tripped
        # during the grace window.
        decision = await check_autonomy(market, **_proposal_fields(session))
        if not decision.allowed:
            entry = f"[System] 자율 승인 취소: {decision.reason}"
            session["state"]["reasoning_log"] = session["state"].get("reasoning_log", []) + [entry]
            await mirror_session_state(
                session_id, {"reasoning_log": session["state"]["reasoning_log"]}
            )
            await _clear_countdown(session_id, session)
            logger.info(
                "auto_approve_cancelled_at_recheck",
                session_id=session_id,
                check=decision.check,
                reason=decision.reason,
            )
            return

        # Lazy import: approval.py imports route packages — importing it at
        # module level from a routes module would create a cycle.
        from app.api.routes import approval

        # expected_proposal_id closes the TOCTOU window: submit_decision
        # re-validates this pin INSIDE its per-session lock (see
        # approval._submit_decision_locked) in case the outside check above
        # passed but a reject -> re-analysis replaced the proposal before this
        # call actually acquired the lock. A stand-down there returns a plain
        # dict ({"status": "stood_down", ...}) rather than raising — this
        # call site doesn't need to inspect it (no mutation happened either
        # way) and the log line below is harmlessly imprecise in that rare
        # race (belt-and-braces logging is not worth the extra branch here).
        await approval.submit_decision(
            session_id, "approved", actor="system", expected_proposal_id=proposal_id
        )
        logger.info("auto_approved", session_id=session_id, market=market)
    except Exception as e:
        # Fail-closed: the session stays awaiting_approval; HITL owns it.
        logger.error("auto_approve_failed", session_id=session_id, error=str(e))


async def _notify_pending(session_id: str, market: str, fields: dict, grace_secs: int) -> None:
    """Best-effort Telegram heads-up for the pending autonomous approval."""
    try:
        from services.telegram import get_telegram_notifier

        notifier = await get_telegram_notifier()
        if notifier.is_ready:
            await notifier.send_message(
                f"🤖 자율 승인 예정 ({market}): {fields['action']} — {grace_secs}초 내 "
                f"거부하지 않으면 자동 승인됩니다. (세션 {session_id[:8]})"
            )
    except Exception as e:
        logger.warning("auto_approve_notify_failed", session_id=session_id, error=str(e))


# -------------------------------------------
# Startup re-arm pass
# -------------------------------------------


def _has_future_auto_approve_at(value) -> bool:
    """True only if `value` parses to an aware datetime strictly in the
    future. A live grace task's own re-checks race harmlessly against this
    (worst case: we skip a session whose countdown is about to fire anyway,
    and the timer either approves it or stands down on its own)."""
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > datetime.now(timezone.utc)


def _scan_legacy_dict(get_dict, market: str, candidates: dict) -> None:
    """Add every AWAITING_APPROVAL session from a legacy in-memory dict into
    `candidates` (session_id -> (market, session)), first-writer-wins."""
    try:
        sessions = get_dict()
    except Exception as e:
        logger.error("autonomy_rearm_legacy_import_failed", market=market, error=str(e))
        return

    for session_id, session in sessions.items():
        try:
            if session.get("status") == SessionStatus.AWAITING_APPROVAL.value:
                candidates.setdefault(session_id, (market, session))
        except Exception as e:
            logger.error(
                "autonomy_rearm_legacy_scan_failed",
                market=market,
                session_id=session_id,
                error=str(e),
            )


async def rearm_awaiting_approvals() -> None:
    """Re-arm the auto-approve injector for sessions ALREADY awaiting_approval.

    Producers only call maybe_schedule_auto_approve() at the moment a session
    first sets awaiting_approval (see the module docstring). A session that
    reached awaiting_approval while the master autonomy gate was off never
    gets a countdown scheduled by anyone — and since AUTONOMY_ENABLED is read
    once at process/settings startup, turning it on always means a restart,
    which never revisits already-awaiting sessions on its own. Without this
    pass such a session stays plain HITL forever even after the operator
    turns autonomy on.

    Meant to be called once, from the app startup lifespan, after the
    SessionManager (and its stranded-session reconcile pass) have
    initialized. Walks every session currently AWAITING_APPROVAL from the
    SessionManager (the durable source of truth — SESSION_SSOT_READS=True,
    the default) — legacy in-memory dicts are no longer scanned; SM is the
    sole rearm source, so the old "legacy wins" tie-break for a session
    found in both places is obsolete.

    SESSION_SSOT_READS=False (kill switch) restores the pre-P1-4 fallback:
    the legacy dicts (kr_stock_sessions / coin_sessions) are scanned too,
    defensively, in case this is ever invoked again on a warm process (e.g.
    a future coordinator-start hook) where they are already populated. A
    session found in a legacy dict wins over its SessionManager copy for the
    same session_id in that branch (the legacy dict is the live,
    mutation-of-record object producers and approval.py read/write during
    normal operation).

    Idempotent / fail-closed:
    - a session that already carries a FUTURE auto_approve_at is skipped —
      a live grace task is presumably already counting it down, so scheduling
      another would stack a duplicate timer.
    - maybe_schedule_auto_approve() itself pre-checks the gate; a deny (e.g.
      master gate still off, or a coin session under HITL-only mode) writes
      nothing and the session stays plain HITL.
    - any error scanning or scheduling a single session is logged and that
      session is skipped — never raised — so one bad session can't block
      startup or the rest of the pass.
    """
    candidates: dict[str, tuple[str, dict]] = {}

    if not get_settings().SESSION_SSOT_READS:
        # kill-switch fallback only — P1 removed the legacy dicts from the
        # rearm scan (SM is the sole awaiting source; the "legacy wins"
        # tie-break is obsolete once there is a single source).
        try:
            from app.api.routes.kr_stocks import get_kr_stock_sessions

            _scan_legacy_dict(get_kr_stock_sessions, "kiwoom", candidates)
        except Exception as e:
            logger.error("autonomy_rearm_legacy_import_failed", market="kiwoom", error=str(e))

        try:
            from app.api.routes.coin import get_coin_sessions

            _scan_legacy_dict(get_coin_sessions, "coin", candidates)
        except Exception as e:
            logger.error("autonomy_rearm_legacy_import_failed", market="coin", error=str(e))

    try:
        manager = await get_session_manager()
        sm_sessions = await manager.get_all_sessions(status=SessionStatus.AWAITING_APPROVAL)
    except Exception as e:
        logger.error("autonomy_rearm_sm_scan_failed", error=str(e))
        sm_sessions = {}

    for session_id, sm_session in sm_sessions.items():
        if session_id in candidates:
            continue  # already have the live legacy-dict copy
        if sm_session.market_type == MarketType.KIWOOM:
            market = "kiwoom"
        elif sm_session.market_type == MarketType.COIN:
            market = "coin"
        else:
            continue  # US stock stack removed (R2) — nothing to re-arm there
        candidates[session_id] = (market, sm_session.to_legacy_dict())

    if not candidates:
        return

    logger.info("autonomy_rearm_scan", candidate_count=len(candidates))

    for session_id, (market, session) in candidates.items():
        try:
            state = session.get("state") or {}
            if not state.get("awaiting_approval"):
                continue
            if _has_future_auto_approve_at(state.get("auto_approve_at")):
                logger.info("autonomy_rearm_skip_live_countdown", session_id=session_id)
                continue
            await maybe_schedule_auto_approve(session_id, market, session)
        except Exception as e:
            logger.error("autonomy_rearm_session_failed", session_id=session_id, error=str(e))
