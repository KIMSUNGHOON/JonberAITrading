"""포트폴리오 목표 노출도 — 순수 계산.

설계: docs/superpowers/specs/2026-08-06-portfolio-exposure-observation-design.md
"""
import pytest

from services.trading.exposure_target import (
    EXPOSURE_FLOOR,
    compute_target_exposure,
)


def _args(**over):
    base = dict(
        equity=497_403_042.0,
        stock_value=49_426_800.0,
        index_returns=[],
        regime_label="neutral",
        n_round_trips=8,
        equity_peak=497_403_042.0,
        e_base=0.50,
        e_max=0.30,
    )
    base.update(over)
    return base


class TestComponentsMoveTargetIndependently:
    """성분 하나만 바꿨을 때 목표가 그 방향으로만 움직이는가."""

    def test_live_state_reproduces_current_exposure(self):
        """2026-08-06 실측 재현: 0.50 × 1.0 × 1.0 × 0.20 × 1.0 = 10.0%.

        실제 주식 비중이 9.9%였다. 공식이 현재를 '적정'이라 말해야
        관측 기간의 변화가 신호로 읽힌다.
        """
        r = compute_target_exposure(**_args())
        assert r.target_pct == pytest.approx(0.10, abs=1e-9)

    def test_evidence_is_monotone_non_decreasing(self):
        """왕복 수가 늘면 목표가 줄어들면 안 된다."""
        prev = -1.0
        for n in (0, 8, 20, 40, 80):
            r = compute_target_exposure(**_args(n_round_trips=n))
            assert r.target_pct >= prev
            prev = r.target_pct

    def test_evidence_saturates_at_forty(self):
        at40 = compute_target_exposure(**_args(n_round_trips=40))
        at80 = compute_target_exposure(**_args(n_round_trips=80))
        assert at40.m_evidence == pytest.approx(1.0)
        assert at40.target_pct == pytest.approx(at80.target_pct)

    def test_risk_off_shrinks_more_than_risk_on_grows(self):
        """비대칭 — 축소 오판보다 확대 오판의 비용이 크다."""
        neutral = compute_target_exposure(**_args(regime_label="neutral"))
        on = compute_target_exposure(**_args(regime_label="risk_on"))
        off = compute_target_exposure(**_args(regime_label="risk_off"))
        assert off.target_pct < neutral.target_pct < on.target_pct
        assert (neutral.target_pct - off.target_pct) > (on.target_pct - neutral.target_pct)

    def test_drawdown_shrinks_target(self):
        """고점 대비 10% 낙폭 → 배수 0.7."""
        r = compute_target_exposure(
            **_args(equity=450_000_000.0, equity_peak=500_000_000.0)
        )
        assert r.m_drawdown == pytest.approx(0.7)

    def test_drawdown_multiplier_has_a_floor(self):
        """낙폭이 아무리 커도 0.3 아래로 내려가지 않는다."""
        r = compute_target_exposure(
            **_args(equity=100_000_000.0, equity_peak=500_000_000.0)
        )
        assert r.m_drawdown == pytest.approx(0.3)

    def test_equity_above_peak_is_not_a_drawdown(self):
        r = compute_target_exposure(
            **_args(equity=600_000_000.0, equity_peak=500_000_000.0)
        )
        assert r.m_drawdown == pytest.approx(1.0)


class TestClipping:
    def test_target_never_exceeds_e_max(self):
        r = compute_target_exposure(
            **_args(n_round_trips=40, regime_label="risk_on", e_base=0.90, e_max=0.30)
        )
        assert r.target_pct == pytest.approx(0.30)
        assert r.binding == "e_max"

    def test_target_never_below_floor(self):
        r = compute_target_exposure(**_args(n_round_trips=0))
        assert r.target_pct == pytest.approx(EXPOSURE_FLOOR)
        assert r.binding == "floor"


class TestBindingNamesTheSmallestMultiplier:
    def test_binding_is_evidence_when_evidence_is_smallest(self):
        r = compute_target_exposure(**_args(n_round_trips=8, regime_label="neutral"))
        assert r.binding == "m_evidence"

    def test_binding_is_regime_when_regime_is_smallest(self):
        r = compute_target_exposure(**_args(n_round_trips=40, regime_label="risk_off"))
        assert r.binding == "m_regime"


class TestUnknownRegimeIsRecorded:
    def test_unknown_regime_is_neutral_but_flagged(self):
        """조용한 1.0 금지 — 왜 중립인지 남아야 한다."""
        r = compute_target_exposure(**_args(regime_label="누가봐도이상한값"))
        assert r.m_regime == pytest.approx(1.0)
        assert "regime_unknown" in r.degraded
