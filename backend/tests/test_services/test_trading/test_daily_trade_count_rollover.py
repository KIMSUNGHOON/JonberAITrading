"""자정을 넘겨 도는 라이브 코디네이터에서 `daily_trades_count`가 영원히
낡은 채로 남는 결함(2026-08-04)의 회귀 테스트.

`daily_trades_count`의 달력일 롤오버는 restore 경로에만 있었다. 재시작 없이
자정을 넘기는 살아있는 프로세스는 그 경로를 절대 안 타므로 카운트가 0으로
안 돌아가고, 상한이 나날이 좁아지다 결국 매매가 전부 막힌다.

게다가 persist 경로(`_persist_state`)가 무조건 "오늘" 날짜를 그 낡은
카운트 위에 찍어버리므로, 다음 재시작에서 restore의 날짜 비교가 "일치"로
보고 낡은 값을 그대로 복원한다 -- 재시작으로도 못 고치는 자기영속 결함이다
(실 라이브 사고: daily_trades_count=4 / daily_count_date=오늘, 그중 3건은
전날 거래였다).

`_maybe_reset_daily_trades()`가 `agents/llm/router.py`의
`_maybe_reset_day()`(OpenRouter 일일 예산)와 동일한 lazy-reset 패턴으로
이를 닫는다: 게이트 판정/증가/영속 앞에서 매번 "카운트가 속한 날"과 오늘을
비교해 다르면 되돌린다.
"""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import OrderRequest, OrderResult, OrderSide

pytestmark = pytest.mark.asyncio

DAY1 = date(2026, 8, 3)
DAY2 = date(2026, 8, 4)


def _make_coordinator() -> ExecutionCoordinator:
    return ExecutionCoordinator(kiwoom_client=None)


def _patched_today(target: date):
    """`services.trading.coordinator`가 보는 `date.today()`를 고정한다.
    `.today()`를 제외한 나머지 `date` API(.isoformat()/.strftime() 등)는
    실제 `datetime.date` 인스턴스가 처리하므로 그대로 동작한다 -- 실 데이트
    타입을 서브클래싱하지 않고도 코디네이터가 부르는 `date.today()`만
    골라서 고정할 수 있다."""
    mock_date = MagicMock(wraps=date)
    mock_date.today.return_value = target
    return patch("services.trading.coordinator.date", mock_date)


async def test_rollover_resets_count_in_process_without_restart():
    """RED (오늘 실패): 재시작 없이 날짜만 바뀌어도 새 날에는 카운트가 0으로
    보여야 한다. 이것이 이 결함의 핵심 증상이다."""
    with _patched_today(DAY1):
        coord = _make_coordinator()
        coord._state.daily_trades_count = 4

    with _patched_today(DAY2):
        assert coord.state.daily_trades_count == 0


async def test_same_day_activity_does_not_reset():
    """같은 날 안에서는 몇 번을 읽어도 카운트가 살아있어야 한다 -- 상한을
    매 호출마다 지워버리면 하루 한도 자체가 무의미해진다."""
    with _patched_today(DAY1):
        coord = _make_coordinator()
        coord._state.daily_trades_count = 2

        assert coord.state.daily_trades_count == 2
        assert coord.state.daily_trades_count == 2


async def test_increment_after_rollover_starts_fresh_not_stale_plus_one():
    """증가 지점(`_execute_order`)도 롤오버를 통과해야 한다 -- 그렇지 않으면
    새 날의 첫 체결이 어제 카운트 위에 쌓인다."""
    order = OrderRequest(ticker="005930", side=OrderSide.SELL, quantity=1, price=70_000)
    result = OrderResult(
        order_id="o1",
        ticker="005930",
        side=OrderSide.SELL,
        requested_quantity=1,
        filled_quantity=1,
        avg_price=70_000,
        status="filled",
    )

    with _patched_today(DAY1):
        coord = _make_coordinator()
        coord._state.daily_trades_count = 4
        coord.order_agent.execute_order = AsyncMock(return_value=result)

    with _patched_today(DAY2):
        await coord._execute_order(order)

    assert coord._state.daily_trades_count == 1


async def test_persist_cannot_stamp_fresh_date_onto_stale_count(isolated_storage_service):
    """가장 위험한 경로: persist가 오늘 날짜를 어제 몫 카운트에 찍으면,
    다음 재시작에서 restore가 그 낡은 값을 '오늘 것'으로 믿고 그대로
    복원해버린다 -- 실 라이브 사고의 정확한 재현 경로."""
    with _patched_today(DAY1):
        coord = _make_coordinator()
        coord._persistence_active = True
        coord._state.daily_trades_count = 4

    with _patched_today(DAY2):
        await coord._persist_state()

    blob = json.loads(await isolated_storage_service.get_app_setting(coord._STATE_KEY))
    assert blob["daily_trades_count"] == 0
    assert blob["daily_count_date"] == DAY2.isoformat()


async def test_restore_same_day_restart_preserves_count(isolated_storage_service):
    """기존 동작 보존: 재시작이 같은 달력일 안에서 일어나면 카운트는 그대로
    복원돼야 한다(상한을 되살리면 안 됨) -- 그리고 그 provenance(오늘)가
    in-memory day에도 반영돼야 다음 읽기에서 잘못 리셋되지 않는다."""
    await isolated_storage_service.set_app_setting(
        "trading:coordinator_state",
        json.dumps(
            {
                "positions": [],
                "trade_queue": [],
                "watch_list": [],
                "daily_trades_count": 3,
                "daily_count_date": DAY1.isoformat(),
            }
        ),
    )

    with _patched_today(DAY1):
        coord = _make_coordinator()
        await coord._restore_state()

        assert coord._state.daily_trades_count == 3
        # 복원 직후 바로 다시 읽어도(같은 날) 지워지면 안 된다.
        assert coord.state.daily_trades_count == 3
