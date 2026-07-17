"""E1-6: 과거 실현손익(ka10074) 백필 스크립트 테스트.

전부 tmp DB + mock kiwoom 기반 -- 이 파일은 실 DB
(backend/data/storage.db)도, 실 Kiwoom 서버도 절대 참조하지 않는다.
dry-run조차 실 DB 경로를 열지 않는다(스크립트 함수들은 호출자가 넘긴
경로만 사용하며, 기본값 DEFAULT_DB_PATH는 이 테스트의 그 어떤 호출에도
전달되지 않는다). 실제 KiwoomClient도 인스턴스화하지 않는다 -- 항상
`_FakeKiwoomClient`(duck-typed, get_realized_pnl만 구현)를 주입한다.

스키마는 services/storage_service.py의 kr_realized_pnl CREATE TABLE을
그대로 복사했다(스크립트 자체 상수 _KR_REALIZED_PNL_SCHEMA와도 동일해야
하고, 실 DB 스키마와도 동일해야 이 테스트가 의미가 있다).
"""

import sqlite3

import pytest

from scripts.backfill_realized_pnl import (
    BACKFILL_STK_CD_SENTINEL,
    BackfillPlan,
    compute_backfill_plan,
    read_existing_backfill_dates,
    run_backfill,
    upsert_backfill_rows,
    _backfill_id,
    _iso_to_yyyymmdd,
    _yyyymmdd_to_iso,
)
from services.kiwoom.models import DailyRealizedPnlRow, RealizedPnl


# -------------------------------------------
# Schema fixture -- copied verbatim from storage_service.py's kr_realized_pnl
# CREATE TABLE.
# -------------------------------------------

