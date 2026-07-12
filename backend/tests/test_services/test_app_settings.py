"""R3 t1: app_settings key-value persistence in storage_service.

Runtime settings were previously all in-memory (lost on restart). The
Autonomous|HITL trading_mode must survive restarts, so storage_service gains
a generic app_settings table + helpers.
"""

import os
from pathlib import Path

import pytest

from services.storage_service import StorageService

TEST_DB = Path("data/test_app_settings.db")


@pytest.fixture
async def storage():
    if TEST_DB.exists():
        os.remove(TEST_DB)
    service = StorageService(db_path=TEST_DB)
    await service.initialize()
    yield service
    if TEST_DB.exists():
        os.remove(TEST_DB)


async def test_set_get_round_trip(storage):
    await storage.set_app_setting("trading_mode:kiwoom", "autonomous")
    assert await storage.get_app_setting("trading_mode:kiwoom") == "autonomous"


async def test_missing_key_returns_default(storage):
    assert await storage.get_app_setting("trading_mode:coin") is None
    assert await storage.get_app_setting("trading_mode:coin", "hitl") == "hitl"


async def test_overwrite_updates_value(storage):
    await storage.set_app_setting("k", "v1")
    await storage.set_app_setting("k", "v2")
    assert await storage.get_app_setting("k") == "v2"


async def test_survives_a_fresh_service_instance(storage):
    """The whole point: settings must outlive the process."""
    await storage.set_app_setting("trading_mode:kiwoom", "autonomous")

    fresh = StorageService(db_path=TEST_DB)
    await fresh.initialize()
    assert await fresh.get_app_setting("trading_mode:kiwoom") == "autonomous"
