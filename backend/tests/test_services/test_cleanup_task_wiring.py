"""Final-review fix (Critical 1, session-ssot): production sweep wiring pin.

Before this fix, `app/main.py`'s lifespan scheduled ONLY
`app.core.analysis_limiter.cleanup_old_sessions()` as its background sweep
task, and that function ran its own standalone `while True: cleanup_expired_
sessions(); sleep(300)` loop -- a stripped-down duplicate that pre-dated
P5-2. The cadence P5-2 actually built (a cycle counter that also fires
`_sweep_terminal_session_rows`/`_sweep_orphan_checkpoints` every
`_ORPHAN_SWEEP_CYCLE_INTERVAL`-th cycle) lived ONLY in
`services.session_manager.run_session_cleanup_task`, which nothing in
production ever called -- the whole orphan-sweep backstop was dead code.

The fix makes `cleanup_old_sessions` a pure delegate to
`run_session_cleanup_task` (services/session_manager.py), so main.py's
existing wiring (unchanged) now reaches the real cadence loop. These two
tests pin:

1. `run_session_cleanup_task` itself: cleanup_expired_sessions every cycle,
   both orphan sweeps every 12th cycle, 300s sleep between cycles (the
   cadence logic P5-2 wrote, now finally reachable from production).
2. `cleanup_old_sessions` delegates to (rather than duplicates) it -- the
   actual production wiring gap this Critical fixes.
"""
from unittest.mock import AsyncMock

import pytest

import app.core.analysis_limiter as al_mod
import services.session_manager as sm_mod

pytestmark = pytest.mark.asyncio


class _StopLoop(Exception):
    """Breaks the intentionally-infinite `while True` loop under test."""


async def test_run_session_cleanup_task_cadence(monkeypatch):
    """cleanup_expired_sessions runs every cycle; both orphan sweeps run
    only on every _ORPHAN_SWEEP_CYCLE_INTERVAL-th cycle (12); the loop
    sleeps 300s between cycles regardless of any single call's outcome."""
    manager = sm_mod.SessionManager()
    manager.cleanup_expired_sessions = AsyncMock(return_value=0)
    manager._sweep_terminal_session_rows = AsyncMock(return_value=0)
    manager._sweep_orphan_checkpoints = AsyncMock(return_value=0)

    async def _fake_get_session_manager():
        return manager

    monkeypatch.setattr(sm_mod, "get_session_manager", _fake_get_session_manager)

    # Run for 2 full sweep cycles + 1 (25 iterations) so both the 12th and
    # 24th cycle sweep firings are observed, then bail out via the fake
    # sleep -- the loop under test has no other exit.
    iterations = 2 * sm_mod._ORPHAN_SWEEP_CYCLE_INTERVAL + 1
    sleep_calls = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= iterations:
            raise _StopLoop()

    monkeypatch.setattr(sm_mod.asyncio, "sleep", _fake_sleep)

    with pytest.raises(_StopLoop):
        await sm_mod.run_session_cleanup_task()

    assert sleep_calls == [300] * iterations
    assert manager.cleanup_expired_sessions.await_count == iterations
    # Cycles 1..25 -> multiples of 12 are 12 and 24 -> exactly 2 firings.
    assert manager._sweep_terminal_session_rows.await_count == 2
    assert manager._sweep_orphan_checkpoints.await_count == 2


async def test_run_session_cleanup_task_survives_cleanup_failure(monkeypatch):
    """P5-2 review-fix invariant, re-pinned at the now-production-reachable
    entrypoint: a PERSISTENTLY failing cleanup_expired_sessions must not
    starve the orphan sweeps -- `cycle` advances and the sweeps run in
    their own try/except regardless of cleanup's own outcome."""
    manager = sm_mod.SessionManager()
    manager.cleanup_expired_sessions = AsyncMock(side_effect=RuntimeError("boom"))
    manager._sweep_terminal_session_rows = AsyncMock(return_value=0)
    manager._sweep_orphan_checkpoints = AsyncMock(return_value=0)

    async def _fake_get_session_manager():
        return manager

    monkeypatch.setattr(sm_mod, "get_session_manager", _fake_get_session_manager)

    iterations = sm_mod._ORPHAN_SWEEP_CYCLE_INTERVAL
    sleep_calls = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= iterations:
            raise _StopLoop()

    monkeypatch.setattr(sm_mod.asyncio, "sleep", _fake_sleep)

    with pytest.raises(_StopLoop):
        await sm_mod.run_session_cleanup_task()

    assert manager.cleanup_expired_sessions.await_count == iterations
    assert manager._sweep_terminal_session_rows.await_count == 1
    assert manager._sweep_orphan_checkpoints.await_count == 1


async def test_cleanup_old_sessions_delegates_to_sm_cadence_loop(monkeypatch):
    """The actual production-wiring pin: app/main.py's lifespan only ever
    calls analysis_limiter.cleanup_old_sessions() (import/call site
    unchanged by this fix). That function must reach
    services.session_manager.run_session_cleanup_task() -- the function
    P5-2's orphan-sweep cadence lives in -- instead of running its own
    separate loop that only ever touches cleanup_expired_sessions."""
    delegate = AsyncMock()
    monkeypatch.setattr(al_mod, "run_session_cleanup_task", delegate)

    await al_mod.cleanup_old_sessions()

    delegate.assert_awaited_once_with()
