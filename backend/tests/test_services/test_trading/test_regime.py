"""Task 2 (Phase2 EOD review): minimal daily market-regime snapshot from the
background scanner's breadth distribution.

There is no market-wide sentiment/regime signal anywhere in this codebase
(confirmed by audit) — the only durable, market-wide artifact is the
background scanner's `scan_sessions` row (buy/sell/hold/watch/avoid counts
across the day's KOSPI/KOSDAQ sweep), which stands in as a breadth proxy.
Index/flow fetchers are a later phase; this is intentionally minimal.

`compute_regime_snapshot` is a pure, synchronous function (no LLM, no
network) that reads the LATEST completed `scan_sessions` row for a given
trade_date directly off the scanner's own sqlite db, computes
`breadth_ratio = (buy - sell) / max(1, buy + sell + hold)`, and labels it
risk_on/risk_off/neutral against the configurable
`EOD_REGIME_BREADTH_THRESHOLD`. Failure-harmless: returns `None` on any
error or when no completed scan exists for that date, never raises.

The storage half (`save_regime_snapshot`/`get_regime_snapshots`) is a plain
persistence mirror of `save_coin_realized_pnl`/`get_coin_realized_pnl`.
"""

import sqlite3
import uuid
from datetime import datetime

import pytest

from services.storage_service import StorageService
from services.trading.regime import compute_regime_snapshot

pytestmark = pytest.mark.asyncio


def _make_scanner_db(tmp_path, sessions: list[dict]) -> str:
    """Build a temp scanner_results.db with a `scan_sessions` table + rows.

    Mirrors the real DDL in
    services/background_scanner/scanner.py::ScannerService._init_db exactly
    (only the columns this task reads/needs are populated per-row; the rest
    default to 0/None like the real writer's start-row does).
    """
    db_path = tmp_path / "scanner_results.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE scan_sessions (
            id TEXT PRIMARY KEY,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            total_stocks INTEGER,
            completed INTEGER,
            failed INTEGER,
            buy_count INTEGER,
            sell_count INTEGER,
            hold_count INTEGER,
            watch_count INTEGER,
            avoid_count INTEGER,
            status TEXT
        )
        """
    )
    for s in sessions:
        conn.execute(
            """
            INSERT INTO scan_sessions
            (id, started_at, completed_at, total_stocks, completed, failed,
             buy_count, sell_count, hold_count, watch_count, avoid_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s["id"],
                s["started_at"],
                s.get("completed_at"),
                s.get("total_stocks", 0),
                s.get("completed", 0),
                s.get("failed", 0),
                s["buy_count"],
                s["sell_count"],
                s["hold_count"],
                s.get("watch_count", 0),
                s.get("avoid_count", 0),
                s["status"],
            ),
        )
    conn.commit()
    conn.close()
    return str(db_path)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


async def test_compute_regime_snapshot_buy_heavy_is_risk_on(tmp_path):
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "completed",
                "buy_count": 40,
                "sell_count": 5,
                "hold_count": 10,
            }
        ],
    )

    record = compute_regime_snapshot(db_path, today)

    assert record is not None
    assert record["breadth_ratio"] > 0.15
    assert record["regime_label"] == "risk_on"
    assert record["breadth_buy"] == 40
    assert record["breadth_sell"] == 5
    assert record["breadth_hold"] == 10
    assert record["trade_date"] == today
    assert record["source"] == "scanner"
    uuid.UUID(record["id"])  # raises ValueError if not a valid uuid


async def test_compute_regime_snapshot_sell_heavy_is_risk_off(tmp_path):
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "completed",
                "buy_count": 5,
                "sell_count": 40,
                "hold_count": 10,
            }
        ],
    )

    record = compute_regime_snapshot(db_path, today)

    assert record is not None
    assert record["breadth_ratio"] < -0.15
    assert record["regime_label"] == "risk_off"


async def test_compute_regime_snapshot_balanced_is_neutral(tmp_path):
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "completed",
                "buy_count": 20,
                "sell_count": 18,
                "hold_count": 20,
            }
        ],
    )

    record = compute_regime_snapshot(db_path, today)

    assert record is not None
    assert -0.15 <= record["breadth_ratio"] <= 0.15
    assert record["regime_label"] == "neutral"


