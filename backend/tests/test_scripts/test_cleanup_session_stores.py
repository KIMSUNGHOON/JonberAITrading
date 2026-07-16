"""P5-3: 세션 저장소(sessions.db/storage.db) 1회성 정리 스크립트 테스트.

전부 tmp DB 기반 -- 이 파일은 실 DB(backend/data/sessions.db 612MB,
backend/data/storage.db 1GB)를 절대 참조하지 않는다. dry-run조차 실 DB
경로를 열지 않는다(스크립트 함수들은 호출자가 넘긴 경로만 사용하며, 기본값
DEFAULT_SESSIONS_DB/DEFAULT_STORAGE_DB는 이 테스트의 그 어떤 호출에도
전달되지 않는다).

스키마는 services/session_manager.py의 analysis_sessions CREATE TABLE과
services/storage_service.py의 checkpoints CREATE TABLE을 그대로 복사했다
(컬럼 이름·타입·제약이 실 DB와 어긋나면 스크립트의 SELECT/DELETE가 실 DB에서
깨질 수 있으므로, 정확히 동일해야 의미가 있는 테스트다).
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.cleanup_session_stores import (
    CHECKPOINT_ORPHAN_GRACE,
    _chunked,
    analyze_checkpoints,
    analyze_ghost_file,
    analyze_sessions_db,
    delete_orphan_checkpoints,
    delete_terminal_session_rows,
    main,
    run_cleanup,
)

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)

# -------------------------------------------
# Schema fixtures -- copied verbatim from the production CREATE TABLE
# statements (session_manager.py / storage_service.py).
# -------------------------------------------

_ANALYSIS_SESSIONS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS analysis_sessions (
        session_id TEXT PRIMARY KEY,
        market_type TEXT NOT NULL,
        ticker TEXT NOT NULL,
        display_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        error TEXT,
        last_node TEXT,
        state_json TEXT,
        stk_cd TEXT,
        stk_nm TEXT,
        market TEXT,
        korean_name TEXT,
        kind TEXT NOT NULL DEFAULT 'analysis'
    )
"""

_CHECKPOINTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id, thread_id)
    )
