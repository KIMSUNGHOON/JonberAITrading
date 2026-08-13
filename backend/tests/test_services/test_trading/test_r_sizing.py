"""S-4 (생존 규율): R-based sizing helper — `r_cap_value` pure function.

Spec: docs/superpowers/specs/2026-07-19-survival-discipline-design.md §1/§2
S-4. r_cap = equity * (risk_budget_pct / 100) / stop_distance_pct, where
stop_distance_pct = (entry_price - stop_price) / entry_price. Both sizing
sites (portfolio_agent._calculate_max_position_value, decision_nodes'
quantity calc) call this SAME function and min() it against their existing
cap — this is the single source of truth for the math, tested here in
isolation.
"""

import pytest

from services.trading.r_sizing import r_cap_value


def test_r_cap_value_hand_calculated():
    """계좌 5억, 예산 0.75%, 손절거리 5% -> 7,500만원 (브리프 수기 계산 대조)."""
    cap = r_cap_value(
        equity=500_000_000,
        risk_budget_pct=0.75,
        entry_price=100_000,
        stop_price=95_000,  # 5% distance
    )
    assert cap == pytest.approx(75_000_000)


def test_r_cap_value_another_hand_calculated_point():
    """계좌 5억, 예산 0.75%, 손절거리 10% -> 3,750만원."""
    cap = r_cap_value(
        equity=500_000_000,
        risk_budget_pct=0.75,
        entry_price=100_000,
        stop_price=90_000,  # 10% distance
    )
    assert cap == pytest.approx(37_500_000)


def test_r_cap_value_none_when_stop_missing():
    """가드 1: stop_price=None -> R 캡 미적용."""
    assert r_cap_value(500_000_000, 0.75, 100_000, None) is None


def test_r_cap_value_none_when_entry_non_positive():
    """가드 2: entry_price<=0 -> R 캡 미적용."""
    assert r_cap_value(500_000_000, 0.75, 0, 95_000) is None
    assert r_cap_value(500_000_000, 0.75, -100, -50) is None


def test_r_cap_value_none_when_stop_at_or_above_entry():
    """가드 3: stop_price>=entry_price (롱 방향 리스크축소 스탑이 아님) -> R 캡 미적용."""
    assert r_cap_value(500_000_000, 0.75, 100_000, 100_000) is None
    assert r_cap_value(500_000_000, 0.75, 100_000, 105_000) is None


def test_r_cap_value_none_when_stop_non_positive():
    """가드 5 (N4, gap-discipline G-3, spec docs/superpowers/specs/
    2026-07-20-gap-discipline-design.md §2): stop_price<=0 -> R 캡 미적용.
    가드 없이는 거리가 ~100%로 계산되어 캡이 equity*risk_budget_pct%로
    붕괴한다(보수적 방향이지만 의도치 않은 값 -- "R 룰 미적용"이어야 한다)."""
    assert r_cap_value(500_000_000, 0.75, 100_000, 0) is None
    assert r_cap_value(500_000_000, 0.75, 100_000, -1) is None


def test_r_cap_value_none_when_distance_under_half_percent_floor():
    """가드 4: 손절거리 비율 < 0.5% -> R 캡 미적용 (0으로 나누기 근접 방지)."""
    # distance = 0.4% < 0.5% floor
    assert r_cap_value(500_000_000, 0.75, 100_000, 99_600) is None


def test_r_cap_value_applies_at_exactly_half_percent_boundary():
    """경계값: 정확히 0.5% 거리는 (엄격한 '<' 가드이므로) 적용된다."""
    cap = r_cap_value(500_000_000, 0.75, 100_000, 99_500)  # exactly 0.5%
    assert cap is not None
    assert cap == pytest.approx(500_000_000 * 0.0075 / 0.005)
