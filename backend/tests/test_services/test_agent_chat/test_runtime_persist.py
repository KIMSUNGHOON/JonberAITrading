"""재시작 안전 Task 3: ChatCoordinator 런타임 설정의 영속과 부팅 재개.

_running/check_interval/max_concurrent가 전부 인메모리라 재시작이
생성자 기본값(1분 / 동시 3)으로 되돌렸다. 운영자가 동시 토론을 10으로
올려도 배포 한 번이면 3으로 돌아가, 매번 손으로 다시 넣어야 했다.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

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


# -------------------------------------------
# CRITICAL 2 (2026-07-29): start()가 실패/취소돼도 _running이 True로 남으면
# 안 된다. 남으면 resume_if_persisted()의 60s wait_for가 타임아웃 났을 때
# _running=True인 채로 멈추고, 운영자가 수동 POST /agent-chat/start를 눌러도
# `if self._running: return`에 걸려 아무 것도 안 하면서 HTTP 200 "started"를
# 돌려준다 — 방어가 실제로는 꺼진 채 성공 응답만 받는다.
# -------------------------------------------


def _patch_position_manager(mock_pm, *, sync_side_effect=None):
    mock_pm.return_value = AsyncMock()
    mock_pm.return_value.start = AsyncMock()
    mock_pm.return_value.set_chat_coordinator = MagicMock()
    mock_pm.return_value.sync_from_account = AsyncMock(side_effect=sync_side_effect)
    mock_pm.return_value.restore_stop_overlay = AsyncMock()
    mock_pm.return_value.get_all_positions = MagicMock(return_value=[])


async def test_start_rolls_back_running_on_exception():
    """position_manager 동기화 실패(예: 키움 장애) 시 _running이 False로
    되돌아가야 한다."""
    coord = ChatCoordinator()

    with patch.object(coord, "_position_manager", None):
        with patch(
            "services.agent_chat.coordinator.get_position_manager"
        ) as mock_pm:
            _patch_position_manager(
                mock_pm, sync_side_effect=RuntimeError("kiwoom down")
            )

            with pytest.raises(RuntimeError, match="kiwoom down"):
                await coord.start()

    assert coord._running is False


async def test_start_rolls_back_running_on_cancellation():
    """CancelledError(부팅 60s wait_for 타임아웃)도 반드시 롤백돼야 한다 —
    Exception이 아니라 BaseException이므로 얕은 except Exception으로는 못
    잡는다."""

    async def _hang(*args, **kwargs):
        await asyncio.sleep(3600)

    coord = ChatCoordinator()

    with patch.object(coord, "_position_manager", None):
        with patch(
            "services.agent_chat.coordinator.get_position_manager"
        ) as mock_pm:
            mock_pm.return_value = AsyncMock()
            mock_pm.return_value.start = AsyncMock()
            mock_pm.return_value.set_chat_coordinator = MagicMock()
            mock_pm.return_value.sync_from_account = _hang

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(coord.start(), timeout=0.05)

    assert coord._running is False


async def test_start_after_rollback_can_retry_and_succeed():
    """롤백 후 재시도가 실제로 다시 시작할 수 있어야 한다 — _running이
    False로 정확히 돌아가지 않으면(예: 값이 아니라 참조가 꼬이는 등) 다음
    start() 호출이 `if self._running: return`에 걸려 조용히 no-op된다."""
    coord = ChatCoordinator()

    with patch.object(coord, "_position_manager", None):
        with patch(
            "services.agent_chat.coordinator.get_position_manager"
        ) as mock_pm:
            _patch_position_manager(
                mock_pm, sync_side_effect=RuntimeError("kiwoom down")
            )
            with pytest.raises(RuntimeError):
                await coord.start()

        with patch(
            "services.agent_chat.coordinator.get_position_manager"
        ) as mock_pm:
            _patch_position_manager(mock_pm)  # 이번엔 성공
            coord._persist_runtime_state = AsyncMock()
            await coord.start()

    assert coord._running is True
    await coord.stop()


# -------------------------------------------
# IMPORTANT 4 (2026-07-29): stop()의 영속 호출은 반드시 finally로 실행돼야
# 한다. scheduler.shutdown()이나 position_manager.stop()이 중간에 터지면
# (CRITICAL 2로 half-started된 코디네이터가 정확히 이 경로를 탄다 —
# _scheduler는 만들어졌지만 .start()된 적이 없어 shutdown()이
# SchedulerNotRunningError를 던진다) 메모리는 _running=False인데 영속된
# 블롭은 여전히 running: True로 남아, 다음 부팅이 운영자가 끈 코디네이터를
# 되살린다.
# -------------------------------------------


async def test_stop_persists_running_false_even_if_body_raises():
    coord = ChatCoordinator()
    coord._running = True
    coord._scheduler = MagicMock()
    coord._scheduler.shutdown = MagicMock(
        side_effect=RuntimeError("scheduler not running")
    )
    coord._persist_runtime_state = AsyncMock()

    with patch.object(coord, "_position_manager", None):
        with pytest.raises(RuntimeError, match="scheduler not running"):
            await coord.stop()

    assert coord._running is False
    coord._persist_runtime_state.assert_awaited_once()
