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

P2-6 (session-SSOT): this module is a native SessionManager (SM) reader/
writer. Every entry point takes only a `session_id` (+ `market` where the
caller already knows it) — never a session dict/snapshot/view — and resolves
the live AnalysisSession itself via `sm.get_session(session_id)`, both at
schedule time (maybe_schedule_auto_approve) and again inside the grace
task's re-check (_auto_approve_after_grace). auto_approve_at / reasoning_log
writes go through a single `sm.update_state(...)` call; there is no longer a
"mutate a shared dict, then best-effort mirror_session_state it" pair to keep
in sync, and no snapshot anywhere in this path that can go stale relative to
a decision another caller records during the grace window. This retired
approval.py's `_SmSessionView` shim (it existed only to hand this module
something dict-shaped from a live AnalysisSession) and the
`sm_session.to_legacy_dict()` calls the KR/coin producers and the rearm scan
used to build for it.

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
)

logger = structlog.get_logger()

# Fixed 60s grace window (user decision). Module constant so tests can patch it.
AUTONOMY_GRACE_SECONDS = 60.0


def _proposal_fields(state: dict) -> dict:
    """P2-6: operates on a session's `state` dict directly (a live
    AnalysisSession.state reference) — callers no longer wrap it in a
    session-shaped dict first."""
    proposal = state.get("trade_proposal") or {}
    action = proposal.get("action", "HOLD")
    if hasattr(action, "value"):
        action = action.value
    return {
        "action": str(action).upper(),
        "quantity": proposal.get("quantity"),
        "entry_price": proposal.get("entry_price"),
    }


