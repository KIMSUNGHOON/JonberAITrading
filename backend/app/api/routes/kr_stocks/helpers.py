"""
Korean Stock Route Helpers

Helper functions for Korean stock routes.
"""

from fastapi import HTTPException, status

from app.api.routes.settings import (
    get_kiwoom_app_key,
    get_kiwoom_secret_key,
)
from .constants import kr_stock_sessions


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
