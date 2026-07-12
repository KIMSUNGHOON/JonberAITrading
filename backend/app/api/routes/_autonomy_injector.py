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

from services.autonomy import check_autonomy
from services.session_manager import mirror_session_state

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

        await approval.submit_decision(session_id, "approved", actor="system")
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