"""


def _make_sessions_db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(_ANALYSIS_SESSIONS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _make_storage_db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(_CHECKPOINTS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _insert_session(
    db_path: str,
    session_id: str,
    status: str,
    updated_at: datetime = NOW,
    market_type: str = "kiwoom",
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO analysis_sessions
            (session_id, market_type, ticker, display_name, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                market_type,
                "005930",
                "삼성전자",
                status,
                updated_at.isoformat(),
                updated_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_checkpoint(
    db_path: str, session_id: str, thread_id: str, created_at: datetime
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO checkpoints (session_id, thread_id, data, created_at) VALUES (?, ?, ?, ?)",
            (session_id, thread_id, "{}", created_at.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def _session_exists(db_path: str, session_id: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT 1 FROM analysis_sessions WHERE session_id = ?", (session_id,)
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _checkpoint_exists(db_path: str, session_id: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT 1 FROM checkpoints WHERE session_id = ?", (session_id,)
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


@pytest.fixture
def dbs(tmp_path):
    """Fresh tmp sessions.db + storage.db with the production schema, plus
    a tmp ghost-file path (not created -- individual tests create it when
    they need it). Returns (sessions_db, storage_db, ghost_file) as str
    paths."""
    sessions_db = str(tmp_path / "sessions.db")
    storage_db = str(tmp_path / "storage.db")
    ghost_file = str(tmp_path / "analysis_sessions.db")

    _make_sessions_db(sessions_db)
    _make_storage_db(storage_db)

    return sessions_db, storage_db, ghost_file


# -------------------------------------------
# _chunked (copied utility) -- quick sanity
# -------------------------------------------


def test_chunked_splits_and_preserves_order():
    items = [str(i) for i in range(7)]
    chunks = _chunked(items, 3)
    assert [len(c) for c in chunks] == [3, 3, 1]
    assert sum(chunks, []) == items


def test_chunked_empty():
    assert _chunked([], 500) == []


# -------------------------------------------
# 1) dry-run: counts correctly, deletes nothing
# -------------------------------------------


def test_dry_run_counts_correctly_and_deletes_nothing(dbs):
    sessions_db, storage_db, ghost_file = dbs

    _insert_session(sessions_db, "live-running", "running")
    _insert_session(sessions_db, "live-awaiting", "awaiting_approval")
    _insert_session(sessions_db, "t-completed", "completed")
    _insert_session(sessions_db, "t-error", "error")
    _insert_session(sessions_db, "t-cancelled", "cancelled")

    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(hours=1)
    recent = NOW - timedelta(hours=1)
    _insert_checkpoint(storage_db, "ghost-past-grace", "main", old)  # case (a), past grace
    _insert_checkpoint(storage_db, "ghost-fresh", "main", recent)  # case (a), within grace
    _insert_checkpoint(storage_db, "t-completed", "main", old)  # case (b), past grace
    _insert_checkpoint(storage_db, "live-running", "main", old)  # LIVE -- never touch

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=False,
        now=NOW,
    )

    assert summary.sessions.total_rows == 5
    assert set(summary.sessions.terminal_ids) == {"t-completed", "t-error", "t-cancelled"}
    assert summary.sessions.deleted == 0

    assert summary.checkpoints.total_checkpoint_sessions == 4
    assert set(summary.checkpoints.orphan_session_ids) == {"ghost-past-grace", "t-completed"}
    assert summary.checkpoints.deleted_sessions == 0

    # Nothing was actually deleted from either DB.
    for sid in ["live-running", "live-awaiting", "t-completed", "t-error", "t-cancelled"]:
        assert _session_exists(sessions_db, sid) is True
    for sid in ["ghost-past-grace", "ghost-fresh", "t-completed", "live-running"]:
        assert _checkpoint_exists(storage_db, sid) is True


def test_dry_run_reports_missing_files_without_raising(tmp_path):
    missing_sessions = str(tmp_path / "nope-sessions.db")
    missing_storage = str(tmp_path / "nope-storage.db")
    missing_ghost = str(tmp_path / "nope-ghost.db")

    summary = run_cleanup(
        sessions_db=missing_sessions,
        storage_db=missing_storage,
        ghost_file=missing_ghost,
        apply=False,
        now=NOW,
    )

    assert summary.sessions.file_exists is False
    assert summary.sessions.total_rows == 0
    assert summary.checkpoints.file_exists is False
    assert summary.ghost_file.exists is False


# -------------------------------------------
# 2) --apply deletes terminal rows only, preserves running/awaiting
# -------------------------------------------


def test_apply_deletes_terminal_rows_preserves_live(dbs):
    sessions_db, storage_db, ghost_file = dbs

    _insert_session(sessions_db, "live-running", "running")
    _insert_session(sessions_db, "live-awaiting", "awaiting_approval")
    _insert_session(sessions_db, "t-completed", "completed")
    _insert_session(sessions_db, "t-error", "error")
    _insert_session(sessions_db, "t-cancelled", "cancelled")

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        now=NOW,
    )

    assert summary.sessions.deleted == 3
    assert _session_exists(sessions_db, "live-running") is True
    assert _session_exists(sessions_db, "live-awaiting") is True
    assert _session_exists(sessions_db, "t-completed") is False
    assert _session_exists(sessions_db, "t-error") is False
    assert _session_exists(sessions_db, "t-cancelled") is False


def test_apply_deletes_terminal_row_ttl_independent(dbs):
    """Distinguishing feature vs session_manager._sweep_terminal_session_rows'
    periodic backstop (which respects COMPLETED_SESSION_TTL): this is a
    one-time backlog cleanup, so a row that went terminal MOMENTS ago (not
    just long-stale ones) is still a deletion candidate -- terminal is
    terminal, TTL is irrelevant here."""
    sessions_db, storage_db, ghost_file = dbs
    _insert_session(sessions_db, "just-completed", "completed", updated_at=NOW)

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        now=NOW,
    )

    assert summary.sessions.deleted == 1
    assert _session_exists(sessions_db, "just-completed") is False


def test_apply_with_small_chunk_size_deletes_all_terminal_rows(dbs):
    sessions_db, storage_db, ghost_file = dbs
    terminal_ids = [f"t-{i}" for i in range(5)]
    for sid in terminal_ids:
        _insert_session(sessions_db, sid, "completed")

    report = analyze_sessions_db(sessions_db)
    deleted = delete_terminal_session_rows(sessions_db, report.terminal_ids, chunk_size=2)

    assert deleted == 5
    for sid in terminal_ids:
        assert _session_exists(sessions_db, sid) is False


# -------------------------------------------
# 3) orphan checkpoints deleted; fresh + live preserved
# -------------------------------------------


def test_apply_deletes_orphan_checkpoints_preserves_fresh_and_live(dbs):
    sessions_db, storage_db, ghost_file = dbs

    _insert_session(sessions_db, "live-running", "running")
    _insert_session(sessions_db, "term-row", "completed")

    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(hours=1)
    recent = NOW - timedelta(hours=1)

    _insert_checkpoint(storage_db, "ghost-orphan", "main", old)  # (a) absent + past grace -> delete
    _insert_checkpoint(storage_db, "ghost-fresh", "main", recent)  # (a) absent + within grace -> keep
    _insert_checkpoint(storage_db, "term-row", "main", old)  # (b) terminal + past grace -> delete
    _insert_checkpoint(storage_db, "live-running", "main", old)  # LIVE -- keep, even though old

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        now=NOW,
    )

    assert summary.checkpoints.deleted_sessions == 2
    assert _checkpoint_exists(storage_db, "ghost-orphan") is False
    assert _checkpoint_exists(storage_db, "term-row") is False
    assert _checkpoint_exists(storage_db, "ghost-fresh") is True
    assert _checkpoint_exists(storage_db, "live-running") is True


def test_apply_preserves_live_checkpoint_no_matter_how_old(dbs):
    """Absolute invariant: RUNNING/AWAITING_APPROVAL checkpoints are never
    reclaimed regardless of age -- pinned separately from the mixed test
    above with an extreme age to make the invariant unmistakable."""
    sessions_db, storage_db, ghost_file = dbs
    _insert_session(sessions_db, "live-awaiting", "awaiting_approval")
    ancient = NOW - timedelta(days=365)
    _insert_checkpoint(storage_db, "live-awaiting", "main", ancient)

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        now=NOW,
    )

    assert summary.checkpoints.deleted_sessions == 0
    assert _checkpoint_exists(storage_db, "live-awaiting") is True


def test_orphan_checkpoint_grace_uses_max_created_at_across_threads(dbs):
    """A session_id with multiple checkpoint rows is graced against the
    MOST RECENT write across all of them -- mirrors
    session_manager._sweep_orphan_checkpoints' MAX(created_at) semantics."""
    sessions_db, storage_db, ghost_file = dbs
    stale = NOW - timedelta(days=5)
    recent = NOW - timedelta(hours=1)
    _insert_checkpoint(storage_db, "multi-1", "thread-a", stale)
    _insert_checkpoint(storage_db, "multi-1", "thread-b", recent)

    report = analyze_checkpoints(sessions_db, storage_db, now=NOW)

    assert "multi-1" not in report.orphan_session_ids


