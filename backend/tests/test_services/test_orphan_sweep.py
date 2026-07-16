"""P5-2: 고아 sweep — checkpoints + sessions.db terminal 행.

P5-1이 terminal 전이 시점에 체크포인트를 동기 삭제하는 best-effort 훅
(`_on_terminal_transition`)을 달았지만, 그 훅이 놓치는 두 가지 진행형 누수가
남는다:

1. **sessions.db terminal 행 누수** (spec §1.1-6 근본 원인, 612MB): 기존
   `cleanup_expired_sessions`는 `self._sessions`(인메모리) 순회로만 만료 행을
   찾는다. `_load_active_sessions`는 시작 시 RUNNING/AWAITING_APPROVAL 행만
   메모리에 올리므로, 어떤 세션이 terminal로 전이된 직후 프로세스가 재시작되면
   그 행은 이 프로세스의 `self._sessions`에 절대 로드되지 않는다 —
   `cleanup_expired_sessions`의 인메모리 순회가 원천적으로 볼 수 없는 행이
   되어 영구 잔존한다. `_sweep_terminal_session_rows`는 이를 SQLite 직접
   쿼리로 우회하는 백스톱이다.
2. **checkpoints 고아** (storage.db, 1GB): `_on_terminal_transition`은
   best-effort라 실패할 수 있고(디스크 문제, 락 경합), P5-1 이전에 terminal로
   전이된 세션들은 애초에 훅이 존재하지 않았을 때 전이됐다. `_sweep_orphan_
   checkpoints`는 checkpoints 테이블 자체를 훑어 소유 세션이 없거나
   terminal인 것을 24h 유예 후 회수한다.

두 sweep 모두 이 파일에서 실 DB를 절대 건드리지 않는다 — 전부 tmp DB
(monkeypatch DB_PATH / StorageService(db_path=tmp)) 기반.

절대 불변식: RUNNING/AWAITING_APPROVAL 세션의 행·체크포인트는 어떤 sweep도
절대 건드리지 않는다 (grace 유예와 무관하게, 아무리 오래돼도).
"""

import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from services.session_manager import (
    CHECKPOINT_ORPHAN_GRACE,
    COMPLETED_SESSION_TTL,
    AnalysisSession,
    MarketType,
    SessionManager,
    SessionStatus,
)
from services.storage_service import StorageService

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def _sess(sid, status, created=NOW, updated=None, market=MarketType.KIWOOM):
    return AnalysisSession(
        session_id=sid,
        market_type=market,
        ticker="005930",
        display_name="삼성전자",
        status=status,
        created_at=created,
        updated_at=updated or created,
        stk_cd="005930",
        stk_nm="삼성전자",
    )


@pytest.fixture
async def rig(tmp_path, monkeypatch):
    """Fresh SessionManager (tmp sessions.db) + real StorageService (tmp
    storage.db) wired together exactly like production
    (services.session_manager.get_storage_service patched to return the
    tmp-backed instance) -- but with delete_checkpoints wrapped so calls
    can be observed without losing the real SQL behavior underneath
    (unlike test_checkpoint_gc.py's _FakeStorage, these tests need
    get_checkpoint_session_ids' real GROUP BY/MAX SQL, not a stub).
    """
    sessions_db = str(tmp_path / "sessions.db")
    storage_db = str(tmp_path / "storage.db")

    monkeypatch.setattr("services.session_manager.DB_PATH", sessions_db)

    storage = StorageService(db_path=storage_db)
    await storage.initialize()

    delete_calls: list[str] = []
    _real_delete = storage.delete_checkpoints

    async def _spy_delete(session_id: str) -> bool:
        delete_calls.append(session_id)
        return await _real_delete(session_id)

    storage.delete_checkpoints = _spy_delete

    async def _fake_get_storage_service():
        return storage

    monkeypatch.setattr(
        "services.session_manager.get_storage_service", _fake_get_storage_service
    )

    manager = SessionManager()
    await manager.initialize()
    manager._delete_calls = delete_calls  # test-only handle

    yield manager, storage

    task = manager._flush_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    manager._sessions.clear()


async def _insert_checkpoint(
    storage: StorageService, session_id: str, thread_id: str, created_at: datetime
) -> None:
    """Insert a checkpoint row with an EXPLICIT created_at (save_checkpoint
    doesn't accept one -- it always takes CURRENT_TIMESTAMP -- so ageing a
    row for grace-period tests requires a raw INSERT)."""
    async with aiosqlite.connect(str(storage.db_path)) as db:
        await db.execute(
            "INSERT INTO checkpoints (session_id, thread_id, data, created_at) VALUES (?, ?, ?, ?)",
            (session_id, thread_id, "{}", created_at.strftime("%Y-%m-%d %H:%M:%S")),
        )
        await db.commit()


