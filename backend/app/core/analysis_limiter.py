"""
Analysis Concurrency Control Module

Provides semaphore-based limiting for concurrent analysis sessions
to prevent LLM server overload and manage rate limits.

Note: This module now delegates to the unified SessionManager service.
The old dict-based storage is deprecated in favor of the new system.

Features:
- Maximum concurrent analysis limit (default: 3)
- Session cleanup for completed/expired sessions
- Statistics tracking
- Unified session storage across all market types
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import structlog

# Import from unified session manager
from services.session_manager import (
    get_session_manager,
    SessionManager,
    MarketType,
    SessionStatus,
    MAX_CONCURRENT_ANALYSES,
    COMPLETED_SESSION_TTL,
    run_session_cleanup_task,
)

logger = structlog.get_logger()


# -------------------------------------------
# Backward Compatibility Layer
# -------------------------------------------
# These functions delegate to the unified SessionManager
# while maintaining the original API signatures.

# Legacy active_sessions dict for backward compatibility
# This is now a view into the unified SessionManager
active_sessions: Dict[str, Dict[str, Any]] = {}


def _sync_active_sessions() -> None:
    """
    Sync the legacy active_sessions dict with the SessionManager.

    This is called periodically to keep the legacy dict updated
    for any code still accessing it directly.
    """
    # Note: This is a transitional measure.
    # Eventually, all code should use the async SessionManager methods.
    pass


# -------------------------------------------
# Semaphore for Concurrent Analysis Control
# -------------------------------------------

_analysis_semaphore: Optional[asyncio.Semaphore] = None
_semaphore_lock = asyncio.Lock()


def _get_semaphore() -> asyncio.Semaphore:
    """Get or create the analysis semaphore (lazy initialization)."""
    global _analysis_semaphore
    if _analysis_semaphore is None:
        _analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)
    return _analysis_semaphore


async def acquire_analysis_slot(timeout: float = 60.0) -> bool:
    """
    Acquire an analysis slot from the semaphore.

    Args:
        timeout: Maximum time to wait for a slot (seconds)

    Returns:
        True if slot acquired, False if timeout
    """
    # Delegate to SessionManager
    manager = await get_session_manager()
    return await manager.acquire_analysis_slot(timeout)


def release_analysis_slot() -> None:
    """Release an analysis slot back to the semaphore."""
    # Delegate to SessionManager
    from services.session_manager import _session_manager
    if _session_manager:
        _session_manager.release_analysis_slot()
    else:
        # Fallback for cases where manager isn't initialized
        semaphore = _get_semaphore()
        semaphore.release()
        logger.debug("analysis_slot_released", available=get_available_slots())


def get_active_analysis_count() -> int:
    """Get the number of currently active analyses."""
    from services.session_manager import _session_manager
    if _session_manager:
        return _session_manager.get_active_analysis_count()
    # Fallback
    semaphore = _get_semaphore()
    return MAX_CONCURRENT_ANALYSES - semaphore._value


def get_available_slots() -> int:
    """Get the number of available analysis slots."""
    from services.session_manager import _session_manager
    if _session_manager:
        return _session_manager.get_available_slots()
    # Fallback
    semaphore = _get_semaphore()
    return semaphore._value


# -------------------------------------------
# Session Storage (Delegated to SessionManager)
# -------------------------------------------

def register_session(
    session_id: str,
    market_type: str,
    ticker: str,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register a new analysis session.

    Note: This is a synchronous wrapper. For new code, prefer the async
    version from services.session_manager.

    Args:
        session_id: Unique session identifier
        market_type: 'kiwoom', 'coin', or 'stock'
        ticker: Stock/coin code
        display_name: Human-readable name

    Returns:
        The session dict
    """
    # Create synchronously for backward compatibility
    session = {
        "session_id": session_id,
        "market_type": market_type,
        "ticker": ticker,
        "display_name": display_name or ticker,
        "status": "running",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "state": {},
        "error": None,
    }
    active_sessions[session_id] = session

    # Also register in the unified manager (async)
    # This will be done via the async version in routes
    logger.info(
        "session_registered",
        session_id=session_id,
        market_type=market_type,
        ticker=ticker,
    )
    return session


