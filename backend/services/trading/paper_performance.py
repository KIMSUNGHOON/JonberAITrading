"""모의투자 운용 성과 집계 (Paper-Proof Phase D1).

ka10074 기간 실현손익(RealizedPnl)과 계좌 스냅샷으로 관찰 운용(Phase D3)의
성과를 집계한다. 순수 계산만 담당 — 브로커 호출은 호출자
(scripts/paper_performance_report.py, 향후 API)가 한다.

승률은 일 단위다 (ka10074는 일자별 집계라 매매별 승패는 종목별 TR이 필요 —
운용 중 필요해지면 ka10072/73으로 확장).
"""

from datetime import date, timedelta
from typing import Optional, TypedDict

from pydantic import BaseModel, Field

from services.kiwoom.models import DailyRealizedPnlRow, RealizedPnl


class DailyPnlPoint(TypedDict):
    """일별 손익 시계열 포인트 (차트 소비용, dt 오름차순으로 정렬됨)."""

    dt: str
    pnl: int
    cumulative_pnl: int


def _dt_sort_key(dt: str, index: int) -> tuple[int, object]:
    """daily_pnl_series 정렬 키.

    dt가 YYYYMMDD 8자리 숫자면 (0, dt) — 문자열 비교가 곧 날짜 오름차순이다
    (자리수 고정 zero-padded). 파싱 불가한 dt는 (1, index)로 원래 순서를
    유지한 채 뒤로 보낸다 (크래시 방지, 정렬 불능이라 값을 신뢰할 수 없음을
    표시). 첫 원소가 다르면 둘째 원소(str vs int)는 비교되지 않는다.
    """
    if isinstance(dt, str) and len(dt) == 8 and dt.isdigit():
        return (0, dt)
    return (1, index)


def compute_daily_win_loss(
    daily: list[DailyRealizedPnlRow],
) -> tuple[int, int, int, Optional[float]]:
    """일별 실현손익 승/패/보합 집계 + 일 단위 승률(%).

    Returns (win_days, loss_days, flat_days, win_rate_pct). 승부(승+패)가
    없으면 win_rate_pct는 None (0%가 아니라 미정).
    """
    win_days = sum(1 for d in daily if d.sell_pnl > 0)
    loss_days = sum(1 for d in daily if d.sell_pnl < 0)
    flat_days = sum(1 for d in daily if d.sell_pnl == 0)
    decided = win_days + loss_days
    win_rate_pct = (win_days / decided * 100.0) if decided else None
    return win_days, loss_days, flat_days, win_rate_pct


def compute_cumulative_return_pct(
    current_asset: int, base_asset: Optional[int]
) -> Optional[float]:
    """기준 자산 대비 누적 수익률 %; 기준이 없거나 0/음수면 None."""
    if base_asset is not None and base_asset > 0:
        return (current_asset - base_asset) / base_asset * 100.0
    return None


def daily_pnl_series(daily: list[DailyRealizedPnlRow]) -> list[DailyPnlPoint]:
    """일별 손익 + 누적 손익 시계열 (차트/API 소비용).

    ka10074 dt_rlzt_pl의 브로커 응답 순서와 무관하게 dt 오름차순으로 정렬한
    뒤 누적합을 계산한다 (Kiwoom이 내림차순/뒤섞인 순서로 줘도 누적 P&L이
    역방향으로 도는 것을 방지). dt를 8자리 숫자로 파싱할 수 없는 행은 정렬
    불능으로 보고 원래 순서를 유지한 채 뒤로 보낸다 (크래시하지 않음).
    """
    ordered = sorted(
        enumerate(daily), key=lambda pair: _dt_sort_key(pair[1].dt, pair[0])
    )
    cumulative = 0
    points: list[DailyPnlPoint] = []
    for _, d in ordered:
        cumulative += d.sell_pnl
        points.append({"dt": d.dt, "pnl": d.sell_pnl, "cumulative_pnl": cumulative})
    return points