def test_delete_orphan_checkpoints_direct_with_small_chunk_size(dbs):
    sessions_db, storage_db, ghost_file = dbs
    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(hours=1)
    sids = [f"orphan-{i}" for i in range(5)]
    for sid in sids:
        _insert_checkpoint(storage_db, sid, "main", old)

    deleted = delete_orphan_checkpoints(storage_db, sids, chunk_size=2)

    assert deleted == 5
    for sid in sids:
        assert _checkpoint_exists(storage_db, sid) is False


# -------------------------------------------
# 4) ghost file (data/analysis_sessions.db)
# -------------------------------------------


def test_dry_run_reports_ghost_file_without_deleting(dbs):
    sessions_db, storage_db, ghost_file = dbs
    Path(ghost_file).touch()  # 0-byte ghost file

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=False,
        now=NOW,
    )

    assert summary.ghost_file.exists is True
    assert summary.ghost_file.size_bytes == 0
    assert summary.ghost_file.deleted is False
    assert Path(ghost_file).exists() is True


def test_apply_deletes_ghost_file(dbs):
    sessions_db, storage_db, ghost_file = dbs
    Path(ghost_file).touch()

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        now=NOW,
    )

    assert summary.ghost_file.deleted is True
    assert Path(ghost_file).exists() is False