async def maybe_schedule_auto_approve(session_id: str, market: str) -> None:
    """Called by a producer (or approval.py's reject->re-analysis rearm)
    right after it committed awaiting_approval to the SessionManager.
    Pre-checks the gate; if allowed, announces the countdown and schedules
    the grace task. A deny here writes NOTHING — the session is ordinary
    HITL.

    P2-6: no `session` argument — the session is resolved here via a live
    `sm.get_session(session_id)` lookup. A session that has vanished from
    the SM by the time this runs (removed, or never existed — e.g. a
    kill-switch-only legacy-dict candidate, see rearm_awaiting_approvals) is
    a no-op: nothing to schedule against.
    """
    try:
        sm = await get_session_manager()
        sm_session = await sm.get_session(session_id)
        if sm_session is None:
            logger.warning(
                "auto_approve_schedule_skipped_session_missing",
                session_id=session_id,
                market=market,
            )
            return

        fields = _proposal_fields(sm_session.state)
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

        # Single write-through: sm.update_state applies both keys to the
        # live SM row, flushes them (auto_approve_at is a critical key —
        # see services/session_manager.py::_CRITICAL_STATE_KEYS), and
        # notifies WS subscribers — replacing the old "mutate the shared
        # dict directly, then best-effort mirror_session_state" pair.
        reasoning_log = sm_session.state.get("reasoning_log", []) + [
            f"[System] {grace_secs}초 후 자율 승인 예정 — REJECT로 거부 가능"
        ]
        await sm.update_state(
            session_id,
            {"auto_approve_at": auto_approve_at, "reasoning_log": reasoning_log},
        )

        await _notify_pending(session_id, market, fields, grace_secs)

        # Pin the proposal identity: the grace task may only approve the exact
        # proposal it announced. A reject→re-analyze cycle mutates the SAME
        # SM row in place and can re-arm awaiting_approval with a NEW
        # proposal — without this pin the stale timer could approve a proposal
        # the user never saw (and with zero grace).
        proposal_id = (sm_session.state.get("trade_proposal") or {}).get("id")

        asyncio.create_task(
            _auto_approve_after_grace(session_id, market, proposal_id)
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


async def _clear_countdown(session_id: str) -> None:
    """Remove a no-longer-valid auto_approve_at directly on the SM so
    late-joining WS clients and restart recovery never see a stale
    countdown. Only ever called from inside _auto_approve_after_grace's own
    try/except (fail-closed logging), so no separate error handling here —
    a raise here (e.g. the session was removed between the caller's checks
    and this call) just gets logged as auto_approve_failed."""
    sm = await get_session_manager()
    await sm.update_state(session_id, {"auto_approve_at": None})


async def _auto_approve_after_grace(
    session_id: str, market: str, proposal_id: str | None
) -> None:
    try:
        await asyncio.sleep(AUTONOMY_GRACE_SECONDS)

        sm = await get_session_manager()
        sm_session = await sm.get_session(session_id)
        if sm_session is None:
            logger.info("auto_approve_stood_down_session_missing", session_id=session_id)
            return

        state = sm_session.state

        # Manual decisions during the grace always win. Read LIVE off the SM
        # (P2-6): sm_session is the exact object any concurrent writer
        # (submit_decision, a cancel route, ...) mutates in place, so this
        # always observes the latest status/state, never a frozen snapshot.
        # approval_status is set the moment ANY decision is recorded — it
        # also guards the brief mid-reject window where the resuming graph
        # re-emits awaiting_approval=True before re_analyze clears it.
        if (
            sm_session.status != SessionStatus.AWAITING_APPROVAL
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
            await _clear_countdown(session_id)
            return

        # Re-check the gate — the mode may have been flipped or a limit tripped
        # during the grace window.
        decision = await check_autonomy(market, **_proposal_fields(state))
        if not decision.allowed:
            entry = f"[System] 자율 승인 취소: {decision.reason}"
            reasoning_log = state.get("reasoning_log", []) + [entry]
            await sm.update_state(session_id, {"reasoning_log": reasoning_log})
            await _clear_countdown(session_id)
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
    """Add every AWAITING_APPROVAL session_id from a legacy in-memory dict
    into `candidates` (session_id -> market), first-writer-wins.

    P2-6: candidates map to a plain market string now, not a
    (market, session) snapshot pair — maybe_schedule_auto_approve no longer
    accepts a session argument at all, so there is nothing left to snapshot
    here; every candidate's actual state is re-resolved live from the SM
    right before it is scheduled (see rearm_awaiting_approvals's final
    loop)."""
    try:
        sessions = get_dict()
    except Exception as e:
        logger.error("autonomy_rearm_legacy_import_failed", market=market, error=str(e))
        return

    for session_id, session in sessions.items():
        try:
            if session.get("status") == SessionStatus.AWAITING_APPROVAL.value:
                candidates.setdefault(session_id, market)
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

    SESSION_SSOT_READS=False (kill switch): P2-6 declares this branch
    INVALID going forward (see the field's docstring in app/config.py) — it
    is left in place unchanged (P3-1 deletes it) so flipping the flag stays
    a pure config change, but it no longer restores any real fallback
    behavior. It still scans the legacy dicts (kr_stock_sessions /
    coin_sessions) for AWAITING_APPROVAL entries, but nothing has written to
    those dicts since P2 — so in practice this scan only ever adds
    candidates that either don't exist, or are also independently found via
    the SessionManager scan below (in which case the SM copy is skipped as a
    duplicate, since a legacy-scan candidate already claimed the session_id
    key). Even in the hypothetical case of a genuine legacy-only session,
    maybe_schedule_auto_approve (P2-6) now ALWAYS re-resolves the session via
    a live sm.get_session() call before doing anything — a session that was
    never created in the SM simply schedules nothing.

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
    candidates: dict[str, str] = {}  # session_id -> market

    if not get_settings().SESSION_SSOT_READS:
        # kill-switch fallback only — see the docstring above and
        # SESSION_SSOT_READS in app/config.py: this branch is declared
        # invalid since P2, kept unchanged until P3-1 deletes it.
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
            continue  # already have a candidate for this session_id
        if sm_session.market_type == MarketType.KIWOOM:
            market = "kiwoom"
        elif sm_session.market_type == MarketType.COIN:
            market = "coin"
        else:
            continue  # US stock stack removed (R2) — nothing to re-arm there
        candidates[session_id] = market

    if not candidates:
        return

    logger.info("autonomy_rearm_scan", candidate_count=len(candidates))

    # P2-6: re-fetch each candidate live right before scheduling it, rather
    # than acting on the scan-time sm_session/to_legacy_dict() snapshot above
    # — maybe_schedule_auto_approve does its own live lookup anyway, so the
    # awaiting/countdown pre-filter here should see the same freshest state.
    manager = await get_session_manager()
    for session_id, market in candidates.items():
        try:
            sm_session = await manager.get_session(session_id)
            if sm_session is None:
                continue  # legacy-only candidate never reached the SM (or vanished)
            state = sm_session.state or {}
            if not state.get("awaiting_approval"):
                continue
            if _has_future_auto_approve_at(state.get("auto_approve_at")):
                logger.info("autonomy_rearm_skip_live_countdown", session_id=session_id)
                continue
            await maybe_schedule_auto_approve(session_id, market)
        except Exception as e:
            logger.error("autonomy_rearm_session_failed", session_id=session_id, error=str(e))
