"""재시작 안전 Task 3: ChatCoordinator 런타임 설정의 영속과 부팅 재개.

_running/check_interval/max_concurrent가 전부 인메모리라 재시작이
생성자 기본값(1분 / 동시 3)으로 되돌렸다. 운영자가 동시 토론을 10으로
올려도 배포 한 번이면 3으로 돌아가, 매번 손으로 다시 넣어야 했다.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.agent_chat.coordinator import ChatCoordinator
from services.storage_service import StorageService

pytestmark = pytest.mark.asyncio


async def test_persist_writes_running_and_settings(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = ChatCoordinator(check_interval_minutes=5, max_concurrent_discussions=10)
    coord._running = True

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord._persist_runtime_state()
        blob = await storage.get_app_setting(coord._RUNTIME_KEY)

    data = json.loads(blob)
    assert data == {"running": True, "check_interval": 5, "max_concurrent": 10}


async def test_resume_restores_settings_and_starts(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = ChatCoordinator()  # 기본값 1 / 3
    await storage.set_app_setting(
        coord._RUNTIME_KEY,
        json.dumps({"running": True, "check_interval": 5, "max_concurrent": 10}),
    )
    coord.start = AsyncMock()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        resumed = await coord.resume_if_persisted()

    assert resumed is True
    assert coord.check_interval == 5
    assert coord.max_concurrent == 10
    coord.start.assert_awaited_once()


async def test_resume_noop_when_not_running(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = ChatCoordinator()
    await storage.set_app_setting(
        coord._RUNTIME_KEY,
        json.dumps({"running": False, "check_interval": 5, "max_concurrent": 10}),
    )
    coord.start = AsyncMock()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        resumed = await coord.resume_if_persisted()

    assert resumed is False
    coord.start.assert_not_awaited()
    # 재개하지 않을 때는 설정도 건드리지 않는다.
    assert coord.check_interval == 1
    assert coord.max_concurrent == 3


async def test_resume_noop_when_no_blob(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = ChatCoordinator()
    coord.start = AsyncMock()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        resumed = await coord.resume_if_persisted()

    assert resumed is False
    coord.start.assert_not_awaited()


async def test_resume_ignores_nonsense_settings(tmp_path):
    """0이나 음수, 문자열 같은 값은 무시하고 기본값을 지킨다 —
    check_interval=0이면 APScheduler가 매초 도는 폭주가 된다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = ChatCoordinator()
    await storage.set_app_setting(
        coord._RUNTIME_KEY,
        json.dumps({"running": True, "check_interval": 0, "max_concurrent": "열"}),
    )
    coord.start = AsyncMock()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        resumed = await coord.resume_if_persisted()

    assert resumed is True
    assert coord.check_interval == 1
    assert coord.max_concurrent == 3
