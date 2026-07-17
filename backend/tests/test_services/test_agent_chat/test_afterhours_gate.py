"""E2-1: 장외에는 워치 체크·전략 재평가·포지션 감시가 no-op이어야 한다.

Spec: docs/superpowers/specs/2026-07-17-three-issues-design.md §2 (E2-1)
Task: .superpowers/sdd/task-E2-1-brief.md

Gate points covered (agent_chat 게이트 3지점):
- ChatCoordinator._check_watch_list
- PositionManager._check_strategic_reeval
- PositionManager._check_all_positions (완전 idle — 방어 감시 포함 전체 skip)

Plus a small unit-test class for the shared cache helper
(``market_hours.is_krx_open_cached`` / ``_reset_krx_open_cache``) that the
three gate points above (and E2-2's 1s loop) all consume.
"""
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

import services.storage_service as ss
from services.agent_chat.coordinator import ChatCoordinator
from services.agent_chat.position_manager import PositionManager, PositionManagerConfig


# -------------------------------------------
# Isolation (PositionManager.add_position fires a fire-and-forget stop-
# persist task whenever a running loop is present — same isolation pattern
# as test_position_manager.py's `temp_storage`, needed here too so this
# file never touches the real on-disk storage.db).
# -------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


# -------------------------------------------
# Fixtures (minimal, module-local copies of the coordinator/position_manager
# fixture shapes used in test_coordinator.py / test_position_manager.py —
# see task-E2-1-brief.md: "픽스처는 기존 테스트 파일의 실제 구성에 맞춰 조정").
# -------------------------------------------


@pytest.fixture()
def closed_market(monkeypatch):
    """세 게이트 지점이 공통 소비하는 캐시 헬퍼를 닫힘으로 고정."""
    import services.agent_chat.coordinator as chat_coord
    import services.agent_chat.position_manager as pm_mod
    monkeypatch.setattr(chat_coord, "is_krx_open_cached", lambda: False)
    monkeypatch.setattr(pm_mod, "is_krx_open_cached", lambda: False)


@pytest.fixture
def coordinator_with_watch():
    """ChatCoordinator with _running=True, one watch-list ticker stubbed in,
    and a spy on _detect_opportunity that records calls without starting a
    real discussion (avoids needing to mock ChatRoom/market-context fetch)."""
    coord = ChatCoordinator(
        check_interval_minutes=5,
        max_concurrent_discussions=3,
        min_discussion_interval_minutes=30,
    )
    coord._running = True
    coord._detect_opportunity_calls = []

    async def _get_watch_list_stub():
        return [{
            "ticker": "005930",
            "stock_name": "삼성전자",
            "current_price": 72500,
            "target_entry_price": 72500,
            "confidence": 0.9,
        }]

    async def _detect_opportunity_spy(stock):
        coord._detect_opportunity_calls.append(stock)
        return False  # no need to exercise _start_discussion for this gate test

    coord._get_watch_list = _get_watch_list_stub
    coord._detect_opportunity = _detect_opportunity_spy
    return coord


@pytest.fixture
def position_manager_with_position():
    """PositionManager with one monitored position and a `_checked_tickers`
    spy standing in for `_update_prices` (the real price-fetch entry point),
    so tests can assert zero price fetches happened when the gate is
    closed."""
    config = PositionManagerConfig(
        check_interval_seconds=30,
        stop_loss_warning_pct=2.0,
        take_profit_warning_pct=2.0,
        significant_gain_pct=10.0,
        significant_loss_pct=5.0,
    )
    pm = PositionManager(config=config)
    pm.add_position(
        ticker="005930",
        stock_name="삼성전자",
        quantity=100,
        avg_price=72500,
        current_price=72500,
        stop_loss=68875,
        take_profit=79750,
    )
    pm._checked_tickers = []

    async def _update_prices_spy():
        pm._checked_tickers.append(list(pm._positions.keys()))
        return set()

    pm._update_prices = _update_prices_spy
    pm._positions_for_test = list(pm._positions.values())
    return pm


# -------------------------------------------
# Gate tests
# -------------------------------------------


@pytest.mark.asyncio
async def test_watch_check_noop_when_closed(closed_market, coordinator_with_watch):
    """장 닫힘이면 _check_watch_list가 기회판정·토론 개시 없이 조기 반환."""
    coord = coordinator_with_watch  # 워치 1종목 + _detect_opportunity 스파이 픽스처
    await coord._check_watch_list()
    assert coord._detect_opportunity_calls == []      # 기회 판정 자체 미도달
    assert coord._active_rooms == {}                  # 토론 미개시


@pytest.mark.asyncio
async def test_strategic_reeval_noop_when_closed(closed_market, position_manager_with_position):
    pm = position_manager_with_position
    event = pm._check_strategic_reeval(pm._positions_for_test[0])
    assert event is None


@pytest.mark.asyncio
async def test_check_all_positions_noop_when_closed(closed_market, position_manager_with_position):
    """방어 감시 포함 사이클 전체 skip (E2-D1 완전 idle)."""
    pm = position_manager_with_position
    await pm._check_all_positions()
    assert pm._checked_tickers == []                  # 가격 조회/이벤트 0


@pytest.mark.asyncio
async def test_open_market_unchanged(monkeypatch, coordinator_with_watch):
    """열림이면 기존 경로 그대로 진입(기회판정 도달)."""
    import services.agent_chat.coordinator as chat_coord
    monkeypatch.setattr(chat_coord, "is_krx_open_cached", lambda: True)
    coord = coordinator_with_watch
    await coord._check_watch_list()
    assert len(coord._detect_opportunity_calls) >= 1


# -------------------------------------------
# Cache helper unit tests
# -------------------------------------------


class TestIsKrxOpenCachedTTL:
    """market_hours.is_krx_open_cached — monotonic TTL cache over
    get_market_hours_service().is_market_open(MarketType.KRX)."""

    @pytest.fixture(autouse=True)
    def _reset_cache_after(self):
        """E2-2 cleanup (review note from E2-1): `_krx_open_cache` is a
        MODULE-LEVEL global — leaving a real/live TTL entry behind after
        these tests would leak up to 30s of stale cache state into whatever
        runs next in the same process. Setup already resets per-test; this
        also resets on teardown."""
        yield
        from services.trading import market_hours
        market_hours._reset_krx_open_cache()

    def test_repeated_calls_within_ttl_hit_real_service_once(self, monkeypatch):
        from services.trading import market_hours

        market_hours._reset_krx_open_cache()
        mock_service = MagicMock()
        mock_service.is_market_open.return_value = True
        monkeypatch.setattr(
            market_hours, "get_market_hours_service", lambda: mock_service
        )

        for _ in range(5):
            assert market_hours.is_krx_open_cached(ttl_seconds=30.0) is True

        assert mock_service.is_market_open.call_count == 1

    def test_reset_forces_requery(self, monkeypatch):
        from services.trading import market_hours

        market_hours._reset_krx_open_cache()
        mock_service = MagicMock()
        mock_service.is_market_open.return_value = False
        monkeypatch.setattr(
            market_hours, "get_market_hours_service", lambda: mock_service
        )

        assert market_hours.is_krx_open_cached(ttl_seconds=30.0) is False
        assert mock_service.is_market_open.call_count == 1

        market_hours._reset_krx_open_cache()
        mock_service.is_market_open.return_value = True

        assert market_hours.is_krx_open_cached(ttl_seconds=30.0) is True
        assert mock_service.is_market_open.call_count == 2
