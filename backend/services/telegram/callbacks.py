"""
Telegram Approval/Reject Inline Buttons -- Callback Dispatch (TG-3) +
/auto Step-2 Confirm Callback (TG-4)

Handles the two callback_data prefixes `send_approval_request` (service.py)
attaches to every pending-approval message: `a:{session_id}:{pid8}`
(approve) and `r:{session_id}:{pid8}` (reject) -- see
docs/superpowers/specs/2026-07-17-telegram-twoway-design.md F1. Also
handles the `auto_confirm:{nonce}` callback_data prefix commands.py's
`handle_auto` attaches to /auto's step-2 confirm button -- see the
"/auto step-2 confirm callback (TG-4)" section near the bottom of this
file (spec F2; nonce+TTL is a later review fix, see commands.py's
module docstring for the scenario it closes).

Registered into services.telegram.receiver's callback registry at IMPORT
TIME via `register_callback(prefix, handler)`, mirroring commands.py's
command registration convention. `receiver.start_telegram_receiver()`
explicitly imports this module (`from . import callbacks`) right before it
drains the registries into the PTB Application, exactly like it already
does for commands.py -- import-time side-effect registration must be
structurally guaranteed, not incidental (TG-1 carryover finding).

Security (chat_id check + never-raise) is applied once, uniformly, by
receiver._wrap_callback at dispatch time -- this module must NOT re-check
chat_id itself. Handler order per spec F1 (chat_id already cleared by the
wrapper by the time a handler here runs):

  1. `await query.answer()` -- stop the client-side spinner immediately,
     before any lookup/network work.
  2. Re-parse callback_data into (session_id, pid8).
  3. Re-fetch the LIVE session from the SessionManager (the same source
     /operations' awaiting collection reads) and compare its CURRENT
     trade_proposal id against pid8 (prefix match -- pid8 is only the
     first 8 chars, see service.py's docstring for the 64-byte budget this
     is working around). A mismatch (session gone, or a reject-then-
     re-analyze cycle already replaced the proposal) means this button is
     stale -- edit the message to say so and stop; submit_decision is never
     called for a stale button.
  4. `approval.submit_decision(session_id, decision, actor="telegram",
     expected_proposal_id=<live id>)` -- the same direct-call pattern the
     autonomy injector already uses (_autonomy_injector.py:233). actor=
     "telegram" is pinned inside submit_decision's per-session lock too
     (approval.py's stale-proposal guard was widened from
     actor=='system' to actor in ('system','telegram') for exactly this
     caller) -- closing the TOCTOU window between this step's outside
     check and the lock actually being acquired.
  5. Edit the message to a "처리 중" placeholder (dropping the keyboard,
     `reply_markup=None`) -- SYNCHRONOUSLY, before any submit call -- so an
     edited message with no buttons can't be double-clicked into approving
     (or rejecting) the same proposal twice.
  6. Spawn `submit_decision` + the final result edit (success wording, the
     stood-down/stale wording, or an HTTPException's `.detail`) as a
     DETACHED `asyncio.create_task` and return immediately.

N2 review fix (기아 방지): PTB's receiver Application runs with the default
`max_concurrent_updates=1` -- every inbound update (button tap, `/halt`,
...) is processed ONE AT A TIME, sequentially, inline inside the update
loop. `submit_decision("rejected", ...)` resumes the re-analysis graph with
a REAL LLM call that can take minutes. Before this fix, step 4 above
awaited that call directly inside the handler -- which meant the entire
receiver was blocked for that whole duration: `/halt`, a DIFFERENT
session's reject tap, everything queued behind it. In the worst case a
second session's 60s auto-approve grace window expired and auto-approved
(placing a live order) *before* the queued human reject for THAT session
ever got processed -- the remote reject button, the whole point of this
arc, made itself powerless by being slow.

The fix: keep steps 1-3 (answer/parse/live-id validation) synchronous --
they're cheap SessionManager reads -- but detach the submit+edit into a
background task (`_submit_and_edit`, precedent: `_autonomy_injector.py`'s
own grace-window `asyncio.create_task`). The handler returns as soon as the
task is spawned, freeing PTB's single-update loop to process the next
update immediately. The synchronous placeholder edit (step 5) still closes
the double-click window that the old single final edit used to close, so
removing the keyboard promptly is preserved even though the actual
decision now completes asynchronously. The task runs entirely outside
`receiver._wrap_callback`'s try/except (that wrapper has already returned
by the time the task's body executes), so `_submit_and_edit` is its own
fully self-contained never-raise boundary -- any exception it doesn't
expect is caught, logged, and turned into a best-effort error edit rather
than becoming an unretrieved-task-exception warning that nobody sees.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from fastapi import HTTPException
from telegram import Update
from telegram.ext import ContextTypes

from services.telegram import commands
from services.telegram.receiver import register_callback

logger = structlog.get_logger()

_STALE_PROPOSAL_TEXT = "제안이 변경되어 처리할 수 없습니다."
_INVALID_REQUEST_TEXT = "잘못된 요청입니다."
_AUTO_CONFIRM_EXPIRED_TEXT = "확인이 만료되었습니다. /auto를 다시 실행하세요."
_PROCESSING_TEXT = "⏳ 처리 중…"

# N2 review fix: module-level reference set for detached
# submit_decision+edit tasks spawned by `_handle` (see its docstring and the
# module docstring's "N2 review fix" section). Without a strong reference an
# asyncio.Task can be garbage-collected mid-flight (a well-known asyncio
# footgun -- "Task was destroyed but it is pending"); each task's own
# done-callback discards it from this set once it finishes, mirroring the
# standard asyncio background-task idiom.
_PENDING_TASKS: set[asyncio.Task] = set()


async def _fetch_live_session(session_id: str):
    """Lazy-imported SessionManager lookup -- the deliberate mock-injection
    seam for tests (mirrors commands.py's `_fetch_*` convention). Lazy so
    this module (imported early by receiver.start_telegram_receiver) never
    forces services.session_manager to import ahead of when it's actually
    needed."""
    from services.session_manager import get_session_manager

    sm = await get_session_manager()
    return await sm.get_session(session_id)


async def _submit(session_id: str, decision: str, expected_proposal_id: str):
    """Direct call into approval.submit_decision, mirroring the autonomy
    injector's own precedent (_autonomy_injector.py:233 -- same event loop,
    same per-session lock). Lazy-imported: approval.py imports several
    app.api.routes.* modules that would otherwise create an import cycle if
    this were a module-level import inside services.telegram."""
    from app.api.routes import approval

    return await approval.submit_decision(
        session_id, decision, actor="telegram", expected_proposal_id=expected_proposal_id
    )


async def _edit(update: Update, text: str) -> None:
    """Best-effort edit of the original button message -- swallows its own
    failure (e.g. the message was already deleted) rather than letting a
    second exception escape a callback handler."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return
    try:
        await query.edit_message_text(text, reply_markup=None)
    except Exception as e:  # noqa: BLE001 -- best-effort UI feedback only
        logger.warning("telegram_callback_edit_failed", error=str(e))


