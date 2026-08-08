"""순 실현손익 일회성 백필 스크립트 테스트 (2026-08-08).

전부 tmp DB 기반 — 이 파일은 실 DB(backend/data/storage.db)를 절대
참조하지 않는다. 스크립트 함수들은 호출자가 넘긴 경로만 사용하며 기본값
DEFAULT_DB_PATH는 이 테스트의 그 어떤 호출에도 전달되지 않는다.

스키마는 services/storage_service.py의 kr_realized_pnl CREATE TABLE +
2026-08-08 ALTER(fee/tax/net_amount/cost_source)를 그대로 복사했다.
"""

import sqlite3

import pytest

from scripts.backfill_net_realized_pnl import (
    COST_SOURCE_BACKFILL,
    SENTINEL_STK_CD,
    compute_cost_backfill_plan,
    read_all_rows,
    run_backfill,
)

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


# storage_service.py의 kr_realized_pnl CREATE TABLE (컬럼 4개 ALTER 이전 상태
# — 라이브 DB가 백필 시점에 놓여 있는 바로 그 모양이다).
_LEGACY_SCHEMA = """
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

_DECISIONS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS agent_chat_decisions (
        id TEXT PRIMARY KEY,
        ticker TEXT,
        outcome_realized_pnl REAL
    )
"""

# 라이브 실측 행 (005930 삼성전자, exit_at 2026-07-22 09:02:08).
_SAMSUNG = dict(
    id="row-samsung",
    stk_cd="005930",
    entry_price=273_027.0,
    exit_price=273_420.0,
    quantity=56,
    realized_amount=22_008.0,
    entry_decision_id="dec-samsung",
    exit_at="2026-07-22 09:02:08.650523",
)
_SAMSUNG_FEE = 6_120
_SAMSUNG_TAX = 35_216
_SAMSUNG_NET = -19_328.0