def test_ghost_file_absent_is_reported_as_absent(dbs):
    sessions_db, storage_db, ghost_file = dbs
    assert Path(ghost_file).exists() is False

    report = analyze_ghost_file(ghost_file)

    assert report.exists is False
    assert report.size_bytes == 0


# -------------------------------------------
# 5) idempotent -- running twice is safe
# -------------------------------------------


def test_apply_twice_is_idempotent(dbs):
    sessions_db, storage_db, ghost_file = dbs

    _insert_session(sessions_db, "live-running", "running")
    _insert_session(sessions_db, "t-completed", "completed")
    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(hours=1)
    _insert_checkpoint(storage_db, "ghost-orphan", "main", old)
    _insert_checkpoint(storage_db, "live-running", "main", old)
    Path(ghost_file).touch()

    first = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        now=NOW,
    )
    assert first.sessions.deleted == 1
    assert first.checkpoints.deleted_sessions == 1
    assert first.ghost_file.deleted is True

    # Second run: nothing left to delete, must not raise, must report zeros.
    second = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        now=NOW,
    )
    assert second.sessions.deleted == 0
    assert second.sessions.terminal_ids == []
    assert second.checkpoints.deleted_sessions == 0
    assert second.checkpoints.orphan_session_ids == []
    assert second.ghost_file.exists is False
    assert second.ghost_file.deleted is False

    # Live data untouched across both runs.
    assert _session_exists(sessions_db, "live-running") is True
    assert _checkpoint_exists(storage_db, "live-running") is True


# -------------------------------------------
# main() CLI wiring -- separate from run_cleanup's logic (brief: "main()과
# 로직 분리 권장")
# -------------------------------------------


def test_main_defaults_to_dry_run(dbs, capsys):
    sessions_db, storage_db, ghost_file = dbs
    _insert_session(sessions_db, "t-completed", "completed")

    exit_code = main(
        [
            "--sessions-db", sessions_db,
            "--storage-db", storage_db,
            "--ghost-file", ghost_file,
        ]
    )

    assert exit_code == 0
    assert _session_exists(sessions_db, "t-completed") is True  # not deleted -- no --apply
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_main_apply_flag_deletes(dbs, capsys):
    sessions_db, storage_db, ghost_file = dbs
    _insert_session(sessions_db, "t-completed", "completed")

    exit_code = main(
        [
            "--sessions-db", sessions_db,
            "--storage-db", storage_db,
            "--ghost-file", ghost_file,
            "--apply",
        ]
    )

    assert exit_code == 0
    assert _session_exists(sessions_db, "t-completed") is False
    out = capsys.readouterr().out
    assert "APPLY 모드" in out


def test_main_never_touches_default_real_db_paths(dbs):
    """Sanity: main()'s default --sessions-db/--storage-db point at
    backend/data/*.db (the real, huge files) -- but every test in this
    module always passes explicit tmp paths, so those defaults are never
    actually opened here. This test just documents/pins that the defaults
    exist and point where expected, without ever invoking them."""
    from scripts.cleanup_session_stores import (
        DEFAULT_GHOST_FILE,
        DEFAULT_SESSIONS_DB,
        DEFAULT_STORAGE_DB,
    )

    assert str(DEFAULT_SESSIONS_DB).endswith("data/sessions.db")
    assert str(DEFAULT_STORAGE_DB).endswith("data/storage.db")
    assert str(DEFAULT_GHOST_FILE).endswith("data/analysis_sessions.db")


