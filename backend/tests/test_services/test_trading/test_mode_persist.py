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
from services.trading.models import ManagedPosition, TradingMode

pytestmark = pytest.mark.asyncio


def _make_coordinator() -> ExecutionCoordinator:
    """test_risk_params_persist.py의 bare-construction 관례를 따른다 —
    persist/restore는 브로커를 건드리지 않는다."""
    return ExecutionCoordinator(kiwoom_client=None)


def _seed_nonempty_blob(mode: str = "active") -> dict:
    """094840(슈프리마HQ) 실 포지션을 흉내낸, 비어있지 않은 스냅샷. 이
    회귀가 실서비스에서 지웠을 뻔한 것과 같은 모양 -- 손절가가 살아있는
    포지션 하나, 워치 하나, 0이 아닌 daily_trades_count."""
    return {
        "positions": [
            {
                "ticker": "094840",
                "stock_name": "슈프리마HQ",
                "quantity": 1315,
                "avg_price": 13060.0,
                "stop_loss": 12492.0,
            }
        ],
        "trade_queue": [],
        "watch_list": [
            {"id": "watch_1", "session_id": "s1", "ticker": "005930"}
        ],
        "daily_trades_count": 3,
        "daily_count_date": "2026-07-29",
        "mode": mode,
    }


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
    남긴 stale "active"가 다음 부팅에서 트레이딩을 무단으로 켠다.

    REGRESSION 회귀 방지(2026-07-29 리뷰): 블롭을 positions=[]로 심으면
    이 테스트는 "무조건 mode를 쓴다"만 확인할 뿐 "그 김에 positions까지
    지우지는 않는다"는 전혀 검증하지 못한다 -- 지울 게 없으니 어떤 구현도
    통과한다. 비어있지 않은 스냅샷을 심어서, mode=stopped를 쓰는 동시에
    positions/watch_list/daily_trades_count가 살아남는지까지 함께 잡는다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    assert coord._persistence_active is False  # bare construction, never start()ed

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        # 이전 세션이 남긴, 실 포지션이 있는 "active" 블롭을 흉내낸다.
        await storage.set_app_setting(
            coord._STATE_KEY, json.dumps(_seed_nonempty_blob("active"))
        )

        await coord.stop()
        blob = json.loads(await storage.get_app_setting(coord._STATE_KEY))

    assert blob["mode"] == "stopped"
    assert blob["positions"] == _seed_nonempty_blob()["positions"]
    assert blob["watch_list"] == _seed_nonempty_blob()["watch_list"]
    assert blob["daily_trades_count"] == 3


async def test_pause_mode_only_persist_never_clobbers_state(tmp_path):
    """REGRESSION 회귀 방지: pause()도 stop()과 같은 구멍이 있었다 -- 한 번도
    start()되지 않은 코디네이터의 pause()가 mode를 즉시 영속하면서, 메모리
    상 빈 _state를 그대로 직렬화해 블롭의 실제 positions/watch_list/
    daily_trades_count를 지워 버릴 뻔했다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    assert coord._persistence_active is False

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await storage.set_app_setting(
            coord._STATE_KEY, json.dumps(_seed_nonempty_blob("active"))
        )

        await coord.pause("operator pause")
        blob = json.loads(await storage.get_app_setting(coord._STATE_KEY))

    assert blob["mode"] == "paused"
    assert blob["positions"] == _seed_nonempty_blob()["positions"]
    assert blob["watch_list"] == _seed_nonempty_blob()["watch_list"]
    assert blob["daily_trades_count"] == 3


async def test_resume_mode_only_persist_never_clobbers_state(tmp_path):
    """REGRESSION 회귀 방지: resume()도 동일. pause()와 마찬가지로 한 번도
    start()되지 않은 코디네이터가 resume()되는 경로(예: 부팅 직후 사람이
    /trading/resume을 먼저 누르는 첫 배포 창)에서 블롭의 실 데이터를
    지우면 안 된다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    assert coord._persistence_active is False
    coord._market_hours.get_market_session = lambda _m: type(
        "S", (), {"is_open": False}
    )()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await storage.set_app_setting(
            coord._STATE_KEY, json.dumps(_seed_nonempty_blob("paused"))
        )

        await coord.resume()
        blob = json.loads(await storage.get_app_setting(coord._STATE_KEY))

    assert blob["mode"] == "active"
    assert blob["positions"] == _seed_nonempty_blob()["positions"]
    assert blob["watch_list"] == _seed_nonempty_blob()["watch_list"]
    assert blob["daily_trades_count"] == 3


