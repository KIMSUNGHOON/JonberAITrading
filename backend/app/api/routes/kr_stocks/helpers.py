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


async def find_active_kr_session(stk_cd: str) -> Optional[dict]:
    """Return the first RUNNING/AWAITING_APPROVAL session for `stk_cd`, if any.

    P2-3: the KR producer (kr_stocks/analysis.py) writes ONLY to the
    SessionManager now -- so the SessionManager is the sole read source here
    too. `/analysis/start` itself no longer calls this: its dedup check is
    now folded into the atomic `SessionManager.create_session_if_no_active`
    reservation, which closes the check-then-create race directly instead of
    relying on a read here being followed by a separate synchronous write.
    This helper remains for any other caller that needs a plain "is this
    ticker active?" read (and for its own direct test coverage).
    """
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


def check_kiwoom_api_keys() -> None:
    """Check if Kiwoom API keys are configured (runtime or env)."""
    app_key = get_kiwoom_app_key()
    secret_key = get_kiwoom_secret_key()

    if not app_key or not secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kiwoom API keys not configured. Please configure in Settings.",
        )

