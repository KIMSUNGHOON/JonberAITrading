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
        # P2-4 Task P3: ka10074's realized_pnl is ALREADY net of
        # commission/tax (see build_performance_report's docstring for the
        # official-docs evidence) — net_pnl must equal realized_pnl_total,
        # NOT realized_pnl_total - commission - tax (that would be a
        # double deduction).
        assert report.net_pnl == 140_000
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
        # Already net of commission/tax — see P2-4 P3 note above.
        assert report.net_pnl == -163_958
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


class TestNetGrossSemantics:
    """P2-4 Task P3 / audit §D 검증#5: ka10074 rlzt_pl(및 dt_rlzt_pl의
    tdy_sel_pl)이 gross(비용 미차감)인지 net(이미 차감됨)인지 검증.

    자기목 픽스처 금지(Paper-Proof Phase A 사고의 근본원인) — 숫자를
    "정답에 맞춰" 지어내지 않는다. 대신 이 리포에 커밋된 **공식 Kiwoom
    REST API 문서의 실제 예제 응답**을 그대로 쓴다:
    `Kiwoom-REST-API/kiwoom_docs/계좌.md` 일자별종목별실현손익요청_기간
    (ka10073, 216-272행) — ka10074와 동일한 "실현손익" 필드 계열
    (tdy_sel_pl/tdy_trde_cmsn/tdy_trde_tax)을 공유하는 브로커 예제:

        buy_uv=97602.96 (매입단가), cntr_pric=158200 (체결가),
        cntr_qty=1 (체결량), tdy_sel_pl=59813.04 (당일매도손익),
        tdy_trde_cmsn=500 (당일매매수수료), tdy_trde_tax=284 (당일매매세금)

    검산: gross = (cntr_pric - buy_uv) * cntr_qty = 60,597.04
          gross - (trde_cmsn + trde_tax) = 60,597.04 - 784 = 59,813.04
          == tdy_sel_pl (정확히 일치 — 반올림 오차조차 없음)

    이 산술이 "브로커가 이미 수수료·세금을 뺀 값을 실현손익으로 보고한다"는
    유일하게 성립하는 해석이다(반대로 gross라면 59,813.04 + 784 =
    60,597.04가 tdy_sel_pl이어야 하는데 그렇지 않다). 아래 테스트는 이
    검증된 숫자를 RealizedPnl에 그대로 태워 build_performance_report를
    통과시켜, 코드가 이중차감하지 않음을 고정한다.
    """

    def test_net_pnl_matches_verified_kiwoom_doc_example_no_double_deduction(self):
        # 위 ka10073 공식 예제의 실제 숫자를 그대로 사용 (지어낸 값 아님) —
        # 정수 원 단위로 반올림한다 (RealizedPnl/DailyRealizedPnlRow 필드는
        # int이고, 실제 client._parse_change도 int()로 파싱한다; 예제 문서의
        # 소수점은 매입단가 평균원가 계산상의 예시적 표기일 뿐, 반올림해도
        # 검증하려는 gross/net 관계는 그대로 성립한다 — 아래 두 번째 테스트가
        # 원본 소수 산술로 그 근거 자체를 별도로 고정한다).
        tdy_sel_pl = round(59_813.04)
        tdy_trde_cmsn = 500
        tdy_trde_tax = 284

        pnl = RealizedPnl(
            strt_dt="20241128", end_dt="20241128",
            total_buy_amount=0, total_sell_amount=158_200,
            realized_pnl=tdy_sel_pl,
            commission=tdy_trde_cmsn, tax=tdy_trde_tax,
            daily=[
                DailyRealizedPnlRow(
                    dt="20241128", buy_amount=0, sell_amount=158_200,
                    sell_pnl=tdy_sel_pl,
                    commission=tdy_trde_cmsn, tax=tdy_trde_tax,
                )
            ],
        )
        report = build_performance_report(
            pnl, current_asset=500_059_813, base_asset=500_000_000
        )

        # net_pnl == realized_pnl_total (already net) — NOT
        # realized_pnl_total - commission - tax, which would double-deduct
        # a cost the broker already subtracted.
        assert report.net_pnl == pytest.approx(tdy_sel_pl)
        assert report.net_pnl != pytest.approx(tdy_sel_pl - tdy_trde_cmsn - tdy_trde_tax)

    def test_gross_reconstruction_confirms_broker_already_netted_cost(self):
        """이 테스트는 build_performance_report를 검증하는 게 아니라, 위
        docstring의 산술 근거 자체를 코드로 고정한다 (숫자가 바뀌면 이
        테스트가 먼저 깨져 "근거가 stale해졌다"를 알려준다)."""
        buy_uv = 97_602.96
        cntr_pric = 158_200
        cntr_qty = 1
        tdy_sel_pl = 59_813.04
        tdy_trde_cmsn = 500
        tdy_trde_tax = 284

        gross = (cntr_pric - buy_uv) * cntr_qty
        net = gross - (tdy_trde_cmsn + tdy_trde_tax)

        assert net == pytest.approx(tdy_sel_pl, abs=0.01)


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

    def test_descending_input_is_sorted_ascending_before_cumsum(self):
        """Kiwoom(ka10074)이 내림차순으로 줘도 누적합은 정방향이어야 한다."""
        daily = [
            _row("20260708", sell_pnl=120_000),
            _row("20260707", sell_pnl=-30_000),
            _row("20260706", sell_pnl=50_000),
        ]
        points = daily_pnl_series(daily)
        assert points == [
            {"dt": "20260706", "pnl": 50_000, "cumulative_pnl": 50_000},
            {"dt": "20260707", "pnl": -30_000, "cumulative_pnl": 20_000},
            {"dt": "20260708", "pnl": 120_000, "cumulative_pnl": 140_000},
        ]

    def test_shuffled_input_is_sorted_ascending_before_cumsum(self):
        daily = [
            _row("20260707", sell_pnl=-30_000),
            _row("20260706", sell_pnl=50_000),
            _row("20260709", sell_pnl=10_000),
            _row("20260708", sell_pnl=120_000),
        ]
        points = daily_pnl_series(daily)
        assert [p["dt"] for p in points] == [
            "20260706", "20260707", "20260708", "20260709",
        ]
        assert [p["cumulative_pnl"] for p in points] == [
            50_000, 20_000, 140_000, 150_000,
        ]

    def test_malformed_dt_does_not_crash_and_sorts_last(self):
        """dt가 8자리 숫자가 아닌 행은 정렬 불가 — 크래시 없이 뒤로 보낸다."""
        daily = [
            _row("20260708", sell_pnl=10_000),
            _row("", sell_pnl=5_000),
            _row("20260706", sell_pnl=50_000),
        ]
        points = daily_pnl_series(daily)
        assert [p["dt"] for p in points] == ["20260706", "20260708", ""]
        assert [p["cumulative_pnl"] for p in points] == [50_000, 60_000, 65_000]


