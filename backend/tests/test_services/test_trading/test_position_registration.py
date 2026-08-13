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
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.agent_chat.position_manager import MonitoredPosition, PositionManager
from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import (
    AllocationPlan,
    ManagedPosition,
    OrderResult,
    OrderSide,
    StopLossMode,
    TradingMode,
)
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
    # C2(2026-07-31): merge 분기가 이제 avg_price도 가중평균으로 넘긴다
    # (5주@68,000 + 15주@69,000)/20 = 68,750.0. 이 값 검증은 이 테스트의
    # 원래 취지(스탑 coalesce)가 아니라 새 인자가 호출부에 추가됐다는
    # 사실만 반영한다 — 가중평균 자체의 상세 검증은
    # test_merge_updates_avg_price_with_weighted_average가 전담한다.
    pm.add_position.assert_not_called()
    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=20,
        avg_price=68_750.0,
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

    # C2(2026-07-31): avg_price도 함께 넘어간다. 이 테스트는 두 트랜치가 같은
    # 가격(260,000.0)이라 가중평균도 260,000.0 그대로 — quantity 합산이
    # 이 시나리오의 핵심이라는 원래 취지는 그대로 유지된다.
    assert coordinator._add_position.call_count == 1
    pm.add_position.assert_not_called()
    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=48,
        avg_price=260000.0,
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


async def test_missing_stock_name_does_not_raise_and_still_registers(monkeypatch):
    """Task 13: 이름을 못 구한 경로(브로커/세션 조회 실패 등)라도 등록 자체가
    실패하면 안 된다 — 이름 때문에 매매가 멈추는 것이 가장 나쁜 결과다.
    빈 문자열이 stock_name으로 들어와도 예외 없이 양쪽 엔진에 등록된다."""
    coordinator = _coordinator()
    pm = _pm(existing=None)
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(pm)),
    )

    await register_fill_as_position(
        coordinator,
        ticker="005930",
        stock_name="",
        quantity=10,
        avg_price=70000.0,
        stop_loss=66500.0,
        take_profit=77000.0,
    )

    assert coordinator._add_position.call_count == 1
    pos = coordinator._add_position.call_args.args[0]
    assert pos.stock_name == ""
    pm.add_position.assert_called_once()
    assert pm.add_position.call_args.kwargs["stock_name"] == ""


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
# entry_decision_id round trip (L3 introduced this field, 2026-07-19,
# docs/superpowers/specs/2026-07-19-decision-lineage-design.md; L4 corrected
# the merge branch below -- see the docstrings)
# -------------------------------------------
#
# Mirrors the ManagedPosition.analysis_session_id wiring above, but for the
# PM's OWN ledger (MonitoredPosition.entry_decision_id). A fresh position
# gets the incoming session_id outright. An EXISTING position's
# entry_decision_id is NEVER touched by a merge -- not even to backfill a
# None -- mirroring ExecutionCoordinator._add_position's merge branch, which
# never touches analysis_session_id once a position already exists (L4: the
# original L3 implementation backfilled a None entry_decision_id on merge,
# which mis-attributes an unrelated later fill's session_id as the "entry
# decision" for a position whose real entry legitimately has none, e.g. an
# orphan adopted with no upstream decision, D3/D2 -- corrupting
# calibration's entry-decision outcome scoring).


async def test_existing_pm_entry_decision_id_never_backfilled_on_merge(monkeypatch):
    """The PM's own ledger has no entry_decision_id yet (e.g. this ticker was
    adopted as an orphan with no originating decision, D3) -- a later fill's
    session_id must NOT be adopted as the entry decision. entry_decision_id
    is set ONLY on a brand-new position (the branch above), never on merge
    (L4 correction of L3's original backfill-if-None behavior)."""
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
        session_id="sess-should-not-backfill",
    )

    # C2(2026-07-31): avg_price도 가중평균으로 함께 넘어간다
    # (5주@68,000 + 15주@69,000)/20 = 68,750.0 — 이 테스트의 초점은
    # entry_decision_id지만 merge 분기 호출 형태가 바뀌었으므로 반영한다.
    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=20,
        avg_price=68_750.0,
        stop_loss=None,
        take_profit=None,
        entry_decision_id=None,
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

    # C2(2026-07-31): avg_price도 가중평균으로 함께 넘어간다(동일 시나리오,
    # 초점은 entry_decision_id 불변식).
    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=20,
        avg_price=68_750.0,
        stop_loss=None,
        take_profit=None,
        entry_decision_id=None,
    )


