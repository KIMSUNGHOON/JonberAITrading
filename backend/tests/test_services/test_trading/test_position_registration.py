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

    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=20,
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

    pm.update_position.assert_called_once_with(
        ticker="005930",
        quantity=20,
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