from datetime import date

from services.trading.paper_performance import (
    equity_return_for_period,
    period_bounds,
    realized_for_period,
)


def _snap(trade_date: str, equity: float) -> dict:
    """daily_perf_snapshot 행 모양 (trade_date는 하이픈 포함이 실제 저장 형식)."""
    return {"trade_date": trade_date, "equity": equity}


class TestPeriodBounds:
    def test_week_starts_on_monday_and_month_on_first(self):
        # 2026-07-31은 금요일 -> 그 주 월요일은 07-27
        bounds = period_bounds(date(2026, 7, 31), data_start="20260716")
        assert bounds["day"] == ("20260731", "20260731")
        assert bounds["week"] == ("20260727", "20260731")
        assert bounds["month"] == ("20260701", "20260731")
        assert bounds["total"] == ("20260716", "20260731")

    def test_monday_week_start_is_today_itself(self):
        # 2026-07-27은 월요일 -> 주 시작이 그날 자신
        bounds = period_bounds(date(2026, 7, 27), data_start="20260716")
        assert bounds["week"] == ("20260727", "20260727")

    def test_total_falls_back_to_month_start_without_data_start(self):
        bounds = period_bounds(date(2026, 7, 31), data_start=None)
        assert bounds["total"] == ("20260701", "20260731")