class PerformanceReport(BaseModel):
    """기간 성과 리포트 (실현손익 기준 + 자산 스냅샷)."""

    strt_dt: str = Field(..., description="기간 시작 (YYYYMMDD)")
    end_dt: str = Field(..., description="기간 종료 (YYYYMMDD)")
    realized_pnl_total: int = Field(..., description="기간 실현손익 (부호 보존)")
    commission: int = Field(..., description="기간 매매수수료 (참고용 비용 내역 — 이미 realized_pnl_total에 반영됨, 아래 참조)")
    tax: int = Field(..., description="기간 매매세금 (참고용 비용 내역 — 이미 realized_pnl_total에 반영됨, 아래 참조)")
    net_pnl: int = Field(
        ...,
        description=(
            "순손익. P2-4 §D 검증#5 (2026-07-14): ka10074 rlzt_pl(및 "
            "dt_rlzt_pl의 tdy_sel_pl)은 이미 수수료·세금이 차감된 NET "
            "값이다 — realized_pnl_total을 그대로 쓴다. commission/tax를 "
            "다시 빼면 이중차감(과소평가)이 된다. 근거는 build_performance_report "
            "docstring 참조."
        ),
    )
    trade_days: int = Field(..., description="매매 발생 일수")
    win_days: int = Field(..., description="수익 일수")
    loss_days: int = Field(..., description="손실 일수")
    flat_days: int = Field(..., description="보합 일수")
    win_rate_pct: Optional[float] = Field(
        None, description="일 단위 승률 % = 승/(승+패); 승부 없으면 None"
    )
    current_asset: int = Field(..., description="현재 계좌 평가액 (주식+예수금)")
    base_asset: Optional[int] = Field(
        None, description="운용 시작 기준 자산 (운용 개시 시 기록)"
    )
    cumulative_return_pct: Optional[float] = Field(
        None, description="누적 수익률 % (기준 자산 대비); 기준 없으면 None"
    )
    daily_lines: list[str] = Field(
        default_factory=list, description="일별 손익 렌더 행"
    )

    def render_text(self) -> str:
        """터미널 출력용 요약."""
        lines = [
            f"모의투자 성과 리포트  {self.strt_dt} ~ {self.end_dt}",
            "-" * 46,
            f"실현손익 합계      {self.realized_pnl_total:>15,} 원",
            f"수수료/세금        {self.commission:>7,} / {self.tax:,} 원",
            f"순손익             {self.net_pnl:>15,} 원",
            f"매매 일수          {self.trade_days} (승 {self.win_days} / "
            f"패 {self.loss_days} / 보합 {self.flat_days})",
            f"일 단위 승률       "
            + (f"{self.win_rate_pct:.1f}%" if self.win_rate_pct is not None else "—"),
            f"현재 자산          {self.current_asset:>15,} 원",
        ]
        if self.base_asset is not None:
            ret = (
                f"{self.cumulative_return_pct:+.2f}%"
                if self.cumulative_return_pct is not None
                else "—"
            )
            lines.append(f"기준 자산          {self.base_asset:>15,} 원")
            lines.append(f"누적 수익률        {ret:>15}")
        if self.daily_lines:
            lines.append("-" * 46)
            lines.extend(self.daily_lines)
        return "\n".join(lines)


