"""재시작 안전 Task 1: TradingMode의 SQLite 영속.

positions/trade_queue/watch_list/risk_params는 이미 _persist_state 블롭으로
재시작을 넘기지만 `mode`는 담기지 않았다 — 그래서 부팅 시 "꺼져 있었나 켜져
있었나"를 알 수 없고, 자동 방어 복원을 결정할 근거가 없었다.

패치 대상 주의(test_risk_params_persist.py와 동일): _persist_state/
_restore_state는 get_storage_service를 메서드 본문에서 LOCAL import하므로
호출 시점에 services.storage_service에서 이름을 다시 가져온다. 소스를
패치해야 하며 코디네이터 모듈의 사본을 패치하면 보이지 않는다.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.storage_service import StorageService
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import TradingMode

pytestmark = pytest.mark.asyncio


def _make_coordinator() -> ExecutionCoordinator:
    """test_risk_params_persist.py의 bare-construction 관례를 따른다 —
    persist/restore는 브로커를 건드리지 않는다."""
    return ExecutionCoordinator(kiwoom_client=None)


async def test_mode_is_persisted(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True
    coord._state.mode = TradingMode.ACTIVE

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord._persist_state()
        blob = await storage.get_app_setting(coord._STATE_KEY)

    assert json.loads(blob)["mode"] == "active"


async def test_paused_mode_is_persisted(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True
    coord._state.mode = TradingMode.PAUSED

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord._persist_state()
        blob = await storage.get_app_setting(coord._STATE_KEY)

    assert json.loads(blob)["mode"] == "paused"


async def test_mode_is_active_before_persistence_is_armed(tmp_path):
    """순서 회귀 방지. 원래 start()는 _persistence_active=True를 mode 설정보다
    먼저 실행해서, 그 사이에 persist가 트리거되면 직전 mode(STOPPED)가
    저장되고 다음 부팅의 자동 복원이 건너뛰어졌다.

    risk_monitor.start()는 두 문장 **뒤**에 온다. 그 시점에 mode가 이미
    ACTIVE인지 보면 순서가 뒤집혔는지 정확히 잡힌다 — 옛 순서에서는
    이 시점의 mode가 STOPPED다.
    """
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    seen = {}

    async def _capture():
        seen["mode"] = coord._state.mode
        seen["persistence_active"] = coord._persistence_active

    coord._refresh_account_info = AsyncMock()
    coord._restore_state = AsyncMock()
    coord._restore_strategy = AsyncMock()
    coord.risk_monitor.start = AsyncMock(side_effect=_capture)
    coord._notify_state_change = AsyncMock()
    coord.process_trade_queue = AsyncMock()
    coord.get_trade_queue = lambda: []
    coord._market_hours.get_market_session = lambda _m: type(
        "S", (), {"is_open": False}
    )()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord.start()
        await coord.stop()

    assert seen["mode"] == TradingMode.ACTIVE
    assert seen["persistence_active"] is True


async def test_pause_persists_mode(tmp_path):
    """IMPORTANT 3 (2026-07-29): pause()가 mode 변경을 즉시 영속해야 한다.
    다른 뮤테이터가 우연히 persist를 트리거할 때까지 기다리면, 그 사이
    프로세스가 죽었을 때 블롭이 여전히 active로 남고, 부팅 재개가
    pause()로 잠갔던 신규 진입을 무시한 채 켠다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True
    coord._state.mode = TradingMode.ACTIVE

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord.pause("operator pause")
        blob = await storage.get_app_setting(coord._STATE_KEY)

    assert json.loads(blob)["mode"] == "paused"


async def test_resume_persists_mode(tmp_path):
    """IMPORTANT 3: resume()도 동일하게 즉시 영속해야 한다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True
    coord._state.mode = TradingMode.PAUSED
    coord._market_hours.get_market_session = lambda _m: type(
        "S", (), {"is_open": False}
    )()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord.resume()
        blob = await storage.get_app_setting(coord._STATE_KEY)

    assert json.loads(blob)["mode"] == "active"


async def test_stop_persists_mode_unconditionally_even_if_never_started(tmp_path):
    """IMPORTANT 3: stop()의 persist는 무조건이어야 한다. 이 프로세스에서
    한 번도 start()된 적 없는(_persistence_active=False인) 코디네이터의
    stop()도 mode=stopped를 반드시 써야 한다 — 그렇지 않으면 이전 세션이
    남긴 stale "active"가 다음 부팅에서 트레이딩을 무단으로 켠다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    assert coord._persistence_active is False  # bare construction, never start()ed

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        # 이전 세션이 남긴 stale "active" 블롭을 흉내낸다.
        await storage.set_app_setting(
            coord._STATE_KEY,
            json.dumps({
                "positions": [], "trade_queue": [], "watch_list": [],
                "daily_trades_count": 0, "daily_count_date": "2026-07-29",
                "mode": "active",
            }),
        )

        await coord.stop()
        blob = await storage.get_app_setting(coord._STATE_KEY)

    assert json.loads(blob)["mode"] == "stopped"


async def test_restore_ignores_mode_and_survives_blob_without_it(tmp_path):
    """이 기능 이전에 저장된 블롭(mode 키 없음)을 복원해도 터지지 않아야
    하고, _restore_state는 mode를 적용하지 않는다 — 재개 판단은
    resume_if_persisted 전용이고 수동 start()는 무조건 ACTIVE로 간다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True
    coord._state.mode = TradingMode.STOPPED

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await storage.set_app_setting(
            coord._STATE_KEY,
            json.dumps({
                "positions": [],
                "trade_queue": [],
                "watch_list": [],
                "daily_trades_count": 0,
                "daily_count_date": "2026-07-29",
            }),
        )
        await coord._restore_state()

    assert coord._state.mode == TradingMode.STOPPED
