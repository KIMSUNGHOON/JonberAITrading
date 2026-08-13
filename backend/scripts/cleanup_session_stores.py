"""
1회성 세션 저장소 정리 스크립트 (session-ssot P5-3).

배경: sessions.db(analysis_sessions 테이블)가 612MB, storage.db(checkpoints
테이블)가 1GB까지 비대해진 기존 백로그가 있다. P5-2가 "진행형 누수"(앞으로
쌓이는 것)는 주기적 sweep으로 막았지만, 이미 쌓인 백로그 자체는 정리하지
않는다 -- 이 스크립트가 그 백로그를 정리하는 1회성 도구다.

⚠️ dry-run이 기본이다. `--apply`를 명시적으로 넘겨야만 실제 DELETE가
실행된다. 이 스크립트는 작성/테스트 시점(P5-3 태스크)에 실 DB
(backend/data/sessions.db, backend/data/storage.db)에 단 한 번도 실행되지
않았다 -- dry-run조차 실 DB 대상으로 실행하지 않았다(테스트는 전부 tmp
DB). 실행은 사용자의 명시적 승인을 받은 뒤 별도로 이뤄진다.

정리 대상 (session_manager.py/storage_service.py의 스키마·불변식과 동일):
  1. sessions.db의 analysis_sessions -- status가 completed/error/cancelled인
     행. P5-2의 주기적 sweep(_sweep_terminal_session_rows)과 달리 TTL을
     보지 않는다 -- terminal이면 무조건 삭제 대상이다(1회성 백로그 정리가
     목적이므로). running/awaiting_approval 행은 절대 건드리지 않는다.
  2. storage.db의 checkpoints -- session_id가 sessions.db에 없거나(고아)
     terminal인 것. RUNNING/AWAITING_APPROVAL 세션의 체크포인트는 아무리
     오래돼도 절대 삭제하지 않는다(session_manager._sweep_orphan_checkpoints
     와 동일한 절대 불변식). 24시간 유예(체크포인트 자신의
     MAX(created_at) 기준)를 둬서 막 시작된 세션의 체크포인트가
     sessions.db에 아직 반영되지 않았을 때 실수로 지우는 것을 막는다.
  3. data/analysis_sessions.db -- 0바이트 유령 파일(과거 오타/leftover로
     추정, 아무 코드도 참조하지 않음). 존재하면 --apply 시 삭제한다.

이 스크립트는 표준 라이브러리 sqlite3(동기)만 사용한다 -- 서버 프로세스와
완전히 별개로 동작하는 1회성 도구이므로 aiosqlite/asyncio 스택을 끌어올
필요가 없다. 서버가 실행 중일 수도 있다는 전제 하에 PRAGMA busy_timeout을
설정하지만, 그래도 서버를 정지한 뒤 실행하는 것을 권장한다(아래 경고 참고).

사용법 (backend/ 에서):
    # dry-run (기본, 아무것도 지우지 않음) -- 카운트/용량만 출력
    python scripts/cleanup_session_stores.py

    # 실제 삭제
    python scripts/cleanup_session_stores.py --apply

    # 삭제 후 VACUUM까지 실행 (파일 크기를 실제로 회수 -- 시간이 오래 걸릴
    # 수 있음, DB 파일 전체를 재작성하므로 612MB/1GB 규모에서는 수 분 소요
    # 가능)
    python scripts/cleanup_session_stores.py --apply --vacuum

    # 커스텀 DB 경로 (테스트/검증용)
    python scripts/cleanup_session_stores.py \
        --sessions-db /path/to/sessions.db \
        --storage-db /path/to/storage.db \
        --ghost-file /path/to/analysis_sessions.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

# -------------------------------------------
# Constants -- mirror services/session_manager.py's _TERMINAL_STATUSES /
# CHECKPOINT_ORPHAN_GRACE / _SWEEP_IN_CLAUSE_CHUNK_SIZE. Kept as separate
# literals (not imported) so this script stays a standalone sync-sqlite3
# tool that can run without importing the FastAPI app / aiosqlite stack --
# but the VALUES must stay in sync if the production module's ever change.
# -------------------------------------------
TERMINAL_STATUSES: Tuple[str, ...] = ("completed", "error", "cancelled")
LIVE_STATUSES: Tuple[str, ...] = ("running", "awaiting_approval")
CHECKPOINT_ORPHAN_GRACE = timedelta(hours=24)

# SQLite host-parameter cap safety margin -- same rationale as
# session_manager._SWEEP_IN_CLAUSE_CHUNK_SIZE (P5-2 review fix): an
# unbounded `IN (...)` clause can exceed SQLite's per-statement host
# parameter cap (999 pre-3.32.0, 32766 from 3.32.0 on) at backlog scale.
CHUNK_SIZE = 500

# busy_timeout (ms): the script may run while the server process still has
# the DB open (even though running it after stopping the server is the
# recommended path -- see the startup warning printed by run_cleanup).
BUSY_TIMEOUT_MS = 5000

_BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SESSIONS_DB = _BACKEND_DIR / "data" / "sessions.db"
DEFAULT_STORAGE_DB = _BACKEND_DIR / "data" / "storage.db"
DEFAULT_GHOST_FILE = _BACKEND_DIR / "data" / "analysis_sessions.db"


def _chunked(items: Sequence[str], size: int) -> List[List[str]]:
    """Split `items` into consecutive sub-lists of at most `size` each.
    Order-preserving, no dedup -- mirrors session_manager._chunked."""
    items = list(items)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_dt(value) -> Optional[datetime]:
    """Parse a SQLite TIMESTAMP string (either ISO-8601 with 'T', as
    written by services/session_manager.py's isoformat() calls, or the
    'YYYY-MM-DD HH:MM:SS' shape SQLite's CURRENT_TIMESTAMP default produces
    -- see storage_service.py's `checkpoints.created_at`) into an aware UTC
    datetime. Returns None if unparseable -- callers treat that as "can't
    establish grace elapsed", i.e. conservative skip, never delete.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            try:
                dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


# -------------------------------------------
# Report dataclasses
# -------------------------------------------


@dataclass
class SessionsReport:
    file_exists: bool = False
    file_size_bytes: int = 0
    total_rows: int = 0
    terminal_ids: List[str] = field(default_factory=list)
    deleted: int = 0

    @property
    def terminal_rows(self) -> int:
        return len(self.terminal_ids)


@dataclass
class CheckpointReport:
    file_exists: bool = False
    file_size_bytes: int = 0
    total_checkpoint_sessions: int = 0
    orphan_session_ids: List[str] = field(default_factory=list)
    deleted_sessions: int = 0


@dataclass
class GhostFileReport:
    path: str = ""
    exists: bool = False
    size_bytes: int = 0
    deleted: bool = False


@dataclass
class CleanupSummary:
    sessions: SessionsReport
    checkpoints: CheckpointReport
    ghost_file: GhostFileReport
    apply: bool = False
    vacuumed: bool = False


# -------------------------------------------
# 1) sessions.db -- terminal rows
# -------------------------------------------


def analyze_sessions_db(sessions_db: str) -> SessionsReport:
    """Read-only scan of analysis_sessions: total row count + every
    terminal (completed/error/cancelled) session_id. TTL-independent by
    design -- unlike session_manager._sweep_terminal_session_rows' periodic
    backstop, this is a one-time backlog sweep: any terminal row is a
    deletion candidate regardless of how recently it went terminal.
    running/awaiting_approval rows are never candidates and are not even
    read into terminal_ids.

    Never raises: a missing DB file or missing table is reported as zero
    rows, not an error (the file may legitimately not exist yet in a fresh
    environment, e.g. a test tmp_path with only storage.db seeded).
    """
    report = SessionsReport()
    if not os.path.exists(sessions_db):
        return report

    report.file_exists = True
    report.file_size_bytes = os.path.getsize(sessions_db)

    conn = _connect(sessions_db)
    try:
        try:
            cur = conn.execute("SELECT COUNT(*) FROM analysis_sessions")
            report.total_rows = cur.fetchone()[0]

            placeholders = ",".join("?" * len(TERMINAL_STATUSES))
            cur = conn.execute(
                f"SELECT session_id FROM analysis_sessions WHERE status IN ({placeholders})",
                TERMINAL_STATUSES,
            )
            report.terminal_ids = [row[0] for row in cur.fetchall()]
        except sqlite3.OperationalError:
            # analysis_sessions table doesn't exist -- treat as empty, not fatal.
            pass
    finally:
        conn.close()

    return report


def delete_terminal_session_rows(
    sessions_db: str,
    terminal_ids: Sequence[str],
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """DELETE the given session_ids from analysis_sessions, chunked (see
    CHUNK_SIZE's module comment). Each chunk commits independently -- a
    batch that raises is logged and skipped; a DELETE that never ran is
    always a safe no-op, so the next run of this script would simply retry
    it. Returns the count of rows actually deleted (only from batches that
    committed).
    """
    if not terminal_ids:
        return 0

    deleted = 0
    conn = _connect(sessions_db)
    try:
        for chunk in _chunked(terminal_ids, chunk_size):
            try:
                placeholders = ",".join("?" * len(chunk))
                conn.execute(
                    f"DELETE FROM analysis_sessions WHERE session_id IN ({placeholders})",
                    chunk,
                )
                conn.commit()
                deleted += len(chunk)
            except sqlite3.Error as e:
                print(f"  [WARN] sessions.db 배치({len(chunk)}행) 삭제 실패: {e}")
    finally:
        conn.close()

    return deleted


# -------------------------------------------
# 2) storage.db -- orphan checkpoints
# -------------------------------------------


def _status_lookup(
    sessions_db: str, candidate_ids: Sequence[str], chunk_size: int
) -> Tuple[Dict[str, str], Set[str]]:
    """Look up each candidate_id's sessions.db status, chunked.

    Returns (status_by_sid, unresolved_ids). A session_id missing from
    status_by_sid (and not in unresolved_ids) means "absent from
    sessions.db" (orphan case a). A chunk whose SELECT raises adds its
    session_ids to `unresolved_ids` instead of guessing -- mirrors
    session_manager._sweep_orphan_checkpoints' conservative invariant: a
    status lookup that failed must never be treated as "safe to reclaim",
    since among an unresolved batch could be a genuinely live
    RUNNING/AWAITING_APPROVAL session_id this sweep simply failed to
    observe this run.

    If sessions.db itself does not exist, every candidate is unresolvable
    via this path -- but that is NOT the same as "unresolved" in the
    conservative sense above: with no sessions.db at all, every checkpoint
    session_id is unambiguously case (a) (absent), so this returns an empty
    status map and an empty unresolved set (the caller's "absent from
    status_by_sid" branch already covers it correctly).
    """
    status_by_sid: Dict[str, str] = {}
    unresolved: Set[str] = set()
    if not os.path.exists(sessions_db):
        return status_by_sid, unresolved

    conn = _connect(sessions_db)
    try:
        for chunk in _chunked(candidate_ids, chunk_size):
            try:
                placeholders = ",".join("?" * len(chunk))
                cur = conn.execute(
                    f"SELECT session_id, status FROM analysis_sessions WHERE session_id IN ({placeholders})",
                    chunk,
                )
                for sid, status in cur.fetchall():
                    status_by_sid[sid] = status
            except sqlite3.Error as e:
                print(f"  [WARN] 상태 조회 배치({len(chunk)}개) 실패: {e}")
                unresolved.update(chunk)
    finally:
        conn.close()

    return status_by_sid, unresolved


def analyze_checkpoints(
    sessions_db: str,
    storage_db: str,
    now: Optional[datetime] = None,
    grace: timedelta = CHECKPOINT_ORPHAN_GRACE,
    chunk_size: int = CHUNK_SIZE,
) -> CheckpointReport:
    """Read-only scan of storage.db's checkpoints table, cross-referenced
    against sessions.db's analysis_sessions.

    A checkpoint session_id is an orphan candidate iff:
      (a) it's absent from analysis_sessions entirely, OR
      (b) its analysis_sessions row's status is terminal (completed/error/
          cancelled),
    AND its own last-write time (MAX(created_at) across all of that
    session_id's checkpoint rows) is older than `grace`.

    ABSOLUTE INVARIANT: a session_id whose analysis_sessions status is
    running/awaiting_approval is NEVER an orphan candidate, unconditionally
    -- regardless of grace, regardless of how old its checkpoints are. A
    session_id whose status lookup could not be resolved this run (see
    `_status_lookup`) is also excluded, conservatively.
    """
    now = now or datetime.now(timezone.utc)
    report = CheckpointReport()
    if not os.path.exists(storage_db):
        return report

    report.file_exists = True
    report.file_size_bytes = os.path.getsize(storage_db)

    conn = _connect(storage_db)
    try:
        try:
            cur = conn.execute(
                "SELECT session_id, MAX(created_at) FROM checkpoints GROUP BY session_id"
            )
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            rows = []
    finally:
        conn.close()

    report.total_checkpoint_sessions = len(rows)
    if not rows:
        return report

    last_written_by_sid = {sid: last for sid, last in rows}
    candidate_ids = list(last_written_by_sid.keys())
    status_by_sid, unresolved_ids = _status_lookup(sessions_db, candidate_ids, chunk_size)

    for sid in candidate_ids:
        if sid in unresolved_ids:
            continue  # status lookup failed this run -- conservative skip

        status = status_by_sid.get(sid)
        if status in LIVE_STATUSES:
            continue  # absolute invariant -- never touch a live session's checkpoint

        last_written = _parse_dt(last_written_by_sid[sid])
        if last_written is None:
            continue  # can't establish grace elapsed -- conservative skip
        if (now - last_written) < grace:
            continue  # within grace -- leave it even if orphaned/terminal

        report.orphan_session_ids.append(sid)

    return report


def delete_orphan_checkpoints(
    storage_db: str,
    session_ids: Sequence[str],
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """DELETE all checkpoint rows for the given (already-graced, already
    non-live-verified) session_ids, chunked. Each chunk commits
    independently. Returns the count of session_ids whose checkpoints were
    deleted (only from batches that committed)."""
    if not session_ids:
        return 0

    deleted = 0
    conn = _connect(storage_db)
    try:
        for chunk in _chunked(session_ids, chunk_size):
            try:
                placeholders = ",".join("?" * len(chunk))
                conn.execute(
                    f"DELETE FROM checkpoints WHERE session_id IN ({placeholders})",
                    chunk,
                )
                conn.commit()
                deleted += len(chunk)
            except sqlite3.Error as e:
                print(f"  [WARN] storage.db 배치({len(chunk)}개 세션) 삭제 실패: {e}")
    finally:
        conn.close()

    return deleted


# -------------------------------------------
# 3) ghost file (data/analysis_sessions.db, 0 bytes)
# -------------------------------------------


def analyze_ghost_file(path: str) -> GhostFileReport:
    report = GhostFileReport(path=str(path))
    if os.path.exists(path):
        report.exists = True
        report.size_bytes = os.path.getsize(path)
    return report


def delete_ghost_file(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError as e:
        print(f"  [WARN] 유령 파일 삭제 실패 {path}: {e}")
        return False


# -------------------------------------------
# 4) VACUUM (optional, --vacuum only, after --apply)
# -------------------------------------------


def vacuum_db(db_path: str) -> None:
    """Rewrites the DB file to actually reclaim freed pages -- a DELETE
    alone does not shrink the file on disk. No-op if the file doesn't
    exist."""
    if not os.path.exists(db_path):
        return
    conn = _connect(db_path)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


# -------------------------------------------
# Orchestration
# -------------------------------------------


def run_cleanup(
    sessions_db: str,
    storage_db: str,
    ghost_file: str,
    apply: bool = False,
    vacuum: bool = False,
    now: Optional[datetime] = None,
) -> CleanupSummary:
    """Runs one full dry-run/apply cleanup pass and prints a report to
    stdout. Never raises on a missing DB file (analyze_* helpers all treat
    that as "nothing to clean" for that store).

    Ordering note: the terminal-row deletion (sessions.db) runs BEFORE the
    checkpoint orphan scan (storage.db) when apply=True. This is
    deliberate and harmless: a checkpoint whose owning session_id was just
    deleted for being terminal simply reclassifies from orphan-case-(b)
    ("terminal row present") to orphan-case-(a) ("row absent") by the time
    analyze_checkpoints runs -- both are equally orphan-eligible subject to
    the same grace period, so the outcome is identical either way.
    """
    now = now or datetime.now(timezone.utc)

    print("=" * 70)
    print("세션 저장소 정리 스크립트" + (" -- APPLY 모드" if apply else " -- DRY RUN"))
    print("=" * 70)
    print("서버 정지 후 실행 권장 — busy timeout 설정(PRAGMA busy_timeout=5000ms)"
          "은 했지만, 동시 쓰기 중이면 그래도 실패할 수 있습니다.")
    print(f"sessions.db: {sessions_db}")
    print(f"storage.db:  {storage_db}")
    print()

    # 1) sessions.db terminal rows
    sess_report = analyze_sessions_db(sessions_db)
    if sess_report.file_exists:
        size_mb = sess_report.file_size_bytes / 1024 / 1024
        print(
            f"[sessions.db] 총 {sess_report.total_rows}행 중 terminal"
            f"(completed/error/cancelled) {sess_report.terminal_rows}행"
            f" (파일 크기 {size_mb:.1f}MB)"
        )
    else:
        print(f"[sessions.db] 파일 없음: {sessions_db}")

    if apply and sess_report.terminal_ids:
        sess_report.deleted = delete_terminal_session_rows(sessions_db, sess_report.terminal_ids)
        print(f"  -> {sess_report.deleted}행 삭제됨")

    # 2) storage.db orphan checkpoints
    ckpt_report = analyze_checkpoints(sessions_db, storage_db, now=now)
    if ckpt_report.file_exists:
        size_mb = ckpt_report.file_size_bytes / 1024 / 1024
        print(
            f"[storage.db] 체크포인트 보유 세션 {ckpt_report.total_checkpoint_sessions}개 중"
            f" 고아(24h 유예 경과) {len(ckpt_report.orphan_session_ids)}개"
            f" (파일 크기 {size_mb:.1f}MB)"
        )
    else:
        print(f"[storage.db] 파일 없음: {storage_db}")

    if apply and ckpt_report.orphan_session_ids:
        ckpt_report.deleted_sessions = delete_orphan_checkpoints(
            storage_db, ckpt_report.orphan_session_ids
        )
        print(f"  -> {ckpt_report.deleted_sessions}개 세션의 체크포인트 삭제됨")

    # 3) ghost file
    ghost_report = analyze_ghost_file(ghost_file)
    if ghost_report.exists:
        print(f"[유령 파일] {ghost_file} 존재 ({ghost_report.size_bytes} bytes)")
        if apply:
            ghost_report.deleted = delete_ghost_file(ghost_file)
            print(f"  -> 삭제됨: {ghost_report.deleted}")
    else:
        print(f"[유령 파일] {ghost_file} 없음")

    # 4) VACUUM
    vacuumed = False
    if apply and vacuum:
        print()
        print("VACUUM 실행 중 -- DB 크기에 따라 시간이 오래 걸릴 수 있습니다...")
        vacuum_db(sessions_db)
        vacuum_db(storage_db)
        vacuumed = True
        print("VACUUM 완료")

    print()
    if not apply:
        print("dry-run입니다 -- 실제로 아무것도 삭제되지 않았습니다. --apply를 추가하면 삭제를 실행합니다.")
    else:
        print("삭제 완료.")
        if not vacuum:
            print("파일 크기를 실제로 회수하려면 --vacuum을 추가해 다시 실행하세요.")

    return CleanupSummary(
        sessions=sess_report,
        checkpoints=ckpt_report,
        ghost_file=ghost_report,
        apply=apply,
        vacuumed=vacuumed,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="세션 저장소(sessions.db/storage.db) 1회성 정리 스크립트 (dry-run 기본)"
    )
    parser.add_argument("--sessions-db", default=str(DEFAULT_SESSIONS_DB), help="sessions.db 경로")
    parser.add_argument("--storage-db", default=str(DEFAULT_STORAGE_DB), help="storage.db 경로")
    parser.add_argument("--ghost-file", default=str(DEFAULT_GHOST_FILE), help="유령 파일 경로")
    parser.add_argument("--apply", action="store_true", help="실제로 삭제를 실행 (기본은 dry-run)")
    parser.add_argument(
        "--vacuum", action="store_true", help="--apply 뒤 VACUUM 실행 (파일 크기 실회수, 느릴 수 있음)"
    )
    args = parser.parse_args(argv)

    run_cleanup(
        sessions_db=args.sessions_db,
        storage_db=args.storage_db,
        ghost_file=args.ghost_file,
        apply=args.apply,
        vacuum=args.vacuum,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