def _parse(data: str) -> Optional[tuple[str, str]]:
    """`a:{session_id}:{pid8}` / `r:{session_id}:{pid8}` -> (session_id,
    pid8). A blank pid8 is refused here (not just left to fail the
    live-id prefix check downstream) -- an empty pid8 would make
    `live_id.startswith("")` vacuously true for ANY proposal, which would
    defeat the whole point of the pin."""
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None
    _, session_id, pid8 = parts
    if not session_id or not pid8:
        return None
    return session_id, pid8


async def _handle(update: Update, context: "ContextTypes.DEFAULT_TYPE", decision: str) -> None:
    query = update.callback_query
    await query.answer()

    parsed = _parse(query.data or "")
    if parsed is None:
        await _edit(update, _INVALID_REQUEST_TEXT)
        return
    session_id, pid8 = parsed

    sm_session = await _fetch_live_session(session_id)
    if sm_session is None:
        await _edit(update, _STALE_PROPOSAL_TEXT)
        return

    live_proposal_id = str((sm_session.state.get("trade_proposal") or {}).get("id") or "")
    if not live_proposal_id or not live_proposal_id.startswith(pid8):
        await _edit(update, _STALE_PROPOSAL_TEXT)
        return

    # N2 review fix: remove the keyboard SYNCHRONOUSLY right here, before
    # the (possibly minutes-long) submit is even spawned. The final result
    # edit below also drops the keyboard, but that edit now happens inside
    # a detached task -- without this placeholder edit there would be a
    # window, between this handler returning and the task's own edit
    # landing, where the original message still shows live buttons and a
    # double-tap could spawn a second submit_decision for the same
    # proposal.
    await _edit(update, _PROCESSING_TEXT)

    task = asyncio.create_task(_submit_and_edit(update, session_id, decision, live_proposal_id))
    _PENDING_TASKS.add(task)
    task.add_done_callback(_PENDING_TASKS.discard)
    # Return immediately -- PTB's single-update sequential loop
    # (max_concurrent_updates=1) is now free to process the next update
    # (another session's button, /halt, ...) without waiting for this
    # session's submit_decision to finish.