async def test_compute_regime_snapshot_no_completed_scan_that_day_is_none(tmp_path):
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "running",  # not completed
                "buy_count": 40,
                "sell_count": 5,
                "hold_count": 10,
            }
        ],
    )

    assert compute_regime_snapshot(db_path, today) is None


async def test_compute_regime_snapshot_no_rows_at_all_is_none(tmp_path):
    db_path = _make_scanner_db(tmp_path, [])
    assert compute_regime_snapshot(db_path, _today()) is None


async def test_compute_regime_snapshot_missing_db_file_is_none(tmp_path):
    assert compute_regime_snapshot(str(tmp_path / "does_not_exist.db"), _today()) is None


async def test_compute_regime_snapshot_picks_latest_completed_session_that_day(tmp_path):
    """Two completed sessions the same day -> the LATEST (by started_at)
    wins, not the first inserted."""
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "completed",
                "buy_count": 5,
                "sell_count": 40,
                "hold_count": 10,
            },
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 15:00:00",
                "status": "completed",
                "buy_count": 40,
                "sell_count": 5,
                "hold_count": 10,
            },
        ],
    )

    record = compute_regime_snapshot(db_path, today)

    assert record is not None
    assert record["regime_label"] == "risk_on"  # the 15:00 session, not 09:00


async def test_save_and_get_regime_snapshots_roundtrip(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    record = {
        "id": str(uuid.uuid4()),
        "trade_date": "2026-07-15",
        "breadth_buy": 40,
        "breadth_sell": 5,
        "breadth_hold": 10,
        "breadth_ratio": 0.6363636363636364,
        "regime_label": "risk_on",
        "source": "scanner",
    }

    assert await storage.save_regime_snapshot(record) is True

    rows = await storage.get_regime_snapshots()
    assert len(rows) == 1
    assert rows[0]["trade_date"] == "2026-07-15"
    assert rows[0]["regime_label"] == "risk_on"
    assert rows[0]["breadth_buy"] == 40
    assert rows[0]["breadth_sell"] == 5
    assert rows[0]["breadth_hold"] == 10
    assert rows[0]["source"] == "scanner"


# ---------------------------------------------------------------------------
# SC-1: partial(stop_scan 도중 종결) 세션도 breadth 소비 대상 — 고아
# status='running' 버그의 실측 근본원인(scanner.py stop_scan이 세션을
# 'running'으로 영구 고아화 -> 이 게이트가 0건 반환).
# ---------------------------------------------------------------------------


async def test_compute_regime_snapshot_consumes_partial_session(tmp_path):
    """status='partial' 세션(스캔 도중 stop_scan으로 종결)도 'completed'와
    동일하게 breadth 소비 대상이어야 한다(수정 전 RED=0건/neutral 강제)."""
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "partial",
                "buy_count": 40,
                "sell_count": 5,
                "hold_count": 10,
            }
        ],
    )

    record = compute_regime_snapshot(db_path, today)

    assert record is not None
    assert record["breadth_ratio"] > 0.15
    assert record["regime_label"] == "risk_on"
    assert record["breadth_buy"] == 40


async def test_compute_regime_snapshot_prefers_latest_over_status(tmp_path):
    """같은 날 completed(이른 시각)와 partial(늦은 시각)이 공존하면, 상태와
    무관하게 최신 started_at(partial 쪽)이 우선해야 한다(스펙: '최신
    started_at 우선 유지')."""
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "completed",
                "buy_count": 5,
                "sell_count": 40,
                "hold_count": 10,
            },
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 15:00:00",
                "status": "partial",
                "buy_count": 40,
                "sell_count": 5,
                "hold_count": 10,
            },
        ],
    )

    record = compute_regime_snapshot(db_path, today)

    assert record is not None
    assert record["regime_label"] == "risk_on"  # 15:00 partial 세션 우선


async def test_compute_regime_snapshot_failed_session_still_excluded(tmp_path):
    """status='failed'/'running' 등 partial·completed가 아닌 상태는 여전히
    소비 대상이 아니어야 한다(게이트 확장이 과잉 확장되지 않았음을 확인)."""
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "failed",
                "buy_count": 40,
                "sell_count": 5,
                "hold_count": 10,
            }
        ],
    )

    assert compute_regime_snapshot(db_path, today) is None



