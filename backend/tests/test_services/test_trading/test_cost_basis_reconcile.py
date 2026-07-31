"""원가 단일화 C1(2026-07-31): reconciler가 수량뿐 아니라 원가도 브로커에 맞춘다.

_fix_quantities는 quantity != broker_qty일 때만 진입해 수량과 current_price만
고쳤다. 그런데 07-31 라이브 실측에서 089860·317400은 **수량이 맞는 상태에서
원가만** 어긋나 있었다(-0.370%, +0.120%) — 현 조건으로는 영원히 교정되지 않는다.

임계 0.1%는 브로커 avg_buy_prc가 int라(kiwoom/models.py:202) 생기는 주당 최대
0.5원 절삭을 불일치로 오판하지 않기 위한 값이다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trading.models import ManagedPosition
from services.trading.reconciler import ReconcileReport, _fix_positions

pytestmark = pytest.mark.asyncio


def _holding(ticker="089860", qty=185, avg=38_091, cur=38_750):
    h = MagicMock()
    h.stk_cd = ticker
    h.hldg_qty = qty
    h.avg_buy_prc = avg
    h.cur_prc = cur
    return h


def _coordinator(position):
    c = MagicMock()
    c.state.positions = [position] if position else []
    c.risk_monitor = MagicMock()
    c._schedule_persist = MagicMock()
    c._on_alert = AsyncMock()
    return c


def _managed(ticker="089860", qty=185, avg=37_950.0, cur=38_750.0,
             stop_loss=None, take_profit=None):
    return ManagedPosition(
        ticker=ticker, stock_name="롯데렌탈",
        quantity=qty, avg_price=avg, current_price=cur,
        stop_loss=stop_loss, take_profit=take_profit,
    )


def _pm(position=None):
    pm = MagicMock()
    pm.get_position = MagicMock(return_value=position)
    pm.update_position = MagicMock()
    return pm


async def test_cost_basis_fixed_when_quantity_already_matches():
    """07-31 실측 케이스 — 수량은 맞고 원가만 0.37% 어긋난다."""
    pos = _managed(qty=185, avg=37_950.0)
    coordinator = _coordinator(pos)
    pm_pos = MagicMock(quantity=185, avg_price=37_950.0)
    pm = _pm(pm_pos)
    report = ReconcileReport()

    await _fix_positions(coordinator, pm, {"089860": _holding()}, report)

    assert pos.avg_price == 38_091.0, "coordinator 원가가 브로커 값이 된다"
    assert report.cost_basis_fixed == 1
    kwargs = pm.update_position.call_args.kwargs
    assert kwargs["avg_price"] == 38_091.0, "PM 원가도 브로커 값이 된다"


async def test_quantity_and_cost_both_fixed():
    """148주 원가가 185주에 적용된 상태 — 둘 다 교정된다."""
    pos = _managed(qty=148, avg=37_950.0)
    coordinator = _coordinator(pos)
    pm = _pm(MagicMock(quantity=148, avg_price=37_950.0))
    report = ReconcileReport()

    await _fix_positions(coordinator, pm, {"089860": _holding(qty=185)}, report)

    assert pos.quantity == 185
    assert pos.avg_price == 38_091.0
    assert report.quantity_fixed == 1
    assert report.cost_basis_fixed == 1


async def test_below_threshold_not_fixed():
    """0.05% 편차는 브로커 int 절삭 범위라 교정하지 않는다."""
    pos = _managed(qty=185, avg=38_072.0)  # 38,091 대비 -0.0499%
    coordinator = _coordinator(pos)
    pm = _pm(MagicMock(quantity=185, avg_price=38_072.0))
    report = ReconcileReport()

    await _fix_positions(coordinator, pm, {"089860": _holding()}, report)

    assert pos.avg_price == 38_072.0, "임계 미만은 그대로 둔다"
    assert report.cost_basis_fixed == 0


async def test_stops_are_never_recalculated():
    """원가를 고쳐도 손절·익절은 건드리지 않는다(이 아크의 소급 원칙)."""
    pos = _managed(qty=185, avg=37_950.0, stop_loss=36_425.0, take_profit=41_462.0)
    coordinator = _coordinator(pos)
    pm = _pm(MagicMock(quantity=185, avg_price=37_950.0))
    report = ReconcileReport()

    await _fix_positions(coordinator, pm, {"089860": _holding()}, report)

    assert pos.stop_loss == 36_425.0
    assert pos.take_profit == 41_462.0
    assert "stop_loss" not in pm.update_position.call_args.kwargs or \
        pm.update_position.call_args.kwargs.get("stop_loss") is None


async def test_no_position_is_noop():
    """대응 포지션이 없으면 아무것도 하지 않는다(고아 채택은 별도 단계 소관)."""
    coordinator = _coordinator(None)
    pm = _pm(None)
    report = ReconcileReport()

    await _fix_positions(coordinator, pm, {"089860": _holding()}, report)

    assert report.cost_basis_fixed == 0
    pm.update_position.assert_not_called()


async def test_zero_broker_avg_is_ignored():
    """브로커 평단이 0이면 교정하지 않는다 — 원가를 0으로 만들면 안 된다."""
    pos = _managed(qty=185, avg=37_950.0)
    coordinator = _coordinator(pos)
    pm = _pm(MagicMock(quantity=185, avg_price=37_950.0))
    report = ReconcileReport()

    await _fix_positions(coordinator, pm, {"089860": _holding(avg=0)}, report)

    assert pos.avg_price == 37_950.0
    assert report.cost_basis_fixed == 0


# ---------------------------------------------------------------
# C3: 원가 정합성 감시
# ---------------------------------------------------------------


async def test_drift_sends_alert_once():
    """편차를 발견하면 알리고, 같은 종목은 다시 알리지 않는다."""
    from services.trading import reconciler as R

    R._COST_DRIFT_NOTIFIED.clear()
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    pos = _managed(qty=185, avg=37_950.0)
    coordinator = _coordinator(pos)
    pm = _pm(MagicMock(quantity=185, avg_price=37_950.0))

    with patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(return_value=notifier)):
        await _fix_positions(coordinator, pm, {"089860": _holding()}, ReconcileReport())
        # 두 번째 패스 — 이미 교정됐어도 래치가 재발송을 막는다
        await _fix_positions(coordinator, pm, {"089860": _holding()}, ReconcileReport())

    notifier.send_message.assert_awaited_once()
    body = notifier.send_message.await_args.args[0]
    assert "089860" in body
    assert "원가" in body


async def test_alert_never_raises():
    """통지 실패가 교정 경로를 깨뜨리지 않는다."""
    from services.trading import reconciler as R

    R._COST_DRIFT_NOTIFIED.clear()
    pos = _managed(qty=185, avg=37_950.0)
    coordinator = _coordinator(pos)
    pm = _pm(MagicMock(quantity=185, avg_price=37_950.0))
    report = ReconcileReport()

    with patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(side_effect=RuntimeError("telegram down"))):
        await _fix_positions(coordinator, pm, {"089860": _holding()}, report)

    assert pos.avg_price == 38_091.0, "통지가 터져도 교정은 완료된다"
    assert report.cost_basis_fixed == 1


async def test_no_alert_below_threshold():
    """임계 미만이면 알리지 않는다 — 오탐 방지."""
    from services.trading import reconciler as R

    R._COST_DRIFT_NOTIFIED.clear()
    notifier = MagicMock()
    notifier.is_ready = True
    notifier.send_message = AsyncMock(return_value=True)

    pos = _managed(qty=185, avg=38_072.0)
    coordinator = _coordinator(pos)
    pm = _pm(MagicMock(quantity=185, avg_price=38_072.0))

    with patch("services.telegram.get_telegram_notifier",
               new=AsyncMock(return_value=notifier)):
        await _fix_positions(coordinator, pm, {"089860": _holding()}, ReconcileReport())

    notifier.send_message.assert_not_awaited()
