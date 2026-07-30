"""통지 광역화 Task 8: 이벤트 통지 게이트.

_notify_event가 TELEGRAM_NOTIFY_* 게이트를 전혀 거치지 않아 저가치 알림이
스팸으로 나간다. 07-30 2시간에 13건, 그중 trailing_stop 7건이고 11:35~11:37에만
4건이 스탑 이동폭 ₩124로 발화했다.

사용자 결정(2026-07-30)은 '체결·실패만'이다 — 근접 경고와 트레일링 갱신은
기본 off로 둔다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent_chat.position_manager import PositionEventType

pytestmark = pytest.mark.asyncio


def _event(kind):
    e = MagicMock()
    e.event_type = kind
    e.ticker = "094840"
    e.current_price = 13060.0
    e.message = "테스트 이벤트"
    e.data = {"unrealized_pnl_pct": 3.75, "unrealized_pnl": 644350}
    return e


async def _run(kind, enabled_map):
    from services.agent_chat.position_manager import PositionManager

    pm = PositionManager()
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)), \
         patch("services.agent_chat.position_manager.event_notify_enabled",
               side_effect=lambda k: enabled_map.get(k, False)):
        await pm._notify_event(_event(kind))
    return notifier


async def test_trailing_update_suppressed_by_default():
    notifier = await _run(PositionEventType.TRAILING_STOP_UPDATE, {})
    notifier.send_message.assert_not_awaited()


async def test_stop_loss_hit_still_sent():
    notifier = await _run(
        PositionEventType.STOP_LOSS_HIT,
        {PositionEventType.STOP_LOSS_HIT: True},
    )
    assert notifier.send_message.await_count >= 1


async def test_near_events_suppressed_by_default():
    notifier = await _run(PositionEventType.STOP_LOSS_NEAR, {})
    notifier.send_message.assert_not_awaited()