# ---------------------------------------------------------------------------
# SC-3: regime_snapshot.scan_coverage_pct -- 사후 감사 "이 날 breadth는
# 몇 % 표본이었는가"를 구분 가능하게 함. completed=100 고정,
# partial=completed/total*100, breadth 세션 자체가 없으면(compute_regime_
# snapshot이 None 반환) coverage 개념 자체가 없음.
# ---------------------------------------------------------------------------


async def test_compute_regime_snapshot_coverage_pct_partial_is_completed_over_total(tmp_path):
    """partial 세션(84/100 저장)의 scan_coverage_pct는 completed/total*100
    == 84.0이어야 한다."""
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "partial",
                "total_stocks": 100,
                "completed": 84,
                "buy_count": 40,
                "sell_count": 5,
                "hold_count": 10,
            }
        ],
    )

    record = compute_regime_snapshot(db_path, today)

    assert record is not None
    assert record["scan_coverage_pct"] == 84.0


async def test_compute_regime_snapshot_coverage_pct_completed_is_100(tmp_path):
    """정상 완주(status='completed') 세션의 scan_coverage_pct는 저장된
    completed/total 값과 무관하게 항상 100이어야 한다(정의상 전체 유니버스를
    다 돈 것)."""
    today = _today()
    db_path = _make_scanner_db(
        tmp_path,
        [
            {
                "id": str(uuid.uuid4()),
                "started_at": f"{today} 09:00:00",
                "status": "completed",
                "total_stocks": 100,
                "completed": 100,
                "buy_count": 40,
                "sell_count": 5,
                "hold_count": 10,
            }
        ],
    )

    record = compute_regime_snapshot(db_path, today)

    assert record is not None
    assert record["scan_coverage_pct"] == 100.0


async def test_compute_regime_snapshot_no_session_that_day_returns_none_not_coverage(tmp_path):
    """breadth 세션 자체가 없는 날은 compute_regime_snapshot이 None을
    반환한다 -- scan_coverage_pct도 당연히 존재하지 않는다(record 자체가
    없으므로 coverage 개념도 없음, 소비자는 이 None 자체를 '표본 없음'으로
    읽어야 한다)."""
    db_path = _make_scanner_db(tmp_path, [])
    assert compute_regime_snapshot(db_path, _today()) is None



async def test_save_and_get_regime_snapshot_scan_coverage_pct_roundtrip(tmp_path):
    """storage_service의 regime_snapshot 테이블이 scan_coverage_pct를
    nullable 컬럼으로 저장/조회할 수 있어야 한다(_ensure_columns 관례 --
    fresh DB에서도 CREATE TABLE 직후 ALTER로 추가됨)."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    record = {
        "id": str(uuid.uuid4()),
        "trade_date": "2026-07-20",
        "breadth_buy": 40,
        "breadth_sell": 5,
        "breadth_hold": 10,
        "breadth_ratio": 0.6363636363636364,
        "regime_label": "risk_on",
        "source": "scanner",
        "scan_coverage_pct": 84.0,
    }

    assert await storage.save_regime_snapshot(record) is True

    rows = await storage.get_regime_snapshots()
    assert len(rows) == 1
    assert rows[0]["scan_coverage_pct"] == 84.0


async def test_save_regime_snapshot_scan_coverage_pct_defaults_to_none(tmp_path):
    """record에 scan_coverage_pct 키가 아예 없어도(레거시 호출부/breadth
    폴백 스켈레톤) 저장이 깨지지 않고 NULL로 들어가야 한다(nullable 컬럼
    회귀 -- 기존 test_save_and_get_regime_snapshots_roundtrip이 이미 이
    키 없이 저장하는 것과 동일한 경로)."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    record = {
        "id": str(uuid.uuid4()),
        "trade_date": "2026-07-20",
        "breadth_buy": 40,
        "breadth_sell": 5,
        "breadth_hold": 10,
        "breadth_ratio": 0.6363636363636364,
        "regime_label": "risk_on",
        "source": "scanner",
    }

    assert await storage.save_regime_snapshot(record) is True

    rows = await storage.get_regime_snapshots()
    assert len(rows) == 1
    assert rows[0]["scan_coverage_pct"] is None
