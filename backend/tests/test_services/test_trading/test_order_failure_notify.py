"""통지 광역화 Task 7 (리뷰 Important 3): 자율 주문 실패 통지.

`on_trade_approved`의 "success": False 분기(브로커가 0주 체결로 거부한
경우)에 `_schedule_order_failure_alert`/`_notify_order_failed`를 붙였는데
최초 구현에는 이 경로 테스트가 전혀 없었다 — Task 6의
`_schedule_fill_notification`과 정확히 같은 강참조 태스크 패턴
(`self._notify_tasks` + `add_done_callback(discard)`)을 재사용하므로 같은
헬퍼(`_coord`/`_order`)로 검증한다.

최종 전체 브랜치 리뷰 Critical 1: 위 "success: False" 분기는 사실
`filled_quantity > 0`의 else라 status in {pending, rejected} 전체를
묶는다. 자율 BUY는 LIMIT이고 order_agent가 3폴×0.5초만 기다린 뒤
미체결이면 status="pending"으로 "정상" 반환하는데(주문은 브로커에 살아
있고 9줄 아래 _track_unfilled가 그 주문을 추적 등록한다), 회귀 전
코드는 이 상태에도 "주문 실패, 수동 확인하세요" 알림을 쐈다 — 운영자가
이미 작동 중인 지정가 주문에 중복 매수를 시도할 위험. 아래 두 테스트가
`on_trade_approved`를 실제로 구동해 pending은 무통지/rejected는 통지를
검증한다.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import (
    AllocationPlan,
    OrderRequest,
    OrderResult,
    OrderSide,
    TradingMode,
)

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


# -------------------------------------------
# Critical 1 (최종 전체 브랜치 리뷰): on_trade_approved의 else 분기가
# result.status가 아니라 filled_quantity>0으로만 갈라 pending까지 "실패"로
# 오분류하던 것 — 실제 on_trade_approved를 구동해 검증한다(H3 패턴 재사용,
# test_position_registration.py의 _h3_live_coordinator와 동형).
# -------------------------------------------


def _open_session() -> MarketSession:
    return MarketSession(
        is_open=True,
        current_time=datetime.now(),
        next_open=None,
        next_close=None,
        message="open",
    )


def _live_coordinator() -> ExecutionCoordinator:
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(return_value=_open_session())
    coord._refresh_account_info = AsyncMock()
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="094840",
            stock_name="슈프리마에이치큐",
            side=OrderSide.BUY,
            quantity=100,
            entry_price=13550,
            estimated_amount=1_355_000,
            position_pct=1.0,
            rationale="stub allocation",
            rebalance_orders=[],
        )
    )
    return coord


async def test_pending_limit_buy_does_not_fire_false_order_failure_alert():
    """RED(회귀 전): LIMIT BUY가 폴링 창(3폴×0.5초) 안에 체결되지 않아
    order_agent가 status="pending", filled_quantity=0으로 "정상" 반환해도
    — 이건 브로커 거부가 아니라 살아있는 미체결 주문이다(_track_unfilled가
    바로 아래서 추적 등록한다). 이 상태에서 "주문 실패" 알림이 나가면
    운영자가 이미 작동 중인 지정가 주문에 중복 매수를 시도하게 된다."""
    coord = _live_coordinator()

    async def _exec(order: OrderRequest) -> OrderResult:
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=0,
            avg_price=0,
            status="pending",
            message=None,
        )

    coord._execute_order = _exec
    coord._schedule_order_failure_alert = MagicMock()

    await coord.on_trade_approved(
        session_id="sess-pending",
        ticker="094840",
        stock_name="슈프리마에이치큐",
        action="BUY",
        entry_price=13550,
        stop_loss=12800,
        take_profit=14800,
        risk_score=5,
    )

    coord._schedule_order_failure_alert.assert_not_called()


async def test_rejected_buy_still_fires_order_failure_alert():
    """대조군 — 진짜 브로커 거부(status="rejected")는 그대로 알린다."""
    coord = _live_coordinator()

    async def _exec(order: OrderRequest) -> OrderResult:
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=0,
            avg_price=0,
            status="rejected",
            message="잔고 부족",
        )

    coord._execute_order = _exec
    coord._schedule_order_failure_alert = MagicMock()

    await coord.on_trade_approved(
        session_id="sess-rejected",
        ticker="094840",
        stock_name="슈프리마에이치큐",
        action="BUY",
        entry_price=13550,
        stop_loss=12800,
        take_profit=14800,
        risk_score=5,
    )

    coord._schedule_order_failure_alert.assert_called_once()
    order_arg, reason_arg = coord._schedule_order_failure_alert.call_args.args
    assert order_arg.ticker == "094840"
    assert reason_arg == "잔고 부족"
