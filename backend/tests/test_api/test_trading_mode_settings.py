"""R3 t2: per-market trading_mode settings API + autonomy limits.

GET/PUT /api/settings/trading-mode backed by the persisted app_settings store
(R3 t1). Defaults: both markets 'hitl', master gate (AUTONOMY_ENABLED env)
False. RiskParameters gains the autonomy safety-rail defaults.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import services.storage_service as storage_module
from services.storage_service import StorageService
from services.trading.models import RiskParameters

TEST_DB = Path("data/test_trading_mode.db")


@pytest.fixture
def isolated_storage(monkeypatch):
    if TEST_DB.exists():
        os.remove(TEST_DB)
    service = StorageService(db_path=TEST_DB)
    monkeypatch.setattr(storage_module, "_storage_service", service)
    yield service
    if TEST_DB.exists():
        os.remove(TEST_DB)


def test_risk_parameters_have_autonomy_limits():
    params = RiskParameters()
    assert params.max_daily_loss_pct == 3.0
    assert params.max_open_positions == 5
    assert params.max_trade_notional_pct == 15.0


def test_get_defaults_hitl_and_master_disabled(client: TestClient, isolated_storage):
    response = client.get("/api/settings/trading-mode")
    assert response.status_code == 200
    data = response.json()
    assert data["kiwoom"] == "hitl"
    assert data["coin"] == "hitl"
    assert data["master_enabled"] is False  # AUTONOMY_ENABLED defaults False


def test_put_updates_one_market_and_persists(client: TestClient, isolated_storage):
    response = client.put(
        "/api/settings/trading-mode",
        json={"market": "kiwoom", "mode": "autonomous"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["kiwoom"] == "autonomous"
    assert data["coin"] == "hitl"

    # Reflected on subsequent GET (read from the persisted store)
    data = client.get("/api/settings/trading-mode").json()
    assert data["kiwoom"] == "autonomous"


def test_put_rejects_invalid_values(client: TestClient, isolated_storage):
    assert client.put(
        "/api/settings/trading-mode", json={"market": "stock", "mode": "hitl"}
    ).status_code == 422
    assert client.put(
        "/api/settings/trading-mode", json={"market": "kiwoom", "mode": "yolo"}
    ).status_code == 422