def build_performance_report(
    pnl: RealizedPnl,
    *,
    current_asset: int,
    base_asset: Optional[int],
) -> PerformanceReport:
    """RealizedPnl + 자산 스냅샷 → PerformanceReport (순수 함수).

    P2-4 Task P3 (2026-07-14) — net/gross 검증 결과, ka10074 rlzt_pl은
    이미 수수료·세금이 차감된 NET 값이다. `net_pnl`을
    `realized_pnl - commission - tax`로 계산하던 이전 코드는 이미
    net인 값을 다시 한번 차감하는 **이중차감(과소평가)** 버그였다 —
    coin의 낙관(과대평가) 버그들과 반대 방향이지만 "수익률 신뢰"에는
    똑같이 치명적이다.

    근거 (자기목 픽스처 아님 — 공식 Kiwoom REST API 문서의 실제 예제
    응답): `Kiwoom-REST-API/kiwoom_docs/계좌.md`의
    일자별종목별실현손익요청_기간 (ka10073, ka10074와 같은
    "실현손익" 필드 계열 — tdy_sel_pl/tdy_trde_cmsn/tdy_trde_tax를
    공유) 응답 예제(해당 파일 216-272행):
        buy_uv=97602.96, cntr_pric=158200, cntr_qty=1,
        tdy_sel_pl=59813.04, tdy_trde_cmsn=500, tdy_trde_tax=284
    검산: gross = (cntr_pric - buy_uv) * cntr_qty = 60597.04
          gross - (trde_cmsn + trde_tax) = 60597.04 - 784 = 59813.04
          == tdy_sel_pl (정확히 일치, 반올림 오차 없음)
    즉 브로커가 이미 수수료·세금을 뺀 값을 "실현손익"으로 보고한다.
    ka10074의 dt_rlzt_pl.tdy_sel_pl은 ka10073과 동일한 필드명·의미이므로
    (같은 브로커의 같은 "실현손익" TR 계열), 상위 합계 rlzt_pl도 동일
    관례를 따른다고 보는 것이 합리적이다. 회귀 테스트:
    test_paper_performance.py::TestNetGrossSemantics 참조.
    """
    win_days, loss_days, flat_days, win_rate_pct = compute_daily_win_loss(pnl.daily)
    cumulative_return_pct = compute_cumulative_return_pct(current_asset, base_asset)

    return PerformanceReport(
        strt_dt=pnl.strt_dt,
        end_dt=pnl.end_dt,
        realized_pnl_total=pnl.realized_pnl,
        commission=pnl.commission,
        tax=pnl.tax,
        # realized_pnl (ka10074 rlzt_pl)은 이미 NET이므로 그대로 사용.
        # commission/tax를 여기서 다시 빼면 이중차감이 된다 (위 docstring 근거).
        net_pnl=pnl.realized_pnl,
        trade_days=len(pnl.daily),
        win_days=win_days,
        loss_days=loss_days,
        flat_days=flat_days,
        win_rate_pct=win_rate_pct,
        current_asset=current_asset,
        base_asset=base_asset,
        cumulative_return_pct=cumulative_return_pct,
        daily_lines=[
            f"{d.dt}  매도 {d.sell_amount:>13,} 원  손익 {d.sell_pnl:>+12,} 원"
            for d in pnl.daily
        ],
    )


def period_bounds(
    today: date, data_start: Optional[str]
) -> dict[str, tuple[str, str]]:
    """일/주/월/누적 버킷의 (start, end) YYYYMMDD. end는 모두 `today`.

    캘린더 기준이다 — 주는 이번 주 **월요일**부터, 월은 이번 달 **1일**부터.

    누적(`total`)은 day/week/month의 시작과 `data_start`(가장 이른 스냅샷
    일자, YYYYMMDD) 중 **가장 이른** 값이다 — 그래서 항상 다른 세 버킷을
    모두 포함하는 가장 넓은 창이 된다. `data_start`만 썼을 때(예전 구현)는
    운용 첫 달처럼 `data_start`가 이번 달 1일보다 늦으면 `total`이
    `month`보다 좁아져 "월간 실현손익 > 누적 실현손익"이라는 모순이
    생겼다 — 리뷰 지적. `total`은 정의상 그 어떤 하위 구간보다도 작을 수
    없어야 한다. 엔드포인트가 이 네 버킷을 한 번의 브로커 호출로 덮을 때도
    `total`의 시작이 곧 그 호출의 창 시작이 되므로(다른 버킷을 포함하는
    가장 이른 값이라서) 실제로 요청한 창과 "누적" 라벨이 항상 일치한다.

    `day`의 start를 `today`로 두는 것은 두 소비자 모두에게 옳다: 실현손익은
    [today, today] 구간 합이고, 평가금 수익률은 start '직전' 종가를 분모로
    쓰므로 자연히 전일 종가가 잡힌다.
    """
    end = today.strftime("%Y%m%d")
    monday_str = (today - timedelta(days=today.weekday())).strftime("%Y%m%d")
    month_start = today.replace(day=1).strftime("%Y%m%d")

    total_candidates = [end, monday_str, month_start]
    if data_start is not None:
        total_candidates.append(data_start)
    total_start = min(total_candidates)

    return {
        "day": (end, end),
        "week": (monday_str, end),
        "month": (month_start, end),
        "total": (total_start, end),
    }