# -------------------------------------------
# H3 — on_trade_approved's IMMEDIATE-fill BUY branch must register through
# register_fill_as_position too (dual-engine parity with the pending/partial
# fill branch at coordinator.py:~3240), not a bare manual `_add_position`.
# -------------------------------------------


def _h3_open_session() -> MarketSession:
    """A market session that is open right now — mirrors
    test_r5_p0_autotrade_safety.py's `_open_session` so `on_trade_approved`
    takes the immediate-execution path instead of queueing."""
    return MarketSession(
        is_open=True,
        current_time=datetime.now(),
        next_open=None,
        next_close=None,
        message="open",
    )


def _h3_live_coordinator() -> ExecutionCoordinator:
    """A coordinator wired to execute a BUY immediately (ACTIVE + market
    open + a stubbed allocation), same shape as
    test_r5_p0_autotrade_safety.py's `_live_coordinator`."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(return_value=_h3_open_session())
    coord._refresh_account_info = AsyncMock()
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=OrderSide.BUY,
            quantity=10,
            entry_price=70_000,
            estimated_amount=700_000,
            position_pct=1.0,
            rationale="stub allocation",
            rebalance_orders=[],
        )
    )
    return coord


def _h3_stub_immediate_full_fill(coord: ExecutionCoordinator) -> None:
    """Stub `_execute_order` so the order fills in FULL immediately
    (result.filled_quantity > 0), driving `on_trade_approved`'s
    immediate-fill BUY branch rather than the unfilled/partial tracker."""

    async def _exec(order):
        return OrderResult(
            order_id="o1",
            ticker=order.ticker,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=order.price or 70_000,
            status="filled",
        )

    coord._execute_order = _exec


async def test_immediate_fill_buy_registers_via_register_fill_as_position(monkeypatch):
    """H3: 즉시체결 BUY가 pending체결과 동일하게 register_fill_as_position로
    등록돼 PositionManager까지 미러된다(단일 _add_position 아님)."""
    from unittest.mock import patch

    coord = _h3_live_coordinator()
    _h3_stub_immediate_full_fill(coord)

    with patch("services.trading.coordinator.register_fill_as_position", new=AsyncMock()) as reg:
        await coord.on_trade_approved(
            session_id="sess-h3",
            ticker="005930",
            stock_name="삼성전자",
            action="BUY",
            entry_price=70_000,
            stop_loss=66_500,
            take_profit=77_000,
            risk_score=5,
        )

        reg.assert_awaited_once()
        _, kwargs = reg.call_args
        assert kwargs["ticker"] == "005930"
        assert kwargs["quantity"] > 0
        assert kwargs["source"] == "placement_fill"


def test_mirror_sell_full_close_calls_pm_remove(monkeypatch):
    """remaining<=0 → PM.remove_position 호출."""
    from unittest.mock import MagicMock
    import services.trading.position_registration as pr
    pm = MagicMock()
    chat = MagicMock(); chat.position_manager = pm
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator_sync", lambda: chat
    )
    pr.mirror_sell_to_position_manager("005930", 0)
    pm.remove_position.assert_called_once_with("005930")
    pm.update_position.assert_not_called()


def test_mirror_sell_partial_calls_pm_update_with_remaining(monkeypatch):
    """remaining>0 → PM.update_position(quantity=remaining) 절대값 할당."""
    from unittest.mock import MagicMock
    import services.trading.position_registration as pr
    pm = MagicMock()
    chat = MagicMock(); chat.position_manager = pm
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator_sync", lambda: chat
    )
    pr.mirror_sell_to_position_manager("005930", 25)
    pm.update_position.assert_called_once_with("005930", quantity=25)
    pm.remove_position.assert_not_called()


def test_mirror_sell_pm_not_running_is_noop(monkeypatch):
    """PM 미기동(position_manager None) → no-op, 예외 없음."""
    from unittest.mock import MagicMock
    import services.trading.position_registration as pr
    chat = MagicMock(); chat.position_manager = None
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator_sync", lambda: chat
    )
    pr.mirror_sell_to_position_manager("005930", 0)  # 예외 없이 통과


def test_mirror_sell_never_raises_on_pm_error(monkeypatch):
    """PM 미러가 예외를 던져도 never-raise(로그만)."""
    from unittest.mock import MagicMock
    import services.trading.position_registration as pr
    pm = MagicMock(); pm.remove_position.side_effect = RuntimeError("boom")
    chat = MagicMock(); chat.position_manager = pm
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator_sync", lambda: chat
    )
    pr.mirror_sell_to_position_manager("005930", 0)  # 예외 전파 안 함


# ---------------------------------------------------------------
# 원가 단일화 C2 (2026-07-31): merge 분기가 avg_price를 갱신한다
#
# 지금까지 merge 분기는 quantity만 합산하고 avg_price를 넘기지 않아
# PM 평단이 첫 체결 트랜치에 영구 동결됐다. 그 평단은 표시가 아니라
# 손절·익절 거리의 기준선이라, 낮게 고정되면 손절가도 낮게 잡혀
# 실제 손실 허용폭이 설계보다 커진다.
#
# NOTE: 브리프 원문의 예시 코드는 register_fill_as_position을 동기 호출로,
# position_manager를 직접 인자로 넘기는 형태로 적어 두었으나, 이 저장소의
# 실제 시그니처는 async이고 PM은 함수 내부에서 get_chat_coordinator()로
# 지연 조회한다(F3 설계, 위 헬퍼 docstring 참조). 시나리오·수치·검증 내용은
# 브리프와 동일하게 유지하고, 호출부만 파일 상단의 기존 비동기 테스트들과
# 같은 방식(await + monkeypatch)으로 맞췄다.
# ---------------------------------------------------------------


async def test_merge_updates_avg_price_with_weighted_average(monkeypatch):
    """2트랜치 체결: 20주@10,000 보유 + 28주@11,000 체결 → 평단 10,583.33"""
    existing = MonitoredPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=20,
        avg_price=10_000.0,
        current_price=11_000.0,
    )
    pm = _pm(existing)
    coordinator = _coordinator()
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(pm)),
    )

    await register_fill_as_position(
        coordinator,
        ticker="005930",
        stock_name="삼성전자",
        quantity=28,
        avg_price=11_000.0,
        stop_loss=9_000.0,
        take_profit=13_000.0,
        session_id="sess-1",
        source="test",
    )

    pm.update_position.assert_called_once()
    kwargs = pm.update_position.call_args.kwargs
    assert kwargs["quantity"] == 48
    expected = (20 * 10_000.0 + 28 * 11_000.0) / 48
    assert kwargs["avg_price"] == pytest.approx(expected)
    assert kwargs["avg_price"] == pytest.approx(10_583.3333, abs=0.001)


async def test_merge_preserves_existing_stops(monkeypatch):
    """원가를 갱신해도 기존 손절·익절은 덮어쓰지 않는다(coalesce 불변)."""
    existing = MonitoredPosition(
        ticker="005930", stock_name="삼성전자",
        quantity=20, avg_price=10_000.0, current_price=11_000.0,
        stop_loss=9_500.0, take_profit=12_000.0,
    )
    pm = _pm(existing)
    coordinator = _coordinator()
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(pm)),
    )

    await register_fill_as_position(
        coordinator,
        ticker="005930", stock_name="삼성전자",
        quantity=28, avg_price=11_000.0,
        stop_loss=8_000.0, take_profit=14_000.0,
        session_id="sess-1", source="test",
    )

    kwargs = pm.update_position.call_args.kwargs
    assert kwargs["stop_loss"] is None, "기존 스탑이 있으면 None을 넘겨 coalesce"
    assert kwargs["take_profit"] is None
    assert kwargs["avg_price"] is not None, "원가는 갱신한다"


async def test_merge_never_touches_entry_decision_id(monkeypatch):
    """merge 분기는 entry_decision_id를 절대 건드리지 않는다(고아 채택 보호)."""
    existing = MonitoredPosition(
        ticker="005930", stock_name="삼성전자",
        quantity=20, avg_price=10_000.0, current_price=11_000.0,
    )
    pm = _pm(existing)
    coordinator = _coordinator()
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(pm)),
    )

    await register_fill_as_position(
        coordinator,
        ticker="005930", stock_name="삼성전자",
        quantity=28, avg_price=11_000.0,
        stop_loss=None, take_profit=None,
        session_id="sess-2", source="test",
    )

    assert pm.update_position.call_args.kwargs["entry_decision_id"] is None


async def test_new_position_still_uses_add_position(monkeypatch):
    """기존 포지션이 없으면 add_position 경로 그대로 — merge 변경의 영향 없음."""
    pm = _pm(None)
    coordinator = _coordinator()
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_chat_coordinator",
        AsyncMock(return_value=_chat_coordinator(pm)),
    )

    await register_fill_as_position(
        coordinator,
        ticker="005930", stock_name="삼성전자",
        quantity=28, avg_price=11_000.0,
        stop_loss=9_000.0, take_profit=13_000.0,
        session_id="sess-1", source="test",
    )

    pm.add_position.assert_called_once()
    pm.update_position.assert_not_called()
    assert pm.add_position.call_args.kwargs["avg_price"] == 11_000.0
