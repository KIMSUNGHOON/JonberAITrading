"""포트폴리오 목표 노출도 — 순수 계산.

설계: docs/superpowers/specs/2026-08-06-portfolio-exposure-observation-design.md

2026-08-07: `compute_target_exposure`(M_evidence 기반 관측 전용 계산)는
레짐 앵커 + 일일 변화 한도 방식(`compute_regime_target`)으로 대체됐다 --
왕복 표본이 모의 시장에서 쌓인 것이라 안전장치로 기능하지 않았기 때문이다.
그 계산을 검증하던 테스트는 함께 지웠다(참조 심볼 자체가 없어졌으므로
유지하면 거짓 신호가 된다). `compute_regime_target`/`slots_for_target`
테스트는 test_exposure_target_regime.py에 있다.

이 파일에는 이번 교체에서도 그대로 유지된 `annualized_vol`(퍼센트 등락률의
연환산 변동성)에 대한 순수 단위 테스트만 남는다.
"""
import pytest

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