# -------------------------------------------
# Review fix (P5-3): --vacuum guard pinning + invariant-protection tests.
#
# Reviewer's Important: the `if apply and vacuum:` gate in run_cleanup was
# untested -- since this script is meant to eventually run against the real
# 612MB/1GB backlog, a future edit that loosens that gate (e.g. `if vacuum:`
# alone, accidentally running VACUUM on a dry-run) would only be discovered
# on the day it actually runs. The two tests below spy on `vacuum_db` (via
# monkeypatch on the module object, not a script-code change) to pin the
# gate's exact truth table.
#
# Minor #1: `_status_lookup`'s per-batch failure isolation -- when the
# sessions.db status query itself fails, the affected checkpoint session_ids
# must be treated as unresolved (never deleted), not defaulted to "absent"
# (which would incorrectly reclaim a checkpoint that might belong to a live
# RUNNING/AWAITING_APPROVAL session this run simply failed to observe).
#
# Minor #2: constant-drift guard -- this script intentionally re-derives
# TERMINAL_STATUSES/LIVE_STATUSES/CHECKPOINT_ORPHAN_GRACE as standalone
# literals (see the module docstring) rather than importing them from
# services/session_manager.py, so it can stay a sync-sqlite3-only tool. That
# duplication is only safe as long as the values stay identical -- this test
# asserts they do, so any future change to session_manager.py's values (or
# this script's copies) that lets them drift apart fails loudly here instead
# of silently reclaiming the wrong rows on the real backlog.
# -------------------------------------------


def test_vacuum_alone_without_apply_is_noop(dbs, monkeypatch):
    """--vacuum with no --apply must never call vacuum_db -- VACUUM is only
    ever meaningful/safe after an actual delete pass, and the review's
    concern is exactly a future loosening of the `if apply and vacuum:`
    gate that would run VACUUM even on a dry-run."""
    sessions_db, storage_db, ghost_file = dbs
    _insert_session(sessions_db, "t-completed", "completed")

    import scripts.cleanup_session_stores as cleanup_mod

    calls = []
    monkeypatch.setattr(cleanup_mod, "vacuum_db", lambda path: calls.append(path))

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=False,
        vacuum=True,
        now=NOW,
    )

    assert calls == []
    assert summary.vacuumed is False
    # Sanity: dry-run still didn't delete anything either -- vacuum=True
    # alone must not smuggle in apply behavior.
    assert _session_exists(sessions_db, "t-completed") is True


def test_apply_and_vacuum_runs_vacuum_on_both_dbs(dbs, monkeypatch):
    """--apply --vacuum together must call vacuum_db for BOTH sessions_db
    and storage_db, in that order, exactly once each."""
    sessions_db, storage_db, ghost_file = dbs
    _insert_session(sessions_db, "t-completed", "completed")

    import scripts.cleanup_session_stores as cleanup_mod

    calls = []
    monkeypatch.setattr(cleanup_mod, "vacuum_db", lambda path: calls.append(path))

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        vacuum=True,
        now=NOW,
    )

    assert calls == [sessions_db, storage_db]
    assert summary.vacuumed is True


def test_apply_without_vacuum_flag_never_calls_vacuum_db(dbs, monkeypatch):
    """Symmetric check: --apply alone (no --vacuum) must not run VACUUM --
    pins the other half of the gate's truth table."""
    sessions_db, storage_db, ghost_file = dbs
    _insert_session(sessions_db, "t-completed", "completed")

    import scripts.cleanup_session_stores as cleanup_mod

    calls = []
    monkeypatch.setattr(cleanup_mod, "vacuum_db", lambda path: calls.append(path))

    summary = run_cleanup(
        sessions_db=sessions_db,
        storage_db=storage_db,
        ghost_file=ghost_file,
        apply=True,
        vacuum=False,
        now=NOW,
    )

    assert calls == []
    assert summary.vacuumed is False


