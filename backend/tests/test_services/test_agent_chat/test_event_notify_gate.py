"""통지 광역화 Task 8: 이벤트 통지 게이트.

_notify_event가 TELEGRAM_NOTIFY_* 게이트를 전혀 거치지 않아 저가치 알림이
스팸으로 나간다. 07-30 2시간에 13건, 그중 trailing_stop 7건이고 11:35~11:37에만
4건이 스탑 이동폭 ₩124로 발화했다.

사용자 결정(2026-07-30)은 '체결·실패만'이다 — 근접 경고와 트레일링 갱신은
기본 off로 둔다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent_chat.position_manager import (
    PositionEventType,
    event_notify_enabled,
)

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


async def test_real_gate_matches_real_default_config():
    """리뷰 지적(Important 2): 위 세 테스트는 전부 event_notify_enabled 자체를
    patch하므로 실제 구현이 실제 기본 CSV와 맞는지는 아무 것도 검증하지 않는다.
    enum 값 리네임이나 기본 CSV 오타가 생겨도 잡아낼 테스트가 없었다 — 이 테스트는
    patch 없이 진짜 함수를 진짜 기본 설정(TELEGRAM_NOTIFY_EVENT_KINDS 기본값)에
    대고 돌려 stop_loss_hit만 허용됨을 고정한다.

    최종 전체 브랜치 리뷰 Important 5: take_profit_hit은 *_NEAR와 달리 래치가
    없어(position_manager.py — 익절가 위에서 매 틱 재발화가 의도된 동작)
    auto_execute_take_profit=False(기본)일 때 시간당 최대 120건까지 발화할 수
    있었다. 실제 매도는 체결 통지로, 토론 결과는 _notify_decision으로 이미
    별도 도달하므로 기본 CSV에서 뺀다 — stop_loss_hit만 남는다.
    """
    assert event_notify_enabled(PositionEventType.STOP_LOSS_HIT) is True
    assert event_notify_enabled(PositionEventType.TAKE_PROFIT_HIT) is False
    assert event_notify_enabled(PositionEventType.TRAILING_STOP_UPDATE) is False


async def test_take_profit_hit_no_longer_floods_by_default():
    """RED(회귀 전): take_profit_hit이 기본 화이트리스트에 있어 auto_execute_
    take_profit=False(기본)에서도 _handle_event가 조기 반환하지 않고 매 틱
    _notify_event까지 도달해 30초 간격 기준 시간당 최대 120건을 보냈다.
    GREEN: 기본 설정에서는 무통지 — 실제 매도는 체결 통지가, 토론 결과는
    _notify_decision이 이미 커버한다."""
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    from services.agent_chat.position_manager import PositionManager

    pm = PositionManager()
    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        await pm._notify_event(_event(PositionEventType.TAKE_PROFIT_HIT))

    notifier.send_message.assert_not_awaited()
