"""
Analysis Concurrency Control Module

Provides semaphore-based limiting for concurrent analysis sessions
to prevent LLM server overload and manage rate limits.

P3-2 (session SSOT consolidation): this module used to keep its own local
`active_sessions` dict copy of session state ("Store E") in addition to the
unified SessionManager (SM). That copy, its sync register/update/get/remove
wrappers, and a fallback semaphore that could get created disconnected from
SM's own were all retired -- SM is now the sole session store and the sole
owner of the concurrency semaphore. Everything below is a pure delegate to
`services.session_manager`.

Features:
- Maximum concurrent analysis limit (default: 3)
- Session cleanup for completed/expired sessions (delegates to SM)
"""

import structlog

from services.session_manager import (
    get_session_manager,
    run_session_cleanup_task,
    MAX_CONCURRENT_ANALYSES,
)

logger = structlog.get_logger()


# -------------------------------------------
# Semaphore for Concurrent Analysis Control
# -------------------------------------------
# The semaphore itself lives on the SessionManager singleton -- this module
# holds no state of its own.


async def acquire_analysis_slot(timeout: float = 60.0) -> bool:
    """
    Acquire an analysis slot from the semaphore.

    Args:
        timeout: Maximum time to wait for a slot (seconds)

    Returns:
        True if slot acquired, False if timeout
    """
    manager = await get_session_manager()
    return await manager.acquire_analysis_slot(timeout)


def release_analysis_slot() -> None:
    """Release an analysis slot back to the semaphore."""
    from services.session_manager import release_analysis_slot as sm_release_analysis_slot
    sm_release_analysis_slot()


def get_active_analysis_count() -> int:
    """Get the number of currently active analyses."""
    from services.session_manager import get_active_analysis_count as sm_get_active_analysis_count
    return sm_get_active_analysis_count()


def get_available_slots() -> int:
    """Get the number of available analysis slots."""
    from services.session_manager import get_available_slots as sm_get_available_slots
    return sm_get_available_slots()


# -------------------------------------------
# Session Cleanup (Background Task)
# -------------------------------------------

async def cleanup_old_sessions() -> None:
    """
    Periodically clean up completed/expired sessions.

    Should be run as a background task on server startup (see app/main.py's
    lifespan). Pure delegate to the unified SessionManager's own cleanup
    LOOP -- `services.session_manager.run_session_cleanup_task` -- not just
    its per-call cleanup method. SM is the sole session store AND the sole
    owner of the cleanup cadence.

    Final-review fix (session-ssot): this function used to run its OWN
    standalone `while True: ... cleanup_expired_sessions() ... sleep(300)`
    loop, duplicating (an older, stripped-down copy of) the cadence that
    P5-2 later built into `run_session_cleanup_task` -- the orphan sweeps
    (`_sweep_terminal_session_rows` / `_sweep_orphan_checkpoints`,
    `_ORPHAN_SWEEP_CYCLE_INTERVAL`-th cycle) only ever lived in
    `run_session_cleanup_task`, which nothing in production called: app/
    main.py's lifespan only ever schedules THIS function. That left the
    whole sweep backstop as dead code. Delegating here (rather than
    pointing main.py directly at `run_session_cleanup_task`) keeps main.py's
    import/wiring untouched and preserves this module's P3-2 pure-delegate
    shape -- a single cadence loop now runs in production, not two.
    """
    await run_session_cleanup_task()
