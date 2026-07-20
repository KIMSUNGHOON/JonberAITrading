"""FI-2: GET /trading/discovery/candidates + GET /trading/discovery/performance.

Convention notes (mirrors tests/test_api/test_eod_report.py, verified before
writing this):
- ``client`` is a module-scoped ``TestClient(app)`` with SessionManager
  isolated onto a throwaway sqlite file -- app/main.py's lifespan always
  calls ``get_session_manager()`` regardless of which routes a test hits.
- ``app.api.routes.trading.get_storage_service`` is patched per-test with an
  ``AsyncMock`` returning a ``tmp_path``-backed ``StorageService`` (real
  schema, no mocking of storage internals) -- keeps the real
  ``data/storage.db`` untouched, no real DB/network anywhere in this file.
- Both routes have no ``Depends()`` dependencies beyond ``get_storage_
  service``, so no ``app.dependency_overrides`` needed here (unlike
  eod-report's ``get_trading_coordinator``).
"""

import os
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import services.session_manager as sm_module
from app.main import app
from services.storage_service import StorageService

TEST_SM_DB_PATH = "data/test_discovery_routes_api_sm.db"


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


async def _seed_candidate(
    storage,
    *,
    trade_date,
    ticker="005930",
    name="삼성전자",
    composite_score=0.72,
    promoted=1,
    skip_reason=None,
    rank=1,
    regime_label="neutral",
    strategy_scores=None,
    close_price=70_000.0,
    fwd_1d=None,
    fwd_5d=None,
):
    strategy_scores = strategy_scores or {
        "momentum": 0.8, "pullback": 0.2, "flow": 0.1, "meanrev": 0.05,
    }
    rows = [
        {
            "trade_date": trade_date,
            "ticker": ticker,
            "name": name,
            "composite_score": composite_score,
            "strategy_scores_json": strategy_scores,
            "regime_label": regime_label,
            "rank": rank,
            "llm_verdict_json": {"suitable": bool(promoted)},
            "promoted": promoted,
            "skip_reason": skip_reason,
            "close_price": close_price,
        }
    ]
    await storage.save_discovery_candidates(rows)
    row_id = rows[0]["id"]
    if fwd_1d is not None or fwd_5d is not None:
        await storage.update_discovery_forward_returns(row_id, fwd_1d=fwd_1d, fwd_5d=fwd_5d)
    return row_id


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


# -------------------------------------------
# GET /trading/discovery/candidates
# -------------------------------------------


def test_get_discovery_candidates_returns_seeded_rows(client: TestClient, tmp_storage):
    trade_date = "2026-07-18"
    _run(_seed_candidate(
        tmp_storage, trade_date=trade_date, ticker="005930", name="삼성전자",
        composite_score=0.72, promoted=1, rank=1,
        strategy_scores={"momentum": 0.9, "pullback": 0.1, "flow": 0.05, "meanrev": 0.0},
        fwd_1d=0.012, fwd_5d=0.03,
    ))

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/discovery/candidates", params={"trade_date": trade_date})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    c = body["candidates"][0]
    assert c["ticker"] == "005930"
    assert c["name"] == "삼성전자"
    assert c["composite_score"] == pytest.approx(0.72)
    assert c["top_strategy_tag"] == "momentum"
    assert c["regime_label"] == "neutral"
    assert c["rank"] == 1
    assert c["promoted"] is True
    assert c["skip_reason"] is None
    assert c["close_price"] == pytest.approx(70_000.0)
    assert c["fwd_1d"] == pytest.approx(0.012)
    assert c["fwd_5d"] == pytest.approx(0.03)
    assert c["fwd_20d"] is None
    assert c["trade_date"] == trade_date
    assert c["id"]


def test_get_discovery_candidates_empty_returns_200(client: TestClient, tmp_storage):
    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/discovery/candidates")

    assert response.status_code == 200
    body = response.json()
    assert body == {"candidates": [], "count": 0}


def test_get_discovery_candidates_filters_by_trade_date(client: TestClient, tmp_storage):
    _run(_seed_candidate(tmp_storage, trade_date="2026-07-17", ticker="A1"))
    _run(_seed_candidate(tmp_storage, trade_date="2026-07-18", ticker="A2"))

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/discovery/candidates", params={"trade_date": "2026-07-17"})

    body = response.json()
    assert body["count"] == 1
    assert body["candidates"][0]["ticker"] == "A1"