def equity_return_for_period(
    snapshots: list[dict], start: str, end: str, base_asset: Optional[int]
) -> Optional[dict]:
    """평가금(equity) 변화 기준 기간 수익률.

    Args:
        snapshots: `daily_perf_snapshot` 행들. `trade_date`는 '2026-07-31'
            형식(하이픈 포함)이고 `start`/`end`는 '20260731' 형식이라
            비교 전에 하이픈을 제거해 정규화한다.
        start/end: YYYYMMDD.
        base_asset: 기간 시작 이전 행이 없을 때 쓸 분모.

    Returns:
        {"pct": float, "basis": "prior_close" | "base_asset",
        "trade_date": "YYYY-MM-DD"} 또는 계산 불가 시 None (0.0으로
        위장하지 않는다).

        `daily_perf_snapshot`은 장마감에만(coordinator.py의 EOD 스냅샷
        기록) 한 번 쓰인다 — 장중에는 오늘자 행이 없다. 옛 구현은
        `end_equity`를 "end 이하 아무 행"에서 뽑아, 오늘 행이 없으면 어제
        행을 오늘 것인 양 써서 `end_equity == start_equity`가 되어
        `pct=0.0`을 계산해 냈다 — 데이터가 없다는 신호가 아니라 계산된
        값처럼 보이는 것이 문제였다(리뷰 지적). 이제는 [start, end] **구간
        안**에 실제 행이 하나도 없으면 무조건 None을 반환한다.
    """
    rows: list[tuple[str, float]] = []
    for row in snapshots:
        raw_dt = row.get("trade_date")
        equity = row.get("equity")
        if not isinstance(raw_dt, str):
            continue
        dt = raw_dt.replace("-", "")
        if len(dt) != 8 or not dt.isdigit():
            continue
        if not isinstance(equity, (int, float)) or equity <= 0:
            continue
        rows.append((dt, float(equity)))
    rows.sort(key=lambda pair: pair[0])
    if not rows:
        return None

    end_equity: Optional[float] = None
    end_equity_dt: Optional[str] = None
    start_equity: Optional[float] = None
    for dt, equity in rows:
        # end_equity는 구간 [start, end] **안**의 행에서만 뽑는다 — 구간
        # 밖(더 이른) 행을 오늘 값인 척 재사용하지 않는다.
        if start <= dt <= end:
            end_equity = equity
            end_equity_dt = dt
        if dt < start:
            start_equity = equity
    if end_equity is None or end_equity_dt is None:
        return None

    if start_equity is not None:
        basis = "prior_close"
    elif base_asset is not None and base_asset > 0:
        start_equity, basis = float(base_asset), "base_asset"
    else:
        return None

    return {
        "pct": (end_equity / start_equity - 1.0) * 100.0,
        "basis": basis,
        "trade_date": f"{end_equity_dt[:4]}-{end_equity_dt[4:6]}-{end_equity_dt[6:8]}",
    }


def realized_for_period(points: list[DailyPnlPoint], start: str, end: str) -> int:
    """[start, end] 안에 드는 일별 실현손익 합 (YYYYMMDD 문자열 비교).

    `daily_pnl_series`의 출력을 그대로 먹는다. ka10074의 값은 이미 세후이므로
    수수료·세금을 여기서 다시 빼지 않는다. 구간에 거래가 없으면 0 (None 아님).
    """
    total = 0
    for point in points:
        dt = point.get("dt")
        if not isinstance(dt, str) or len(dt) != 8 or not dt.isdigit():
            continue
        if start <= dt <= end:
            total += point.get("pnl", 0)
    return total
