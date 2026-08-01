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

from services.autonomy import check_autonomy
from services.session_manager import (
    KIND_ANALYSIS,
    MarketType,
    SessionStatus,
    get_session_manager,
)
from services.telegram import get_telegram_notifier

logger = structlog.get_logger()

# Fixed 60s grace window (user decision). Module constant so tests can patch it.
AUTONOMY_GRACE_SECONDS = 60.0

# TG-3 review fix (Critical-2, widened by review-fix-2): session-state key
# recording what a Telegram approval-request message last actually SENT for
# this session communicated. See `_send_approval_request_notification` /
# `rearm_awaiting_approvals` below -- without this, every
# rearm_awaiting_approvals() pass (which runs on every app startup, AFTER
# reconcile_stranded_sessions() has already unconditionally cleared
# auto_approve_at -- see session_manager.py's reconcile -- and so can never
# rely on `_has_future_auto_approve_at` to skip a still-awaiting session)
# would re-send a brand new button message for every AWAITING session on
# every restart.
#
# review-fix-2: the stored value is NOT the bare proposal id. It is a
# composite of (proposal_id, whether THAT send carried a countdown) via
# `_notified_marker_value` below. A bare proposal-id key was a second latent
# bug: an operator who received a plain-HITL button (gate denied, no
# countdown) for proposal p1, then flips AUTONOMY_ENABLED on and restarts
# (rearm's entire reason to exist), gets a gate-ALLOW re-schedule for the
# SAME p1 -- the 60s auto-approve grace task genuinely starts counting down
# -- but a proposal-id-only marker would still match and silently swallow
# the notification the operator needed to see the countdown (or hit
# REJECT) at all. Composing in `bool(auto_approve_at)` makes a HITL<->
# autonomous transition for the same proposal look like a change worth
# re-notifying for, while a restart with the SAME gate verdict for the SAME
# proposal still dedups exactly as before.
TELEGRAM_NOTIFIED_PROPOSAL_KEY = "telegram_notified_proposal_id"