async def _checkpoint_exists(storage: StorageService, session_id: str) -> bool:
    threads = await storage.list_checkpoints(session_id)
    return len(threads) > 0


async def _session_row_exists(db_path: str, session_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT 1 FROM analysis_sessions WHERE session_id = ?", (session_id,)
        )
        return (await cur.fetchone()) is not None


# -------------------------------------------
# 1) _sweep_terminal_session_rows
# -------------------------------------------


async def test_sweep_terminal_rows_deletes_untracked_expired_row(rig):
    """Restart-simulation: a COMPLETED row sits in sessions.db with NO
    in-memory representative (never loaded -- _load_active_sessions only
    loads RUNNING/AWAITING_APPROVAL) and its TTL has elapsed. The sweep
    must delete the row via direct SQL and fire the checkpoint-GC hook for
    it, even though self._sessions never tracked it."""
    manager, storage = rig
    old_updated = NOW - COMPLETED_SESSION_TTL - timedelta(minutes=1)
    s = _sess("orphan-row-1", SessionStatus.COMPLETED, created=old_updated, updated=old_updated)
    await manager._save_session(s)  # SQLite only -- NOT manager._sessions

    assert "orphan-row-1" not in manager._sessions  # sanity: truly untracked

    deleted = await manager._sweep_terminal_session_rows(now=NOW)

    assert deleted == ["orphan-row-1"]
    from services import session_manager as sm_mod
    assert await _session_row_exists(sm_mod.DB_PATH, "orphan-row-1") is False
    assert manager._delete_calls == ["orphan-row-1"]  # checkpoint GC hook fired


async def test_sweep_terminal_rows_preserves_awaiting_and_running(rig):
    """Absolute invariant: RUNNING/AWAITING_APPROVAL rows are never
    touched by this sweep, no matter how stale updated_at looks."""
    manager, storage = rig
    ancient = NOW - timedelta(days=30)
    running = _sess("live-running", SessionStatus.RUNNING, created=ancient, updated=ancient)
    awaiting = _sess("live-awaiting", SessionStatus.AWAITING_APPROVAL, created=ancient, updated=ancient)
    await manager._save_session(running)
    await manager._save_session(awaiting)

    deleted = await manager._sweep_terminal_session_rows(now=NOW)

    assert deleted == []
    from services import session_manager as sm_mod
    assert await _session_row_exists(sm_mod.DB_PATH, "live-running") is True
    assert await _session_row_exists(sm_mod.DB_PATH, "live-awaiting") is True
    assert manager._delete_calls == []


async def test_sweep_terminal_rows_preserves_within_ttl(rig):
    """A terminal row whose TTL has NOT yet elapsed must survive -- this
    sweep reuses the exact same COMPLETED_SESSION_TTL boundary as the
    in-memory walk, not a shorter/longer one."""
    manager, storage = rig
    recent = NOW - (COMPLETED_SESSION_TTL / 2)
    s = _sess("fresh-terminal", SessionStatus.COMPLETED, created=recent, updated=recent)
    await manager._save_session(s)

    deleted = await manager._sweep_terminal_session_rows(now=NOW)

    assert deleted == []
    from services import session_manager as sm_mod
    assert await _session_row_exists(sm_mod.DB_PATH, "fresh-terminal") is True
    assert manager._delete_calls == []


async def test_sweep_terminal_rows_cleans_in_memory_if_present(rig):
    """Defensive: if a deleted session_id somehow IS still tracked in
    memory (e.g. a race with a concurrent in-process caller), the sweep
    must also drop it from self._sessions/self._dirty/self._subscribers so
    no dangling entry points at a row that no longer exists in SQLite."""
    manager, storage = rig
    old_updated = NOW - COMPLETED_SESSION_TTL - timedelta(hours=1)
    s = _sess("race-1", SessionStatus.ERROR, created=old_updated, updated=old_updated)
    await manager._save_session(s)
    manager._sessions["race-1"] = s
    manager._dirty.add("race-1")
    manager._subscribers["race-1"] = {asyncio.Queue()}

    deleted = await manager._sweep_terminal_session_rows(now=NOW)

    assert deleted == ["race-1"]
    assert "race-1" not in manager._sessions
    assert "race-1" not in manager._dirty
    assert "race-1" not in manager._subscribers


