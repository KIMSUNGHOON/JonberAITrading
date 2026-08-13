"""리포트 데이터 수집.

각 수집기는 **never-raise**다. 하나가 실패해도 나머지 섹션은 나가야 한다 —
`services/telegram/briefing.py::format_brief`의 기존 철학을 그대로 쓴다.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import structlog

from services.reports.models import AgentVote, PositionResearch

logger = structlog.get_logger(__name__)

_HEADLINE_MAX = 120


def _loads(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _headline(row: dict) -> str:
    """key_factors[0]을 우선 쓴다 — 이미 사람이 읽을 한 줄로 요약돼 있다."""
    kf = _loads(row.get("key_factors"))
    if isinstance(kf, list) and kf and isinstance(kf[0], str) and kf[0].strip():
        return kf[0].strip()
    text = (row.get("reasoning") or "").strip().replace("\n", " ")
    if len(text) > _HEADLINE_MAX:
        return text[:_HEADLINE_MAX] + "…"
    return text


async def attach_research(
    positions: list[PositionResearch], trade_date: str, storage
) -> None:
    """보유 종목마다 그날의 결정·투표를 붙인다. 제자리 변형, never-raise."""
    for p in positions:
        try:
            decisions = await storage.get_ticker_day_decisions_full(p.ticker, trade_date)
        except Exception as e:  # noqa: BLE001
            logger.warning("report_research_failed", ticker=p.ticker, error=str(e))
            continue
        if not decisions:
            continue

        p.discussion_count = len(decisions)
        latest = decisions[-1]
        p.action = latest.get("action")
        p.consensus = latest.get("consensus_level")
        signals = _loads(latest.get("behavioral_signals"))
        p.signals = signals if isinstance(signals, dict) else {}

        try:
            rows = await storage.get_agent_chat_votes(latest["id"])
        except Exception as e:  # noqa: BLE001
            logger.warning("report_votes_failed", ticker=p.ticker, error=str(e))
            rows = []

        target = (p.action or "").strip().lower()
        p.votes = [
            AgentVote(
                agent_type=r.get("agent_type") or "?",
                vote=r.get("vote") or "?",
                confidence=float(r.get("confidence") or 0.0),
                headline=_headline(r),
                is_dissent=bool(target) and (r.get("vote") or "").strip().lower() != target,
            )
            for r in rows
        ]
