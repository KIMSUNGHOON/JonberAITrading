"""포트폴리오 목표 노출도 — 순수 계산 (관측 단계, 2026-08-06).

설계: docs/superpowers/specs/2026-08-06-portfolio-exposure-observation-design.md

이 모듈은 DB도 API도 모른다. 입력을 받아 목표 노출도와 그 성분을 돌려줄 뿐이다.
호출자가 어떤 값을 넣었는지, 결과를 어디에 쓸지는 관심 밖이다 — 그래야 테스트가
실제 계산을 검증하고 목(mock)을 검증하지 않는다.

⚠️ 이 단계에서 결과는 **기록만** 된다. 주문 수량에 연결되지 않는다.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

# 레짐 배수. 비대칭인 이유: 확대 오판의 비용이 축소 오판보다 크다 —
# 잘못 줄이면 기회를 놓치고, 잘못 키우면 손실이 커진다.
REGIME_MULTIPLIERS: dict[str, float] = {
    "risk_on": 1.2,
    "neutral": 1.0,
    "risk_off": 0.5,
}

# 엣지가 "측정됐다"고 볼 왕복 거래 수. MinTRL 근사에서 쓸 만한 엣지
# (거래당 샤프 ≈ 0.25)라면 약 43 왕복이면 드러난다 — 그 자리에 40을 둔다.
EVIDENCE_TARGET_TRIPS: int = 40

# 노출도 하한. 증거가 0이어도 완전히 0이 되지는 않게 한다.
EXPOSURE_FLOOR: float = 0.02

# 낙폭 배수의 기울기와 바닥. 고점 대비 10% 빠지면 0.7배.
DRAWDOWN_SLOPE: float = 3.0
DRAWDOWN_FLOOR: float = 0.3


@dataclass
class TargetExposure:
    """목표 노출도와 그것을 만든 성분들.

    `binding`/`degraded`가 있는 이유는 숫자만 남기면 몇 주 뒤 "왜 이 값이었나"를
    풀 수 없기 때문이다. `PortfolioAgent._calculate_max_position_value`의
    `lineage` out-param과 같은 계열이다.
    """

    target_pct: float
    m_regime: float
    m_vol: float
    m_evidence: float
    m_drawdown: float
    binding: str
    degraded: list[str] = field(default_factory=list)
    index_vol_annualized: Optional[float] = None
    index_vol_n: int = 0


def _drawdown_multiplier(equity: float, equity_peak: float) -> float:
    if not equity_peak or equity_peak <= 0 or not math.isfinite(equity_peak):
        return 1.0
    drawdown = max(0.0, (equity_peak - equity) / equity_peak)
    return max(DRAWDOWN_FLOOR, 1.0 - DRAWDOWN_SLOPE * drawdown)


def compute_target_exposure(
    *,
    equity: float,
    stock_value: float,
    index_returns: list[float],
    regime_label: str,
    n_round_trips: int,
    equity_peak: float,
    e_base: float = 0.50,
    e_max: float = 0.30,
) -> TargetExposure:
    """목표 주식 비중(0~1)을 계산한다.

        E = e_base × M_regime × M_vol × M_evidence × M_drawdown
            (EXPOSURE_FLOOR ≤ E ≤ e_max)

    `stock_value`는 이 단계에서 계산에 쓰이지 않는다 — 호출자가 실제 비중을
    함께 기록할 수 있도록 시그니처에만 두었다(목표와 실제를 같은 스냅샷에서
    떠야 대조가 성립한다).
    """
    degraded: list[str] = []

    m_regime = REGIME_MULTIPLIERS.get(regime_label)
    if m_regime is None:
        m_regime = 1.0
        degraded.append("regime_unknown")

    # Task 2에서 실제 변동성 배수로 교체된다. 그때까지도 "조용한 중립"은
    # 금지이므로 사유를 남긴다 — 이 값이 왜 1.0인지가 기록에 있어야 한다.
    m_vol = 1.0
    degraded.append("index_vol_not_implemented")
    vol_ann: Optional[float] = None
    vol_n = 0

    m_evidence = min(1.0, max(0, n_round_trips) / EVIDENCE_TARGET_TRIPS)
    m_drawdown = _drawdown_multiplier(equity, equity_peak)

    raw = e_base * m_regime * m_vol * m_evidence * m_drawdown

    multipliers = {
        "m_regime": m_regime,
        "m_vol": m_vol,
        "m_evidence": m_evidence,
        "m_drawdown": m_drawdown,
    }
    binding = min(multipliers, key=multipliers.get)

    target = raw
    if target > e_max:
        target = e_max
        binding = "e_max"
    elif target < EXPOSURE_FLOOR:
        target = EXPOSURE_FLOOR
        binding = "floor"

    return TargetExposure(
        target_pct=target,
        m_regime=m_regime,
        m_vol=m_vol,
        m_evidence=m_evidence,
        m_drawdown=m_drawdown,
        binding=binding,
        degraded=degraded,
        index_vol_annualized=vol_ann,
        index_vol_n=vol_n,
    )