async def test_sweep_terminal_rows_multiple_statuses(rig):
    """All three terminal statuses (COMPLETED/ERROR/CANCELLED) are swept,
    not just COMPLETED."""
    manager, storage = rig
    old = NOW - COMPLETED_SESSION_TTL - timedelta(minutes=5)
    for sid, status in [
        ("t-completed", SessionStatus.COMPLETED),
        ("t-error", SessionStatus.ERROR),
        ("t-cancelled", SessionStatus.CANCELLED),
    ]:
        await manager._save_session(_sess(sid, status, created=old, updated=old))

    deleted = await manager._sweep_terminal_session_rows(now=NOW)

    assert set(deleted) == {"t-completed", "t-error", "t-cancelled"}


async def test_sweep_terminal_rows_failure_is_harmless(rig, monkeypatch):
    """A broken DB_PATH (simulating disk trouble) must not raise -- the
    sweep logs and returns an empty list; the next periodic cycle retries."""
    manager, storage = rig
    # Point DB_PATH at a directory (not a file) -- aiosqlite.connect fails
    # to open a database there, exercising the except branch.
    import tempfile

    with tempfile.TemporaryDirectory() as broken_dir:
        monkeypatch.setattr("services.session_manager.DB_PATH", broken_dir)
        deleted = await manager._sweep_terminal_session_rows(now=NOW)  # must not raise
        assert deleted == []


# -------------------------------------------
# 2) _sweep_orphan_checkpoints
# -------------------------------------------


async def test_orphan_checkpoint_no_sm_row_past_grace_deleted(rig):
    """Case (a): no analysis_sessions row at all for this session_id, and
    the checkpoint's own last-write time is past the 24h grace -- reclaim
    it."""
    manager, storage = rig
    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(hours=1)
    await _insert_checkpoint(storage, "ghost-1", "main", old)

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)

    assert deleted_count == 1
    assert await _checkpoint_exists(storage, "ghost-1") is False


async def test_orphan_checkpoint_no_sm_row_within_grace_preserved(rig):
    """Same case (a), but the checkpoint was written recently (< 24h ago)
    -- e.g. a graph is mid-flight and its SM row hasn't landed yet, or
    landed and was already reclaimed moments ago. Must survive."""
    manager, storage = rig
    recent = NOW - timedelta(hours=1)
    await _insert_checkpoint(storage, "ghost-2", "main", recent)

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)

    assert deleted_count == 0
    assert await _checkpoint_exists(storage, "ghost-2") is True


async def test_orphan_checkpoint_terminal_sm_row_past_grace_deleted(rig):
    """Case (b): analysis_sessions row exists and is terminal, checkpoint
    is past grace -- reclaim, regardless of the session row's own TTL
    state (that's _sweep_terminal_session_rows' job, not this sweep's)."""
    manager, storage = rig
    s = _sess("term-1", SessionStatus.COMPLETED, created=NOW, updated=NOW)  # fresh row, still terminal
    await manager._save_session(s)
    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(minutes=1)
    await _insert_checkpoint(storage, "term-1", "main", old)

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)

    assert deleted_count == 1
    assert await _checkpoint_exists(storage, "term-1") is False


async def test_orphan_checkpoint_terminal_sm_row_within_grace_preserved(rig):
    manager, storage = rig
    s = _sess("term-2", SessionStatus.CANCELLED, created=NOW, updated=NOW)
    await manager._save_session(s)
    recent = NOW - timedelta(hours=2)
    await _insert_checkpoint(storage, "term-2", "main", recent)

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)

    assert deleted_count == 0
    assert await _checkpoint_exists(storage, "term-2") is True


@pytest.mark.parametrize(
    "status", [SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL]
)
async def test_orphan_checkpoint_absolute_preserve_live_session(rig, status):
    """Absolute invariant: a RUNNING/AWAITING_APPROVAL session's checkpoint
    is NEVER reclaimed, even when its last-write timestamp is drastically
    past the 24h grace (e.g. a long-parked HITL approval)."""
    manager, storage = rig
    s = _sess("live-1", status, created=NOW, updated=NOW)
    await manager._save_session(s)
    ancient = NOW - timedelta(days=10)
    await _insert_checkpoint(storage, "live-1", "main", ancient)

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)

    assert deleted_count == 0
    assert await _checkpoint_exists(storage, "live-1") is True


