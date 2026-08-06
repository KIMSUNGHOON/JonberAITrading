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


class TestDegradedRecordsOnlyWhenSignalExistedButFailed:
    """degraded는 판정에 쓸 신호가 있었는데 못 쓴 경우만 기록한다.

    반대로 신호가 애초에 존재하지 않아 항등원을 쓰는 경우(no history, equity_peak=0)와
    계산 결과가 정당하게 1.0인 경우(낙폭 없음, equity == equity_peak)는
    사실이지 저하가 아니므로 기록하지 않는다. degraded는 "무언가 잘못됐다"는
    신호이어야 하므로, 둘을 섞으면 그 값을 잃는다.
    """

    def test_no_history_is_not_a_degradation(self):
        """신규 계좌(equity_peak=0) → drawdown 계산이 항등원 1.0을 쓴다.

        이는 신호 부족이 아니라 사실이므로, equity_peak_invalid 같은 항목을
        degraded에 추가하지 않는다. 다만 empty index_returns는 충분한 표본이
        아니므로 index_vol_insufficient가 기록된다.
        """
        r = compute_target_exposure(**_args(equity_peak=0.0))
        assert r.m_drawdown == pytest.approx(1.0)
        assert r.degraded == ["index_vol_insufficient"]

    def test_no_drawdown_is_not_a_degradation(self):
        """정상 상태(equity == equity_peak) → drawdown 없음.

        계산 결과가 정당하게 1.0이므로, drawdown은 degraded에 기록하지 않는다.
        다만 empty index_returns는 충분한 표본이 아니므로 index_vol_insufficient가 기록된다.
        """
        r = compute_target_exposure(**_args(equity=497_403_042.0, equity_peak=497_403_042.0))
        assert r.m_drawdown == pytest.approx(1.0)
        assert r.degraded == ["index_vol_insufficient"]

    def test_signal_existed_but_failed_is_recorded(self):
        """Unknown regime는 신호(regime_label)가 있었는데 못 썼으므로 기록된다.

        이는 위의 두 경우(신호 자체가 없거나 계산이 정당함)와 다르다.
        Test reference: TestUnknownRegimeIsRecorded.test_unknown_regime_is_neutral_but_flagged
        """
        r = compute_target_exposure(**_args(regime_label="unknown_regime_value"))
        assert r.m_regime == pytest.approx(1.0)
        assert "regime_unknown" in r.degraded


from services.trading.exposure_target import annualized_vol


class TestAnnualizedVol:
    def test_annualizes_with_sqrt_250(self):
        """일별 1% 표준편차 → 연 15.8%."""
        returns = [1.0, -1.0] * 10
        vol, n = annualized_vol(returns)
        assert n == 20
        assert vol == pytest.approx(1.0 * (250 ** 0.5), rel=0.05)

    def test_uses_only_the_last_window(self):
        returns = [50.0] * 30 + [1.0, -1.0] * 10
        vol, n = annualized_vol(returns, window=20)
        assert n == 20
        assert vol == pytest.approx(1.0 * (250 ** 0.5), rel=0.05)

    def test_short_series_reports_actual_sample_size(self):
        vol, n = annualized_vol([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        assert n == 6
        assert vol is not None

    def test_too_few_samples_returns_none(self):
        vol, n = annualized_vol([1.0, -1.0])
        assert vol is None
        assert n == 2


class TestVolHygieneGate:
    """모의 시장 데이터가 공식에 새어들지 않게 막는다.

    라이브 실측(2026-08-06): regime_snapshot의 지수 등락률 14일치가 연변동성
    112.1%다. 지수 레벨 변화와 등락률이 서로 일치하므로 파싱 오류가 아니라
    데이터 자체가 ±10~18%로 움직인다(계좌는 paper 모드). 브로드 지수로는
    불가능한 값이므로 신뢰하지 않는다.
    """

    # 2026-08-06 라이브 실측값 그대로
    LIVE_MOCK_RETURNS = [
        -6.36, -6.37, -4.46, 0.74, 4.4, -5.72, 0.97,
        -10.84, -5.98, -1.23, 17.91, -5.12, 1.62, 3.76,
    ]

    def test_implausible_vol_is_neutralized_and_flagged(self):
        r = compute_target_exposure(**_args(index_returns=self.LIVE_MOCK_RETURNS))
        assert r.m_vol == pytest.approx(1.0)
        assert "index_vol_implausible" in r.degraded

    def test_implausible_vol_preserves_the_raw_value(self):
        """중립으로 처리하되 원값은 남긴다 — 나중에 판정하려면 필요하다."""
        r = compute_target_exposure(**_args(index_returns=self.LIVE_MOCK_RETURNS))
        assert r.index_vol_annualized is not None
        assert r.index_vol_annualized > 60.0
        assert r.index_vol_n == 14

    def test_plausible_vol_is_actually_applied(self):
        """일별 1.14% → 연 18% → 배수 1.0 근처."""
        returns = [1.14, -1.14] * 10
        r = compute_target_exposure(**_args(index_returns=returns))
        assert r.m_vol == pytest.approx(1.0, abs=0.15)
        assert r.degraded == []

    def test_calm_market_raises_the_multiplier(self):
        returns = [0.5, -0.5] * 10   # 연 ≈ 7.9%
        r = compute_target_exposure(**_args(index_returns=returns))
        assert r.m_vol > 1.0

    def test_multiplier_is_clipped_both_ways(self):
        calm = compute_target_exposure(**_args(index_returns=[0.35, -0.35] * 10))
        rough = compute_target_exposure(**_args(index_returns=[3.5, -3.5] * 10))
        assert calm.m_vol == pytest.approx(1.5)
        assert rough.m_vol == pytest.approx(0.5)

    def test_insufficient_samples_is_neutral_and_flagged(self):
        r = compute_target_exposure(**_args(index_returns=[1.0, -1.0]))
        assert r.m_vol == pytest.approx(1.0)
        assert "index_vol_insufficient" in r.degraded

    def test_empty_series_is_neutral_and_flagged(self):
        r = compute_target_exposure(**_args(index_returns=[]))
        assert r.m_vol == pytest.approx(1.0)
        assert "index_vol_insufficient" in r.degraded
