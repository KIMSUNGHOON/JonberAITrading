"""BackgroundScanner.get_latest_adtv — NULL factor_json 최신행 함정 봉합 (T8).

ROOT: `scan_results`에는 세 writer가 있다 — discovery 모드만 T3가
factor_json(adtv20_med 포함)을 채우고, quick/LLM 스캔 모드(`_save_result_to_db`/
`_save_results_batch`)는 factor_json 컬럼을 아예 언급하지 않아 NULL로 남는다.
`get_latest_adtv`가 `ORDER BY scanned_at DESC LIMIT 1`만으로 최신 행을 골라
factor_json IS NOT NULL을 걸지 않으면, EOD discovery 스캔 다음날 아침 일반
`/api/scanner/start` 스윕이 같은 종목의 NULL factor_json 행을 더 최신으로
삽입한 순간 폴백이 조용히 무력화된다(T6 재리뷰 Minor).

이 테스트는 정확히 그 순서(과거 non-NULL discovery 행 -> 미래 NULL quick 행)를
재현해 `get_latest_adtv`가 여전히 과거의 non-NULL adtv20_med를 찾아오는지
검증한다."""

import json

import aiosqlite
import pytest

from services.background_scanner import scanner as scanner_module
from services.background_scanner.scanner import BackgroundScanner

# Note: no module-level pytestmark — pytest.ini sets asyncio_mode = auto.


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "scanner_get_latest_adtv_test.db"


@pytest.fixture(autouse=True)
def patched_db(monkeypatch, db_path):
    """실 scanner_results.db를 절대 건드리지 않도록 모듈 전역 DB_PATH를
    tmp 경로로 교체."""
    monkeypatch.setattr(scanner_module, "DB_PATH", db_path)


async def _insert_scan_result(db_path, stk_cd: str, scanned_at: str, factor_json):
    """discovery/quick 두 writer 경로를 흉내내 scan_results에 직접 행을
    삽입한다. factor_json=None이면 quick/LLM 스캔 모드(컬럼 미기재)와 동일하게
    NULL로 남는다."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO scan_results
            (stk_cd, stk_nm, action, signal, confidence, summary,
             key_factors, current_price, market_type, scanned_at,
             scan_session_id, factor_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stk_cd,
                "테스트종목",
                "WATCH",
                "hold",
                0.6,
                "요약",
                "",
                10_000,
                "코스피",
                scanned_at,
                "session-x",
                json.dumps(factor_json) if factor_json is not None else None,
            ),
        )
        await db.commit()


async def test_ignores_newer_null_factor_json_row(db_path):
    """EOD discovery가 어제 adtv20_med를 저장한 뒤, 오늘 아침 quick 스윕이
    같은 종목에 factor_json=NULL 행을 더 최신 scanned_at으로 얹어도,
    get_latest_adtv는 그 NULL 최신행이 아니라 과거의 non-NULL 값을
    반환해야 한다."""
    scanner = BackgroundScanner()
    await scanner._init_db()

    await _insert_scan_result(
        db_path,
        "093190",
        "2026-07-23 15:30:00",
        {"adtv20_med": 120_000_000.0},
    )
    await _insert_scan_result(
        db_path,
        "093190",
        "2026-07-24 09:05:00",
        None,  # quick/LLM 스캔 모드 — factor_json 미기재
    )

    result = await scanner.get_latest_adtv("093190")

    assert result == pytest.approx(120_000_000.0)


async def test_returns_latest_when_it_is_non_null(db_path):
    """가장 최근 행이 non-NULL factor_json이면 그대로 그 값을 반환한다
    (회귀 방지 — factor_json IS NOT NULL 필터가 단순히 항상 가장 오래된
    값을 강제하는 게 아니라 '최신 non-NULL'을 고르는지 확인)."""
    scanner = BackgroundScanner()
    await scanner._init_db()

    await _insert_scan_result(
        db_path,
        "089860",
        "2026-07-20 15:30:00",
        {"adtv20_med": 50_000_000.0},
    )
    await _insert_scan_result(
        db_path,
        "089860",
        "2026-07-23 15:30:00",
        {"adtv20_med": 227_000_000.0},
    )

    result = await scanner.get_latest_adtv("089860")

    assert result == pytest.approx(227_000_000.0)


async def test_all_rows_null_returns_none(db_path):
    """전부 NULL factor_json이면 fail-open으로 None을 반환한다(크래시 금지)."""
    scanner = BackgroundScanner()
    await scanner._init_db()

    await _insert_scan_result(db_path, "999999", "2026-07-24 09:05:00", None)

    result = await scanner.get_latest_adtv("999999")

    assert result is None


async def test_no_rows_returns_none(db_path):
    """해당 종목의 scan_results 행이 아예 없으면 None."""
    scanner = BackgroundScanner()
    await scanner._init_db()

    result = await scanner.get_latest_adtv("000000")

    assert result is None