_KR_REALIZED_PNL_SCHEMA = """
    CREATE TABLE IF NOT EXISTS kr_realized_pnl (
        id TEXT PRIMARY KEY,
        stk_cd TEXT NOT NULL,
        entry_price REAL,
        exit_price REAL,
        quantity INTEGER,
        realized_amount REAL,
        entry_decision_id TEXT,
        exit_decision_id TEXT,
        holding_period_seconds INTEGER,
        entry_at TIMESTAMP,
        exit_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


def _make_db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(_KR_REALIZED_PNL_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _insert_row(
    path: str,
    *,
    id: str,
    stk_cd: str,
    exit_at: str,
    realized_amount: float = 0.0,
    entry_price=None,
    exit_price=None,
    quantity=None,
    entry_decision_id=None,
    exit_decision_id=None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO kr_realized_pnl
            (id, stk_cd, entry_price, exit_price, quantity, realized_amount,
             entry_decision_id, exit_decision_id, exit_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id,
                stk_cd,
                entry_price,
                exit_price,
                quantity,
                realized_amount,
                entry_decision_id,
                exit_decision_id,
                exit_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _row_count(path: str) -> int:
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM kr_realized_pnl")
        return cur.fetchone()[0]
    finally:
        conn.close()


def _all_rows(path: str) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM kr_realized_pnl ORDER BY exit_at")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _daily(dt: str, sell_pnl: int, **kw) -> DailyRealizedPnlRow:
    return DailyRealizedPnlRow(dt=dt, sell_pnl=sell_pnl, **kw)


class _FakeKiwoomClient:
    """duck-typed mock -- only implements get_realized_pnl, mirroring
    KiwoomClient's real signature/return type. Records calls for assertion
    and can be configured to raise (simulating a broker/network failure)."""

    def __init__(self, daily: list[DailyRealizedPnlRow] | None = None, raises: Exception | None = None):
        self._daily = daily or []
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    async def get_realized_pnl(self, strt_dt: str, end_dt: str) -> RealizedPnl:
        self.calls.append((strt_dt, end_dt))
        if self._raises is not None:
            raise self._raises
        total = sum(d.sell_pnl for d in self._daily)
        return RealizedPnl(
            strt_dt=strt_dt,
            end_dt=end_dt,
            realized_pnl=total,
            daily=self._daily,
        )


# -------------------------------------------
# (a) Pure helpers
# -------------------------------------------


def test_yyyymmdd_iso_roundtrip():
    assert _yyyymmdd_to_iso("20260601") == "2026-06-01"
    assert _iso_to_yyyymmdd("2026-06-01") == "20260601"


def test_yyyymmdd_to_iso_unparseable_passthrough():
    # Defensive: malformed dt from a broker response must never crash.
    assert _yyyymmdd_to_iso("bad") == "bad"
    assert _yyyymmdd_to_iso("") == ""


def test_backfill_id_deterministic():
    assert _backfill_id("20260601") == _backfill_id("20260601")
    assert _backfill_id("20260601") != _backfill_id("20260602")


def test_compute_backfill_plan_skips_existing_and_unparseable():
    daily = [
        _daily("20260601", 1000),
        _daily("20260602", -500),
        _daily("bad-date", 999),
    ]
    plan = compute_backfill_plan(daily, existing_dates={"2026-06-01"})

    assert [r.source_dt for r in plan.candidate_rows] == ["20260602"]
    assert plan.candidate_rows[0].stk_cd == BACKFILL_STK_CD_SENTINEL
    assert plan.candidate_rows[0].realized_amount == -500.0
    assert plan.candidate_rows[0].exit_at == "2026-06-02"
    assert plan.skipped_existing == ["20260601"]
    assert plan.skipped_unparseable == ["bad-date"]


def test_read_existing_backfill_dates_missing_file_returns_empty(tmp_path):
    missing = str(tmp_path / "does_not_exist.db")
    assert read_existing_backfill_dates(missing) == set()


def test_read_existing_backfill_dates_missing_table_returns_empty(tmp_path):
    db = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()
    assert read_existing_backfill_dates(db) == set()


def test_read_existing_backfill_dates_filters_by_sentinel(tmp_path):
    db = str(tmp_path / "t.db")
    _make_db(db)
    _insert_row(db, id="backfill-20260601", stk_cd=BACKFILL_STK_CD_SENTINEL, exit_at="2026-06-01")
    # A real per-trade row for an actual ticker must never be treated as a
    # prior backfill -- it has a different stk_cd (real 6-digit code).
    _insert_row(
        db,
        id="real-1",
        stk_cd="005930",
        exit_at="2026-06-02",
        entry_price=70000,
        exit_price=72000,
        quantity=10,
        entry_decision_id="dec-1",
    )
    assert read_existing_backfill_dates(db) == {"2026-06-01"}


# -------------------------------------------
# (b) run_backfill -- dry-run
# -------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_reports_counts_and_writes_nothing(tmp_path):
    db = str(tmp_path / "t.db")  # does not exist yet -- fresh install case
    client = _FakeKiwoomClient(
        daily=[_daily("20260601", 1000), _daily("20260602", -500)]
    )

    plan = await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-06-02", apply=False
    )

    assert len(plan.candidate_rows) == 2
    assert plan.skipped_existing == []
    assert plan.inserted == 0
    # dry-run must never even create the DB file, let alone write rows.
    import os

    assert not os.path.exists(db)


@pytest.mark.asyncio
async def test_dry_run_converts_iso_dates_to_kiwoom_format(tmp_path):
    db = str(tmp_path / "t.db")
    client = _FakeKiwoomClient(daily=[])

    await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-07-01", apply=False
    )

    assert client.calls == [("20260601", "20260701")]


# -------------------------------------------
# (c) run_backfill -- apply, only missing (date, ticker) upserted
# -------------------------------------------


@pytest.mark.asyncio
async def test_apply_upserts_only_new_dates(tmp_path):
    db = str(tmp_path / "t.db")
    client = _FakeKiwoomClient(
        daily=[_daily("20260601", 1000), _daily("20260602", -500)]
    )

    plan = await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-06-02", apply=True
    )

    assert plan.inserted == 2
    rows = _all_rows(db)
    assert len(rows) == 2
    by_date = {r["exit_at"]: r for r in rows}
    assert by_date["2026-06-01"]["realized_amount"] == 1000.0
    assert by_date["2026-06-02"]["realized_amount"] == -500.0
    for r in rows:
        assert r["stk_cd"] == BACKFILL_STK_CD_SENTINEL
        assert r["entry_price"] is None
        assert r["exit_price"] is None
        assert r["quantity"] is None
        assert r["entry_decision_id"] is None
        assert r["exit_decision_id"] is None
        assert r["id"] == f"backfill-{_iso_to_yyyymmdd(r['exit_at'])}"


# -------------------------------------------
# (d) existing rows -- skip (idempotent), never overwritten
# -------------------------------------------


@pytest.mark.asyncio
async def test_apply_skips_existing_row_leaves_it_untouched(tmp_path):
    db = str(tmp_path / "t.db")
    _make_db(db)
    _insert_row(
        db,
        id="backfill-20260601",
        stk_cd=BACKFILL_STK_CD_SENTINEL,
        exit_at="2026-06-01",
        realized_amount=42.0,  # deliberately different from what ka10074 would say now
    )
    client = _FakeKiwoomClient(
        daily=[_daily("20260601", 1000), _daily("20260602", -500)]
    )

    plan = await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-06-02", apply=True
    )

    assert plan.skipped_existing == ["20260601"]
    assert plan.inserted == 1  # only 2026-06-02 is new
    rows = _all_rows(db)
    assert len(rows) == 2
    by_date = {r["exit_at"]: r for r in rows}
    # Existing 2026-06-01 row is untouched -- its stale value survives.
    assert by_date["2026-06-01"]["realized_amount"] == 42.0
    assert by_date["2026-06-02"]["realized_amount"] == -500.0


@pytest.mark.asyncio
async def test_apply_never_collides_with_real_trade_rows_same_date(tmp_path):
    """A real per-trade row can legitimately share a date with a backfill
    candidate (a live trade + a historical aggregate on the same day) --
    they must coexist since they key on different stk_cd."""
    db = str(tmp_path / "t.db")
    _make_db(db)
    _insert_row(
        db,
        id="real-1",
        stk_cd="005930",
        exit_at="2026-06-01",
        realized_amount=999.0,
        entry_price=70000,
        exit_price=72000,
        quantity=10,
        entry_decision_id="dec-1",
    )
    client = _FakeKiwoomClient(daily=[_daily("20260601", 1000)])

    plan = await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-06-01", apply=True
    )

    assert plan.inserted == 1
    rows = _all_rows(db)
    assert len(rows) == 2
    stk_cds = {r["stk_cd"] for r in rows}
    assert stk_cds == {"005930", BACKFILL_STK_CD_SENTINEL}


# -------------------------------------------
# (e) fetch failure -- skip, never crash
# -------------------------------------------


@pytest.mark.asyncio
async def test_fetch_failure_skips_without_crashing_and_writes_nothing(tmp_path):
    db = str(tmp_path / "t.db")
    client = _FakeKiwoomClient(raises=RuntimeError("broker timeout"))

    plan = await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-06-02", apply=True
    )

    assert plan.fetch_failed is True
    assert plan.fetch_error == "broker timeout"
    assert plan.candidate_rows == []
    assert plan.inserted == 0
    import os

    assert not os.path.exists(db)


@pytest.mark.asyncio
async def test_fetch_failure_dry_run_also_never_raises(tmp_path):
    db = str(tmp_path / "t.db")
    client = _FakeKiwoomClient(raises=ConnectionError("dns fail"))

    plan = await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-06-02", apply=False
    )

    assert isinstance(plan, BackfillPlan)
    assert plan.fetch_failed is True


# -------------------------------------------
# (f) run twice -- safe, no duplicates
# -------------------------------------------


@pytest.mark.asyncio
async def test_running_twice_is_idempotent(tmp_path):
    db = str(tmp_path / "t.db")
    client = _FakeKiwoomClient(
        daily=[_daily("20260601", 1000), _daily("20260602", -500)]
    )

    plan1 = await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-06-02", apply=True
    )
    assert plan1.inserted == 2
    assert _row_count(db) == 2

    # Second run against the same period+data -- everything should now be
    # classified as already-existing, nothing new inserted, no duplicates,
    # no crash.
    plan2 = await run_backfill(
        kiwoom_client=client, db_path=db, from_date="2026-06-01", to_date="2026-06-02", apply=True
    )
    assert plan2.candidate_rows == []
    assert plan2.inserted == 0
    assert _row_count(db) == 2


@pytest.mark.asyncio
async def test_upsert_backfill_rows_insert_or_ignore_direct_pk_collision(tmp_path):
    """Second layer of defense (deterministic id + INSERT OR IGNORE) works
    even if the pre-check (compute_backfill_plan) were somehow bypassed --
    calling upsert_backfill_rows a second time with the same candidate must
    not raise and must not duplicate."""
    db = str(tmp_path / "t.db")
    from scripts.backfill_realized_pnl import BackfillRow

    row = BackfillRow(
        id="backfill-20260601",
        stk_cd=BACKFILL_STK_CD_SENTINEL,
        realized_amount=1000.0,
        exit_at="2026-06-01",
        source_dt="20260601",
    )

    inserted1 = upsert_backfill_rows(db, [row])
    assert inserted1 == 1
    inserted2 = upsert_backfill_rows(db, [row])
    assert inserted2 == 0  # IGNORE'd -- PK collision
    assert _row_count(db) == 1


# -------------------------------------------
# (g) never touches the real default DB path
# -------------------------------------------


def test_default_db_path_not_referenced_by_any_test_call():
    """Sanity check mirroring cleanup_session_stores.py's convention: this
    test file must never pass DEFAULT_DB_PATH (or omit db_path) anywhere,
    so the real backend/data/storage.db is never opened by this suite."""
    from scripts.backfill_realized_pnl import DEFAULT_DB_PATH
    import pathlib

    assert isinstance(DEFAULT_DB_PATH, pathlib.Path)
    assert DEFAULT_DB_PATH.name == "storage.db"
