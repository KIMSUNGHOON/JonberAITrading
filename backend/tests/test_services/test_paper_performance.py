"""모의투자 성과 리포트 계산 (Paper-Proof Phase D1).

ka10074(get_realized_pnl)의 기간 실현손익 + 계좌 스냅샷으로 운용 성과를
집계하는 순수 함수. 스크립트/향후 API가 같은 로직을 쓰도록 서비스 모듈로
분리한다. 손익 부호가 그대로 전파되어야 한다 (Phase A 감사의 abs() 교훈).
"""

import pytest

from services.kiwoom.models import DailyRealizedPnlRow, RealizedPnl
from services.trading.paper_performance import (
    build_performance_report,
    compute_cumulative_return_pct,
    compute_daily_win_loss,
    daily_pnl_series,
)


def _pnl(daily, **totals):
    return RealizedPnl(
        strt_dt="20260701", end_dt="20260712",
        daily=daily, **totals,
    )


def _row(dt, sell_pnl, sell_amount=1_000_000, commission=100, tax=200):
    return DailyRealizedPnlRow(
        dt=dt, sell_pnl=sell_pnl, sell_amount=sell_amount,
        buy_amount=0, commission=commission, tax=tax,
    )


class TestBuildPerformanceReport:
    def test_aggregates_totals_and_daily_win_loss(self):
        pnl = _pnl(
            [
                _row("20260706", sell_pnl=50_000),
                _row("20260707", sell_pnl=-30_000),
                _row("20260708", sell_pnl=0),
                _row("20260709", sell_pnl=120_000),
            ],
            realized_pnl=140_000, commission=400, tax=800,
        )
        report = build_performance_report(pnl, current_asset=500_140_000,
                                          base_asset=500_000_000)

        assert report.realized_pnl_total == 140_000
        assert report.net_pnl == 140_000 - 400 - 800
        assert report.trade_days == 4
        assert report.win_days == 2
        assert report.loss_days == 1
        assert report.flat_days == 1
        assert report.win_rate_pct == pytest.approx(2 / 3 * 100)  # 승/(승+패)

    def test_cumulative_return_from_base_asset(self):
        pnl = _pnl([], realized_pnl=0)
        report = build_performance_report(pnl, current_asset=510_000_000,
                                          base_asset=500_000_000)
        assert report.cumulative_return_pct == pytest.approx(2.0)

    def test_no_base_asset_returns_none_return(self):
        pnl = _pnl([], realized_pnl=0)
        report = build_performance_report(pnl, current_asset=500_000_000,
                                          base_asset=None)
        assert report.cumulative_return_pct is None

    def test_loss_sign_preserved_end_to_end(self):
        pnl = _pnl(
            [_row("20260706", sell_pnl=-163_958)],
            realized_pnl=-163_958, commission=3_500, tax=12_420,
        )
        report = build_performance_report(pnl, current_asset=499_820_122,
                                          base_asset=500_000_000)
        assert report.realized_pnl_total == -163_958
        assert report.net_pnl == -163_958 - 3_500 - 12_420
        assert report.cumulative_return_pct < 0

    def test_empty_period_is_all_zero(self):
        pnl = _pnl([], realized_pnl=0)
        report = build_performance_report(pnl, current_asset=500_000_000,
                                          base_asset=500_000_000)
        assert report.trade_days == 0
        assert report.win_rate_pct is None  # 승부 없음 — 0%가 아니라 미정
        assert report.cumulative_return_pct == pytest.approx(0.0)

    def test_render_text_contains_key_lines(self):
        pnl = _pnl(
            [_row("20260706", sell_pnl=50_000)],
            realized_pnl=50_000, commission=100, tax=200,
        )
        report = build_performance_report(pnl, current_asset=500_050_000,
                                          base_asset=500_000_000)
        text = report.render_text()
        assert "20260701" in text and "20260712" in text
        assert "50,000" in text
        assert "%" in text


class TestComputeDailyWinLoss:
    """/api/trading/performance의 pnl 섹션이 자산 스냅샷 없이도 독립적으로
    쓰는 순수 헬퍼 — build_performance_report와 동일 로직을 공유한다."""

    def test_counts_win_loss_flat(self):
        daily = [
            _row("20260706", sell_pnl=50_000),
            _row("20260707", sell_pnl=-30_000),
            _row("20260708", sell_pnl=0),
            _row("20260709", sell_pnl=120_000),
        ]
        win, loss, flat, win_rate = compute_daily_win_loss(daily)
        assert (win, loss, flat) == (2, 1, 1)
        assert win_rate == pytest.approx(2 / 3 * 100)

    def test_no_decided_days_returns_none_rate(self):
        win, loss, flat, win_rate = compute_daily_win_loss([_row("20260706", sell_pnl=0)])
        assert (win, loss, flat) == (0, 0, 1)
        assert win_rate is None

    def test_empty_daily_returns_zeros_and_none(self):
        assert compute_daily_win_loss([]) == (0, 0, 0, None)


class TestComputeCumulativeReturnPct:
    def test_positive_return(self):
        assert compute_cumulative_return_pct(510_000_000, 500_000_000) == pytest.approx(2.0)

    def test_negative_return_sign_preserved(self):
        assert compute_cumulative_return_pct(490_000_000, 500_000_000) == pytest.approx(-2.0)

    def test_no_base_asset_is_none(self):
        assert compute_cumulative_return_pct(500_000_000, None) is None

    def test_zero_or_negative_base_asset_is_none(self):
        assert compute_cumulative_return_pct(500_000_000, 0) is None
        assert compute_cumulative_return_pct(500_000_000, -1) is None


class TestDailyPnlSeries:
    def test_running_cumulative_sum_preserves_sign(self):
        daily = [
            _row("20260706", sell_pnl=50_000),
            _row("20260707", sell_pnl=-30_000),
            _row("20260708", sell_pnl=120_000),
        ]
        points = daily_pnl_series(daily)
        assert points == [
            {"dt": "20260706", "pnl": 50_000, "cumulative_pnl": 50_000},
            {"dt": "20260707", "pnl": -30_000, "cumulative_pnl": 20_000},
            {"dt": "20260708", "pnl": 120_000, "cumulative_pnl": 140_000},
        ]

    def test_empty_daily_returns_empty_list(self):
        assert daily_pnl_series([]) == []
