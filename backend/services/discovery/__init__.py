"""
Discovery Package (DS 아크)

레짐 적응형 종목 발굴 — 팩터/전략 엔진(DS-1), 스캐너 수집(DS-2), 레짐 랭킹(DS-4).
DS-1은 순수 함수만 노출한다: I/O·네트워크·DB 없음.
"""

from services.discovery.factors import (
    STRATEGIES,
    DEFAULT_MIN_HISTORY,
    DEFAULT_MIN_MARKET_CAP,
    FlowRank,
    StockSnapshot,
    compute_strategy_scores,
    passes_quality_filter,
)
from services.discovery.liquidity import (
    GATE_PARTICIPATION_PCT,
    HARD_FLOOR_ADTV,
    SIZING_PARTICIPATION_PCT,
    adtv_median,
    liquidity_cap_value,
    liquidity_gate_score,
    participation_rate,
    required_min_adtv,
)
from services.discovery.ranker import (
    DEFAULT_REGIME_WEIGHTS,
    WATCH_TOTAL_CAP,
    Candidate,
    PromoteSummary,
    llm_review_top,
    promote_candidates,
    rank_candidates,
)

__all__ = [
    "STRATEGIES",
    "DEFAULT_MIN_HISTORY",
    "DEFAULT_MIN_MARKET_CAP",
    "FlowRank",
    "StockSnapshot",
    "compute_strategy_scores",
    "passes_quality_filter",
    "GATE_PARTICIPATION_PCT",
    "HARD_FLOOR_ADTV",
    "SIZING_PARTICIPATION_PCT",
    "adtv_median",
    "liquidity_cap_value",
    "liquidity_gate_score",
    "participation_rate",
    "required_min_adtv",
    "DEFAULT_REGIME_WEIGHTS",
    "WATCH_TOTAL_CAP",
    "Candidate",
    "PromoteSummary",
    "llm_review_top",
    "promote_candidates",
    "rank_candidates",
]