async def test_pause_persists_full_snapshot_when_started(tmp_path):
    """대조군: _persistence_active=True(실제 start()를 거친) 코디네이터의
    pause()는 여전히 전체 스냅샷을 써야 한다 -- mode-only 경로가 시작된
    코디네이터까지 새어 들어가 라이브 포지션을 안 쓰게 되는 회귀가 없는지
    확인한다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()

    coord._refresh_account_info = AsyncMock()
    coord._restore_state = AsyncMock()
    coord._restore_strategy = AsyncMock()
    coord.risk_monitor.start = AsyncMock()
    coord._notify_state_change = AsyncMock()
    coord.process_trade_queue = AsyncMock()
    coord.get_trade_queue = lambda: []
    coord._market_hours.get_market_session = lambda _m: type(
        "S", (), {"is_open": False}
    )()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord.start()
        assert coord._persistence_active is True

        # start() 이후 실제 방어 대상 포지션이 생겼다고 가정 -- 라이브
        # 상황(094840 슈프리마HQ)을 흉내낸다.
        coord._state.positions = [
            ManagedPosition(
                ticker="094840",
                stock_name="슈프리마HQ",
                quantity=1315,
                avg_price=13060.0,
                stop_loss=12492.0,
            )
        ]

        await coord.pause("operator pause")
        blob = json.loads(await storage.get_app_setting(coord._STATE_KEY))

        await coord.stop()  # patch 안에서 정리 -- 실제 storage 싱글톤을 안 건드리도록

    assert blob["mode"] == "paused"
    assert len(blob["positions"]) == 1
    assert blob["positions"][0]["ticker"] == "094840"
    assert blob["positions"][0]["stop_loss"] == 12492.0


async def test_persist_fields_leaves_corrupt_blob_untouched(tmp_path):
    """일반화된 `_persist_fields`의 안전성(2026-07-29 리뷰: "읽어보면 맞다"로만
    확인되고 테스트가 없다고 지적된 속성). 기존 블롭이 파싱 불가능한
    JSON이면 `json.loads`가 try 안에서 실패해 아무것도 쓰지 않는다 --
    부분 블롭으로 원본을 덮어쓰는 것보다, 손상된 원본이라도 그대로 남는
    편이 낫다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    corrupt = "{not json"

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await storage.set_app_setting(coord._STATE_KEY, corrupt)

        await coord._persist_fields(mode="stopped")

        blob = await storage.get_app_setting(coord._STATE_KEY)

    assert blob == corrupt


async def test_persist_fields_no_write_when_parsed_blob_is_not_a_dict(tmp_path):
    """파싱은 되지만 dict가 아닌 블롭(JSON 배열, `null` 등)도 마찬가지로
    아무것도 쓰지 않는다 -- 원본을 dict가 아닌 값으로 오염시킬 수 없다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    not_a_dict = json.dumps([1, 2, 3])

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await storage.set_app_setting(coord._STATE_KEY, not_a_dict)

        await coord._persist_fields(mode="stopped")

        blob = await storage.get_app_setting(coord._STATE_KEY)

    assert blob == not_a_dict


async def test_persist_fields_null_blob_also_results_in_no_write(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    null_blob = json.dumps(None)

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await storage.set_app_setting(coord._STATE_KEY, null_blob)

        await coord._persist_fields(mode="stopped")

        blob = await storage.get_app_setting(coord._STATE_KEY)

    assert blob == null_blob


async def test_persist_fields_writes_only_passed_keys_when_blob_absent(tmp_path):
    """블롭이 아직 없으면 넘겨받은 필드만 담은 새 블롭을 쓴다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord._persist_fields(mode="stopped")
        blob = json.loads(await storage.get_app_setting(coord._STATE_KEY))

    assert blob == {"mode": "stopped"}


async def test_persist_fields_arbitrary_key_preserves_untouched_fields(tmp_path):
    """mode 외 임의 키(예: risk_params)로도 동작하고, 건드리지 않은 다른
    필드는 그대로 남는다 -- PUT /risk-params 라우트가 실제로 쓰는 모양."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await storage.set_app_setting(
            coord._STATE_KEY, json.dumps(_seed_nonempty_blob("active"))
        )

        await coord._persist_fields(risk_params={"max_trade_notional_pct": 22.0})

        blob = json.loads(await storage.get_app_setting(coord._STATE_KEY))

    assert blob["risk_params"] == {"max_trade_notional_pct": 22.0}
    assert blob["mode"] == "active"
    assert blob["positions"] == _seed_nonempty_blob()["positions"]


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