def test_status_lookup_batch_failure_is_conservative_skip(dbs, monkeypatch):
    """Minor #1: if the sessions.db status SELECT itself fails (e.g. lock
    contention, disk hiccup), the checkpoint session_ids in that batch must
    be treated as UNRESOLVED -- never deleted this run -- not defaulted to
    "absent from sessions.db" (which would otherwise look identical to a
    genuine orphan and get reclaimed). Simulated by wrapping the real
    sqlite3 connection so only the exact status-lookup SQL raises; every
    other query (including the checkpoints GROUP BY scan) passes through to
    the real connection untouched."""
    sessions_db, storage_db, ghost_file = dbs
    old = NOW - CHECKPOINT_ORPHAN_GRACE - timedelta(hours=1)
    _insert_checkpoint(storage_db, "would-be-orphan", "main", old)  # no SM row -- case (a) if resolved

    import scripts.cleanup_session_stores as cleanup_mod

    real_connect = cleanup_mod._connect

    class _FailingStatusLookupConn:
        def __init__(self, real_conn):
            self._real = real_conn

        def execute(self, sql, params=()):
            if "SELECT session_id, status FROM analysis_sessions" in sql:
                raise sqlite3.OperationalError("simulated status-lookup failure")
            return self._real.execute(sql, params)

        def commit(self):
            return self._real.commit()

        def close(self):
            return self._real.close()

    def _patched_connect(db_path):
        return _FailingStatusLookupConn(real_connect(db_path))

    monkeypatch.setattr(cleanup_mod, "_connect", _patched_connect)

    report = analyze_checkpoints(sessions_db, storage_db, now=NOW)

    # Conservative: the status lookup failed, so this candidate must NOT be
    # classified as an orphan (even though, if resolved, it would have been
    # one -- absent from sessions.db, past grace).
    assert report.orphan_session_ids == []
    assert report.total_checkpoint_sessions == 1  # the checkpoint scan itself still succeeded

    # And the delete path (driven by orphan_session_ids) leaves it intact.
    deleted = delete_orphan_checkpoints(storage_db, report.orphan_session_ids)
    assert deleted == 0
    assert _checkpoint_exists(storage_db, "would-be-orphan") is True


def test_constants_match_session_manager_production_values():
    """Minor #2: this script deliberately re-derives its own
    TERMINAL_STATUSES/LIVE_STATUSES/CHECKPOINT_ORPHAN_GRACE literals instead
    of importing services/session_manager.py (see the module docstring's
    duplication-vs-coupling rationale) -- pin that the copies have not
    drifted from the production values they mirror."""
    from services.session_manager import (
        CHECKPOINT_ORPHAN_GRACE as PROD_GRACE,
        SessionStatus,
        _TERMINAL_STATUSES as PROD_TERMINAL_STATUSES,
    )

    import scripts.cleanup_session_stores as cleanup_mod

    assert set(cleanup_mod.TERMINAL_STATUSES) == {s.value for s in PROD_TERMINAL_STATUSES}
    assert set(cleanup_mod.LIVE_STATUSES) == {
        SessionStatus.RUNNING.value,
        SessionStatus.AWAITING_APPROVAL.value,
    }
    # Every SessionStatus value is accounted for by exactly one of the two
    # sets -- guards against a future SessionStatus addition that neither
    # this script's TERMINAL_STATUSES/LIVE_STATUSES nor the production
    # _TERMINAL_STATUSES set was updated to cover.
    all_status_values = {s.value for s in SessionStatus}
    assert set(cleanup_mod.TERMINAL_STATUSES) | set(cleanup_mod.LIVE_STATUSES) == all_status_values
    assert cleanup_mod.CHECKPOINT_ORPHAN_GRACE == PROD_GRACE
