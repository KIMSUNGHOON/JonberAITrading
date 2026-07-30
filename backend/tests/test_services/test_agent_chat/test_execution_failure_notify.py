"""통지 광역화 Task 7: 집행 실패 통지.

손절 집행이 실패하면 포지션이 무방비로 남는다 — 체결 통지보다 급하다.
지금은 _execute_close_position의 예외가 auto_execute_failed 로그만 남기고
끝난다. 아무도 모른다.

실패 통지는 '무엇을 하라'를 담아야 한다. 상태만 알려주고 조치를 안 알려주면
운영자가 잘못된 복구를 한다(재시작 안전 아크에서 실제로 겪었다).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_auto_execute_exception_sends_alert():
    from services.agent_chat.position_manager import PositionManager, PositionEventType

    pm = PositionManager()
    position = MagicMock()
    position.ticker = "094840"
    position.stock_name = "슈프리마에이치큐"
    event = MagicMock()
    event.ticker = "094840"
    event.event_type = PositionEventType.STOP_LOSS_HIT

    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    with patch.object(pm, "_execute_close_position",
                      new=AsyncMock(side_effect=RuntimeError("broker down"))), \
         patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await pm._auto_execute_event(event, position)

    notifier.send_message.assert_awaited_once()
    body = notifier.send_message.await_args.args[0]
    assert "094840" in body
    assert "손절" in body
    assert "확인" in body or "수동" in body, "조치 지시가 있어야 한다"


async def test_alert_failure_does_not_propagate():
    """통지까지 실패해도 집행 경로가 죽으면 안 된다."""
    from services.agent_chat.position_manager import PositionManager, PositionEventType

    pm = PositionManager()
    position = MagicMock()
    position.ticker = "094840"
    position.stock_name = "슈프리마에이치큐"
    event = MagicMock()
    event.ticker = "094840"
    event.event_type = PositionEventType.STOP_LOSS_HIT

    with patch.object(pm, "_execute_close_position",
                      new=AsyncMock(side_effect=RuntimeError("broker down"))), \
         patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(side_effect=RuntimeError("telegram down"))):
        await pm._auto_execute_event(event, position)  # raise하지 않아야 한다
