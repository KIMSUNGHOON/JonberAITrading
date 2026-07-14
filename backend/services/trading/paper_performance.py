"""모의투자 운용 성과 집계 (Paper-Proof Phase D1).

ka10074 기간 실현손익(RealizedPnl)과 계좌 스냅샷으로 관찰 운용(Phase D3)의
성과를 집계한다. 순수 계산만 담당 — 브로커 호출은 호출자
(scripts/paper_performance_report.py, 향후 API)가 한다.

승률은 일 단위다 (ka10074는 일자별 집계라 매매별 승패는 종목별 TR이 필요 —
운용 중 필요해지면 ka10072/73으로 확장).
"""

from typing import Optional, TypedDict

from pydantic import BaseModel, Field

from services.kiwoom.models import DailyRealizedPnlRow, RealizedPnl


class DailyPnlPoint(TypedDict):
    """일별 손익 시계열 포인트 (차트 소비용, dt 오름차순 가정)."""

    dt: str
    pnl: int
    cumulative_pnl: int


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

    ka10074 dt_rlzt_pl은 일자 오름차순으로 온다고 가정 — 누적합은 그 순서를
    그대로 따른다.
    """
    cumulative = 0
    points: list[DailyPnlPoint] = []
    for d in daily:
        cumulative += d.sell_pnl
        points.append({"dt": d.dt, "pnl": d.sell_pnl, "cumulative_pnl": cumulative})
    return points


class PerformanceReport(BaseModel):
    """기간 성과 리포트 (실현손익 기준 + 자산 스냅샷)."""

    strt_dt: str = Field(..., description="기간 시작 (YYYYMMDD)")
    end_dt: str = Field(..., description="기간 종료 (YYYYMMDD)")
    realized_pnl_total: int = Field(..., description="기간 실현손익 (부호 보존)")
    commission: int = Field(..., description="기간 매매수수료")
    tax: int = Field(..., description="기간 매매세금")
    net_pnl: int = Field(..., description="비용 차감 순손익")
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
    """RealizedPnl + 자산 스냅샷 → PerformanceReport (순수 함수)."""
    win_days, loss_days, flat_days, win_rate_pct = compute_daily_win_loss(pnl.daily)
    cumulative_return_pct = compute_cumulative_return_pct(current_asset, base_asset)

    return PerformanceReport(
        strt_dt=pnl.strt_dt,
        end_dt=pnl.end_dt,
        realized_pnl_total=pnl.realized_pnl,
        commission=pnl.commission,
        tax=pnl.tax,
        net_pnl=pnl.realized_pnl - pnl.commission - pnl.tax,
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
