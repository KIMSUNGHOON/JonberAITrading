"""
Analysis Concurrency Control Module

Provides semaphore-based limiting for concurrent analysis sessions
to prevent LLM server overload and manage rate limits.

Features:
- Maximum concurrent analysis limit (default: 3)
- Session cleanup for completed/expired sessions
- Statistics tracking
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import structlog

logger = structlog.get_logger()

# -------------------------------------------
# Configuration
# -------------------------------------------

MAX_CONCURRENT_ANALYSES = 3
COMPLETED_SESSION_TTL = timedelta(hours=1)

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
    semaphore = _get_semaphore()
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
        logger.debug(
            "analysis_slot_acquired",
            available=get_available_slots(),
            active=get_active_analysis_count(),
        )
        return True
    except asyncio.TimeoutError:
        logger.warning(
            "analysis_slot_timeout",
            timeout=timeout,
            active=get_active_analysis_count(),
        )
        return False


def release_analysis_slot() -> None:
    """Release an analysis slot back to the semaphore."""
    semaphore = _get_semaphore()
    semaphore.release()
    logger.debug(
        "analysis_slot_released",
        available=get_available_slots(),
    )


def get_active_analysis_count() -> int:
    """Get the number of currently active analyses."""
    semaphore = _get_semaphore()
    # Semaphore value indicates available slots
    # Active = Max - Available
    return MAX_CONCURRENT_ANALYSES - semaphore._value


def get_available_slots() -> int:
    """Get the number of available analysis slots."""
    semaphore = _get_semaphore()
    return semaphore._value


# -------------------------------------------
# Session Storage (Unified across all markets)
# -------------------------------------------

active_sessions: Dict[str, Dict[str, Any]] = {}


def register_session(
    session_id: str,
    market_type: str,
    ticker: str,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register a new analysis session.

    Args:
        session_id: Unique session identifier
        market_type: 'kiwoom', 'coin', or 'stock'
        ticker: Stock/coin code
        display_name: Human-readable name

    Returns:
        The session dict
    """
    session = {
        "session_id": session_id,
        "market_type": market_type,
        "ticker": ticker,
        "display_name": display_name or ticker,
        "status": "running",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "state": {},
        "error": None,
    }
    active_sessions[session_id] = session
    logger.info(
        "session_registered",
        session_id=session_id,
        market_type=market_type,
        ticker=ticker,
    )
    return session


def update_session_status(
    session_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update session status."""
    if session_id in active_sessions:
        active_sessions[session_id]["status"] = status
        active_sessions[session_id]["updated_at"] = datetime.utcnow()
        if error:
            active_sessions[session_id]["error"] = error


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session by ID."""
    return active_sessions.get(session_id)


def remove_session(session_id: str) -> None:
    """Remove a session from active sessions."""
    if session_id in active_sessions:
        del active_sessions[session_id]
        logger.info("session_removed", session_id=session_id)


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
    """
    logger.info("session_cleanup_task_started", ttl_hours=COMPLETED_SESSION_TTL.total_seconds() / 3600)

    while True:
        try:
            now = datetime.utcnow()
            expired_sessions = []

            for session_id, session in list(active_sessions.items()):
                # Only cleanup completed or errored sessions
                if session.get("status") in ("completed", "error", "cancelled"):
                    created_at = session.get("created_at", now)
                    if now - created_at > COMPLETED_SESSION_TTL:
                        expired_sessions.append(session_id)

            for session_id in expired_sessions:
                del active_sessions[session_id]
                logger.debug("session_expired_cleanup", session_id=session_id)

            if expired_sessions:
                logger.info(
                    "session_cleanup_completed",
                    removed_count=len(expired_sessions),
                    remaining_count=len(active_sessions),
                )

        except Exception as e:
            logger.error("session_cleanup_error", error=str(e))

        await asyncio.sleep(300)  # Run every 5 minutes


# -------------------------------------------
# Statistics
# -------------------------------------------

def get_analysis_stats() -> Dict[str, Any]:
    """Get analysis system statistics."""
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
