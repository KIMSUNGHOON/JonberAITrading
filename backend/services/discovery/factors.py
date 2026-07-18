"""
Discovery Factor/Strategy Engine (DS-1).

전부 순수 함수 + 데이터클래스 — I/O·네트워크·DB 절대 없음. 입력은 이미 수집된
pandas OHLCV DataFrame(`StockSnapshot.chart_df`)뿐이며, 이 모듈은 그 위에서
지표를 계산해 4개 전략(momentum/pullback/flow/meanrev)의 0~1 스코어를 낸다.

소비자:
- DS-2 스캐너가 종목당 StockSnapshot을 만들어 compute_strategy_scores 결과를 저장.
- DS-4가 레짐 가중치로 이 스코어들을 랭킹.

주의: `services.technical_indicators.TechnicalIndicators.detect_signals()`가 내는
'warning'/'opportunity'/'info' 타입 문자열은 여기서 소비하지 않는다(디스커버리
설계 문서에서 확인된 죽은 매칭의 근원 — quick 스크리닝이 이 문자열을 잘못된
값과 비교해 항상 HOLD를 내던 버그). 이 모듈은 SMA/RSI/MACD/볼린저/거래량 등
수치 지표만 직접 계산해 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from services.technical_indicators import TechnicalIndicators

# ---------------------------------------------------------------------------
# 품질 필터 사유 코드
# ---------------------------------------------------------------------------
REASON_PRICE_ZERO = "price_zero"
REASON_MARKET_CAP_LOW = "market_cap_low"
REASON_INSUFFICIENT_HISTORY = "insufficient_history"

DEFAULT_MIN_MARKET_CAP = 50_000_000_000  # 500억원
DEFAULT_MIN_HISTORY = 60  # 일봉 60개(SMA60 계산 가능 최소치)

STRATEGIES: tuple[str, ...] = ("momentum", "pullback", "flow", "meanrev")

# flow 전략의 순매수 금액 정규화 스케일(기관+외인 합산, 원). 이 값 이상이면
# 만점(1.0). 발굴 랭킹의 상대 비교 용도이므로 정밀한 시장 데이터 캘리브레이션은
# 후속 아크(DS-4 레짐 가중) 몫으로 남긴다.
FLOW_NET_AMOUNT_SCALE = 20_000_000_000  # 200억원


@dataclass
class StockSnapshot:
    """수집 셔틀(DS-2)이 채우는 종목 스냅샷. 이 모듈은 순수 소비자."""

    ticker: str
    name: str
    price: float
    market_cap: float
    per: float
    pbr: float
    volume: float
    chart_df: pd.DataFrame


@dataclass
class FlowRank:
    """ka10131(기관/외인 순매수 랭킹) 한 행."""

    ticker: str
    orgn_net_amt: float
    frgnr_net_amt: float
    orgn_cont_days: int
    frgnr_cont_days: int
    rank: int


def _clamp01(value: Optional[float]) -> float:
    """None/NaN/Inf는 0.0으로, 나머지는 [0, 1] 구간으로 클램프."""
    if value is None:
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if np.isnan(f) or np.isinf(f):
        return 0.0
    return max(0.0, min(1.0, f))


def _safe(value) -> Optional[float]:
    """NaN/Inf/None을 None으로 정규화한 float, 아니면 float 그대로."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(f) or np.isinf(f):
        return None
    return f


def passes_quality_filter(
    snap: StockSnapshot,
    *,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    min_history: int = DEFAULT_MIN_HISTORY,
) -> tuple[bool, Optional[str]]:
    """공통 품질 필터(spec §2). (통과여부, 실패사유) 반환 — 통과 시 사유는 None.

    검사 순서: 가격>0 → 시총 하한 → 히스토리 길이. 관리종목 제외 등 나머지
    필터는 수집 단계(DS-2, exclude_warnings)의 몫이라 여기선 다루지 않는다.
    """
    if snap.price is None or snap.price <= 0:
        return False, REASON_PRICE_ZERO
    if snap.market_cap is None or snap.market_cap < min_market_cap:
        return False, REASON_MARKET_CAP_LOW
    history_len = 0 if snap.chart_df is None else len(snap.chart_df)
    if history_len < min_history:
        return False, REASON_INSUFFICIENT_HISTORY
    return True, None


