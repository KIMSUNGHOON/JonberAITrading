"""P3-2: analysis_limiter semaphore regression pin.

Session SSOT consolidation P3-2 deleted analysis_limiter's local
`active_sessions` dict (Store E), its sync register/update/get/remove
wrappers, and a fallback semaphore that could get created disconnected from
SessionManager's (SM) own. After the refactor,
`acquire_analysis_slot`/`release_analysis_slot`/`get_active_analysis_count`/
`get_available_slots` are pure delegates to SM's single semaphore.

Both the KR (`app/api/routes/kr_stocks/analysis.py`) and coin
(`app/api/routes/coin/analysis.py`) analysis-start endpoints import these
functions directly from `app.core.analysis_limiter` and share the same
underlying SM semaphore -- spec section 1 row E calls out that this gate is
live for BOTH markets. This file pins:

  1) slot exhaustion -> the (N+1)th acquire times out (returns False, not an
     exception) -- matches the pre-refactor contract.
  2) release frees a slot for a subsequent acquire.
  3) a waiter blocked on a full semaphore is woken by a release, not just by
     its own timeout expiring -- pins the wait/notify semantics, not just
     the final True/False outcome.
  4) the semaphore is a single shared instance across markets: slots held
     "as KR" block a "coin" acquire, and releasing them unblocks it -- there
     is exactly one global limiter, not one per market.

Headless: fresh SessionManager on an isolated test SQLite db, following the
`sm` fixture convention in test_kr_producer_direct_write.py /
test_coin_producer_direct_write.py. MAX_CONCURRENT_ANALYSES is monkeypatched
small so exhaustion is cheap to trigger.
"""

import asyncio
import os

import pytest

import services.session_manager as sm_module
from services.session_manager import SessionManager

from app.core.analysis_limiter import (
    acquire_analysis_slot,
    get_active_analysis_count,
    get_available_slots,
    release_analysis_slot,
)

TEST_DB_PATH = "data/test_analysis_slots.db"
TEST_MAX_CONCURRENT = 2


@pytest.fixture
async def sm(monkeypatch):
    """Fresh SessionManager on a test db, installed as the process singleton,
    with a small MAX_CONCURRENT_ANALYSES so exhaustion tests stay fast."""
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    monkeypatch.setattr(sm_module, "DB_PATH", TEST_DB_PATH)
    monkeypatch.setattr(sm_module, "MAX_CONCURRENT_ANALYSES", TEST_MAX_CONCURRENT)
    manager = SessionManager()
    await manager.initialize()
    monkeypatch.setattr(sm_module, "_session_manager", manager)
    yield manager
    manager._sessions.clear()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


async def test_slots_exhaust_then_timeout(sm):
    """Acquiring all slots succeeds; the next acquire times out (False, not
    raised or hung) instead -- the timeout contract is unchanged by the
    refactor."""
    for _ in range(TEST_MAX_CONCURRENT):
        acquired = await acquire_analysis_slot(timeout=1.0)
        assert acquired is True

    assert get_available_slots() == 0
    assert get_active_analysis_count() == TEST_MAX_CONCURRENT

    timed_out = await acquire_analysis_slot(timeout=0.1)
    assert timed_out is False

    for _ in range(TEST_MAX_CONCURRENT):
        release_analysis_slot()


async def test_release_frees_slot_for_next_acquire(sm):
    """After exhaustion, a release makes exactly one slot available again --
    a subsequent acquire succeeds without waiting out any timeout."""
    for _ in range(TEST_MAX_CONCURRENT):
        assert await acquire_analysis_slot(timeout=1.0) is True

    assert get_available_slots() == 0

    release_analysis_slot()
    assert get_available_slots() == 1

    reacquired = await acquire_analysis_slot(timeout=1.0)
    assert reacquired is True
    assert get_available_slots() == 0

    for _ in range(TEST_MAX_CONCURRENT):
        release_analysis_slot()


async def test_concurrent_waiter_unblocks_on_release_not_just_timeout(sm):
    """A waiter blocked on a full semaphore is woken by a release (not just
    by its own timeout expiring)."""
    for _ in range(TEST_MAX_CONCURRENT):
        assert await acquire_analysis_slot(timeout=1.0) is True

    async def _release_soon():
        await asyncio.sleep(0.05)
        release_analysis_slot()

    release_task = asyncio.create_task(_release_soon())
    start = asyncio.get_running_loop().time()
    acquired = await acquire_analysis_slot(timeout=5.0)
    elapsed = asyncio.get_running_loop().time() - start

    assert acquired is True
    # Woken well before the 5s timeout would have elapsed.
    assert elapsed < 1.0

    await release_task

    for _ in range(TEST_MAX_CONCURRENT):
        release_analysis_slot()


async def test_semaphore_shared_across_kr_and_coin_markets(sm):
    """KR and coin analysis-start both call the SAME module-level
    acquire_analysis_slot/release_analysis_slot -- there is one global
    semaphore, not a per-market one. Exhausting slots "as KR" blocks a
    "coin" acquire; releasing the KR-held slots unblocks it."""
    # Simulate a KR session holding every slot.
    for _ in range(TEST_MAX_CONCURRENT):
        assert await acquire_analysis_slot(timeout=1.0) is True

    # A "coin" start, using the identical function, must see the gate as
    # fully saturated -- proving it isn't scoped per market.
    coin_acquired = await acquire_analysis_slot(timeout=0.1)
    assert coin_acquired is False

    # KR releases its slots; the coin acquire can now succeed.
    for _ in range(TEST_MAX_CONCURRENT):
        release_analysis_slot()

    coin_acquired = await acquire_analysis_slot(timeout=1.0)
    assert coin_acquired is True

    release_analysis_slot()
