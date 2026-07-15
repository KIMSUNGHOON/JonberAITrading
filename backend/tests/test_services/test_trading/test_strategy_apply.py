"""Phase4 T2: strategy -> RiskParameters safe mapping.

The self-deregulation seal: an LLM-adapted strategy may move ONLY the 4
allowlisted sizing/stop knobs, never the autonomy-gate fields. The denylist
invariant test here is the cheapest permanent seal against that vector.
"""

import pytest

from services.trading.models import RiskParameters, StopLossMode
from services.trading.strategy import TradingStrategy
from services.trading.strategy_apply import (
    GATE_PROTECTED_FIELDS,
    STRATEGY_MAPPED_FIELDS,
    apply_strategy_to_risk_params,
)


def _strategy(**kw):
    s = TradingStrategy()
    for k, v in kw.items():
        obj, attr = (
            (s.position_sizing, k) if hasattr(s.position_sizing, k) else (s.exit_conditions, k)
        )
        setattr(obj, attr, v)
    return s


def test_allowlist_and_denylist_are_disjoint_and_exact():
    assert set(STRATEGY_MAPPED_FIELDS) == {
        "max_single_position_pct", "min_cash_ratio",
        "default_stop_loss_pct", "default_take_profit_pct",
    }
    assert GATE_PROTECTED_FIELDS == frozenset({
        "max_daily_loss_pct", "max_open_positions", "max_trade_notional_krw",
        "stop_loss_mode", "take_profit_mode", "sudden_move_threshold_pct",
        "sudden_move_cooldown_ticks", "sudden_move_stabilization_pct",
        "max_daily_trades",
    })
    assert not (set(STRATEGY_MAPPED_FIELDS) & GATE_PROTECTED_FIELDS)
    # 두 집합 모두 실제 RiskParameters 필드명이어야 한다 (오타 봉인)
    fields = set(RiskParameters.model_fields)
    assert set(STRATEGY_MAPPED_FIELDS) <= fields
    assert GATE_PROTECTED_FIELDS <= fields


def test_mapping_applies_with_unit_conversion_in_place():
    rp = RiskParameters()
    strategy = _strategy(max_position_pct=0.12, min_cash_ratio=0.25,
                         stop_loss_pct=0.06, take_profit_pct=0.20)
    rp_id = id(rp)
    changes = apply_strategy_to_risk_params(strategy, rp)
    assert id(rp) == rp_id  # in-place, 객체 교체 없음
    assert rp.max_single_position_pct == pytest.approx(0.12)
    assert rp.min_cash_ratio == pytest.approx(0.25)
    assert rp.default_stop_loss_pct == pytest.approx(6.0)   # 분율→퍼센트 ×100
    assert rp.default_take_profit_pct == pytest.approx(20.0)
    assert set(changes) == set(STRATEGY_MAPPED_FIELDS)
    assert changes["default_stop_loss_pct"] == (pytest.approx(8.0), pytest.approx(6.0))


def test_mapping_clamps_to_bounds():
    rp = RiskParameters()
    strategy = _strategy(max_position_pct=0.50, stop_loss_pct=0.01)
    apply_strategy_to_risk_params(strategy, rp)
    assert rp.max_single_position_pct == pytest.approx(0.30)  # hi 클램프
    assert rp.default_stop_loss_pct == pytest.approx(3.0)     # lo 클램프 (0.01→1.0%→3.0%)


def test_gate_protected_fields_never_move():
    """자기-탈규제 봉인 — 극단 전략을 적용해도 denylist 9필드는 원값 그대로."""
    rp = RiskParameters()
    before = {f: getattr(rp, f) for f in GATE_PROTECTED_FIELDS}
    strategy = _strategy(max_position_pct=0.50, min_cash_ratio=0.0,
                         stop_loss_pct=0.50, take_profit_pct=1.0)
    strategy.position_sizing.max_positions = 50  # 매핑 대상 아님 — 게이트 캡에 못 닿아야 함
    apply_strategy_to_risk_params(strategy, rp)
    for field, value in before.items():
        assert getattr(rp, field) == value, f"{field} moved!"
    assert rp.stop_loss_mode == StopLossMode.USER_APPROVAL


def test_none_strategy_resets_mapped_fields_to_defaults():
    rp = RiskParameters()
    apply_strategy_to_risk_params(_strategy(max_position_pct=0.12, stop_loss_pct=0.06), rp)
    changes = apply_strategy_to_risk_params(None, rp)
    defaults = RiskParameters()
    for field in STRATEGY_MAPPED_FIELDS:
        assert getattr(rp, field) == getattr(defaults, field)
    assert set(changes) == set(STRATEGY_MAPPED_FIELDS)


def test_no_change_returns_empty_changes():
    rp = RiskParameters()
    strategy = TradingStrategy()  # 기본 노브
    first = apply_strategy_to_risk_params(strategy, rp)
    second = apply_strategy_to_risk_params(strategy, rp)
    assert second == {}  # 두 번째 적용은 무변경


async def test_set_strategy_wires_mapping_and_shared_references_see_it():
    """coordinator.set_strategy가 매핑을 호출하고, 참조 공유자(PortfolioAgent)가
    같은 객체로 새 값을 본다. (이웃 테스트의 coordinator 생성 관례 재사용 —
    ExecutionCoordinator(kiwoom_client=None) 패턴, test_strategy_restore.py 참조)"""
    from services.trading.coordinator import ExecutionCoordinator

    coordinator = ExecutionCoordinator(kiwoom_client=None)
    strategy = _strategy(max_position_pct=0.12, stop_loss_pct=0.06)
    coordinator.set_strategy(strategy)
    assert coordinator.risk_params.max_single_position_pct == pytest.approx(0.12)
    assert coordinator.portfolio_agent.risk_params is coordinator.risk_params
    assert coordinator.risk_monitor.risk_params is coordinator.risk_params
    coordinator.set_strategy(None)
    assert coordinator.risk_params.max_single_position_pct == pytest.approx(0.15)
