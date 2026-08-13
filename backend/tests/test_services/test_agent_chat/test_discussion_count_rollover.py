"""자정을 넘겨 도는 라이브 PositionManager에서 `Position.discussion_count`가
영원히 낡은 채로 남는 결함(2026-08-04)의 회귀 테스트.

라이브 사고: 2026-08-04 5개 실 포지션 중 4개가 12:53경
`max_discussions_per_position`(기본 8)에 도달했고, 그 이후 장마감까지
2.5시간 동안 전략 재평가가 단 한 번도 열리지 않았다. 아무에게도 통지되지
않았다. 저장소 repo-wide grep으로 확인: `discussion_count`를 재설정하는
코드는 어디에도 없었다 -- 스케줄된 잡도, restore 경로도 없다.

이 결함은 같은 저장소에서 반복되는 패턴의 세 번째 사례다:
- `agents/llm/router.py`의 `_maybe_reset_day()` (OpenRouter 일일 예산) 원형.
- `services/trading/coordinator.py`의 `_maybe_reset_daily_trades()`
  (`daily_trades_count`, 어제 봉합) -- 그 결함은 restore 경로에만 롤오버가
  있어서 재시작 없이 도는 프로세스는 자정을 넘겨도 카운트가 0으로 안
  돌아갔고, 게다가 persist가 무조건 "오늘" 날짜를 낡은 카운트 위에 찍어버려
  재시작으로도 못 고치는 자기영속 결함이었다.

`discussion_count`는 이 저장소에서 아예 영속되지 않는다 -- `_persist_stops`/
`restore_stop_overlay`는 stop_loss/take_profit/trailing_stop_pct/
take_profit_reached_at만 직렬화한다(코드 확인, 아래 `TestDiscussionCountNotPersisted`
로 고정). 그래서 coordinator처럼 persist가 restore를 오염시키는 자기영속
경로는 없다 -- 재시작은 `sync_from_account` -> `add_position`으로 포지션을
다시 만들어 discussion_count=0을 공짜로 준다. 유일한 결함은 재시작 없이
자정을 넘기는 것이다.

`_maybe_reset_discussion_count()`가 위 두 원형과 동일한 lazy-reset 패턴으로
이를 닫는다: 스케줄된 잡 없이, 읽거나 쓰는 시점마다 "카운트가 속한 날"과
오늘을 비교해 다르면 되돌린다. Position마다 독립적으로(`discussion_count_date`
필드) 추적한다 -- coordinator/router의 단일 전역 카운터와 달리 포지션별
카운터이기 때문이다.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.agent_chat.position_manager as pm_mod
from services.agent_chat.position_manager import (
    MonitoredPosition,
    PositionManager,
    PositionManagerConfig,
)

pytestmark = pytest.mark.asyncio

DAY1 = date(2026, 8, 3)
DAY2 = date(2026, 8, 4)


def _patched_today(target: date, monkeypatch):
    """`services.agent_chat.position_manager`가 보는 `date.today()`만
    고정한다. `_daily_count_day` 비교 패턴(coordinator 테스트)과 동일하게,
    `date`의 나머지 API(.isoformat() 등)는 실제 `datetime.date` 인스턴스가
    처리하므로 그대로 동작한다."""
    mock_date = MagicMock(wraps=date)
    mock_date.today.return_value = target
    monkeypatch.setattr(pm_mod, "date", mock_date)


def _position_manager(**config_overrides) -> PositionManager:
    cfg = PositionManagerConfig(
        min_discussion_interval_minutes=0,
        **config_overrides,
    )
    return PositionManager(config=cfg)


def _position(pm: PositionManager, discussion_count: int = 0) -> MonitoredPosition:
    p = pm.add_position(
        ticker="005930",
        stock_name="삼성전자",
        quantity=100,
        avg_price=72500,
        current_price=72500,
    )
    p.discussion_count = discussion_count
    return p


class TestRolloverInProcessWithoutRestart:
    async def test_gate_resets_stale_count_on_new_day(self, monkeypatch):
        """RED (수정 전 실패): 재시작 없이 날짜만 바뀌어도 새 날에는
        max_discussions_per_position에 도달했던 포지션도 다시 토론이
        허용돼야 한다 -- 이것이 이 결함의 핵심 증상(2.5시간 무토론)이다."""
        _patched_today(DAY1, monkeypatch)
        pm = _position_manager(max_discussions_per_position=8)
        position = _position(pm, discussion_count=8)

        _patched_today(DAY2, monkeypatch)
        assert pm._should_trigger_discussion(position) is True
        assert position.discussion_count == 0

    async def test_get_position_resets_stale_count_on_new_day(self, monkeypatch):
        """외부 접근자(`GET /positions/{ticker}` 배선)도 게이트 없이 그 날의
        첫 접근이 될 수 있다 -- 여기서도 롤오버가 확인돼야 새 날의 첫 조회가
        어제 카운트를 보여주지 않는다."""
        _patched_today(DAY1, monkeypatch)
        pm = _position_manager()
        _position(pm, discussion_count=8)

        _patched_today(DAY2, monkeypatch)
        fetched = pm.get_position("005930")
        assert fetched.discussion_count == 0

    async def test_get_all_positions_resets_stale_count_on_new_day(self, monkeypatch):
        """`GET /positions`(목록) 배선 -- 두 번째 외부 접근자."""
        _patched_today(DAY1, monkeypatch)
        pm = _position_manager()
        _position(pm, discussion_count=8)

        _patched_today(DAY2, monkeypatch)
        [fetched] = pm.get_all_positions()
        assert fetched.discussion_count == 0


class TestSameDayActivityDoesNotReset:
    async def test_gate_does_not_reset_within_same_day(self, monkeypatch):
        """같은 날 안에서는 몇 번을 확인해도 카운트가 살아있어야 한다 --
        상한을 매 호출마다 지워버리면 하루 한도 자체가 무의미해진다."""
        _patched_today(DAY1, monkeypatch)
        pm = _position_manager(max_discussions_per_position=8)
        position = _position(pm, discussion_count=8)

        assert pm._should_trigger_discussion(position) is False
        assert pm._should_trigger_discussion(position) is False
        assert position.discussion_count == 8

    async def test_get_all_positions_does_not_reset_within_same_day(self, monkeypatch):
        _patched_today(DAY1, monkeypatch)
        pm = _position_manager()
        _position(pm, discussion_count=3)

        [fetched] = pm.get_all_positions()
        assert fetched.discussion_count == 3
        [fetched_again] = pm.get_all_positions()
        assert fetched_again.discussion_count == 3


class TestIncrementAfterRollover:
    async def test_increment_after_rollover_starts_fresh_not_stale_plus_one(
        self, monkeypatch
    ):
        """증가 지점(`_trigger_discussion`)도 롤오버를 통과해야 한다 --
        그렇지 않으면 새 날의 첫 토론이 어제 카운트 위에 쌓인다."""
        _patched_today(DAY1, monkeypatch)
        pm = _position_manager()
        position = _position(pm, discussion_count=7)
        session = MagicMock(id="s1", decision=None)
        coordinator = MagicMock()
        coordinator.start_manual_discussion = AsyncMock(return_value=session)
        pm.set_chat_coordinator(coordinator)
        event = MagicMock(ticker="005930", stock_name="삼성전자")

        _patched_today(DAY2, monkeypatch)
        await pm._trigger_discussion(event, position)

        assert position.discussion_count == 1

    async def test_increment_within_same_day_stacks_normally(self, monkeypatch):
        """회귀 방지: 롤오버 로직을 넣었다고 같은 날의 정상 누적까지
        건드리면 안 된다."""
        _patched_today(DAY1, monkeypatch)
        pm = _position_manager()
        position = _position(pm, discussion_count=3)
        session = MagicMock(id="s1", decision=None)
        coordinator = MagicMock()
        coordinator.start_manual_discussion = AsyncMock(return_value=session)
        pm.set_chat_coordinator(coordinator)
        event = MagicMock(ticker="005930", stock_name="삼성전자")

        await pm._trigger_discussion(event, position)

        assert position.discussion_count == 4


class TestDiscussionCountNotPersisted:
    """`discussion_count`가 아예 영속되지 않는다는 사실을 고정한다 --
    coordinator의 daily_trades_count와 달리 restore-path 자기영속 함정이
    존재하지 않는 이유. 누군가 나중에 discussion_count를 영속 스키마에
    추가하면서 date-provenance 처리(위 coordinator 패턴)를 빠뜨리면 이
    테스트가 그 REGRESSION을 잡는다."""

    async def test_persist_stops_payload_excludes_discussion_count(
        self, isolated_storage_service
    ):
        pm = _position_manager()
        position = _position(pm, discussion_count=8)
        position.stop_loss = 68000

        await pm._persist_stops(generation=None)

        import json

        blob = json.loads(
            await isolated_storage_service.get_app_setting(pm._STOPS_KEY)
        )
        assert "discussion_count" not in json.dumps(blob)

    async def test_restart_via_fresh_position_gives_zero_regardless_of_date(self):
        """포지션 재구성(=재시작에서 sync_from_account가 하는 일)은
        discussion_count=0을 공짜로 준다 -- 영속되지 않으므로 날짜 처리가
        전혀 필요 없다는 것을 보여준다."""
        pm = PositionManager(config=PositionManagerConfig())
        position = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=72500,
        )
        assert position.discussion_count == 0
        assert position.discussion_count_date == date.today()
