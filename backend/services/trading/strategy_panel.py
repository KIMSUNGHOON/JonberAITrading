"""Phase 3: the strategy-level panel — context assembly from the Phase1/2
ledgers + one parallel structured-vote round by 3 strategy-altitude
panelists.

Deliberately NOT the agent-chat ChatRoom: every agent-chat model
(ChatSession/MarketContext/prompts) is ticker-bound and a fake-ticker
session would pollute the agent_chat_decisions ledger that EOD aggregation
reads. This panel is a new, lightweight loop that reuses only the shared
LLM layer (get_llm_provider().generate_structured — JSON parse + required
keys, raises on failure) with TaskType.STRATEGIC_DECISION (opus routing).

Structured-only by contract: a panelist whose call fails (parse error,
LLMAllBackendsFailed, timeout) becomes {"panelist", "error"} — excluded
from the electorate by strategy_consensus.valid_votes. No free-text
parsing, no defaults masquerading as data.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from agents.llm.tasks import TaskType
from agents.llm_provider import get_llm_provider

from services.discovery.ledger import get_discovery_performance

from .strategy_consensus import STRATEGY_VOTE_SCHEMA

logger = logging.getLogger(__name__)

# 최근 N일 시계열 창 (컨텍스트 크기 통제)
_REGIME_DAYS = 14
_PERF_ROWS = 30

# DS-5 폐루프(spec §6): get_discovery_performance의 lookback 창 — DS-3의
# 자체 기본값(14)과 동일하게 맞춘다.
_DISCOVERY_PERFORMANCE_DAYS = 14

_SCHEMA_INSTRUCTION = (
    "반드시 아래 JSON 스키마에 맞는 JSON 객체 하나만 출력하십시오. "
    "stance는 aggressive/neutral/defensive 중 하나, confidence는 0.0~1.0. "
    "adjustments에는 조정을 제안하고 싶은 노브만 넣으십시오(강제 아님): "
    "max_position_pct(종목당 최대 비중, 소수분율), min_cash_ratio(최소 현금 비율), "
    "max_positions(최대 보유 종목 수, 정수), stop_loss_pct(손절, 소수분율 예 0.07=7%), "
    "take_profit_pct(익절, 소수분율), max_trade_notional_pct(1건당 명목 상한, "
    "퍼센트 단위 5~30 — 위 소수분율 노브들과 달리 0.15가 아니라 15처럼 그대로 "
    "퍼센트 숫자로 제안), consensus_threshold(4-에이전트 토론의 매수/매도 합의 "
    "문턱, 소수분율 0.60~0.85 — 낮추면 진입 기회가 늘고 오탐도 늘며, 높이면 "
    "반대), "
    "target_vol_pct(변동성 타게팅 기준, 퍼센트 10~40 — 이 변동성에서 전량 "
    "사이즈로 간다. 시장 실현변동성이 이보다 높으면 노출을 줄인다), "
    "vol_multiplier_min(변동성 축소 하한, 분율 0.2~0.8 — 아무리 변동성이 "
    "높아도 이 배수 아래로는 안 줄인다). "
    "제안 값은 현행 값에서 크게 벗어나면 "
    "시스템이 안전 한도로 잘라냅니다."
)

PANELISTS: dict[str, str] = {
    "performance_reviewer": (
        "당신은 트레이딩 성과 리뷰어입니다. 오늘의 EOD 리뷰(포트폴리오 손익, "
        "종목별 실현손익, thesis_valid)와 최근 성과 시계열을 근거로 '무엇이 "
        "작동했고 무엇이 손실을 냈는지'를 판정하고, 내일의 전략 스탠스"
        "(aggressive/neutral/defensive)와 노브 조정을 제안하십시오. 데이터에 "
        "없는 사실을 만들지 마십시오. " + _SCHEMA_INSTRUCTION
    ),
    "regime_strategist": (
        "당신은 시장 레짐 전략가입니다. 레짐 스냅샷 시계열(risk_on/risk_off/"
        "neutral, breadth_ratio)에 더해 KOSPI/KOSDAQ 지수 등락률, 외국인/기관 "
        "수급(순매매액), 파생 시장심리(market_sentiment_label/sentiment_score)의 "
        "추세를 근거로, 현행 전략이 레짐에 맞는지 판정하고 내일의 전략 스탠스와 "
        "노브 조정을 제안하십시오. 지수·수급·심리 데이터가 없으면(과거 breadth만 "
        "있는 날) breadth로만 판단하되 낮은 confidence로 답하십시오. "
        + _SCHEMA_INSTRUCTION
    ),
    "risk_officer": (
        "당신은 리스크 관리자입니다. 노출도(exposure)·집중도(concentration)·"
        "누적수익률·승패 분포·에이전트 적중률(calibration)을 근거로 사이징과 "
        "손절/익절 노브가 적절한지 판정하십시오. 손실 확대 국면에서는 defensive "
        "스탠스와 보수적 노브(작은 max_position_pct, 높은 min_cash_ratio, 타이트한 "
        "stop_loss_pct)를 제안하는 것이 당신의 책무입니다. " + _SCHEMA_INSTRUCTION
    ),
}


def _latest_per_key(rows: list[dict], key: str) -> list[dict]:
    """Accrete 원장(같은 키로 재실행 시 append)에서 키별 최신 행만.
    rows는 created_at DESC로 들어오므로 첫 등장이 최신이다."""
    seen: set = set()
    out: list[dict] = []
    for row in rows:
        k = row.get(key)
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
    return out


async def build_strategy_context(
    storage: Any, trade_date: str, current_strategy_knobs: dict
) -> Optional[dict]:
    """Assemble the panel's shared evidence. None = not enough data to hold
    a meaningful debate (no/error-only EOD review for `trade_date`) — the
    orchestrator then skips the run entirely."""
    reviews = await storage.get_eod_reviews(limit=40)
    today_row = next((r for r in reviews if r.get("trade_date") == trade_date), None)
    if today_row is None:
        return None
    try:
        report = json.loads(today_row.get("report_json") or "{}")
    except (TypeError, ValueError):
        return None
    if not report or (report.get("error") and not report.get("portfolio")):
        return None

    regimes = _latest_per_key(await storage.get_regime_snapshots(limit=60), "trade_date")
    perf = await storage.get_daily_perf_snapshots(limit=_PERF_ROWS)
    calibration = _latest_per_key(
        await storage.get_agent_calibration(as_of_date=trade_date), "agent_type"
    )

    # DS-5 폐루프(spec §6): 전략별 발굴 성과(승격/미승격·평균 fwd 수익률·
    # 적중률)를 패널 근거에 추가 — 패널리스트가 발굴이 실제로 통했는지를
    # 참고해 스탠스/노브를 조정할 수 있게 한다. 조회 실패는 패널 자체를
    # 죽이지 않고 그냥 None(패널의 나머지 기존 거동은 불변).
    try:
        discovery_performance = await get_discovery_performance(
            storage, days=_DISCOVERY_PERFORMANCE_DAYS
        )
    except Exception as e:
        logger.warning(f"[StrategyPanel] get_discovery_performance failed: {e}")
        discovery_performance = None

    return {
        "trade_date": trade_date,
        "eod_review": report,
        "regime_history": [
            {
                "trade_date": r.get("trade_date"),
                "id": r.get("id"),
                "regime_label": r.get("regime_label"),
                "breadth_ratio": r.get("breadth_ratio"),
                "market_sentiment_label": r.get("market_sentiment_label"),
                "sentiment_score": r.get("sentiment_score"),
                "index_kospi_chg_pct": r.get("index_kospi_chg_pct"),
                "index_kosdaq_chg_pct": r.get("index_kosdaq_chg_pct"),
                "foreign_net_amount": r.get("foreign_net_amount"),
                "institution_net_amount": r.get("institution_net_amount"),
            }
            for r in regimes[:_REGIME_DAYS]
        ],
        "perf_history": [
            {
                "trade_date": p.get("trade_date"),
                "equity": p.get("equity"),
                "net_pnl": p.get("net_pnl"),
                "win_trades": p.get("win_trades"),
                "loss_trades": p.get("loss_trades"),
                "cumulative_return_pct": p.get("cumulative_return_pct"),
            }
            for p in perf
        ],
        "calibration": [
            {
                "agent_type": c.get("agent_type"),
                "accuracy": c.get("accuracy"),
                "decisions_scored": c.get("decisions_scored"),
                "avg_confidence": c.get("avg_confidence"),
            }
            for c in calibration
        ],
        "current_strategy": current_strategy_knobs,
        "discovery_performance": discovery_performance,
    }


async def _panelist_vote(name: str, system_prompt: str, user_prompt: str) -> dict:
    """One structured vote. Any failure -> {"panelist", "error"} — explicit,
    never a plausible-looking default (the base_agent error-string swallow
    is exactly what we refuse to inherit)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        vote = await get_llm_provider().generate_structured(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
            STRATEGY_VOTE_SCHEMA,
            task=TaskType.STRATEGIC_DECISION,
        )
        return {**vote, "panelist": name}
    except Exception as e:
        logger.warning(f"[StrategyPanel] {name} vote failed: {e}")
        return {"panelist": name, "error": str(e)}


async def run_strategy_panel(context: dict) -> list[dict]:
    """All panelists in parallel over the same evidence. Always returns one
    entry per panelist (vote or error) — the electorate math downstream
    decides what counts."""
    user_prompt = (
        "다음은 오늘의 EOD 종합 데이터입니다. 이를 근거로 전략 스탠스와 "
        "노브 조정을 투표하십시오.\n\n"
        + json.dumps(context, ensure_ascii=False, default=str)
    )
    tasks = [
        _panelist_vote(name, prompt, user_prompt)
        for name, prompt in PANELISTS.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    votes: list[dict] = []
    for name, result in zip(PANELISTS, results):
        if isinstance(result, BaseException):  # gather 방어 — _panelist_vote는 삼키지만
            votes.append({"panelist": name, "error": str(result)})
        else:
            votes.append(result)
    return votes