def _notified_marker_value(proposal_id: str | None, auto_approve_at: str | None) -> str | None:
    """Composite dedup-marker value (review-fix-2): `None` when there is no
    proposal id to key on (caller must then always send, never dedup).
    Otherwise `"{proposal_id}:{0|1}"` -- the second field is whether THIS
    send carries a live countdown, so a gate-verdict flip (deny<->allow) for
    the exact same proposal always compares unequal to a previously-stored
    marker and triggers a fresh send, while a repeat with the identical
    verdict compares equal and dedups."""
    if proposal_id is None:
        return None
    return f"{proposal_id}:{int(bool(auto_approve_at))}"


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
    the grace task. A deny writes nothing schedule-related — the session is
    ordinary HITL — but the Telegram approval-request button (below) still
    fires either way.

    P2-6: no `session` argument — the session is resolved here via a live
    `sm.get_session(session_id)` lookup. A session that has vanished from
    the SM by the time this runs (removed, or never existed — e.g. a
    kill-switch-only legacy-dict candidate, see rearm_awaiting_approvals) is
    a no-op: nothing to schedule against.

    TG-3 (spec F1): this is also the de-facto dispatch point for the
    Telegram approve/reject inline-keyboard message — every caller of this
    function is a producer's awaiting-commit success path
    (kr_stocks/analysis.py's `_finalize_awaiting_transition` — coin's
    equivalent existed too before the 2026-08-01 Upbit removal) or
    approval.py's reject->re-analysis rearm, i.e. exactly the point where
    session_id + the SM-persisted
    trade_proposal.id are both confirmed and BOTH HITL and autonomous
    sessions are covered. The notify call below fires unconditionally
    (regardless of `decision.allowed`) — this replaces the old auto-only
    `_notify_pending` text heads-up, which only ever fired inside the
    gate-allowed branch and therefore never reached plain-HITL sessions.
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

        # Pin the proposal identity up front: used both by the grace task
        # below (approve only the exact proposal announced) and by the
        # Telegram dedup marker (Critical-2 fix, see
        # TELEGRAM_NOTIFIED_PROPOSAL_KEY) -- a single read instead of two
        # independent ones of the same field.
        proposal_id = (sm_session.state.get("trade_proposal") or {}).get("id")

        auto_approve_at: str | None = None

        if decision.allowed:
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

            asyncio.create_task(
                _auto_approve_after_grace(session_id, market, proposal_id)
            )
            logger.info(
                "auto_approve_scheduled",
                session_id=session_id,
                market=market,
                auto_approve_at=auto_approve_at,
            )
        else:
            logger.info(
                "auto_approve_not_scheduled",
                session_id=session_id,
                market=market,
                check=decision.check,
                reason=decision.reason,
            )

        await _send_approval_request_notification(
            session_id, market, sm_session.state, proposal_id, auto_approve_at
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


async def _send_approval_request_notification(
    session_id: str, market: str, state: dict, proposal_id: str | None,
    auto_approve_at: str | None,
) -> None:
    """Best-effort Telegram approve/reject inline-keyboard request (TG-3,
    spec F1) — replaces `_notify_pending`'s old auto-only text heads-up.
    Fires unconditionally for both HITL (`auto_approve_at is None`) and
    autonomous (`auto_approve_at` set) sessions; any failure here is
    swallowed so it can never affect the awaiting-commit/scheduling
    pipeline that already completed by the time this runs.

    TG-3 review fix (Critical-2, widened by review-fix-2): dedups on the
    composite `_notified_marker_value(proposal_id, auto_approve_at)` before
    sending -- NOT on the bare proposal id (see TELEGRAM_NOTIFIED_PROPOSAL_KEY's
    module comment for why a bare-id marker silently swallowed the one
    notification an operator most needs: the deny->allow transition on
    restart that starts a live 60s auto-approve countdown for a proposal
    they'd only ever seen as plain HITL).

    `maybe_schedule_auto_approve` is called far more than once per proposal
    in practice -- most notably `rearm_awaiting_approvals()` re-scanning
    every still-AWAITING session on EVERY app startup, since
    reconcile_stranded_sessions() always clears auto_approve_at first (see
    TELEGRAM_NOTIFIED_PROPOSAL_KEY's module-level comment), which defeats
    the `_has_future_auto_approve_at` skip in rearm. `state` here is the
    live SM session state (whatever the caller already resolved), so a
    marker written earlier in THIS process is visible immediately even
    before its debounced SQLite flush lands; a marker written by an EARLIER
    process is visible because it's part of the state_json a restart
    reloads. A session whose proposal has no `id` (defensive only -- every
    real trade_proposal carries one) always sends, since there is no safe
    identity to dedup on."""
    try:
        proposal = state.get("trade_proposal") or {}
        if not proposal:
            return
        marker_value = _notified_marker_value(proposal_id, auto_approve_at)
        if marker_value is not None and state.get(TELEGRAM_NOTIFIED_PROPOSAL_KEY) == marker_value:
            logger.info(
                "approval_request_notify_skipped_duplicate",
                session_id=session_id,
                proposal_id=proposal_id,
                marker_value=marker_value,
            )
            return
        notifier = await get_telegram_notifier()
        if notifier.is_ready:
            sent = await notifier.send_approval_request(session_id, market, proposal, auto_approve_at)
            # N1 review fix: only persist the dedup marker when the send
            # actually succeeded. `send_approval_request` never raises on a
            # Telegram-side failure (NetworkError/RetryAfter 429/...) -- it
            # returns `False` (service.py's `_send_message` swallows
            # TelegramError into a bool). Persisting the marker unconditionally
            # here meant a transient send failure (e.g. a 429 during a
            # startup rearm burst) still wrote the marker, and every later
            # `_send_approval_request_notification` call for the SAME
            # (proposal_id, auto_approve_at) then deduped on it forever --
            # the operator never gets a retry, the notification is lost for
            # good. Leaving the marker unwritten on failure means the next
            # call with the same marker_value (a later rearm pass, or the
            # next producer commit) is NOT deduped and retries the send.
            if sent:
                await _persist_notified_marker(session_id, marker_value)
            else:
                logger.warning(
                    "approval_request_notify_send_failed_marker_not_persisted",
                    session_id=session_id,
                    proposal_id=proposal_id,
                )
    except Exception as e:
        logger.warning("approval_request_notify_failed", session_id=session_id, error=str(e))


async def _persist_notified_marker(session_id: str, marker_value: str | None) -> None:
    """Best-effort dedup-marker write (Critical-2 fix; value format widened
    by review-fix-2, see `_notified_marker_value`). Deliberately its own
    try/except, separate from the send call above: a failure here must never
    be mistaken for (or interfere with) a send failure, and must never
    propagate -- the awaiting/scheduling flow this runs after has already
    completed. Worst case on a persist failure is exactly one further
    duplicate notification the next time this proposal is (re-)scheduled,
    never a missed one, which the task brief accepts explicitly."""
    if marker_value is None:
        return
    try:
        sm = await get_session_manager()
        await sm.update_state(session_id, {TELEGRAM_NOTIFIED_PROPOSAL_KEY: marker_value})
    except Exception as e:
        logger.warning(
            "telegram_notified_marker_persist_failed", session_id=session_id, error=str(e)
        )


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
    SessionManager (the durable source of truth) — legacy in-memory dicts
    were retired in P3-1; SM is the sole rearm source.

    Idempotent / fail-closed:
    - a session that already carries a FUTURE auto_approve_at is skipped —
      a live grace task is presumably already counting it down, so scheduling
      another would stack a duplicate timer.
    - maybe_schedule_auto_approve() itself pre-checks the gate; a deny (e.g.
      master gate still off, or the session's trading mode set to
      HITL-only) writes nothing and the session stays plain HITL.
    - any error scanning or scheduling a single session is logged and that
      session is skipped — never raised — so one bad session can't block
      startup or the rest of the pass.

    TG-3 review fix (Critical-2): this pass runs on EVERY startup, and
    reconcile_stranded_sessions() (called from inside SessionManager's own
    initialize(), which app/main.py's lifespan awaits via get_session_manager()
    BEFORE calling this function) unconditionally clears auto_approve_at on
    every session it loads — so the FUTURE-auto_approve_at skip above never
    actually fires for a session that survived a restart, and every prior
    restart used to re-send a brand new Telegram button for every AWAITING
    session. maybe_schedule_auto_approve()'s own TELEGRAM_NOTIFIED_PROPOSAL_KEY
    dedup (see its docstring) is what now makes repeated rearm passes for the
    SAME proposal safe. One accepted side effect: a session reconcile flipped
    BACK to AWAITING_APPROVAL from a stranded RUNNING shape (an unclean-exit
    recovery, not a normal restart of an already-awaiting session) never had
    a marker written for it in the first place, so it still gets a fresh
    button on this rearm pass — which is desirable, since that session's
    operator-facing state materially changed across the restart.
    """
    candidates: dict[str, str] = {}  # session_id -> market

    try:
        manager = await get_session_manager()
        # P4-1: kind='analysis' only -- a discussion (or other non-analysis
        # producer) session sharing the SM store must never be re-armed for
        # autonomous trade approval.
        sm_sessions = await manager.get_all_sessions(
            status=SessionStatus.AWAITING_APPROVAL, kind=KIND_ANALYSIS
        )
    except Exception as e:
        logger.error("autonomy_rearm_sm_scan_failed", error=str(e))
        sm_sessions = {}

    for session_id, sm_session in sm_sessions.items():
        if session_id in candidates:
            continue  # already have a candidate for this session_id
        if sm_session.market_type == MarketType.KIWOOM:
            market = "kiwoom"
        else:
            # 코인 스택 제거(2026-08-01) 이후 KIWOOM 외 시장은 재무장 대상
            # 아니다 -- 조용히 건너뛰면 "승인대기 세션이 재무장 스캔에서
            # 소리 없이 빠졌다"로만 보이므로 진단 가능하도록 경고 로그를
            # 남긴다(레거시 coin 체크포인트 등).
            logger.warning(
                "autonomy_rearm_skip_non_kiwoom_session",
                session_id=session_id,
                market_type=str(sm_session.market_type),
            )
            continue
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
