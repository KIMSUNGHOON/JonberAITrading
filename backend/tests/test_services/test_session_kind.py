"""P4-1: SM `kind` column + kind-scoped active-collision checks.

Session SSOT 통합 Phase P4(Store A 완전 병합)의 첫 태스크. P4-2가 agent-chat
토론 세션을 SessionManager(SM)에 등록하기 시작하면, 분석 세션 전용 전역
스캔들(ticker dedup, /operations, /pending, 자율 rearm)이 토론 세션을
"활성 분석 세션"으로 오인해 흡수하는 오염이 생긴다. `kind` 컬럼은 그 오염을
선제 차단하기 위한 SM 레벨 계약이다:

- `AnalysisSession.kind` 기본값은 "analysis" -- 기존 세션/호출자는 전부
  byte-불변으로 남는다.
- `create_session`/`create_session_if_no_active`는 `kind`를 스레딩한다.
- `create_session_if_no_active`의 활성-충돌 검사는 SAME kind끼리만 비교한다
  -- 다른 kind는 같은 (market_type, ticker)라도 충돌하지 않는다.
- `get_all_sessions(kind=...)`는 kind 필터를 지원한다(None=전체, 하위호환).
- SQLite 스키마는 리포 관례 `_ensure_columns`(PRAGMA+ALTER) 패턴으로 이식됨
  -- 컬럼이 없던 구 DB 행은 NULL -> `_row_to_session`이 "analysis"로 폴백.

소비자별(kr_stocks/helpers, coin/helpers, trading.py /operations,
approval.py /pending, _autonomy_injector.py rearm) 필터 검증은 각자의 기존
테스트 파일에 추가되었다 -- 여기는 SM 자체의 계약만 검증한다.

픽스처는 tests/test_services/test_session_manager_p2.py의 tmp DB 패턴을
그대로 따른다(싱글턴 미오염, 테스트 전용 SQLite 파일).
"""

import asyncio
import os

import aiosqlite
import pytest

from services.session_manager import (
    AnalysisSession,
    KIND_ANALYSIS,
    MarketType,
    SessionManager,
    SessionStatus,
)

TEST_DB_PATH = "data/test_session_kind.db"


@pytest.fixture
def clean_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


async def _fake_get_storage_service():
    """P5-1: stand-in for services.storage_service.get_storage_service.

    update_status/remove_session/cleanup_expired_sessions now fire a
    checkpoint-GC hook that calls the REAL storage_service singleton unless
    patched -- that singleton points at the production
    backend/data/storage.db by default, which a live dev server may have
    open concurrently. Every fixture in this file patches it out.
    """
    class _NoopStorage:
        async def delete_checkpoints(self, session_id):
            return True
    return _NoopStorage()


@pytest.fixture
async def sm(clean_db, monkeypatch):
    """Fresh SessionManager on an isolated tmp DB -- no singleton involved."""
    monkeypatch.setattr("services.session_manager.DB_PATH", TEST_DB_PATH)
    monkeypatch.setattr(
        "services.session_manager.get_storage_service", _fake_get_storage_service
    )
    manager = SessionManager()
    await manager.initialize()
    yield manager
    # Same defensive flush-task cleanup as test_session_manager_p2.py's `sm`
    # fixture -- a debounced flush left pending past teardown leaks a task
    # into a closing event loop.
    task = manager._flush_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    manager._sessions.clear()


# -------------------------------------------
# 1) Dataclass defaults / to_legacy_dict
# -------------------------------------------


def test_analysis_session_default_kind_is_analysis():
    session = AnalysisSession(
        session_id="x",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
    )
    assert session.kind == KIND_ANALYSIS == "analysis"


def test_to_legacy_dict_includes_kind_additive():
    session = AnalysisSession(
        session_id="x",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        kind="discussion",
    )
    d = session.to_legacy_dict()
    assert d["kind"] == "discussion"
    # additive only -- existing legacy fields untouched
    assert d["stk_cd"] == "005930" or "stk_cd" not in d  # KIWOOM path sets stk_cd via ticker fallback
    assert d["session_id"] == "x"


# -------------------------------------------
# 2) create_session / create_session_if_no_active thread kind through
# -------------------------------------------


