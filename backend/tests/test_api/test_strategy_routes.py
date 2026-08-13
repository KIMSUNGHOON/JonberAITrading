"""Phase3 T5b: strategy REST — revisions listing, manual consensus run,
and manual CRUD persistence wiring.

Convention notes (verified against neighboring tests/test_api files before
writing this):
- ``client: TestClient`` is the repo's established shared fixture
  (tests/conftest.py, module-scoped `with TestClient(app) as test_client`)
  used by test_trading_mode_settings.py / test_approval.py — used here
  instead of constructing a fresh ``TestClient(app)`` per test.
- ``get_trading_coordinator`` is a real ``Depends()`` dependency (see
  app/dependencies.py + app/api/routes/trading.py's
  ``from app.dependencies import get_trading_coordinator`` + per-route
  ``coordinator=Depends(get_trading_coordinator)``), so
  ``app.dependency_overrides[get_trading_coordinator] = lambda: coordinator``
  is the correct/idiomatic FastAPI override mechanism for it — no existing
  test_api file needed to stub a Depends() coordinator via TestClient before,
  so there was no prior local precedent to mirror for that specific piece.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes.trading import get_trading_coordinator
from app.main import app
from services.storage_service import StorageService
from services.trading.strategy import TradingStrategy
from services.trading.strategy_orchestrator import ACTIVE_STRATEGY_REVISION_KEY


@pytest.fixture
def stub_coordinator():
    coordinator = MagicMock()
    coordinator.get_strategy.return_value = None
    app.dependency_overrides[get_trading_coordinator] = lambda: coordinator
    yield coordinator
    app.dependency_overrides.clear()


@pytest.fixture
def tmp_storage(tmp_path):
    return StorageService(db_path=str(tmp_path / "storage.db"))


def test_get_revisions_returns_parsed_rows(client: TestClient, stub_coordinator, tmp_storage):
    import asyncio

    asyncio.get_event_loop().run_until_complete(
        tmp_storage.save_strategy_revision({
            "id": "rev-1", "trade_date": "2026-07-15", "source": "eod_consensus",
            "stance": "defensive", "consensus_level": 0.8, "changed": 1,
            "strategy_json": TradingStrategy().model_dump_json(),
            "parent_revision_id": None, "rationale": "r",
            "votes_json": json.dumps([{"panelist": "risk_officer"}]),
            "regime_snapshot_id": None,
        })
    )
    with patch("app.api.routes.trading.get_storage_service",
               new=AsyncMock(return_value=tmp_storage)):
        response = client.get("/api/trading/strategy/revisions")
    assert response.status_code == 200
    revisions = response.json()["revisions"]
    assert len(revisions) == 1
    assert isinstance(revisions[0]["strategy_json"], dict)   # 파싱돼 나감
    assert isinstance(revisions[0]["votes_json"], list)


def test_post_consensus_run_invokes_force(client: TestClient, stub_coordinator, tmp_storage):
    fake = {"ok": True, "reason": None, "revision_id": "rev-x",
            "stance": "neutral", "consensus_level": 0.9, "changed": False}
    with patch("app.api.routes.trading.get_storage_service",
               new=AsyncMock(return_value=tmp_storage)), \
         patch("app.api.routes.trading.run_strategy_consensus",
               new=AsyncMock(return_value=fake)) as mock_run:
        response = client.post(
            "/api/trading/strategy/consensus/run", json={"trade_date": "2026-07-15"}
        )
    assert response.status_code == 200 and response.json()["revision_id"] == "rev-x"
    assert mock_run.await_args.kwargs.get("force") is True


def test_post_strategy_persists_manual_revision(client: TestClient, stub_coordinator, tmp_storage):
    import asyncio

    with patch("app.api.routes.trading.get_storage_service",
               new=AsyncMock(return_value=tmp_storage)):
        response = client.post(
            "/api/trading/strategy", json={"name": "수동 전략"}
        )
    assert response.status_code == 200
    assert response.json().get("persisted") is True
    rows = asyncio.get_event_loop().run_until_complete(
        tmp_storage.get_strategy_revisions()
    )
    assert len(rows) == 1 and rows[0]["source"] == "manual"
    pointer = asyncio.get_event_loop().run_until_complete(
        tmp_storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY)
    )
    assert pointer == rows[0]["id"]


def test_put_strategy_persists_manual_revision(client: TestClient, stub_coordinator, tmp_storage):
    """PUT follows the same _persist_manual_strategy wiring as POST."""
    import asyncio

    stub_coordinator.get_strategy.return_value = TradingStrategy()
    with patch("app.api.routes.trading.get_storage_service",
               new=AsyncMock(return_value=tmp_storage)):
        response = client.put(
            "/api/trading/strategy", json={"name": "수정된 전략"}
        )
    assert response.status_code == 200
    assert response.json().get("persisted") is True
    rows = asyncio.get_event_loop().run_until_complete(
        tmp_storage.get_strategy_revisions()
    )
    assert len(rows) == 1 and rows[0]["source"] == "manual"


def test_apply_preset_persists_manual_revision_without_mutating_shared_preset(
    client: TestClient, stub_coordinator, tmp_storage
):
    """apply-preset must mirror the POST /strategy persistence wiring (revision
    + pointer move) — AND must deep-copy the preset before persisting, since
    get_strategy_preset returns the shared module-level STRATEGY_PRESETS
    instance for non-CUSTOM presets and persistence mutates strategy.id."""
    import asyncio

    from services.trading.strategy import STRATEGY_PRESETS, StrategyPreset

    original_id = STRATEGY_PRESETS[StrategyPreset.GROWTH_MOMENTUM].id
    with patch("app.api.routes.trading.get_storage_service",
               new=AsyncMock(return_value=tmp_storage)):
        response = client.post("/api/trading/strategy/apply-preset/growth_momentum")
    assert response.status_code == 200
    assert response.json().get("persisted") is True
    rows = asyncio.get_event_loop().run_until_complete(
        tmp_storage.get_strategy_revisions()
    )
    assert len(rows) == 1 and rows[0]["source"] == "manual"
    pointer = asyncio.get_event_loop().run_until_complete(
        tmp_storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY)
    )
    assert pointer == rows[0]["id"]
    # shared preset object must be untouched by the persistence id-mutation
    assert STRATEGY_PRESETS[StrategyPreset.GROWTH_MOMENTUM].id == original_id
    assert STRATEGY_PRESETS[StrategyPreset.GROWTH_MOMENTUM].id != rows[0]["id"]


def test_delete_strategy_clears_pointer(client: TestClient, stub_coordinator, tmp_storage):
    import asyncio

    asyncio.get_event_loop().run_until_complete(
        tmp_storage.set_app_setting(ACTIVE_STRATEGY_REVISION_KEY, "rev-1")
    )
    stub_coordinator.get_strategy.return_value = TradingStrategy()
    with patch("app.api.routes.trading.get_storage_service",
               new=AsyncMock(return_value=tmp_storage)):
        response = client.delete("/api/trading/strategy")
    assert response.status_code == 200
    pointer = asyncio.get_event_loop().run_until_complete(
        tmp_storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY)
    )
    assert pointer == ""   # 빈 센티널 = 해제
