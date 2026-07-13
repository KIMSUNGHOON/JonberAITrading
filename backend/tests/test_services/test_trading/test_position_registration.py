"""register_fill_as_position 단위 테스트 — 양쪽 감시 엔진(coordinator+PM) 공용 등록.

register_fill_as_position은 (1) ExecutionCoordinator._add_position을 항상 먼저
실행하고, (2) agent-chat PositionManager 미러링을 전체 try/except로 감싸 실패해도
(1)을 되돌리거나 예외를 전파하지 않는다. PM에 이미 사용자가 설정한 스탑(non-None)이
있으면 신규 체결값으로 덮어쓰지 않는다(coalesce).

지연 import(함수 내부 import)를 쓰므로 patch 지점은 헬퍼 모듈이 아니라 원본
`services.agent_chat.coordinator.get_chat_coordinator`.
"""
from unittest.mock import AsyncMock, MagicMock

from services.agent_chat.position_manager import MonitoredPosition, PositionManager
from services.trading.models import ManagedPosition
from services.trading.position_registration import register_fill_as_position


def _coordinator():
    coordinator = MagicMock()
    coordinator._add_position = MagicMock()
    return coordinator


def _pm(existing: MonitoredPosition | None = None):
    pm = MagicMock(spec=PositionManager)
    pm.get_position = MagicMock(return_value=existing)
    pm.add_position = MagicMock()
    pm.update_position = MagicMock()
    return pm


def _chat_coordinator(pm):
    cc = MagicMock()
    cc.position_manager = pm
    return cc


async def test_new_position_registers_in_both_engines_with_stops(monkeypatch):
    coordinator = _coordinator()
    pm = _pm(existing=None)
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(pm)),
    )

    await register_fill_as_position(
        coordinator,
        ticker="005930",
        stock_name="삼성전자",
        quantity=10,
        avg_price=70000.0,
        stop_loss=66500.0,
        take_profit=77000.0,
        session_id="sess-1",
    )

    # (1) 코디네이터: ManagedPosition으로 등록
    assert coordinator._add_position.call_count == 1
    pos = coordinator._add_position.call_args.args[0]
    assert isinstance(pos, ManagedPosition)
    assert pos.ticker == "005930"
    assert pos.stock_name == "삼성전자"
    assert pos.quantity == 10
    assert pos.avg_price == 70000.0
    assert pos.stop_loss == 66500.0
    assert pos.take_profit == 77000.0
    assert pos.analysis_session_id == "sess-1"

    # (2) PM: 신규 티커 → add_position, 스탑 그대로 전달
    pm.add_position.assert_called_once_with(
        ticker="005930",
        stock_name="삼성전자",
        quantity=10,
        avg_price=70000.0,
        stop_loss=66500.0,
        take_profit=77000.0,
    )
    pm.update_position.assert_not_called()


async def test_existing_pm_stop_is_preserved_but_quantity_updates(monkeypatch):
    coordinator = _coordinator()
    existing = MonitoredPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=5,
        avg_price=68000.0,
        current_price=70000.0,
        stop_loss=64000.0,  # 사용자가 수동으로 설정한 손절가 — 덮어쓰면 안 됨
        take_profit=None,   # 익절은 미설정 — 신규 체결값으로 채워도 됨
    )
    pm = _pm(existing=existing)
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(pm)),
    )

    await register_fill_as_position(
        coordinator,
        ticker="005930",
        stock_name="삼성전자",
        quantity=15,
        avg_price=69000.0,
        stop_loss=66500.0,
        take_profit=77000.0,
    )

    # 코디네이터 등록은 항상 실행
    assert coordinator._add_position.call_count == 1

    # PM: 기존 티커 → update_position, stop_loss는 기존 non-None이라 미전달(None),
    # take_profit은 기존 None이었으므로 신규값 전달, quantity는 항상 갱신
    pm.add_position.assert_not_called()
    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=15,
        stop_loss=None,
        take_profit=77000.0,
    )


async def test_pm_lookup_failure_does_not_prevent_coordinator_registration(monkeypatch):
    coordinator = _coordinator()
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(side_effect=RuntimeError("chat coordinator boom")),
    )

    # 예외가 전파되면 실패
    await register_fill_as_position(
        coordinator,
        ticker="005930",
        stock_name="삼성전자",
        quantity=10,
        avg_price=70000.0,
        stop_loss=66500.0,
        take_profit=77000.0,
    )

    assert coordinator._add_position.call_count == 1