def test_get_discovery_candidates_filters_by_promoted_true(client: TestClient, tmp_storage):
    trade_date = "2026-07-18"
    _run(_seed_candidate(tmp_storage, trade_date=trade_date, ticker="PROMO", promoted=1))
    _run(_seed_candidate(tmp_storage, trade_date=trade_date, ticker="SKIP", promoted=0, skip_reason="below_threshold"))

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get(
            "/api/trading/discovery/candidates",
            params={"trade_date": trade_date, "promoted": "true"},
        )

    body = response.json()
    assert body["count"] == 1
    assert body["candidates"][0]["ticker"] == "PROMO"
    assert body["candidates"][0]["promoted"] is True


def test_get_discovery_candidates_filters_by_promoted_false(client: TestClient, tmp_storage):
    trade_date = "2026-07-18"
    _run(_seed_candidate(tmp_storage, trade_date=trade_date, ticker="PROMO", promoted=1))
    _run(_seed_candidate(tmp_storage, trade_date=trade_date, ticker="SKIP", promoted=0, skip_reason="below_threshold"))

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get(
            "/api/trading/discovery/candidates",
            params={"trade_date": trade_date, "promoted": "false"},
        )

    body = response.json()
    assert body["count"] == 1
    assert body["candidates"][0]["ticker"] == "SKIP"
    assert body["candidates"][0]["skip_reason"] == "below_threshold"
    assert body["candidates"][0]["promoted"] is False


def test_get_discovery_candidates_respects_limit_and_offset(client: TestClient, tmp_storage):
    trade_date = "2026-07-18"
    # save_discovery_candidates in one call preserves insertion order for
    # equal created_at -- get_discovery_candidates orders by
    # "created_at DESC, rowid DESC" so within one batch the LAST-inserted
    # row (highest rowid) sorts first.
    for i in range(3):
        _run(_seed_candidate(tmp_storage, trade_date=trade_date, ticker=f"T{i}", rank=i))

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get(
            "/api/trading/discovery/candidates",
            params={"trade_date": trade_date, "limit": 1, "offset": 1},
        )

    body = response.json()
    assert body["count"] == 1
    # newest-first order: T2 (rowid highest), T1, T0 -- offset=1 skips T2.
    assert body["candidates"][0]["ticker"] == "T1"


# -------------------------------------------
# GET /trading/discovery/performance
# -------------------------------------------


def test_get_discovery_performance_empty_returns_200(client: TestClient, tmp_storage):
    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/discovery/performance")

    assert response.status_code == 200
    assert response.json() == {"days": 14, "by_strategy_tag": {}}


def test_get_discovery_performance_groups_by_strategy_tag(client: TestClient, tmp_storage):
    d0 = (date.today() - timedelta(days=2)).isoformat()
    _run(_seed_candidate(
        tmp_storage, trade_date=d0, ticker="A1", promoted=1,
        strategy_scores={"momentum": 0.9, "pullback": 0.1, "flow": 0.2, "meanrev": 0.0},
        fwd_1d=0.01, fwd_5d=0.05,
    ))
    _run(_seed_candidate(
        tmp_storage, trade_date=d0, ticker="A2", promoted=0,
        strategy_scores={"momentum": 0.7, "pullback": 0.2, "flow": 0.1, "meanrev": 0.0},
        fwd_1d=-0.02, fwd_5d=-0.03,
    ))

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/discovery/performance", params={"days": 30})

    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 30
    mom = body["by_strategy_tag"]["momentum"]
    assert mom["candidates"] == 2
    assert mom["promoted"] == 1
    assert mom["avg_fwd_1d"] == pytest.approx((0.01 + -0.02) / 2)
    assert mom["avg_fwd_5d"] == pytest.approx((0.05 + -0.03) / 2)
    assert mom["hit_rate_5d"] == pytest.approx(0.5)


def test_get_discovery_performance_excludes_candidates_outside_window(client: TestClient, tmp_storage):
    old_date = (date.today() - timedelta(days=30)).isoformat()
    _run(_seed_candidate(tmp_storage, trade_date=old_date, ticker="OLD"))

    with patch(
        "app.api.routes.trading.get_storage_service", new=AsyncMock(return_value=tmp_storage)
    ):
        response = client.get("/api/trading/discovery/performance", params={"days": 14})

    assert response.json()["by_strategy_tag"] == {}
