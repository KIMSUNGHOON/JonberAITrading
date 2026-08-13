"""E3-4: EOD 리포트 API — GET(조회)·POST(수동 재생성+재통지).

Convention notes (verified against neighboring tests before writing this):
- ``get_trading_coordinator`` is a real ``Depends()`` — override via
  ``app.dependency_overrides`` (tests/test_api/test_strategy_routes.py
  precedent, docstring there explains why).
- ``app.api.routes.trading.get_storage_service`` is patched per-test with an
  ``AsyncMock`` returning a ``tmp_path``-backed ``StorageService`` — same
  precedent file, keeps the real ``data/storage.db`` untouched.
- ``client`` additionally isolates SessionManager onto a throwaway SQLite
  file (mirrors tests/test_api/test_status_routes_ssot.py's
  ``_isolated_sm_db``): ``TestClient(app)``'s lifespan (app/main.py) always
  calls ``get_session_manager()`` regardless of which routes a test exercises,
  so without this the real ``data/sessions.db`` would be opened. Scoped to
  the *module* here (unlike the per-function original) — one lifespan
  startup for the whole file cuts test time by >10x (measured: function-
  scoped ~23s/test vs module-scoped ~4s/test-equivalent) and none of this
  file's tests depend on cross-test SessionManager isolation.
- ``narrate_eod_digest`` is the module's one real LLM call (services/
  trading/eod_digest.py) — always patched with an ``AsyncMock`` per the
  global "실 LLM 금지" constraint. ``build_eod_digest`` itself does NOT call
  an LLM (pure aggregation) and is left real, exercising the actual
  digest-reassembly path against the stub coordinator + tmp storage.

Review-fix update (E3-4 리뷰픽스, this file's second pass):
- ``staleness_note`` lives ONLY at ``digest["staleness_note"]`` now, in both
  GET and POST responses (the POST route used to also mirror it as a
  top-level sidecar key -- removed, single exposure depth).
- ``_compute_staleness_note`` (route module) now checks regime_snapshot
  staleness independently from strategy_revisions staleness, not just
  strategy -- see the two new tests near the end of the POST section.
- ``stub_coordinator._notify_eod_summary`` must have an explicit
  ``return_value`` now that the route surfaces it as response field
  ``notified`` (a bare ``AsyncMock()`` awaits to a ``MagicMock``, which
  isn't JSON-serializable and would 500 every POST test).
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import services.session_manager as sm_module
from app.api.routes.trading import get_trading_coordinator
from app.main import app
from services.storage_service import StorageService
from services.trading.strategy import TradingStrategy

KST = timezone(timedelta(hours=9))
TEST_SM_DB_PATH = "data/test_eod_report_api_sm.db"


@pytest.fixture(scope="module")
def _isolated_sm_db():
    if os.path.exists(TEST_SM_DB_PATH):
        os.remove(TEST_SM_DB_PATH)
    original_db_path = sm_module.DB_PATH
    original_singleton = sm_module._session_manager
    sm_module.DB_PATH = TEST_SM_DB_PATH
    sm_module._session_manager = None
    try:
        yield
    finally:
        sm_module.DB_PATH = original_db_path
        sm_module._session_manager = original_singleton
        if os.path.exists(TEST_SM_DB_PATH):
            os.remove(TEST_SM_DB_PATH)


@pytest.fixture(scope="module")
def client(_isolated_sm_db):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def tmp_storage(tmp_path):
    return StorageService(db_path=str(tmp_path / "storage.db"))


@pytest.fixture
def stub_coordinator():
    coordinator = MagicMock()
    coordinator.get_watch_list.return_value = []
    coordinator.get_portfolio_summary.return_value = {
        "cash": 10_000_000,
        "total_equity": 50_000_000,
        "positions": [],
    }
    # Must be JSON-serializable -- the route now forwards this call's
    # return value verbatim as response field "notified" (E3-4 리뷰픽스).
    coordinator._notify_eod_summary = AsyncMock(return_value=True)
    app.dependency_overrides[get_trading_coordinator] = lambda: coordinator
    yield coordinator
    app.dependency_overrides.clear()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _save_review(tmp_storage, trade_date, digest=None, narrative=None, extra=None):
    report = {
        "trade_date": trade_date,
        "portfolio": {},
        "per_stock": [],
        "agents": [],
        "regime": {},
    }
    if digest is not None:
        report["digest"] = digest
    if narrative is not None:
        report["narrative"] = narrative
    if extra:
        report.update(extra)
    _run(
        tmp_storage.save_eod_review(
            {"trade_date": trade_date, "report_json": json.dumps(report)}
        )
    )
    return report


def _save_strategy_revision(tmp_storage, revision_id, trade_date):
    _run(
        tmp_storage.save_strategy_revision(
            {
                "id": revision_id,
                "trade_date": trade_date,
                "source": "eod_consensus",
                "stance": "neutral",
                "consensus_level": 0.9,
                "changed": 0,
                "strategy_json": TradingStrategy().model_dump_json(),
                "parent_revision_id": None,
                "rationale": "r",
                "votes_json": None,
                "regime_snapshot_id": None,
            }
        )
    )


def _save_regime_snapshot(tmp_storage, snapshot_id, trade_date):
    _run(
        tmp_storage.save_regime_snapshot(
            {
                "id": snapshot_id,
                "trade_date": trade_date,
                "breadth_buy": 100,
                "breadth_sell": 50,
                "breadth_hold": 10,
                "breadth_ratio": 0.6,
                "regime_label": "risk_on",
            }
        )
    )


# -------------------------------------------
# GET /trading/eod-report
# -------------------------------------------


def test_get_eod_report_latest_when_no_date(client: TestClient, tmp_storage):
    _save_review(tmp_storage, "2026-07-15", digest={"trade_date": "2026-07-15"}, narrative="어제 요약")
    _save_review(tmp_storage, "2026-07-16", digest={"trade_date": "2026-07-16"}, narrative="오늘 요약")

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/eod-report")

    assert response.status_code == 200
    body = response.json()
    assert body["trade_date"] == "2026-07-16"
    assert body["narrative"] == "오늘 요약"
    assert body["digest"]["trade_date"] == "2026-07-16"
    assert "created_at" in body


def test_get_eod_report_by_date(client: TestClient, tmp_storage):
    _save_review(tmp_storage, "2026-07-15", digest={"trade_date": "2026-07-15"}, narrative="어제 요약")
    _save_review(tmp_storage, "2026-07-16", digest={"trade_date": "2026-07-16"}, narrative="오늘 요약")

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/eod-report", params={"date": "2026-07-15"})

    assert response.status_code == 200
    body = response.json()
    assert body["trade_date"] == "2026-07-15"
    assert body["narrative"] == "어제 요약"


def test_get_eod_report_404_for_missing_date(client: TestClient, tmp_storage):
    _save_review(tmp_storage, "2026-07-15")

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/eod-report", params={"date": "2026-01-01"})

    assert response.status_code == 404


def test_get_eod_report_404_when_table_empty(client: TestClient, tmp_storage):
    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/eod-report")

    assert response.status_code == 404


# -------------------------------------------
# POST /trading/eod-report/run
# -------------------------------------------


def test_post_eod_report_run_default_date_is_today_kst(client, stub_coordinator, tmp_storage):
    expected_date = datetime.now(KST).strftime("%Y-%m-%d")
    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="브리핑")
    ):
        response = client.post("/api/trading/eod-report/run", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["trade_date"] == expected_date
    assert body["narrative"] == "브리핑"
    stub_coordinator._notify_eod_summary.assert_awaited_once_with(expected_date)


def test_post_eod_report_run_explicit_past_date_saves_and_notifies(
    client, stub_coordinator, tmp_storage
):
    trade_date = "2026-07-10"
    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="과거 브리핑")
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": trade_date})

    assert response.status_code == 200
    body = response.json()
    assert body["trade_date"] == trade_date
    assert body["digest"]["trade_date"] == trade_date
    assert body["narrative"] == "과거 브리핑"
    assert body["notified"] is True  # stub_coordinator default return_value=True
    stub_coordinator._notify_eod_summary.assert_awaited_once_with(trade_date)

    rows = _run(tmp_storage.get_eod_reviews(limit=10))
    assert len(rows) == 1
    saved = json.loads(rows[0]["report_json"])
    assert saved["digest"]["trade_date"] == trade_date
    assert saved["narrative"] == "과거 브리핑"
    assert "staleness_note" in saved["digest"]


def test_post_eod_report_run_notified_false_when_notify_skips(
    client, stub_coordinator, tmp_storage
):
    """_notify_eod_summary가 자체 stale 가드 등으로 스킵하면 False를 반환하고
    (E3-4 리뷰픽스), 이 라우트는 그 값을 response["notified"]에 그대로
    실어 보낸다."""
    stub_coordinator._notify_eod_summary = AsyncMock(return_value=False)
    trade_date = "2026-07-10"
    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="x")
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": trade_date})

    assert response.status_code == 200
    assert response.json()["notified"] is False


def test_post_eod_report_run_reuses_existing_row_other_sections(
    client, stub_coordinator, tmp_storage
):
    """기존 행이 있으면 digest/narrative만 갱신하고 나머지 섹션은 보존한다."""
    trade_date = "2026-07-10"
    _save_review(
        tmp_storage,
        trade_date,
        digest={"trade_date": trade_date, "stale": True},
        narrative="구버전",
        extra={"portfolio": {"equity": 999}},
    )

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="새 브리핑")
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": trade_date})

    assert response.status_code == 200
    rows = _run(tmp_storage.get_eod_reviews(limit=10))
    saved = json.loads(rows[0]["report_json"])
    assert saved["portfolio"] == {"equity": 999}  # 보존
    assert saved["narrative"] == "새 브리핑"  # 갱신


def test_post_eod_report_run_staleness_note_set_for_past_date(
    client, stub_coordinator, tmp_storage
):
    """strategy_revisions 최신 행이 요청 date보다 최신이면 digest.staleness_note가
    채워지고 "strategy"를 언급한다."""
    _save_strategy_revision(tmp_storage, "rev-latest", "2026-07-16")
    trade_date = "2026-07-10"

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="x")
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": trade_date})

    note = response.json()["digest"]["staleness_note"]
    assert note is not None
    assert "strategy" in note
    assert "2026-07-16" in note
    assert "regime" not in note  # regime 쪽은 리비전이 없어 stale 판정 대상 아님


def test_post_eod_report_run_staleness_note_regime_only(
    client, stub_coordinator, tmp_storage
):
    """regime_snapshot 최신 행만 요청 date보다 최신인 경우(전략 합의는 정상,
    레짐 파이프라인만 정체된 시나리오) -- digest.staleness_note가 "regime"을
    언급하고 "strategy"는 언급하지 않는다 (리뷰픽스: 최초 구현은 regime을
    검사하지 않아 이 케이스를 오판(None)했다)."""
    _save_regime_snapshot(tmp_storage, "regime-latest", "2026-07-16")
    trade_date = "2026-07-10"

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="x")
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": trade_date})

    note = response.json()["digest"]["staleness_note"]
    assert note is not None
    assert "regime" in note
    assert "2026-07-16" in note
    assert "strategy" not in note


def test_post_eod_report_run_staleness_note_both_stale(
    client, stub_coordinator, tmp_storage
):
    """strategy/regime 둘 다 요청 date보다 최신이면 둘 다 개별 언급한다."""
    _save_strategy_revision(tmp_storage, "rev-latest", "2026-07-15")
    _save_regime_snapshot(tmp_storage, "regime-latest", "2026-07-16")
    trade_date = "2026-07-10"

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="x")
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": trade_date})

    note = response.json()["digest"]["staleness_note"]
    assert note is not None
    assert "strategy" in note and "2026-07-15" in note
    assert "regime" in note and "2026-07-16" in note


def test_post_eod_report_run_staleness_note_none_when_dates_match(
    client, stub_coordinator, tmp_storage
):
    trade_date = "2026-07-10"
    _save_strategy_revision(tmp_storage, "rev-match", trade_date)
    _save_regime_snapshot(tmp_storage, "regime-match", trade_date)

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="x")
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": trade_date})

    assert response.json()["digest"]["staleness_note"] is None


def test_post_eod_report_run_staleness_note_none_when_no_revisions(
    client, stub_coordinator, tmp_storage
):
    """판단 불가(strategy_revisions도 regime_snapshot도 无) -> None."""
    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value="x")
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": "2026-07-10"})

    assert response.json()["digest"]["staleness_note"] is None


def test_post_eod_report_run_llm_failure_returns_200_with_none_narrative(
    client, stub_coordinator, tmp_storage
):
    """narrate_eod_digest 실패(None 반환)에도 200 + narrative None (E3-2 계약)."""
    trade_date = "2026-07-10"
    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ), patch(
        "app.api.routes.trading.narrate_eod_digest", new=AsyncMock(return_value=None)
    ):
        response = client.post("/api/trading/eod-report/run", json={"date": trade_date})

    assert response.status_code == 200
    body = response.json()
    assert body["narrative"] is None
    stub_coordinator._notify_eod_summary.assert_awaited_once_with(trade_date)
