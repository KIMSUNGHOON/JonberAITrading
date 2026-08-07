"""포트폴리오 목표 노출도 — 순수 계산 (레짐 인지 노출도 제어, 2026-08-07).

설계: docs/superpowers/specs/2026-08-06-portfolio-exposure-observation-design.md

이 모듈은 DB도 API도 모른다. 입력을 받아 목표 노출도와 그 성분을 돌려줄 뿐이다.
호출자가 어떤 값을 넣었는지, 결과를 어디에 쓸지는 관심 밖이다 — 그래야 테스트가
실제 계산을 검증하고 목(mock)을 검증하지 않는다.

이 결과는 이제 사이징 구속력이 있다 -- 게이트 검사 8(목표 노출도 상한)이
`target_pct`를 실제 매수 상한으로 쓴다. 2026-08-06까지는 관측 전용
(`compute_target_exposure`, M_evidence 기반)이었으나, 왕복 표본이 모의
시장에서 쌓인 것이라 안전장치로 기능하지 못해 레짐 앵커 + 일일 변화
한도 방식(`compute_regime_target`)으로 대체됐다.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

# 레짐 앵커 — 목표 주식 비중(분율). 사용자 결정(2026-08-07):
# 강세면 현금 20%, 약세면 45%. 중간은 그 사이.
REGIME_ANCHORS: dict[str, float] = {"bull": 0.80, "neutral": 0.65, "bear": 0.55}

# 판정 1회당 목표가 움직일 수 있는 폭. LLM의 단 한 번의 판정이 계좌
# 절반을 움직이는 것을 막는다. 8.55%에서 시작하면 4거래일에 55%에 닿는다.
DAILY_TARGET_DELTA_MAX: float = 0.15

# 종목당 상한(분율, 고정). 목표 ÷ 이 값 = 필요 슬롯 수.
REGIME_PER_POSITION_PCT: float = 0.05

# 이보다 오래된 판정은 없는 것으로 취급한다(역일).
JUDGMENT_MAX_AGE_DAYS: int = 5

# 목표 상한 — bull 앵커와 같다. 배수는 깎기만 하므로 이 위로는 못 간다.
TARGET_CEILING: float = 0.80

# 노출도 하한. 방어 배수가 아무리 눌러도 완전히 0이 되지는 않게 한다.
EXPOSURE_FLOOR: float = 0.02

# 낙폭 배수의 기울기와 바닥. 고점 대비 10% 빠지면 0.7배.
DRAWDOWN_SLOPE: float = 3.0
DRAWDOWN_FLOOR: float = 0.3

# 변동성 배수. 목표·실측·게이트 경계는 **전부 퍼센트 단위**다 — 목표만 소수로
# 두면 배수가 100배 틀어진다.
TARGET_VOL_PCT: float = 18.0
VOL_WINDOW: int = 20
VOL_MIN_SAMPLES: int = 5
VOL_MULTIPLIER_MIN: float = 0.5
VOL_MULTIPLIER_MAX: float = 1.5

# 위생 게이트. 이 밖의 실현 변동성은 시장이 아니라 데이터 소스를 의심한다.
VOL_GATE_MIN_PCT: float = 5.0
VOL_GATE_MAX_PCT: float = 60.0
TRADING_DAYS_PER_YEAR: int = 250


@dataclass
class TargetExposure:
    """목표 노출도와 그것을 만든 성분들.

    `binding`/`degraded`가 있는 이유는 숫자만 남기면 몇 주 뒤 "왜 이 값이었나"를
    풀 수 없기 때문이다. `PortfolioAgent._calculate_max_position_value`의
    `lineage` out-param과 같은 계열이다.
    """

    target_pct: float
    m_vol: float
    m_drawdown: float
    binding: str
    anchor_pct: float
    prev_effective_pct: Optional[float] = None
    degraded: list[str] = field(default_factory=list)
    index_vol_annualized: Optional[float] = None
    index_vol_n: int = 0


def _drawdown_multiplier(equity: float, equity_peak: float) -> float:
    if not equity_peak or equity_peak <= 0 or not math.isfinite(equity_peak):
        return 1.0
    drawdown = max(0.0, (equity_peak - equity) / equity_peak)
    return max(DRAWDOWN_FLOOR, 1.0 - DRAWDOWN_SLOPE * drawdown)


def annualized_vol(
    index_returns: list[float], window: int = VOL_WINDOW
) -> tuple[Optional[float], int]:
    """최근 `window`개 등락률(%)의 표본표준편차 × √250, 그리고 사용한 표본 수.

    표본이 `VOL_MIN_SAMPLES` 미만이면 (None, 실제 표본 수)를 돌려준다 —
    표본 수는 부족해도 기록에는 남아야 한다.
    """
    usable = [r for r in (index_returns or []) if r is not None and math.isfinite(r)]
    sample = usable[-window:]
    n = len(sample)
    if n < VOL_MIN_SAMPLES:
        return None, n
    sd = statistics.stdev(sample)
    vol = sd * math.sqrt(TRADING_DAYS_PER_YEAR)
    if not math.isfinite(vol):
        return None, n
    return vol, n


def compute_regime_target(
    *,
    regime_label: str,
    prev_effective_pct: Optional[float],
    seed_actual_pct: float,
    index_returns: list[float],
    equity: float,
    equity_peak: float,
) -> TargetExposure:
    """레짐 라벨에서 목표 주식 비중(분율)을 만든다.

        ramped    = clamp(anchor, prev - 0.15, prev + 0.15)
        effective = clamp(ramped × M_vol × M_drawdown, 0.02, 0.80)

    **한도는 앵커에만 걸고 배수는 그 뒤에 곱한다** — 방어(낙폭·변동성)는
    일일 한도보다 빠르게 줄일 수 있어야 하기 때문이다.

    `prev_effective_pct`가 None이면(최초 실행) `seed_actual_pct`를 직전값으로
    쓴다. 이후에는 **직전 목표**를 잇는다 — 익절로 실제 비중이 떨어졌다고
    목표까지 따라 내려가면 안 된다.
    """
    degraded: list[str] = []

    anchor = REGIME_ANCHORS.get(regime_label)
    if anchor is None:
        # 모르는 라벨에서 중간값을 고르지 않는다. 가장 보수적인 앵커를 쓴다 --
        # 조회/파싱 실패가 노출도를 위로 여는 것이 이 리포의 알려진 함정이다.
        anchor = REGIME_ANCHORS["bear"]
        degraded.append("regime_unknown")

    prev = prev_effective_pct if prev_effective_pct is not None else seed_actual_pct
    ramped = max(prev - DAILY_TARGET_DELTA_MAX,
                 min(anchor, prev + DAILY_TARGET_DELTA_MAX))

    vol_ann, vol_n = annualized_vol(index_returns)
    if vol_ann is None:
        m_vol = 1.0
        degraded.append("index_vol_insufficient")
    elif not (VOL_GATE_MIN_PCT <= vol_ann <= VOL_GATE_MAX_PCT):
        m_vol = 1.0
        degraded.append("index_vol_implausible")
    else:
        m_vol = min(VOL_MULTIPLIER_MAX,
                    max(VOL_MULTIPLIER_MIN, TARGET_VOL_PCT / vol_ann))

    m_drawdown = _drawdown_multiplier(equity, equity_peak)

    raw = ramped * m_vol * m_drawdown

    # 무엇이 목표를 눌렀는지 하나만 고른다. 우선순위는 위에서부터다 --
    # 일일 한도가 앵커를 못 따라가게 막았다면 그것이 이 행의 이야기이고,
    # 아니면 더 작은 배수가, 아무것도 안 눌렀으면 앵커 그 자체다.
    if ramped != anchor:
        binding = "daily_limit"
    elif min(m_vol, m_drawdown) < 1.0:
        binding = "m_vol" if m_vol <= m_drawdown else "m_drawdown"
    else:
        binding = "anchor"

    target = raw
    if target > TARGET_CEILING:
        target = TARGET_CEILING
        binding = "ceiling"
    elif target < EXPOSURE_FLOOR:
        target = EXPOSURE_FLOOR
        binding = "floor"

    return TargetExposure(
        target_pct=target,
        m_vol=m_vol,
        m_drawdown=m_drawdown,
        binding=binding,
        anchor_pct=anchor,
        prev_effective_pct=prev,
        degraded=degraded,
        index_vol_annualized=vol_ann,
        index_vol_n=vol_n,
    )


def slots_for_target(
    target_pct: float,
    current_max: int,
    per_position_pct: float = REGIME_PER_POSITION_PCT,
) -> int:
    """목표를 담는 데 필요한 슬롯 수. **올리기만 한다.**

    목표가 내려갔다고 슬롯을 줄이면 같은 금액을 더 적은 종목에 담게 되어
    집중도가 오른다 -- 축소하려는 의도와 정반대다. 총량 축소는 전적으로
    게이트 검사 8(목표 노출도 상한)이 담당한다.
    """
    needed = math.ceil(target_pct / per_position_pct) if per_position_pct > 0 else current_max
    return max(current_max, int(needed))
