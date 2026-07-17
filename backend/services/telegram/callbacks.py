"""
Telegram Approval/Reject Inline Buttons -- Callback Dispatch (TG-3)

Handles the two callback_data prefixes `send_approval_request` (service.py)
attaches to every pending-approval message: `a:{session_id}:{pid8}`
(approve) and `r:{session_id}:{pid8}` (reject) -- see
docs/superpowers/specs/2026-07-17-telegram-twoway-design.md F1.

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
  5. Edit the original message with the result (success wording, the
     stood-down/stale wording, or an HTTPException's `.detail`) and DROP
     the keyboard (`reply_markup=None`) -- an edited message with no
     buttons can't be double-clicked into approving (or rejecting) the same
     proposal twice.
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import HTTPException
from telegram import Update
from telegram.ext import ContextTypes

from services.telegram.receiver import register_callback

logger = structlog.get_logger()

_STALE_PROPOSAL_TEXT = "제안이 변경되어 처리할 수 없습니다."
_INVALID_REQUEST_TEXT = "잘못된 요청입니다."


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

    try:
        result = await _submit(session_id, decision, live_proposal_id)
    except HTTPException as e:
        await _edit(update, f"오류: {e.detail}")
        return

    if isinstance(result, dict) and result.get("status") == "stood_down":
        await _edit(update, _STALE_PROPOSAL_TEXT)
        return

    label = "승인" if decision == "approved" else "거부"
    await _edit(update, f"{label} 처리되었습니다.")


async def handle_approve_callback(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    await _handle(update, context, "approved")


async def handle_reject_callback(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    await _handle(update, context, "rejected")


# -------------------------------------------
# Registration (import-time side effect -- see module docstring)
# -------------------------------------------

register_callback("a:", handle_approve_callback)
register_callback("r:", handle_reject_callback)