def _extract_atoms(chart_df: Optional[pd.DataFrame]) -> dict:
    """chart_df에서 원자 팩터를 뽑는다. 데이터가 부족한 항목은 None으로 남긴다
    (스코어 함수가 None→0 성분으로 처리, 절대 NaN을 전파하지 않는다)."""
    atoms: dict = {
        "current_price": None,
        "sma5": None,
        "sma20": None,
        "sma60": None,
        "rsi": None,
        "macd_line": None,
        "macd_signal": None,
        "macd_diff": None,
        "bb_upper": None,
        "bb_middle": None,
        "bb_lower": None,
        "vol_ratio": None,
        "high20": None,
        "high20_proximity": None,
        "drawdown_5d": None,
        "sma20_proximity_pct": None,
        "sma20_slope_pct": None,
        "touched_lower_recently": False,
    }

    if chart_df is None or len(chart_df) == 0:
        return atoms

    n = len(chart_df)
    try:
        ind = TechnicalIndicators(chart_df)
    except ValueError:
        # 필수 컬럼 누락 등 — 원자 팩터 전부 None으로 반환(스코어는 0으로 수렴).
        return atoms

    close = ind.close
    current = _safe(close.iloc[-1])
    atoms["current_price"] = current

    if n >= 5:
        atoms["sma5"] = _safe(ind.sma(5).iloc[-1])
    if n >= 20:
        atoms["sma20"] = _safe(ind.sma(20).iloc[-1])
    if n >= 60:
        atoms["sma60"] = _safe(ind.sma(60).iloc[-1])

    if n >= 15:
        atoms["rsi"] = _safe(ind.rsi().iloc[-1])

    macd_line, macd_signal, macd_hist = ind.macd()
    atoms["macd_line"] = _safe(macd_line.iloc[-1])
    atoms["macd_signal"] = _safe(macd_signal.iloc[-1])
    atoms["macd_diff"] = _safe(macd_hist.iloc[-1])

    if n >= 20:
        bb_upper, bb_middle, bb_lower = ind.bollinger_bands()
        atoms["bb_upper"] = _safe(bb_upper.iloc[-1])
        atoms["bb_middle"] = _safe(bb_middle.iloc[-1])
        atoms["bb_lower"] = _safe(bb_lower.iloc[-1])

        touch_window = min(5, n)
        lows_tail = ind.low.tail(touch_window).reset_index(drop=True)
        bb_lower_tail = bb_lower.tail(touch_window).reset_index(drop=True)
        comparable = lows_tail.notna() & bb_lower_tail.notna()
        touched = bool((lows_tail[comparable] <= bb_lower_tail[comparable]).any())
        atoms["touched_lower_recently"] = touched

        atoms["high20"] = _safe(ind.high.tail(20).max())
        if current is not None and atoms["high20"]:
            atoms["high20_proximity"] = current / atoms["high20"]

    vol_window = min(5, n)
    vol5 = _safe(ind.volume.tail(vol_window).mean())
    vol20_window = min(20, n)
    vol20 = _safe(ind.volume.tail(vol20_window).mean())
    if vol5 is not None and vol20:
        atoms["vol_ratio"] = vol5 / vol20

    if n >= 6:
        close_5d_ago = _safe(close.iloc[-6])
        if close_5d_ago:
            atoms["drawdown_5d"] = (close_5d_ago - current) / close_5d_ago

    sma20 = atoms["sma20"]
    if sma20 and current is not None:
        atoms["sma20_proximity_pct"] = (current - sma20) / sma20

    if n >= 25:
        sma20_series = ind.sma(20)
        sma20_5d_ago = _safe(sma20_series.iloc[-6])
        if sma20_5d_ago and sma20 is not None:
            atoms["sma20_slope_pct"] = (sma20 - sma20_5d_ago) / sma20_5d_ago

    return atoms


def _score_momentum(atoms: dict) -> float:
    """MA 정배열 + MACD>시그널 + 20일 고가 근접도 + 거래량 증가율(5d/20d)."""
    sma5, sma20, sma60 = atoms["sma5"], atoms["sma20"], atoms["sma60"]
    align_checks = []
    if sma5 is not None and sma20 is not None:
        align_checks.append(1.0 if sma5 > sma20 else 0.0)
    if sma20 is not None and sma60 is not None:
        align_checks.append(1.0 if sma20 > sma60 else 0.0)
    if sma5 is not None and sma60 is not None:
        align_checks.append(1.0 if sma5 > sma60 else 0.0)
    ma_alignment = (sum(align_checks) / len(align_checks)) if align_checks else 0.0

    macd_diff = atoms["macd_diff"]
    macd_bullish = 1.0 if (macd_diff is not None and macd_diff > 0) else 0.0

    high20_proximity = _clamp01(atoms["high20_proximity"])

    vol_ratio = atoms["vol_ratio"]
    vol_component = _clamp01((vol_ratio - 1.0) / 1.0) if vol_ratio is not None else 0.0

    return _clamp01((ma_alignment + macd_bullish + high20_proximity + vol_component) / 4.0)


