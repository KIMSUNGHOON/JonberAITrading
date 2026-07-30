"""통지 광역화 최종 전체 브랜치 리뷰 Important 4 (+ Important 2 코디네이터 측):
방어적 SELL(_close_position/_reduce_position/_execute_order_from_monitor)이
브로커에서 거부돼도 통지가 전혀 없던 갭.

브로커 거부는 예외가 아니라 정상 OrderResult(status="rejected",
filled_quantity=0)로 돌아온다. `_apply_sell_fill`은 filled_quantity<=0이면
경고 로그만 남기고 반환하고, `_alert_execution_failed`(PositionManager)는
예외 전용이라 걸리지 않으며, `_schedule_order_failure_alert`는 지금까지
`on_trade_approved`에만 있었다 — 그 결과 자율 손절/익절/청산/축소가 브로커
단에서 거부되면 폰에는 아무것도 오지 않았다(스탑이 조용히 미집행).

수정: 세 진입점 전부에 `_handle_defensive_sell_rejection`(coordinator.py)을
붙여 `_schedule_order_failure_alert`를 재사용한다. PositionManager의 30초
감시 틱에서 반복 호출될 수 있으므로 `ManagedPosition.close_order_rejected_
notified` 래치로 거부 에피소드당 한 번만 알린다(gate-denied 알림의
`monitor_gate_denied_notified`와 동일한 형태).

Important 2 (코디네이터 측): `_close_position`/`_reduce_position`이 새로 받는
`reason` 파라미터가 실제로 OrderRequest.reason에 실려 `_notify_fill`의
source로 나가는지 — 미전달 시 기존 하드코딩 기본값을 유지하는지도 함께
고정한다.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.autonomy as autonomy_pkg
import services.storage_service as ss
from services.autonomy import GateDecision
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import ManagedPosition, OrderRequest, OrderResult, OrderSide, StopLossMode

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _coordinator_with_position(
    quantity=10,
    stop_loss_mode=StopLossMode.USER_APPROVAL,
) -> tuple[ExecutionCoordinator, ManagedPosition]:
    coord = ExecutionCoordinator(kiwoom_client=None)
    position = ManagedPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=quantity,
        avg_price=250_000,
        current_price=260_000,
        stop_loss_mode=stop_loss_mode,
    )
    coord._add_position(position)
    return coord, position


def _stub_execute_order_status(coord: ExecutionCoordinator, status: str, message=None):
    """매 호출마다 filled_quantity=0인 OrderResult를 돌려준다(브로커 거부/미체결)."""

    async def _exec(order: OrderRequest) -> OrderResult:
        return OrderResult(
            order_id="R1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=0,
            avg_price=0,
            status=status,
            message=message,
        )

    coord._execute_order = _exec


def _stop_loss_order(quantity=10) -> OrderRequest:
    return OrderRequest(
        ticker="005930",
        stock_name="삼성전자",
        side=OrderSide.SELL,
        quantity=quantity,
        price=68_000,
        reason="Stop-loss auto-execution",
    )


async def _allow_gate(market, **kwargs):
    return GateDecision(allowed=True, reason="ok", check="all")


# -------------------------------------------
# _close_position
# -------------------------------------------


async def test_close_position_rejected_fires_failure_alert(temp_storage):
    """RED(회귀 전): 브로커가 거부해도 _close_position은 무통지였다."""
    coord, position = _coordinator_with_position()
    _stub_execute_order_status(coord, status="rejected", message="잔고 부족")
    coord._schedule_order_failure_alert = MagicMock()

    result = await coord._close_position("005930")

    assert result.status == "rejected"
    coord._schedule_order_failure_alert.assert_called_once()
    order_arg, reason_arg = coord._schedule_order_failure_alert.call_args.args
    assert order_arg.ticker == "005930"
    assert reason_arg == "잔고 부족"
    # 거부된 SELL은 여전히 포지션을 유지한다(A3) — 무방비 방치 확인.
    assert any(p.ticker == "005930" for p in coord._state.positions)


async def test_close_position_pending_does_not_fire_failure_alert(temp_storage):
    """대조군: 살아있는 미체결(pending)은 거부가 아니므로 무통지."""
    coord, position = _coordinator_with_position()
    _stub_execute_order_status(coord, status="pending")
    coord._schedule_order_failure_alert = MagicMock()

    await coord._close_position("005930")

    coord._schedule_order_failure_alert.assert_not_called()


async def test_close_position_repeated_rejection_notifies_once(temp_storage):
    """tick 기반 재시도(반복 거부)에서 매번 재통지하면 안 된다 — 거부
    에피소드당 한 번만."""
    coord, position = _coordinator_with_position()
    _stub_execute_order_status(coord, status="rejected", message="거래정지")
    coord._schedule_order_failure_alert = MagicMock()

    await coord._close_position("005930")
    await coord._close_position("005930")
    await coord._close_position("005930")

    coord._schedule_order_failure_alert.assert_called_once()


async def test_close_position_rejection_latch_resets_after_non_rejection(temp_storage):
    """거부가 아닌 상태로 돌아오면 래치가 풀려 다음 거부가 다시 통지된다."""
    coord, position = _coordinator_with_position()
    coord._schedule_order_failure_alert = MagicMock()

    _stub_execute_order_status(coord, status="rejected", message="일시 거부")
    await coord._close_position("005930")
    assert coord._schedule_order_failure_alert.call_count == 1

    _stub_execute_order_status(coord, status="pending")
    await coord._close_position("005930")
    assert coord._schedule_order_failure_alert.call_count == 1  # 안 늘어남

    _stub_execute_order_status(coord, status="rejected", message="재거부")
    await coord._close_position("005930")
    assert coord._schedule_order_failure_alert.call_count == 2  # 래치 풀려 재통지


# -------------------------------------------
# _reduce_position
# -------------------------------------------


async def test_reduce_position_rejected_fires_failure_alert(temp_storage):
    coord, position = _coordinator_with_position(quantity=50)
    _stub_execute_order_status(coord, status="rejected", message="수량 오류")
    coord._schedule_order_failure_alert = MagicMock()

    result = await coord._reduce_position("005930", 20)

    assert result.status == "rejected"
    coord._schedule_order_failure_alert.assert_called_once()


# -------------------------------------------
# _execute_order_from_monitor (AGENT_AUTO 손절/익절)
# -------------------------------------------


async def test_monitor_defensive_sell_rejected_fires_failure_alert(temp_storage, monkeypatch):
    """가장 중요한 경로: RiskMonitor의 자율 손절/익절이 브로커에서 거부되면
    — 07-24 손절/07-27 익절과 정확히 같은 트리거 지점 — 반드시 통지돼야
    한다."""
    coord, position = _coordinator_with_position(
        quantity=10, stop_loss_mode=StopLossMode.AGENT_AUTO
    )
    _stub_execute_order_status(coord, status="rejected", message="거래정지")
    monkeypatch.setattr(autonomy_pkg, "check_autonomy", _allow_gate)
    coord._schedule_order_failure_alert = MagicMock()

    submitted = await coord._execute_order_from_monitor(_stop_loss_order())

    assert submitted is True  # 게이트 통과 + 실제 제출까지는 됐다(브로커가 거부)
    coord._schedule_order_failure_alert.assert_called_once()
    order_arg, reason_arg = coord._schedule_order_failure_alert.call_args.args
    assert reason_arg == "거래정지"


async def test_monitor_defensive_sell_repeated_rejection_notifies_once(temp_storage, monkeypatch):
    coord, position = _coordinator_with_position(
        quantity=10, stop_loss_mode=StopLossMode.AGENT_AUTO
    )
    _stub_execute_order_status(coord, status="rejected", message="거래정지")
    monkeypatch.setattr(autonomy_pkg, "check_autonomy", _allow_gate)
    coord._schedule_order_failure_alert = MagicMock()

    await coord._execute_order_from_monitor(_stop_loss_order())
    await coord._execute_order_from_monitor(_stop_loss_order())

    coord._schedule_order_failure_alert.assert_called_once()


# -------------------------------------------
# Important 2 (코디네이터 측): reason 파라미터가 실제로 OrderRequest.reason에
# 실리는지, 미전달 시 기존 기본값이 보존되는지.
# -------------------------------------------


async def test_close_position_reason_param_overrides_default_label(temp_storage):
    coord, position = _coordinator_with_position()
    captured: list[OrderRequest] = []

    async def _exec(order: OrderRequest) -> OrderResult:
        captured.append(order)
        return OrderResult(
            order_id="C1", ticker=order.ticker, side=order.side,
            requested_quantity=order.quantity, filled_quantity=order.quantity,
            avg_price=260_000, status="filled",
        )

    coord._execute_order = _exec

    await coord._close_position("005930", reason="방어청산(손절)")

    assert captured[0].reason == "방어청산(손절)"


async def test_close_position_default_reason_preserved_when_not_passed(temp_storage):
    """handle_alert_action의 CLOSE_POSITION처럼 진짜 사람이 건드린 경로는
    reason을 안 넘긴다 — 기존 문자열이 byte-invariant로 유지돼야 한다."""
    coord, position = _coordinator_with_position()
    captured: list[OrderRequest] = []

    async def _exec(order: OrderRequest) -> OrderResult:
        captured.append(order)
        return OrderResult(
            order_id="C2", ticker=order.ticker, side=order.side,
            requested_quantity=order.quantity, filled_quantity=order.quantity,
            avg_price=260_000, status="filled",
        )

    coord._execute_order = _exec

    await coord._close_position("005930")

    assert captured[0].reason == "User-initiated close"