@pytest.mark.asyncio
async def test_create_session_defaults_kind_to_analysis(sm):
    session = await sm.create_session(
        session_id="p41-default",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
    )
    assert session.kind == "analysis"
    fetched = await sm.get_session("p41-default")
    assert fetched.kind == "analysis"


@pytest.mark.asyncio
async def test_create_session_accepts_explicit_kind(sm):
    session = await sm.create_session(
        session_id="p41-explicit",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        kind="discussion",
    )
    assert session.kind == "discussion"
    fetched = await sm.get_session("p41-explicit")
    assert fetched.kind == "discussion"


@pytest.mark.asyncio
async def test_reservation_different_kind_does_not_collide(sm):
    """Same (market_type, ticker), different kind -- not a collision. This is
    the T4-2 pollution guard: a discussion reservation for a ticker must
    never be blocked by (or block) an analysis reservation for that same
    ticker, and vice versa."""
    created1, existing1 = await sm.create_session_if_no_active(
        "p41-kind-analysis", MarketType.KIWOOM, "005930", "삼성전자", kind="analysis"
    )
    created2, existing2 = await sm.create_session_if_no_active(
        "p41-kind-discussion", MarketType.KIWOOM, "005930", "삼성전자", kind="discussion"
    )
    assert existing1 is None and existing2 is None
    assert created1 is not None and created2 is not None
    assert created1.kind == "analysis"
    assert created2.kind == "discussion"


@pytest.mark.asyncio
async def test_reservation_same_kind_still_collides(sm):
    """Regression guard: the kind check must NARROW the existing
    ticker-collision guard, not remove it -- two reservations of the SAME
    kind for the same (market_type, ticker) must still collide exactly as
    before this task."""
    created1, existing1 = await sm.create_session_if_no_active(
        "p41-dup-a", MarketType.KIWOOM, "005930", "삼성전자", kind="discussion"
    )
    created2, existing2 = await sm.create_session_if_no_active(
        "p41-dup-b", MarketType.KIWOOM, "005930", "삼성전자", kind="discussion"
    )
    assert created1 is not None and existing1 is None
    assert created2 is None and existing2 is not None
    assert existing2.session_id == created1.session_id


@pytest.mark.asyncio
async def test_reservation_defaults_both_to_analysis_still_collide(sm):
    """Byte-compat guard: two callers that DON'T pass `kind` at all (today's
    only real call sites) still collide with each other exactly as before
    this task -- both default to kind='analysis'."""
    created1, existing1 = await sm.create_session_if_no_active(
        "p41-legacy-a", MarketType.KIWOOM, "005930", "삼성전자"
    )
    created2, existing2 = await sm.create_session_if_no_active(
        "p41-legacy-b", MarketType.KIWOOM, "005930", "삼성전자"
    )
    assert created1 is not None and existing1 is None
    assert created2 is None and existing2 is not None
    assert existing2.session_id == created1.session_id


# -------------------------------------------
# 3) get_all_sessions kind filter
# -------------------------------------------


@pytest.mark.asyncio
async def test_get_all_sessions_kind_filter(sm):
    await sm.create_session("p41-a", MarketType.KIWOOM, "005930", "삼성전자")
    await sm.create_session(
        "p41-b", MarketType.KIWOOM, "000660", "SK하이닉스", kind="discussion"
    )

    analysis_only = await sm.get_all_sessions(kind="analysis")
    assert set(analysis_only.keys()) == {"p41-a"}

    discussion_only = await sm.get_all_sessions(kind="discussion")
    assert set(discussion_only.keys()) == {"p41-b"}

    unfiltered = await sm.get_all_sessions()
    assert set(unfiltered.keys()) == {"p41-a", "p41-b"}


@pytest.mark.asyncio
async def test_get_all_sessions_kind_none_is_unfiltered_backcompat(sm):
    """kind=None (the default) must behave exactly as before this task --
    every existing caller that doesn't pass kind keeps seeing every kind."""
    await sm.create_session("p41-c1", MarketType.KIWOOM, "005930", "삼성전자")
    await sm.create_session(
        "p41-c2", MarketType.KIWOOM, "000660", "SK하이닉스", kind="discussion"
    )
    all_sessions = await sm.get_all_sessions()
    assert set(all_sessions.keys()) == {"p41-c1", "p41-c2"}


# -------------------------------------------
# 4) SQLite persistence: kind round-trips, old NULL rows fall back
# -------------------------------------------


