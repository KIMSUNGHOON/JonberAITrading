"""통지 광역화 Task 7 (리뷰 Important 3): 자율 주문 실패 통지.

`on_trade_approved`의 "success": False 분기(브로커가 0주 체결로 거부한
경우)에 `_schedule_order_failure_alert`/`_notify_order_failed`를 붙였는데
최초 구현에는 이 경로 테스트가 전혀 없었다 — Task 6의
`_schedule_fill_notification`과 정확히 같은 강참조 태스크 패턴
(`self._notify_tasks` + `add_done_callback(discard)`)을 재사용하므로 같은
헬퍼(`_coord`/`_order`)로 검증한다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import OrderRequest, OrderSide

pytestmark = pytest.mark.asyncio


def _coord() -> ExecutionCoordinator:
    return ExecutionCoordinator(kiwoom_client=None)


def _order(side=OrderSide.BUY):
    return OrderRequest(
        ticker="094840", stock_name="슈프리마에이치큐", side=side,
        quantity=100, price=13550,
    )


async def test_order_failure_sends_alert_with_instruction():
    coord = _coord()
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        coord._schedule_order_failure_alert(_order(), "브로커 거부")
        await coord._drain_notify_tasks()

    notifier.send_message.assert_awaited_once()
    body = notifier.send_message.await_args.args[0]
    assert "094840" in body
    assert "브로커 거부" in body
    assert "확인" in body or "수동" in body, "조치 지시가 있어야 한다"


async def test_order_failure_alert_never_raises(caplog):
    """통지가 터져도 주문 처리 흐름이 죽으면 안 된다(never-raise)."""
    import logging

    coord = _coord()

    with patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(side_effect=RuntimeError("telegram down"))):
        with caplog.at_level(logging.ERROR):
            # raise 없이 반환되면 never-raise 계약은 지켜진 것 — 예외가
            # 새면 이 await 자체가 테스트를 실패시킨다.
            await coord._notify_order_failed(_order(), "브로커 거부")

    assert "order_failure_alert_failed" in caplog.text


async def test_order_failure_alert_skipped_when_notifier_not_ready():
    coord = _coord()
    notifier = MagicMock()
    notifier.is_ready = False
    notifier.send_message = AsyncMock(return_value=True)

    with patch("services.telegram.get_telegram_notifier", new=AsyncMock(return_value=notifier)):
        coord._schedule_order_failure_alert(_order(), "브로커 거부")
        await coord._drain_notify_tasks()

    notifier.send_message.assert_not_awaited()