async def _submit_and_edit(
    update: Update, session_id: str, decision: str, live_proposal_id: str
) -> None:
    """Detached task body spawned by `_handle` (N2 review fix, see module
    docstring). Runs entirely outside `receiver._wrap_callback`'s
    try/except -- that wrapper has already returned by the time this task's
    body executes -- so this function is its own fully self-contained
    never-raise boundary: nothing here may propagate out uncaught, or it
    becomes a silent "Task exception was never retrieved" asyncio warning
    that no user-facing edit ever reflects.
    """
    try:
        result = await _submit(session_id, decision, live_proposal_id)
    except HTTPException as e:
        await _edit(update, f"오류: {e.detail}")
        return
    except Exception as e:  # noqa: BLE001 -- never let a detached task die unlogged/unreported
        logger.error(
            "telegram_callback_submit_task_failed",
            session_id=session_id,
            decision=decision,
            error=str(e),
        )
        await _edit(update, f"오류: {e}")
        return

    if isinstance(result, dict) and result.get("status") == "stood_down":
        await _edit(update, _STALE_PROPOSAL_TEXT)
        return

    label = "승인" if decision == "approved" else "거부"
    await _edit(update, f"{label} 처리되었습니다.")


async def _flush_pending_callback_tasks() -> None:
    """Test-only helper: await every currently in-flight `_submit_and_edit`
    task spawned by `_handle`. Production code never calls this -- PTB's
    own event loop simply lets these tasks run to completion on their own
    schedule, which is the entire point of detaching them (N2 review fix).
    Tests that assert on the FINAL edit/submit outcome (rather than just
    the fact that the handler returned early) need a deterministic point to
    await, since the task is not awaited by `_handle` itself."""
    pending = list(_PENDING_TASKS)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def handle_approve_callback(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    await _handle(update, context, "approved")


async def handle_reject_callback(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    await _handle(update, context, "rejected")


# -------------------------------------------
# /auto step-2 confirm callback (TG-4)
#
# Spec: docs/superpowers/specs/2026-07-17-telegram-twoway-design.md F2.
# Pairs with commands.py's `handle_auto`, which sends the confirm button
# after checking the master gate is ON but performs neither the mode write
# nor the rearm itself -- both happen here, only after the user taps
# confirm.
# -------------------------------------------

AUTO_CONFIRM_CALLBACK_PREFIX = commands.AUTO_CONFIRM_CALLBACK_PREFIX
"""Re-exported from `commands.py` (single source of truth) rather than a
second independent literal -- TG-4 review fix: the two files used to only
agree by string convention (`"auto_confirm"` declared separately in both
files), which was fine while the value was a dumb literal but stopped
being safe once real nonce STATE needed sharing (see this module's import
of `services.telegram.commands` above). No session_id/proposal to pin
here beyond the nonce itself: /auto resumes kiwoom's Autonomous|HITL
*mode*, not one proposal, so there is nothing proposal-shaped to
re-validate against a live session the way `a:`/`r:` do."""


async def _set_kiwoom_autonomous():
    """Direct call into settings.py's PUT handler -- mirrors commands.py's
    `_set_trading_mode` (same underlying storage write, same
    `TradingModeUpdate` validation). Kept as its own small duplicate rather
    than delegating to `commands._set_trading_mode` -- this module already
    imports `services.telegram.commands` at module level now (for the
    nonce functions, TG-4 review fix), so the import itself is no longer
    the reason to duplicate; it's simply that this call is a one-line,
    argument-free specialization ("kiwoom" + "autonomous" are always the
    values here) and not worth threading two extra literals through."""
    from app.api.routes.settings import TradingModeUpdate, set_trading_mode

    return await set_trading_mode(TradingModeUpdate(market="kiwoom", mode="autonomous"))


async def _rearm_awaiting_approvals():
    """Lazy import -- same import-cycle rationale as `_submit` above.
    Re-invokes the startup-only rearm pass so a session that reached
    awaiting_approval while HITL was in effect (and so never got a
    countdown scheduled by anyone -- producers only call
    `maybe_schedule_auto_approve` at the moment a session FIRST becomes
    awaiting) gets one now, without a server restart (spec F2 discovery
    finding: "startup 전용이라 이미 awaiting 세션에 카운트다운이 안
    걸림"). Idempotent/fail-closed exactly like a startup call -- see
    `rearm_awaiting_approvals`'s own docstring: a session already counting
    down is skipped, and any single-session error is logged, never
    raised."""
    from app.api.routes._autonomy_injector import rearm_awaiting_approvals

    await rearm_awaiting_approvals()


def _parse_auto_confirm_nonce(data: str) -> Optional[str]:
    """`auto_confirm:{nonce}` -> nonce, or None if `data` doesn't carry the
    prefix or the nonce part is blank (mirrors `_parse`'s own blank-part
    refusal above for the `a:`/`r:` buttons -- a blank nonce must never be
    treated as "no nonce to check", it must fail the match explicitly)."""
    if not data.startswith(AUTO_CONFIRM_CALLBACK_PREFIX):
        return None
    nonce = data[len(AUTO_CONFIRM_CALLBACK_PREFIX):]
    return nonce or None


async def handle_auto_confirm_callback(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    """/auto's step-2 confirm button (TG-4, spec F2; nonce+TTL TG-4 review
    fix) -- validates+consumes the button's single-use nonce FIRST
    (`commands.consume_auto_confirm_nonce`); only on success does it flip
    `trading_mode:kiwoom` to autonomous and re-arm every session already
    sitting in awaiting_approval, so one tap covers both future proposals
    and proposals that were already waiting when `/auto` was typed.

    A missing/mismatched/expired nonce -- stale button, superseded by a
    later /auto, or invalidated by an intervening /halt (the review's core
    scenario) -- edits the message to say the confirmation expired and
    performs NEITHER the mode write NOR the rearm: mode stays exactly
    whatever it already was.

    TG-3 x TG-4 interaction (intentional, per spec, on the SUCCESS path
    only): a session that only ever received a plain-HITL button (gate
    denied while kiwoom was hitl) has `TELEGRAM_NOTIFIED_PROPOSAL_KEY` set
    to `"{proposal_id}:0"`. Once `_rearm_awaiting_approvals()` re-schedules
    it under the now-autonomous mode, the gate verdict flips to allow and
    the composite dedup marker (`_autonomy_injector._notified_marker_value`)
    becomes `"{proposal_id}:1"` -- a mismatch against the stored `:0`
    value, so `maybe_schedule_auto_approve` sends a FRESH Telegram
    approval-request message with the live countdown rather than silently
    deduping it away. The operator who only ever saw a plain-HITL button
    for this proposal is told, correctly, that a 60s auto-approve
    countdown just started.
    """
    query = update.callback_query
    await query.answer()

    nonce = _parse_auto_confirm_nonce(query.data or "")
    if nonce is None or not commands.consume_auto_confirm_nonce(nonce):
        await _edit(update, _AUTO_CONFIRM_EXPIRED_TEXT)
        return

    await _set_kiwoom_autonomous()
    await _rearm_awaiting_approvals()

    await _edit(update, "✅ 자율 재개+대기 세션 재무장")


# -------------------------------------------
# Registration (import-time side effect -- see module docstring)
# -------------------------------------------

register_callback("a:", handle_approve_callback)
register_callback("r:", handle_reject_callback)
# 리뷰 픽스(Critical): mutate=True -- 이 콜백이 /auto의 실제 상태 변경(모드
# 플립)이 일어나는 지점이다. commands.handle_auto는 확인 버튼만 보내고
# _set_kiwoom_autonomous/_rearm_awaiting_approvals는 여기서만 호출되므로,
# receiver._wrap_command에 건 _MUTATE_COMMANDS 관문만으로는 이 경로가
# 막히지 않는다 -- 그룹 채팅에서 admin이 아닌 사용자가 admin이 띄운 버튼을
# 누르는 시나리오를 닫는다.
register_callback(AUTO_CONFIRM_CALLBACK_PREFIX, handle_auto_confirm_callback, mutate=True)
