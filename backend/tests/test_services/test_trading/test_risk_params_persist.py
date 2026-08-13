"""Task 3 (autonomous-sizing arc): risk_params SQLite persistence.

Positions/trade_queue/watch_list/daily_count/tracked_orders already survive a
restart via ``ExecutionCoordinator._persist_state`` / ``_restore_state``
(R5-P1 A4 + P2 SSOT prep) — but ``risk_params`` (sizing/gate knobs, now
including T1's ``max_trade_notional_pct``) was never included in that blob,
so a restart silently reverted any live risk-params tuning back to the
``RiskParameters()`` defaults.

``_restore_state`` must apply the restored risk_params IN-PLACE via
``setattr`` rather than rebinding ``self.risk_params`` — the same
``RiskParameters`` instance is reference-shared with ``PortfolioAgent``,
``RiskMonitor``, and ``TradingState`` (all captured in ``__init__``), so a
rebind would desync those holders from the coordinator's own copy.

Patch target note (mirrors test_strategy_restore.py, verified by reading
``_persist_state``/``_restore_state``): both do their
``get_storage_service`` import LOCALLY inside the method body, which
re-fetches the name from ``services.storage_service`` at call time —
patching ``services.storage_service.get_storage_service`` (the source) is
required; patching the coordinator module's copy would not be seen.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.api.routes import trading as trading_mod
from services.storage_service import StorageService
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import ManagedPosition

pytestmark = pytest.mark.asyncio


def _make_coordinator() -> ExecutionCoordinator:
    """Mirrors test_watch_list_persistence.py / test_strategy_restore.py's
    bare-construction convention — persist/restore never touch the broker."""
    return ExecutionCoordinator(kiwoom_client=None)


async def test_risk_params_survive_persist_restore(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True
    coord.risk_params.max_trade_notional_pct = 22.0
    ref = coord.risk_params  # reference identity check

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await coord._persist_state()
        coord.risk_params.max_trade_notional_pct = 15.0  # restore must overwrite
        await coord._restore_state()

    assert coord.risk_params.max_trade_notional_pct == 22.0
    assert coord.risk_params is ref  # in-place, not rebound


async def test_restore_without_risk_params_key_leaves_defaults(tmp_path):
    """A blob persisted before this change (no 'risk_params' key) must not
    blow up restore — best-effort, same contract as the rest of the blob."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        # Seed a pre-T3 blob shape directly (no risk_params key).
        import json
        await storage.set_app_setting(
            coord._STATE_KEY,
            json.dumps({
                "positions": [], "trade_queue": [], "watch_list": [],
                "daily_trades_count": 0, "daily_count_date": "2000-01-01",
                "tracked_orders": [],
            }),
        )
        default_value = coord.risk_params.max_trade_notional_pct
        await coord._restore_state()

    assert coord.risk_params.max_trade_notional_pct == default_value


# -------------------------------------------
# PUT /api/trading/risk-params route (2026-07-29 재시작 안전 리뷰)
#
# 이 라우트는 무조건 `coordinator._persist_state()`(전체 스냅샷)를 불렀다.
# 한 번도 start()되지 않은(_persistence_active=False) 코디네이터에서
# 호출되면 메모리 상 빈 positions/trade_queue/watch_list가 블롭의 실제
# 데이터를 덮어써 지운다 -- coordinator.py의 stop/pause/resume이 이미
# 봉합한 것과 완전히 같은 REGRESSION이 라우트 레이어에도 있었다. 프런트의
# "리스크 설정 저장" 버튼 클릭 한 번이 그대로 재현 경로다.
# -------------------------------------------

def _seed_live_blob() -> dict:
    """094840(슈프리마HQ) 실 포지션을 흉내낸, 비어있지 않은 스냅샷."""
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
        "mode": "active",
    }


async def test_risk_params_route_partial_persist_never_started_preserves_state(tmp_path):
    """이 테스트가 잡았어야 했던 회귀: 한 번도 start()되지 않은 코디네이터의
    PUT /risk-params가 positions/watch_list/daily_trades_count를 지우지
    않으면서 risk_params 필드만 갱신해야 한다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    assert coord._persistence_active is False  # bare construction, never start()ed

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        await storage.set_app_setting(
            coord._STATE_KEY, json.dumps(_seed_live_blob())
        )

        request = trading_mod.RiskParamsUpdateRequest(max_trade_notional_pct=22.0)
        response = await trading_mod.update_risk_params(request, coordinator=coord)

        blob = json.loads(await storage.get_app_setting(coord._STATE_KEY))

    assert response["risk_params"]["max_trade_notional_pct"] == 22.0

    seed = _seed_live_blob()
    assert blob["positions"] == seed["positions"]
    assert blob["watch_list"] == seed["watch_list"]
    assert blob["daily_trades_count"] == 3
    assert blob["risk_params"]["max_trade_notional_pct"] == 22.0


async def test_risk_params_route_full_persist_when_started(tmp_path):
    """대조군: _persistence_active=True(실제 start()를 거친) 코디네이터의
    PUT /risk-params는 여전히 전체 스냅샷을 써야 한다 -- partial 경로가
    시작된 코디네이터까지 새어 들어가 라이브 포지션을 안 쓰게 되는 회귀가
    없는지 확인한다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    coord = _make_coordinator()
    coord._persistence_active = True
    coord._state.positions = [
        ManagedPosition(
            ticker="094840",
            stock_name="슈프리마HQ",
            quantity=1315,
            avg_price=13060.0,
            stop_loss=12492.0,
        )
    ]

    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        request = trading_mod.RiskParamsUpdateRequest(max_trade_notional_pct=22.0)
        await trading_mod.update_risk_params(request, coordinator=coord)

        blob = json.loads(await storage.get_app_setting(coord._STATE_KEY))

    assert blob["risk_params"]["max_trade_notional_pct"] == 22.0
    assert len(blob["positions"]) == 1
    assert blob["positions"][0]["ticker"] == "094840"
    assert blob["positions"][0]["stop_loss"] == 12492.0
