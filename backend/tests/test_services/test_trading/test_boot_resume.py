"""재시작 안전 Task 2: 부팅 자동 방어 복원의 코디네이터 쪽 절반.

resume_if_persisted()는 저장된 mode만 보고 방어를 되살릴지 정한다.
큐는 절대 드레인하지 않는다 — 사람이 앞에 없는 장중 재시작이 몇 시간 묵은
가격으로 주문을 내지 않게 한다(QueuedTrade에 만료가 없고
process_trade_queue에 신선도 검사가 없다).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.storage_service import StorageService
from services.trading.coordinator import ExecutionCoordinator

pytestmark = pytest.mark.asyncio


def _make_coordinator() -> ExecutionCoordinator:
    return ExecutionCoordinator(kiwoom_client=None)


async def _seed(storage: StorageService, coord: ExecutionCoordinator, mode) -> None:
    """mode 필드만 있는 최소 블롭을 심는다. mode=None이면 필드를 아예 뺀다
    (이 기능 이전에 저장된 블롭 모양)."""
    payload = {
        "positions": [],
        "trade_queue": [],
        "watch_list": [],
        "daily_trades_count": 0,
        "daily_count_date": "2026-07-29",
    }
    if mode is not None:
        payload["mode"] = mode
    await storage.set_app_setting(coord._STATE_KEY, json.dumps(payload))


async def test_active_resumes_without_draining(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    await _seed(storage, coord, "active")

    coord.start = AsyncMock()
    coord.pause = AsyncMock()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        resumed = await coord.resume_if_persisted()

    assert resumed is True
    coord.start.assert_awaited_once_with(drain_queue=False, boot_resume=True)
    coord.pause.assert_not_awaited()


async def test_paused_resumes_then_pauses(tmp_path):
    """paused로 껐으면 방어는 켜고 신규 진입만 잠근 채로 되살아나야 한다 —
    pause()는 감시를 유지한다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    await _seed(storage, coord, "paused")

    coord.start = AsyncMock()
    coord.pause = AsyncMock()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        resumed = await coord.resume_if_persisted()

    assert resumed is True
    coord.start.assert_awaited_once_with(drain_queue=False, boot_resume=True)
    coord.pause.assert_awaited_once()


@pytest.mark.parametrize("mode", ["stopped", None])
async def test_stopped_or_missing_mode_is_noop(tmp_path, mode):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    await _seed(storage, coord, mode)

    coord.start = AsyncMock()
    coord.pause = AsyncMock()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        resumed = await coord.resume_if_persisted()

    assert resumed is False
    coord.start.assert_not_awaited()


async def test_no_blob_at_all_is_noop(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()

    coord.start = AsyncMock()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        resumed = await coord.resume_if_persisted()

    assert resumed is False
    coord.start.assert_not_awaited()


async def test_drain_queue_false_skips_process_trade_queue(tmp_path):
    """start(drain_queue=False)는 장이 열려 있고 큐가 있어도
    process_trade_queue를 부르지 않는다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()

    coord._refresh_account_info = AsyncMock()
    coord._restore_state = AsyncMock()
    coord._restore_strategy = AsyncMock()
    coord.risk_monitor.start = AsyncMock()
    coord._notify_state_change = AsyncMock()
    coord.process_trade_queue = AsyncMock()
    coord.get_trade_queue = lambda: [object()]  # 큐가 비어 있지 않다
    coord._market_hours.get_market_session = lambda _m: type(
        "S", (), {"is_open": True}
    )()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord.start(drain_queue=False)
        # stop()은 _persist_state를 부르므로 반드시 patch 안에서 정리한다 —
        # 밖에서 부르면 실제 storage 싱글톤(운영 DB)을 건드린다.
        await coord.stop()

    coord.process_trade_queue.assert_not_awaited()


async def test_drain_queue_default_true_drains(tmp_path):
    """수동 /trading/start 경로(기본값)는 지금 동작 그대로 드레인한다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()

    coord._refresh_account_info = AsyncMock()
    coord._restore_state = AsyncMock()
    coord._restore_strategy = AsyncMock()
    coord.risk_monitor.start = AsyncMock()
    coord._notify_state_change = AsyncMock()
    coord.process_trade_queue = AsyncMock()
    coord.get_trade_queue = lambda: [object()]
    coord._market_hours.get_market_session = lambda _m: type(
        "S", (), {"is_open": True}
    )()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord.start()
        await coord.stop()  # patch 안에서 정리 — 위 테스트와 같은 이유

    coord.process_trade_queue.assert_awaited_once()
