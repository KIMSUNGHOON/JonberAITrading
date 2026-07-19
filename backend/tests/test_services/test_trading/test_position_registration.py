"""register_fill_as_position 단위 테스트 — 양쪽 감시 엔진(coordinator+PM) 공용 등록.

register_fill_as_position은 (1) ExecutionCoordinator._add_position을 항상 먼저
실행하고, (2) agent-chat PositionManager 미러링을 전체 try/except로 감싸 실패해도
(1)을 되돌리거나 예외를 전파하지 않는다. PM에 이미 사용자가 설정한 스탑(non-None)이
있으면 신규 체결값으로 덮어쓰지 않는다(coalesce).

F3 전반에서 `quantity`는 증분 체결량(FillDelta.new_fill_qty)이다 —
coordinator._add_position은 자체적으로 평균 합산하지만 PM.update_position은
절대값 할당이므로, 기존 PM 포지션이 있으면 existing.quantity + delta로 합산해
넘겨야 한다(2-트랜치 체결 20+28=48 시나리오).

지연 import(함수 내부 import)를 쓰므로 patch 지점은 헬퍼 모듈이 아니라 원본
`services.agent_chat.coordinator.get_chat_coordinator`.
"""
from unittest.mock import AsyncMock, MagicMock

from services.agent_chat.position_manager import MonitoredPosition, PositionManager
from services.trading.models import ManagedPosition, StopLossMode
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
    # current_price 누락 시 Pydantic 기본값 0 → unrealized_pnl_pct가 상시 -100%,
    # portfolio_agent 노출 계산도 0으로 잡힘 — coordinator.py:594 관례대로 avg_price.
    assert pos.current_price == 70000.0
    assert pos.stop_loss == 66500.0
    assert pos.take_profit == 77000.0
    assert pos.analysis_session_id == "sess-1"

    # (2) PM: 신규 티커 → add_position, 스탑 그대로 전달 + entry_decision_id=session_id
    # (L3: 코디네이터 쪽 analysis_session_id와 동일 id가 PM 쪽 entry_decision_id로도 전달)
    pm.add_position.assert_called_once_with(
        ticker="005930",
        stock_name="삼성전자",
        quantity=10,
        avg_price=70000.0,
        stop_loss=66500.0,
        take_profit=77000.0,
        entry_decision_id="sess-1",
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
    # take_profit은 기존 None이었으므로 신규값 전달, quantity는 증분 합산(5+15=20).
    # session_id 미전달(None) + 기존 entry_decision_id도 None → coalesce 결과 None
    # (L3: 값이 없으니 백필할 것도 없음).
    pm.add_position.assert_not_called()
    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=20,
        stop_loss=None,
        take_profit=77000.0,
        entry_decision_id=None,
    )


async def test_incremental_fill_delta_sums_into_existing_pm_quantity(monkeypatch):
    """2-트랜치 체결: PM 기존 20주 + 증분 28주 → update_position(quantity=48).

    quantity는 F3 전반에서 증분 델타(FillDelta.new_fill_qty)다. PM.update_position은
    절대값 할당이므로 델타를 그대로 넘기면 PM이 28로 끝나고 코디네이터는 48 —
    PM이 20주를 조용히 과소보고한다.
    """
    coordinator = _coordinator()
    existing = MonitoredPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=20,
        avg_price=260000.0,
        current_price=260000.0,
        stop_loss=None,
        take_profit=None,
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
        quantity=28,
        avg_price=260000.0,
        stop_loss=246560.0,
        take_profit=289440.0,
    )

    assert coordinator._add_position.call_count == 1
    pm.add_position.assert_not_called()
    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=48,
        stop_loss=246560.0,
        take_profit=289440.0,
        entry_decision_id=None,
    )


async def test_pm_not_running_skips_mirror_without_error(monkeypatch):
    """챗 코디네이터는 있으나 미기동(position_manager is None) → 스킵, 예외 없음."""
    coordinator = _coordinator()
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(None)),
    )

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


async def test_optional_stop_mode_and_risk_score_thread_into_managed_position(monkeypatch):
    """F3 review LOW-a: 폴링 경로가 발주 시점 체결 경로(coordinator.py:597-600)와
    같은 의미로 등록되도록 stop_loss_mode/risk_score를 선택 인자로 스레딩한다.
    미전달 시엔 ManagedPosition 기본값 유지(기존 3소비자 하위호환)."""
    coordinator = _coordinator()
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(_pm(existing=None))),
    )

    await register_fill_as_position(
        coordinator,
        ticker="005930",
        stock_name="삼성전자",
        quantity=10,
        avg_price=70000.0,
        stop_loss=66500.0,
        take_profit=77000.0,
        stop_loss_mode=StopLossMode.AGENT_AUTO,
        risk_score=6,
    )

    pos = coordinator._add_position.call_args.args[0]
    assert pos.stop_loss_mode == StopLossMode.AGENT_AUTO
    assert pos.risk_score == 6

    # 미전달이면 모델 기본값 그대로 (하위호환)
    coordinator2 = _coordinator()
    await register_fill_as_position(
        coordinator2,
        ticker="005930",
        stock_name="삼성전자",
        quantity=10,
        avg_price=70000.0,
        stop_loss=66500.0,
        take_profit=77000.0,
    )
    pos2 = coordinator2._add_position.call_args.args[0]
    assert pos2.stop_loss_mode == StopLossMode.USER_APPROVAL
    assert pos2.risk_score is None


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


# -------------------------------------------
# entry_decision_id round trip (L3, 2026-07-19,
# docs/superpowers/specs/2026-07-19-decision-lineage-design.md)
# -------------------------------------------
#
# Mirrors the ManagedPosition.analysis_session_id wiring above, but for the
# PM's OWN ledger (MonitoredPosition.entry_decision_id). Same coalesce
# discipline as stop_loss/take_profit: a fresh position gets the incoming
# session_id outright; an existing position only backfills when its own
# entry_decision_id is still None -- a real, already-recorded entry decision
# is never overwritten by a later fill's session_id (mirrors
# ExecutionCoordinator._add_position's merge branch, which never touches
# analysis_session_id once a position already exists).


async def test_existing_pm_entry_decision_id_backfilled_when_none(monkeypatch):
    """The PM's own ledger has no entry_decision_id yet (e.g. this ticker was
    first registered by a path with no session_id) -- a later fill carrying
    a real session_id backfills it."""
    coordinator = _coordinator()
    existing = MonitoredPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=5,
        avg_price=68000.0,
        current_price=70000.0,
        stop_loss=None,
        take_profit=None,
        entry_decision_id=None,
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
        stop_loss=None,
        take_profit=None,
        session_id="sess-backfill",
    )

    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=20,
        stop_loss=None,
        take_profit=None,
        entry_decision_id="sess-backfill",
    )


async def test_existing_pm_entry_decision_id_not_overwritten_once_set(monkeypatch):
    """The PM's own ledger already has a real entry_decision_id (the first
    tranche's discussion) -- a second tranche's DIFFERENT session_id must
    NOT overwrite it. Entry is a one-time fact, mirroring the coordinator's
    own ManagedPosition.analysis_session_id merge behavior."""
    coordinator = _coordinator()
    existing = MonitoredPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=5,
        avg_price=68000.0,
        current_price=70000.0,
        stop_loss=None,
        take_profit=None,
        entry_decision_id="sess-original-entry",
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
        stop_loss=None,
        take_profit=None,
        session_id="sess-second-tranche",
    )

    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=20,
        stop_loss=None,
        take_profit=None,
        entry_decision_id=None,
    )
