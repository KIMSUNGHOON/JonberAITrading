import pytest

from services.trading.exposure_target import compute_regime_target
from services.trading.models import RiskParameters
from services.trading.strategy import TradingStrategy
from services.trading.strategy_apply import (
    STRATEGY_MAPPED_FIELDS,
    apply_strategy_to_risk_params,
)


def _t(**over):
    kw = dict(
        regime_label="bear", prev_effective_pct=0.30, seed_actual_pct=0.15,
        index_returns=[6.4, -6.4] * 10, equity=100.0, equity_peak=100.0,
    )
    kw.update(over)
    return compute_regime_target(**kw)


def test_knobs_are_mapped_with_the_designed_bounds():
    assert STRATEGY_MAPPED_FIELDS["target_vol_pct"] == (10.0, 40.0)
    assert STRATEGY_MAPPED_FIELDS["vol_multiplier_min"] == (0.2, 0.8)


def test_vol_multiplier_min_cannot_reach_one():
    """1.0을 허용하면 전략이 변동성 방어를 통째로 끌 수 있다."""
    lo, hi = STRATEGY_MAPPED_FIELDS["vol_multiplier_min"]
    assert hi < 1.0


def test_target_vol_pct_changes_the_multiplier():
    """노브가 실제로 계산에 도달하는지 — 기본값과 다른 값을 넣어 확인."""
    base = _t(target_vol_pct=18.0, vol_multiplier_min=0.2)
    high = _t(target_vol_pct=40.0, vol_multiplier_min=0.2)
    assert high.m_vol > base.m_vol


def test_vol_multiplier_min_sets_the_floor():
    tight = _t(target_vol_pct=18.0, vol_multiplier_min=0.2)
    loose = _t(target_vol_pct=18.0, vol_multiplier_min=0.8)
    assert tight.m_vol == pytest.approx(0.2)
    assert loose.m_vol == pytest.approx(0.8)


def test_strategy_values_are_clamped_into_bounds():
    rp = RiskParameters()
    s = TradingStrategy()
    s.position_sizing.target_vol_pct = 40.0
    s.position_sizing.vol_multiplier_min = 0.8
    apply_strategy_to_risk_params(s, rp)
    assert rp.target_vol_pct == pytest.approx(40.0)
    assert rp.vol_multiplier_min == pytest.approx(0.8)


def test_reset_restores_model_defaults():
    rp = RiskParameters()
    rp.target_vol_pct = 33.0
    rp.vol_multiplier_min = 0.7
    apply_strategy_to_risk_params(None, rp)
    assert rp.target_vol_pct == pytest.approx(18.0)
    assert rp.vol_multiplier_min == pytest.approx(0.5)


def test_gate_protected_fields_still_sealed():
    from services.trading.strategy_apply import GATE_PROTECTED_FIELDS

    assert "max_open_positions" in GATE_PROTECTED_FIELDS
    assert "target_vol_pct" not in GATE_PROTECTED_FIELDS