def _make_db(tmp_path, rows, decisions=(), name="t.db") -> str:
    db_path = str(tmp_path / name)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_LEGACY_SCHEMA)
        conn.execute(_DECISIONS_SCHEMA)
        for r in rows:
            cols = ", ".join(r.keys())
            marks = ", ".join("?" * len(r))
            conn.execute(
                f"INSERT INTO kr_realized_pnl ({cols}) VALUES ({marks})",
                tuple(r.values()),
            )
        for d in decisions:
            conn.execute(
                "INSERT INTO agent_chat_decisions (id, ticker, "
                "outcome_realized_pnl) VALUES (?, ?, ?)",
                (d["id"], d.get("ticker"), d.get("outcome_realized_pnl")),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _fetch(db_path, table="kr_realized_pnl"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


# -------------------------------------------
# 1) 값 — 모델 요율이 라이브 행에 그대로 적용된다
# -------------------------------------------


def test_backfill_fills_fee_tax_net_with_model_backfill_source(tmp_path):
    db = _make_db(tmp_path, [_SAMSUNG])

    run_backfill(db_path=db, apply=True)

    row = _fetch(db)[0]
    assert row["realized_amount"] == 22_008.0  # gross 불변
    assert row["fee"] == _SAMSUNG_FEE
    assert row["tax"] == _SAMSUNG_TAX
    assert row["net_amount"] == _SAMSUNG_NET
    assert row["cost_source"] == COST_SOURCE_BACKFILL


def test_dry_run_writes_nothing(tmp_path):
    db = _make_db(tmp_path, [_SAMSUNG])

    plan = run_backfill(db_path=db, apply=False)

    assert len(plan.rows) == 1  # 후보로는 잡힌다
    assert plan.updated_rows == 0
    # dry-run은 ALTER조차 하지 않는다 — 컬럼 자체가 안 생겨야 한다.
    cols = {r[1] for r in sqlite3.connect(db).execute(
        "PRAGMA table_info(kr_realized_pnl)"
    )}
    assert "net_amount" not in cols


# -------------------------------------------
# 2) 결정 백필도 net으로 다시 쓴다
# -------------------------------------------


def test_decision_outcome_rebackfilled_to_net(tmp_path):
    db = _make_db(
        tmp_path,
        [_SAMSUNG],
        decisions=[
            {
                "id": "dec-samsung",
                "ticker": "005930",
                "outcome_realized_pnl": 22_008.0,  # gross로 남아 있던 값
            }
        ],
    )

    run_backfill(db_path=db, apply=True)

    dec = _fetch(db, "agent_chat_decisions")[0]
    assert dec["outcome_realized_pnl"] == _SAMSUNG_NET


def test_partial_fill_slices_use_last_exit_mirroring_runtime_last_write_wins(
    tmp_path,
):
    """한 결정에 부분체결 슬라이스가 여러 행 달리는 것이 라이브의 정상
    형태다(049070은 6행). 런타임 경로는 `update_decision_outcome`이
    덮어쓰기라 **마지막 체결이 이긴다** — 백필도 같은 규칙을 써야 gross를
    net으로 바꾸는 것 이상의 의미 변화가 생기지 않는다."""
    rows = [
        dict(
            id="slice-1",
            stk_cd="093190",
            entry_price=8_000.0,
            exit_price=9_000.0,
            quantity=100,
            realized_amount=100_000.0,
            entry_decision_id="dec-multi",
            exit_at="2026-07-27 09:36:23",
        ),
        dict(
            id="slice-2",
            stk_cd="093190",
            entry_price=8_000.0,
            exit_price=8_500.0,
            quantity=10,
            realized_amount=5_000.0,
            entry_decision_id="dec-multi",
            exit_at="2026-07-27 09:36:56",  # 가장 늦은 체결
        ),
    ]
    db = _make_db(
        tmp_path,
        rows,
        decisions=[
            {
                "id": "dec-multi",
                "ticker": "093190",
                "outcome_realized_pnl": 5_000.0,
            }
        ],
    )

    run_backfill(db_path=db, apply=True)

    by_id = {r["id"]: r for r in _fetch(db)}
    dec = _fetch(db, "agent_chat_decisions")[0]
    assert dec["outcome_realized_pnl"] == by_id["slice-2"]["net_amount"]
    assert dec["outcome_realized_pnl"] != by_id["slice-1"]["net_amount"]


def test_missing_decision_row_is_not_an_error(tmp_path):
    """라이브 25행 중 2건은 entry_decision_id가 가리키는 결정 행이 이미
    없다 — 그때도 원장 백필은 정상 완료돼야 한다."""
    db = _make_db(tmp_path, [_SAMSUNG])  # agent_chat_decisions 비어 있음

    plan = run_backfill(db_path=db, apply=True)

    assert plan.updated_rows == 1
    assert plan.updated_decisions == 0
    assert _fetch(db)[0]["net_amount"] == _SAMSUNG_NET


# -------------------------------------------
# 3) 'ALL' 센티널 제외
# -------------------------------------------


def test_all_sentinel_row_untouched(tmp_path):
    sentinel = dict(
        id="backfill-20260722",
        stk_cd=SENTINEL_STK_CD,
        entry_price=None,
        exit_price=None,
        quantity=None,
        realized_amount=123_456.0,
        exit_at="2026-07-22",
    )
    db = _make_db(tmp_path, [_SAMSUNG, sentinel])

    plan = run_backfill(db_path=db, apply=True)

    by_id = {r["id"]: r for r in _fetch(db)}
    assert by_id["backfill-20260722"]["net_amount"] is None
    assert by_id["backfill-20260722"]["cost_source"] is None
    assert by_id["backfill-20260722"]["realized_amount"] == 123_456.0
    assert plan.skipped_sentinel == 1
    assert plan.updated_rows == 1


# -------------------------------------------
# 4) 멱등 — 두 번 돌려도 값이 같다
# -------------------------------------------


def test_backfill_is_idempotent(tmp_path):
    db = _make_db(
        tmp_path,
        [_SAMSUNG],
        decisions=[
            {
                "id": "dec-samsung",
                "ticker": "005930",
                "outcome_realized_pnl": 22_008.0,
            }
        ],
    )

    run_backfill(db_path=db, apply=True)
    after_first = (_fetch(db), _fetch(db, "agent_chat_decisions"))

    second = run_backfill(db_path=db, apply=True)
    after_second = (_fetch(db), _fetch(db, "agent_chat_decisions"))

    assert after_first == after_second
    # 두 번째 실행은 후보를 하나도 잡지 않는다 — 결정 백필도 중복되지 않는다.
    assert second.rows == []
    assert second.updated_rows == 0
    assert second.updated_decisions == 0
    assert second.already_net == 1


def test_second_run_does_not_clobber_a_newer_decision_outcome(tmp_path):
    """멱등성의 실질 — 재실행이 그 사이 런타임이 갱신한 결정 값을 되돌리면
    안 된다."""
    db = _make_db(
        tmp_path,
        [_SAMSUNG],
        decisions=[
            {"id": "dec-samsung", "ticker": "005930",
             "outcome_realized_pnl": 22_008.0}
        ],
    )
    run_backfill(db_path=db, apply=True)

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE agent_chat_decisions SET outcome_realized_pnl = 777.0 "
        "WHERE id = 'dec-samsung'"
    )
    conn.commit()
    conn.close()

    run_backfill(db_path=db, apply=True)

    assert _fetch(db, "agent_chat_decisions")[0]["outcome_realized_pnl"] == 777.0


# -------------------------------------------
# 5) 순수 계획 함수 — DB 없이도 값이 검증된다
# -------------------------------------------


def test_plan_is_pure_and_skips_rows_that_already_have_net(tmp_path):
    rows = [
        dict(_SAMSUNG, net_amount=_SAMSUNG_NET),
        dict(
            id="row-legacy",
            stk_cd="068270",
            entry_price=183_800.0,
            exit_price=198_339.0,
            quantity=44,
            realized_amount=639_716.0,
            entry_decision_id=None,
            exit_at="2026-08-07 09:33:12",
            net_amount=None,
        ),
    ]

    plan = compute_cost_backfill_plan(rows)

    assert plan.already_net == 1
    assert [r.id for r in plan.rows] == ["row-legacy"]
    assert plan.decision_updates == []  # entry_decision_id 없음


def test_zero_or_missing_prices_leave_net_equal_to_gross(tmp_path):
    rows = [
        dict(
            id="row-zero",
            stk_cd="000660",
            entry_price=0.0,
            exit_price=0.0,
            quantity=0,
            realized_amount=-1_232_000.0,
            entry_decision_id=None,
            exit_at="2026-07-20 10:55:52",
            net_amount=None,
        )
    ]

    plan = compute_cost_backfill_plan(rows)

    assert len(plan.rows) == 1
    assert plan.rows[0].fee == 0
    assert plan.rows[0].tax == 0
    assert plan.rows[0].net_amount == -1_232_000.0


def test_read_all_rows_is_read_only_on_a_pre_alter_db(tmp_path):
    db = _make_db(tmp_path, [_SAMSUNG])

    rows = read_all_rows(db)

    assert len(rows) == 1
    assert rows[0]["net_amount"] is None  # 컬럼이 없어도 None으로 정규화
    cols = {r[1] for r in sqlite3.connect(db).execute(
        "PRAGMA table_info(kr_realized_pnl)"
    )}
    assert "net_amount" not in cols  # 읽기가 스키마를 바꾸지 않았다