async def register_session_async(
    session_id: str,
    market_type: str,
    ticker: str,
    display_name: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Register a new analysis session asynchronously.

    This is the preferred method for registering sessions.
    """
    from services.session_manager import register_session as sm_register
    session_dict = await sm_register(session_id, market_type, ticker, display_name, **kwargs)

    # Keep legacy dict in sync
    active_sessions[session_id] = session_dict

    return session_dict


def update_session_status(
    session_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update session status (synchronous version for backward compatibility)."""
    if session_id in active_sessions:
        active_sessions[session_id]["status"] = status
        active_sessions[session_id]["updated_at"] = datetime.now(timezone.utc)
        if error:
            active_sessions[session_id]["error"] = error


async def update_session_status_async(
    session_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update session status asynchronously (preferred)."""
    from services.session_manager import update_session_status as sm_update
    await sm_update(session_id, status, error)

    # Keep legacy dict in sync
    if session_id in active_sessions:
        active_sessions[session_id]["status"] = status
        active_sessions[session_id]["updated_at"] = datetime.now(timezone.utc)
        if error:
            active_sessions[session_id]["error"] = error


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session by ID (synchronous version)."""
    return active_sessions.get(session_id)


async def get_session_async(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session by ID asynchronously (preferred)."""
    from services.session_manager import get_session as sm_get
    return await sm_get(session_id)


def remove_session(session_id: str) -> None:
    """Remove a session from active sessions (synchronous version)."""
    if session_id in active_sessions:
        del active_sessions[session_id]
        logger.info("session_removed", session_id=session_id)


async def remove_session_async(session_id: str) -> None:
    """Remove a session asynchronously (preferred)."""
    from services.session_manager import remove_session as sm_remove
    await sm_remove(session_id)

    # Keep legacy dict in sync
    if session_id in active_sessions:
        del active_sessions[session_id]


# -------------------------------------------
# Session Cleanup (Background Task)
# -------------------------------------------

async def cleanup_old_sessions() -> None:
    """
    Periodically clean up completed/expired sessions.

    Should be run as a background task on server startup.
    Removes sessions that:
    - Are completed or errored
    - Have been in that state for longer than COMPLETED_SESSION_TTL

    Note: This now delegates to the unified SessionManager cleanup.
    """
    logger.info("session_cleanup_task_started", ttl_hours=COMPLETED_SESSION_TTL.total_seconds() / 3600)

    while True:
        try:
            # Cleanup via SessionManager
            manager = await get_session_manager()
            await manager.cleanup_expired_sessions()

            # Also cleanup local legacy dict
            now = datetime.now(timezone.utc)
            expired_sessions = []

            for session_id, session in list(active_sessions.items()):
                if session.get("status") in ("completed", "error", "cancelled"):
                    created_at = session.get("created_at", now)
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at)
                    if now - created_at > COMPLETED_SESSION_TTL:
                        expired_sessions.append(session_id)

            for session_id in expired_sessions:
                del active_sessions[session_id]

            if expired_sessions:
                logger.debug(
                    "legacy_session_cleanup",
                    removed_count=len(expired_sessions),
                )

        except Exception as e:
            logger.error("session_cleanup_error", error=str(e))

        await asyncio.sleep(300)  # Run every 5 minutes


# -------------------------------------------
# Statistics
# -------------------------------------------

def get_analysis_stats() -> Dict[str, Any]:
    """Get analysis system statistics (synchronous version)."""
    active = get_active_analysis_count()
    available = get_available_slots()

    session_counts = {
        "running": 0,
        "completed": 0,
        "error": 0,
        "awaiting_approval": 0,
        "cancelled": 0,
    }

    for session in active_sessions.values():
        status = session.get("status", "unknown")
        if status in session_counts:
            session_counts[status] += 1

    return {
        "max_concurrent": MAX_CONCURRENT_ANALYSES,
        "active_slots": active,
        "available_slots": available,
        "total_sessions": len(active_sessions),
        "session_counts": session_counts,
    }


async def get_analysis_stats_async() -> Dict[str, Any]:
    """Get analysis system statistics asynchronously (preferred)."""
    from services.session_manager import get_analysis_stats as sm_stats
    return await sm_stats()