@pytest.mark.asyncio
async def test_kind_persists_and_round_trips_via_row_conversion(sm):
    """The exact path a restart's _load_active_sessions() exercises:
    _save_session writes `kind`, a raw row read back and passed through
    _row_to_session() reproduces it."""
    await sm.create_session(
        "p41-persist", MarketType.KIWOOM, "005930", "삼성전자", kind="discussion"
    )

    async with aiosqlite.connect(TEST_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM analysis_sessions WHERE session_id = ?",
            ("p41-persist",),
        ) as cursor:
            row = await cursor.fetchone()

    assert row["kind"] == "discussion"
    reloaded = sm._row_to_session(row)
    assert reloaded.kind == "discussion"


@pytest.mark.asyncio
async def test_row_to_session_null_kind_falls_back_to_analysis(clean_db, monkeypatch):
    """Simulates a row written before this task existed: `kind` is
    ALTER-added as nullable (see _ensure_columns) and old rows are never
    backfilled -- they land NULL. _row_to_session must fall back to
    KIND_ANALYSIS rather than propagating NULL/None.

    Builds the pre-P4-1 table shape (no `kind` column at all) by hand and
    inserts a row directly -- bypasses _save_session entirely (which would
    always supply the "analysis" default) and exercises _ensure_columns in
    isolation, without a full initialize() call's reconcile/resave pass
    (which would otherwise overwrite the NULL back to 'analysis' before this
    test could observe it)."""
    monkeypatch.setattr("services.session_manager.DB_PATH", TEST_DB_PATH)

    async with aiosqlite.connect(TEST_DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE analysis_sessions (
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
                korean_name TEXT
            )
            """
        )
        await db.execute(
            """
            INSERT INTO analysis_sessions
            (session_id, market_type, ticker, display_name, status,
             created_at, updated_at, state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "p41-null-kind", "kiwoom", "005930", "삼성전자", "running",
                "2026-07-16T00:00:00+00:00", "2026-07-16T00:00:00+00:00", "{}",
            ),
        )
        await db.commit()

        # Exercise the ALTER-migration helper directly, mirroring what
        # initialize() does on a pre-existing DB file.
        await SessionManager._ensure_columns(db, "analysis_sessions", {"kind": "TEXT"})
        await db.commit()

        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM analysis_sessions WHERE session_id = ?",
            ("p41-null-kind",),
        ) as cursor:
            row = await cursor.fetchone()

    assert row["kind"] is None  # confirm the simulated pre-P4-1 shape

    manager = SessionManager()  # pure conversion -- no initialize() needed
    reloaded = manager._row_to_session(row)
    assert reloaded.kind == "analysis"


@pytest.mark.asyncio
async def test_ensure_columns_adds_kind_to_pre_existing_table(clean_db, monkeypatch):
    """The repo-convention `_ensure_columns` ALTER path: a DB file created
    BEFORE this task (table exists, no `kind` column at all -- not just a
    NULL value) must gain the column transparently on the next
    initialize(), matching services/storage_service.py's ALTER-migration
    contract."""
    monkeypatch.setattr("services.session_manager.DB_PATH", TEST_DB_PATH)

    # Simulate a pre-P4-1 DB file: create the OLD table shape by hand
    # (mirrors the CREATE TABLE this project shipped before this task, minus
    # the `kind` column).
    async with aiosqlite.connect(TEST_DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE analysis_sessions (
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
                korean_name TEXT
            )
            """
        )
        await db.commit()
        cursor = await db.execute("PRAGMA table_info(analysis_sessions)")
        cols_before = {row[1] for row in await cursor.fetchall()}
    assert "kind" not in cols_before

    manager = SessionManager()
    await manager.initialize()  # must ALTER the pre-existing table, not crash

    async with aiosqlite.connect(TEST_DB_PATH) as db:
        cursor = await db.execute("PRAGMA table_info(analysis_sessions)")
        cols_after = {row[1] for row in await cursor.fetchall()}
    assert "kind" in cols_after

    # And a fresh session on the migrated DB writes/reads kind normally.
    await manager.create_session(
        "p41-post-migration", MarketType.KIWOOM, "005930", "삼성전자"
    )
    fetched = await manager.get_session("p41-post-migration")
    assert fetched.kind == "analysis"
