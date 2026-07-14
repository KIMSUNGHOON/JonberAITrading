"""
Korean Stock Route Helpers

Helper functions for Korean stock routes.
"""

from typing import Optional

from fastapi import HTTPException, status

from app.api.routes.settings import (
    get_kiwoom_app_key,
    get_kiwoom_secret_key,
)
from .constants import kr_stock_sessions

# Statuses that make a session count as "in flight" for ticker-level dedup
# (P4): a session still running or parked at a human/autonomy decision. Once
# a session settles (completed/error/cancelled) it no longer blocks a fresh
# analysis of the same stk_cd.
_ACTIVE_STATUSES = ("running", "awaiting_approval")


async def find_active_kr_session(stk_cd: str) -> Optional[dict]:
    """Return the first RUNNING/AWAITING_APPROVAL session for `stk_cd`, if any.

    Checks the legacy in-process `kr_stock_sessions` dict first (the
    authoritative read path within this process — status transitions are
    written there synchronously), then falls back to the SessionManager.
    The fallback matters right after a restart: `kr_stock_sessions` is wiped
    (plain in-memory dict), but a session that was genuinely parked at
    AWAITING_APPROVAL survives via SessionManager._load_active_sessions +
    reconcile_stranded_sessions (SQLite-backed) before any route has
    re-populated the legacy dict for it.

    Used to prevent `/analysis/start` from spawning a second concurrent
    analysis for a ticker that already has one in progress (P4 dedup) —
    ported from the `ticker in self._active_rooms` guard pattern in
    `services/agent_chat/coordinator.py`.
    """
    for session in kr_stock_sessions.values():
        if session.get("stk_cd") == stk_cd and session.get("status") in _ACTIVE_STATUSES:
            return session

    from services.session_manager import MarketType, SessionStatus, get_session_manager

    manager = await get_session_manager()
    for sm_status in (SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL):
        sessions = await manager.get_all_sessions(
            market_type=MarketType.KIWOOM, status=sm_status
        )
        for sm_session in sessions.values():
            if (sm_session.stk_cd or sm_session.ticker) == stk_cd:
                return sm_session.to_legacy_dict()

    return None


def get_kr_stock_session(session_id: str) -> dict:
    """Get session or raise 404."""
    session = kr_stock_sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Korean stock session {session_id} not found",
        )
    return session


def check_kiwoom_api_keys() -> None:
    """Check if Kiwoom API keys are configured (runtime or env)."""
    app_key = get_kiwoom_app_key()
    secret_key = get_kiwoom_secret_key()

    if not app_key or not secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kiwoom API keys not configured. Please configure in Settings.",
        )


def get_kr_stock_sessions() -> dict:
    """Get reference to Korean stock sessions (for WebSocket, approval routes)."""
    return kr_stock_sessions
