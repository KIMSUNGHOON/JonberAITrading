"""유동성 계산 순수 함수 (유동성 인지 발굴 아크).

전부 순수 함수 — I/O·네트워크·DB 절대 없음(factors.py와 동일 규약). 입력은
`chart_df`(kiwoom get_daily_chart_df 스키마, `value` 컬럼 = 거래대금 원 단위)와
스칼라뿐이다.

설계 근거는 docs/superpowers/specs/2026-07-27-liquidity-aware-discovery-design.md.
핵심 두 가지:
- **중앙값을 쓴다**: 모멘텀 전략은 정의상 급등일을 포함하므로 평균 거래대금은
  체계적으로 상향 편향된다. MSCI ATVR·FTSE GEIS가 유동성 스크린에 median을
  채택한 근거와 같다.
- **게이트(1%)와 사이징(0.5%)은 다른 상수다**: 전자는 진입 자격, 후자는 실제
  포지션 크기. 2계층 방어이며 하나로 합치면 안 된다.
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd

# 절대 하한 — 어떤 완화에서도 뚫리지 않는다. KOSPI 종목의 50.5%가 ADTV 10억
# 미만이며(아주경제 2026-06), 이 대역은 참여율과 무관하게 자율봇이 다룰 수
# 있는 시장이 아니다.
HARD_FLOOR_ADTV: float = 1_000_000_000.0  # 10억원

# 진입 자격 게이트: 포지션이 일평균 거래대금의 1.0%를 넘으면 배제.
# 기관 실무 상한(1%)이자 한국 퀀트 표준(0.5%)의 2배 완화선.
GATE_PARTICIPATION_PCT: float = 0.01

# 사이징 캡: 실제 포지션은 ADTV의 0.5%까지. 한국 퀀트 실무 표준
# (《현명한 퀀트 투자자》 "당일 거래대금의 0.5%").
SIZING_PARTICIPATION_PCT: float = 0.005

# liquidity_gate_score의 로그 스케일 양 끝점.
_GATE_SCORE_MIN_ADTV: float = 1_000_000_000.0    # 10억 -> 0.0
_GATE_SCORE_MAX_ADTV: float = 10_000_000_000.0   # 100억 -> 1.0

DEFAULT_WINDOW = 20
MIN_SAMPLES = 10


def _value_series(chart_df: Optional[pd.DataFrame], window: int) -> Optional[pd.Series]:
    """chart_df에서 최근 `window`일 거래대금 시리즈를 뽑는다. 컬럼 부재/표본
    부족/전부 결측이면 None(호출자가 '데이터 없음'으로 처리)."""
    if chart_df is None or len(chart_df) == 0:
        return None
    if "value" not in chart_df.columns:
        return None
    s = pd.to_numeric(chart_df["value"].tail(window), errors="coerce").dropna()
    if len(s) < MIN_SAMPLES:
        return None
    return s


def adtv_median(
    chart_df: Optional[pd.DataFrame], window: int = DEFAULT_WINDOW
) -> Optional[float]:
    """최근 `window`일 거래대금 중앙값(원). 데이터 부족 시 None."""
    s = _value_series(chart_df, window)
    if s is None:
        return None
    med = float(s.median())
    if math.isnan(med) or math.isinf(med):
        return None
    return med


def required_min_adtv(position_notional: float) -> float:
    """이 포지션 규모가 요구하는 최소 ADTV — 참여율 게이트와 하드플로어의 max."""
    if position_notional is None or position_notional <= 0:
        return HARD_FLOOR_ADTV
    return max(position_notional / GATE_PARTICIPATION_PCT, HARD_FLOOR_ADTV)


def participation_rate(
    position_notional: float, adtv: Optional[float]
) -> Optional[float]:
    """포지션이 일평균 거래대금에서 차지하는 비율(0~1). ADTV 결측이면 None."""
    if adtv is None or adtv <= 0:
        return None
    return float(position_notional) / float(adtv)


def liquidity_cap_value(adtv: Optional[float]) -> Optional[float]:
    """유동성이 허용하는 최대 포지션 금액(원). ADTV 결측이면 None(캡 미적용)."""
    if adtv is None or adtv <= 0:
        return None
    return float(adtv) * SIZING_PARTICIPATION_PCT


def liquidity_gate_score(adtv: Optional[float]) -> float:
    """절대 유동성의 0~1 로그 스코어 — 10억=0.0, 100억=1.0.

    momentum 거래량 성분의 곱셈 게이트로 쓰인다. 선형이 아니라 로그인 이유는
    거래대금 분포가 극단적으로 편중돼 있어(상위 6%가 전체의 88%) 선형 스케일이면
    중형주가 전부 0에 붙기 때문이다.
    """
    if adtv is None or adtv <= 0:
        return 0.0
    ratio = float(adtv) / _GATE_SCORE_MIN_ADTV
    if ratio <= 1.0:
        return 0.0
    span = math.log10(_GATE_SCORE_MAX_ADTV / _GATE_SCORE_MIN_ADTV)
    score = math.log10(ratio) / span
    return max(0.0, min(1.0, score))


def downside_consistency_ok(
    chart_df: Optional[pd.DataFrame],
    min_adtv: float,
    window: int = DEFAULT_WINDOW,
    floor_ratio: float = 0.6,
    max_violations: int = 5,
) -> bool:
    """하방 일관성 — 최근 `window`일 중 거래대금이 `min_adtv * floor_ratio`
    미만인 날이 `max_violations`일 이하여야 한다.

    MSCI의 Frequency of Trading(3개월 거래일 비율 80%)을 일간으로 이식한 것.
    중앙값만 보면 '평소 말라 있다가 며칠 폭발'한 종목을 못 거른다.

    데이터가 없으면 False(fail-closed) — 유동성을 확인할 수 없는 종목은
    통과시키지 않는다.
    """
    s = _value_series(chart_df, window)
    if s is None:
        return False
    floor = float(min_adtv) * floor_ratio
    return int((s < floor).sum()) <= max_violations


def has_zero_volume_day(
    chart_df: Optional[pd.DataFrame], window: int = DEFAULT_WINDOW
) -> bool:
    """최근 `window`일 중 거래량 0인 날이 있으면 True(즉시 배제 대상).

    거래량 0은 호가가 아예 성립하지 않은 날이며, KRX 저유동성 단일가매매
    (평균 체결주기 10분 초과) 대역의 지문이다. 컬럼이 없으면 판단 불가이므로
    False(다른 게이트가 걸러낸다)."""
    if chart_df is None or len(chart_df) == 0 or "volume" not in chart_df.columns:
        return False
    v = pd.to_numeric(chart_df["volume"].tail(window), errors="coerce").fillna(0)
    return bool((v <= 0).any())