class TestEquityReturnForPeriod:
    # 2026-07-31 실측 스냅샷 (설계 문서의 검증표와 같은 값)
    SNAPS = [
        _snap("2026-07-24", 495_435_889),
        _snap("2026-07-27", 496_547_086),
        _snap("2026-07-28", 496_468_186),
        _snap("2026-07-29", 496_468_186),
        _snap("2026-07-30", 497_691_136),
        _snap("2026-07-31", 497_760_401),
    ]

    def test_day_uses_prior_close_as_denominator(self):
        res = equity_return_for_period(
            self.SNAPS, "20260731", "20260731", base_asset=500_000_000
        )
        assert res["basis"] == "prior_close"
        assert round(res["pct"], 4) == 0.0139

    def test_week_denominator_is_the_close_before_monday_not_monday_itself(self):
        # 주 시작 07-27(월)이지만 분모는 07-24 종가 495,435,889다.
        # 07-27 행을 분모로 쓰면 그 주 월요일 성과가 통째로 빠진다.
        res = equity_return_for_period(
            self.SNAPS, "20260727", "20260731", base_asset=500_000_000
        )
        assert res["basis"] == "prior_close"
        assert round(res["pct"], 4) == 0.4692

    def test_month_falls_back_to_base_asset_when_no_prior_row(self):
        res = equity_return_for_period(
            self.SNAPS, "20260701", "20260731", base_asset=500_000_000
        )
        assert res["basis"] == "base_asset"
        assert round(res["pct"], 4) == -0.4479

    def test_gap_day_carries_forward(self):
        # 07-21 행이 없어도 07-20 -> 07-22 구간이 끊기지 않는다
        snaps = [_snap("2026-07-20", 100_000), _snap("2026-07-22", 110_000)]
        res = equity_return_for_period(snaps, "20260722", "20260722", base_asset=None)
        assert res["basis"] == "prior_close"
        assert round(res["pct"], 4) == 10.0

    def test_returns_none_when_no_usable_rows(self):
        assert equity_return_for_period([], "20260731", "20260731", 500_000_000) is None

    def test_returns_none_when_no_prior_row_and_no_base(self):
        snaps = [_snap("2026-07-31", 497_760_401)]
        assert equity_return_for_period(snaps, "20260731", "20260731", None) is None

    def test_ignores_malformed_rows(self):
        snaps = [
            {"trade_date": None, "equity": 1},
            {"trade_date": "2026-07-30", "equity": 0},
            _snap("2026-07-30", 100_000),
            _snap("2026-07-31", 101_000),
        ]
        res = equity_return_for_period(snaps, "20260731", "20260731", None)
        assert round(res["pct"], 4) == 1.0


class TestRealizedForPeriod:
    POINTS = [
        {"dt": "20260727", "pnl": 418_950, "cumulative_pnl": 418_950},
        {"dt": "20260730", "pnl": 0, "cumulative_pnl": 418_950},
        {"dt": "20260731", "pnl": 984_533, "cumulative_pnl": 1_403_483},
    ]

    def test_sums_only_points_inside_the_window(self):
        assert realized_for_period(self.POINTS, "20260731", "20260731") == 984_533
        assert realized_for_period(self.POINTS, "20260727", "20260731") == 1_403_483

    def test_empty_window_is_zero_not_none(self):
        assert realized_for_period(self.POINTS, "20260701", "20260726") == 0

    def test_ignores_unparseable_dt(self):
        points = [{"dt": "bogus", "pnl": 999, "cumulative_pnl": 999}] + self.POINTS
        assert realized_for_period(points, "20260731", "20260731") == 984_533
