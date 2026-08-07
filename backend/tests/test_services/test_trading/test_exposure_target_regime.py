import pytest

from services.trading.exposure_target import (
    DAILY_TARGET_DELTA_MAX,
    REGIME_ANCHORS,
    REGIME_PER_POSITION_PCT,
    compute_regime_target,
    slots_for_target,
)


def _t(regime="bear", prev=None, seed=0.0855, returns=None, equity=100.0, peak=100.0):
    return compute_regime_target(
        regime_label=regime,
        prev_effective_pct=prev,
        seed_actual_pct=seed,
        index_returns=returns if returns is not None else [],
        equity=equity,
        equity_peak=peak,
    )


def test_anchors_are_exactly_the_specified_values():
    assert REGIME_ANCHORS == {"bull": 0.80, "neutral": 0.65, "bear": 0.55}
    assert DAILY_TARGET_DELTA_MAX == 0.15
    assert REGIME_PER_POSITION_PCT == 0.05


def test_first_run_seeds_from_actual_and_ramps_by_the_limit():
    """prev가 없으면 실제 비중에서 시드하고 한 번에 15%p만 오른다."""
    out = _t(regime="bear", prev=None, seed=0.0855)
    assert out.anchor_pct == pytest.approx(0.55)
    assert out.target_pct == pytest.approx(0.2355)


def test_ramp_reaches_anchor_in_four_steps():
    prev = 0.0855
    for _ in range(4):
        prev = _t(regime="bear", prev=prev).target_pct
    assert prev == pytest.approx(0.55)


def test_downward_move_is_also_limited():
    """강세(0.80)에서 약세로 꺾여도 한 번에 15%p만 내려간다."""
    out = _t(regime="bear", prev=0.80)
    assert out.target_pct == pytest.approx(0.65)


def test_multipliers_may_cut_faster_than_the_daily_limit():
    """방어는 한도보다 빠르게 줄일 수 있어야 한다 — 한도는 앵커에만 건다.
    낙폭 20%면 m_drawdown = 1 - 3*0.2 = 0.4."""
    out = _t(regime="bear", prev=0.50, equity=80.0, peak=100.0)
    assert out.m_drawdown == pytest.approx(0.4)
    # ramped = clamp(0.55, 0.35, 0.65) = 0.55 → 0.55 * 1.0 * 0.4 = 0.22
    assert out.target_pct == pytest.approx(0.22)
    assert out.target_pct < 0.50 - DAILY_TARGET_DELTA_MAX


def test_m_evidence_is_gone():
    """필드 자체가 사라져야 한다. `or ... is None`으로 느슨하게 쓰면
    필드가 남아 있어도 통과해 버린다."""
    out = _t()
    assert not hasattr(out, "m_evidence")


def test_unknown_regime_is_degraded_and_treated_as_bear():
    """모르는 라벨에서 중간값을 고르지 않는다 — 가장 보수적인 앵커를 쓴다."""
    out = _t(regime="sideways")
    assert "regime_unknown" in out.degraded
    assert out.anchor_pct == pytest.approx(REGIME_ANCHORS["bear"])


def test_vol_insufficient_is_recorded_not_silently_neutral():
    out = _t(returns=[0.1, 0.2])
    assert out.m_vol == 1.0
    assert "index_vol_insufficient" in out.degraded


def test_implausible_vol_is_gated_and_raw_value_preserved():
    """모의 데이터를 걸러내되 원값은 버리지 않는다."""
    out = _t(returns=[10.0, -12.0, 15.0, -18.0, 11.0, -14.0])
    assert out.m_vol == 1.0
    assert "index_vol_implausible" in out.degraded
    assert out.index_vol_annualized is not None
    assert out.index_vol_annualized > 60.0


def test_slots_only_ever_rise():
    assert slots_for_target(0.55, current_max=7) == 11
    assert slots_for_target(0.80, current_max=11) == 16
    # 목표가 내려가도 슬롯은 안 줄어든다 — 줄이면 집중도가 오른다
    assert slots_for_target(0.20, current_max=16) == 16
    assert slots_for_target(0.2355, current_max=7) == 7
