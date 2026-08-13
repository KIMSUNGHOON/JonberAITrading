"""Phase4 T2: strategy -> RiskParameters safe mapping.

The self-deregulation seal: an LLM-adapted strategy may move ONLY the
allowlisted sizing/stop knobs, never the autonomy-gate fields. The denylist
invariant test here is the cheapest permanent seal against that vector.

Phase5 결정B: max_trade_notional_pct는 이제 allowlist(STRATEGY_MAPPED_FIELDS)
소속 — [5,30] 하드 바운드 내 자율 사이징 적응(test_strategy_notional_pct_
clamped_to_bounds).

S-4 (생존 규율, decision D4): risk_budget_pct도 allowlist 소속 — [0.25, 1.5]
하드 바운드 내 적응(test_risk_budget_pct_clamped_to_bounds).

변동성 타게팅 (2026-08-07): target_vol_pct/vol_multiplier_min도 allowlist
소속 — [10, 40]/[0.2, 0.8] 하드 바운드 내 적응. 전용 왕복 테스트는
test_vol_knobs.py (test_strategy_values_are_clamped_into_bounds,
test_reset_restores_model_defaults).
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
        "max_trade_notional_pct", "risk_budget_pct",
        "target_vol_pct", "vol_multiplier_min",
    }
    assert GATE_PROTECTED_FIELDS == frozenset({
        "max_daily_loss_pct", "max_open_positions",
        "stop_loss_mode", "take_profit_mode", "sudden_move_threshold_pct",
        "sudden_move_cooldown_ticks", "sudden_move_stabilization_pct",
        "max_daily_trades",
    })
    assert not (set(STRATEGY_MAPPED_FIELDS) & GATE_PROTECTED_FIELDS)
    # 두 집합 모두 실제 RiskParameters 필드명이어야 한다 (오타 봉인)
    fields = set(RiskParameters.model_fields)
    assert set(STRATEGY_MAPPED_FIELDS) <= fields
    assert GATE_PROTECTED_FIELDS <= fields


def test_strategy_notional_pct_clamped_to_bounds():
    """결정 B: EOD 전략 합의가 조정한 max_trade_notional_pct는 [5, 30] 하드
    바운드 밖으로 못 나간다 — StrategyPreset에는 MODERATE가 없어(실제 enum은
    CONSERVATIVE_INCOME/GROWTH_MOMENTUM/TECHNICAL_BREAKOUT/VALUE_INVESTING/
    CUSTOM) risk_tolerance=MODERATE인 TECHNICAL_BREAKOUT 프리셋으로 대체."""
    from services.trading.strategy import get_strategy_preset, StrategyPreset

    rp = RiskParameters()
    s = get_strategy_preset(StrategyPreset.TECHNICAL_BREAKOUT)
    s.position_sizing.max_trade_notional_pct = 40.0  # > 상한 30
    apply_strategy_to_risk_params(s, rp)
    assert rp.max_trade_notional_pct == 30.0
    s.position_sizing.max_trade_notional_pct = 2.0  # < 하한 5
    apply_strategy_to_risk_params(s, rp)
    assert rp.max_trade_notional_pct == 5.0


def test_risk_budget_pct_clamped_to_bounds():
    """S-4 (decision D4): 브리프 Step1 ④ — strategy_apply 클램프 (0.25, 1.5)
    왕복. EOD 전략 합의/수동 편집이 risk_budget_pct를 하드 바운드 밖으로
    밀어내려 해도 [0.25, 1.5] 안으로 클램프된다 (RiskParameters Field 자체의
    (0.1, 3.0)보다 좁은, strategy_apply 독자 클램프)."""
    rp = RiskParameters()
    strategy = _strategy(risk_budget_pct=2.0)  # > 상한 1.5
    apply_strategy_to_risk_params(strategy, rp)
    assert rp.risk_budget_pct == pytest.approx(1.5)

    strategy.position_sizing.risk_budget_pct = 0.15  # < 하한 0.25
    apply_strategy_to_risk_params(strategy, rp)
    assert rp.risk_budget_pct == pytest.approx(0.25)


def test_notional_pct_not_in_gate_protected():
    assert "max_trade_notional_pct" in STRATEGY_MAPPED_FIELDS
    assert "max_trade_notional_pct" not in GATE_PROTECTED_FIELDS
    assert "max_trade_notional_krw" not in GATE_PROTECTED_FIELDS  # 필드 자체 제거


def test_mapping_applies_with_unit_conversion_in_place():
    rp = RiskParameters()
    strategy = _strategy(max_position_pct=0.12, min_cash_ratio=0.25,
                         stop_loss_pct=0.06, take_profit_pct=0.20,
                         max_trade_notional_pct=20.0, risk_budget_pct=1.0,
                         target_vol_pct=25.0, vol_multiplier_min=0.6)
    rp_id = id(rp)
    changes = apply_strategy_to_risk_params(strategy, rp)
    assert id(rp) == rp_id  # in-place, 객체 교체 없음
    assert rp.max_single_position_pct == pytest.approx(0.12)
    assert rp.min_cash_ratio == pytest.approx(0.25)
    assert rp.default_stop_loss_pct == pytest.approx(6.0)   # 분율→퍼센트 ×100
    assert rp.default_take_profit_pct == pytest.approx(20.0)
    assert rp.max_trade_notional_pct == pytest.approx(20.0)
    assert rp.risk_budget_pct == pytest.approx(1.0)
    assert rp.target_vol_pct == pytest.approx(25.0)
    assert rp.vol_multiplier_min == pytest.approx(0.6)
    assert set(changes) == set(STRATEGY_MAPPED_FIELDS)
    assert changes["default_stop_loss_pct"] == (pytest.approx(8.0), pytest.approx(6.0))
    assert changes["risk_budget_pct"] == (pytest.approx(0.75), pytest.approx(1.0))
    assert changes["target_vol_pct"] == (pytest.approx(18.0), pytest.approx(25.0))
    assert changes["vol_multiplier_min"] == (pytest.approx(0.5), pytest.approx(0.6))


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
    # S-2 (survival discipline): RiskParameters.stop_loss_mode's model
    # default flipped USER_APPROVAL -> AGENT_AUTO (decision D1). The real
    # seal invariant is the loop above (nothing in GATE_PROTECTED_FIELDS
    # moves when a strategy is applied) — this assertion only additionally
    # pins the CURRENT default value so a future default change is a
    # deliberate, visible edit here too.
    assert rp.stop_loss_mode == StopLossMode.AGENT_AUTO


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