async def test_orphan_checkpoint_grace_boundary_uses_latest_thread(rig):
    """A session_id with multiple checkpoint (thread_id) rows is graced
    against the MOST RECENT write across all of them (MAX(created_at)) --
    one stale thread_id row must not cause a still-active session's
    checkpoint set to be prematurely reclaimed."""
    manager, storage = rig
    stale = NOW - timedelta(days=5)
    recent = NOW - timedelta(hours=1)
    await _insert_checkpoint(storage, "multi-1", "thread-a", stale)
    await _insert_checkpoint(storage, "multi-1", "thread-b", recent)
    # No SM row at all for multi-1 (case a) -- MAX(created_at) must still
    # be `recent`, inside grace.

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)

    assert deleted_count == 0
    assert await _checkpoint_exists(storage, "multi-1") is True


async def test_orphan_checkpoint_sweep_list_failure_is_harmless(rig, monkeypatch):
    """storage.get_checkpoint_session_ids raising must not propagate --
    logged and swallowed, 0 returned."""
    manager, storage = rig

    async def _boom():
        raise RuntimeError("boom: simulated get_checkpoint_session_ids failure")

    monkeypatch.setattr(storage, "get_checkpoint_session_ids", _boom)

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)  # must not raise
    assert deleted_count == 0


async def test_orphan_checkpoint_sweep_status_lookup_failure_is_harmless(rig, monkeypatch):
    """A broken DB_PATH during the second query (status-by-session_id
    lookup, AFTER get_checkpoint_session_ids already succeeded) must not
    raise either -- distinct failure point from the list-failure test
    above."""
    manager, storage = rig
    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(hours=1)
    await _insert_checkpoint(storage, "orphan-x", "main", old)

    import tempfile

    with tempfile.TemporaryDirectory() as broken_dir:
        monkeypatch.setattr("services.session_manager.DB_PATH", broken_dir)
        deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)  # must not raise
        assert deleted_count == 0
    # Left untouched -- the sweep bailed out before reaching any delete.
    assert await _checkpoint_exists(storage, "orphan-x") is True


async def test_orphan_checkpoint_sweep_get_storage_service_failure_is_harmless(rig, monkeypatch):
    async def _raise_get_storage_service():
        raise RuntimeError("boom: simulated get_storage_service failure")

    monkeypatch.setattr(
        "services.session_manager.get_storage_service", _raise_get_storage_service
    )
    manager, storage = rig

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)  # must not raise
    assert deleted_count == 0


async def test_orphan_checkpoint_per_row_delete_failure_does_not_abort_sweep(rig, monkeypatch):
    """One session_id's delete_checkpoints failing must not prevent the
    other eligible orphans in the same sweep from being reclaimed."""
    manager, storage = rig
    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(hours=1)
    await _insert_checkpoint(storage, "bad-1", "main", old)
    await _insert_checkpoint(storage, "good-1", "main", old)

    _real_delete = storage.delete_checkpoints

    async def _flaky_delete(session_id: str) -> bool:
        if session_id == "bad-1":
            raise RuntimeError("boom: simulated delete failure")
        return await _real_delete(session_id)

    storage.delete_checkpoints = _flaky_delete

    deleted_count = await manager._sweep_orphan_checkpoints(now=NOW)  # must not raise

    assert deleted_count == 1  # only good-1 succeeded
    assert await _checkpoint_exists(storage, "good-1") is False
    assert await _checkpoint_exists(storage, "bad-1") is True  # left for next cycle


# -------------------------------------------
# 3) storage_service.get_checkpoint_session_ids (direct)
# -------------------------------------------


async def test_get_checkpoint_session_ids_groups_and_maxes(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "s.db"))
    await storage.initialize()
    t1 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 10, tzinfo=timezone.utc)
    await _insert_checkpoint(storage, "sess-a", "thread-1", t1)
    await _insert_checkpoint(storage, "sess-a", "thread-2", t2)
    await _insert_checkpoint(storage, "sess-b", "thread-1", t1)

    rows = await storage.get_checkpoint_session_ids()
    by_sid = dict(rows)

    assert set(by_sid.keys()) == {"sess-a", "sess-b"}
    assert by_sid["sess-a"].startswith("2026-07-10")  # MAX across sess-a's two rows
    assert by_sid["sess-b"].startswith("2026-07-01")


async def test_get_checkpoint_session_ids_empty_db(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "empty.db"))
    rows = await storage.get_checkpoint_session_ids()
    assert rows == []