def _score_pullback(atoms: dict) -> float:
    """SMA60 위 + RSI 40~55 + SMA20 근접도(±2%) + 추세 기울기."""
    current, sma60 = atoms["current_price"], atoms["sma60"]
    above_sma60 = 1.0 if (current is not None and sma60 is not None and current > sma60) else 0.0

    rsi = atoms["rsi"]
    rsi_band = 1.0 if (rsi is not None and 40.0 <= rsi <= 55.0) else 0.0

    prox_pct = atoms["sma20_proximity_pct"]
    sma20_proximity = _clamp01(1.0 - abs(prox_pct) / 0.02) if prox_pct is not None else 0.0

    slope_pct = atoms["sma20_slope_pct"]
    trend_slope = _clamp01(0.5 + slope_pct * 10.0) if slope_pct is not None else 0.0

    return _clamp01((above_sma60 + rsi_band + sma20_proximity + trend_slope) / 4.0)


def _score_flow(flow: Optional[FlowRank]) -> float:
    """랭킹 존재 + 기관/외인 연속일수(≥3 가점) + 순매수 금액 정규화. 랭킹 밖=0."""
    if flow is None:
        return 0.0

    presence = 1.0

    max_cont_days = max(flow.orgn_cont_days or 0, flow.frgnr_cont_days or 0)
    cont_bonus = 1.0 if max_cont_days >= 3 else _clamp01(max_cont_days / 3.0)

    net_amt = (flow.orgn_net_amt or 0.0) + (flow.frgnr_net_amt or 0.0)
    net_amt_norm = _clamp01(net_amt / FLOW_NET_AMOUNT_SCALE)

    return _clamp01((presence + cont_bonus + net_amt_norm) / 3.0)


def _score_meanrev(atoms: dict) -> float:
    """RSI<30 심도 + 볼린저 하단 이탈 후 복귀 + 5일 낙폭 과대.

    '복귀'가 핵심: 하단을 최근에 터치했더라도 현재가가 아직 밴드 아래(계속
    급락 중)면 재진입 성분은 0 — 여전히 위험한 급락과 과매도 반등을 가른다.
    """
    rsi = atoms["rsi"]
    rsi_depth = _clamp01((30.0 - rsi) / 30.0) if (rsi is not None and rsi < 30.0) else 0.0

    current, bb_lower = atoms["current_price"], atoms["bb_lower"]
    reentered = (
        atoms["touched_lower_recently"]
        and current is not None
        and bb_lower is not None
        and current > bb_lower
    )
    bb_reentry = 1.0 if reentered else 0.0

    drawdown = atoms["drawdown_5d"]
    drawdown_component = _clamp01(drawdown / 0.15) if (drawdown is not None and drawdown > 0) else 0.0

    return _clamp01((rsi_depth + bb_reentry + drawdown_component) / 3.0)


def compute_strategy_scores(snap: StockSnapshot, flow: Optional[FlowRank]) -> dict[str, float]:
    """4전략 스코어 {'momentum','pullback','flow','meanrev'} (0~1) + '_atoms'.

    성분 계산이 데이터 부족으로 불가하면 해당 성분은 0으로 취급(NaN 전파 없음).
    """
    atoms = _extract_atoms(snap.chart_df)

    scores: dict[str, float] = {
        "momentum": _score_momentum(atoms),
        "pullback": _score_pullback(atoms),
        "flow": _score_flow(flow),
        "meanrev": _score_meanrev(atoms),
    }

    atoms_out = dict(atoms)
    if flow is not None:
        atoms_out["flow_rank"] = flow.rank
        atoms_out["flow_orgn_cont_days"] = flow.orgn_cont_days
        atoms_out["flow_frgnr_cont_days"] = flow.frgnr_cont_days
        atoms_out["flow_net_amt"] = (flow.orgn_net_amt or 0.0) + (flow.frgnr_net_amt or 0.0)

    scores["_atoms"] = atoms_out
    return scores
