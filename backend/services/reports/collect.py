"""리포트 데이터 수집.

각 수집기는 **never-raise**다. 하나가 실패해도 나머지 섹션은 나가야 한다 —
`services/telegram/briefing.py::format_brief`의 기존 철학을 그대로 쓴다.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Optional

import structlog

from services.reports.models import AgentVote, NewsItem, PositionResearch

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


def _ago(when) -> str:
    """발행 시각을 '2시간 전'으로. 며칠 지난 기사는 날짜로."""
    try:
        delta = datetime.now() - when
    except Exception:
        return ""
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "방금"
    if mins < 60:
        return f"{mins}분 전"
    hours = mins // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    if days <= 7:
        return f"{days}일 전"
    try:
        return when.strftime("%m-%d")
    except Exception:
        return ""


async def attach_news(positions, *, fetch=None, max_items: int = 3) -> None:
    """종목별 최신 뉴스를 붙인다. `fetch`가 None이면 조용히 스킵."""
    if fetch is None:
        return
    for p in positions:
        try:
            articles = await fetch(p.ticker) or []
        except Exception as e:  # noqa: BLE001
            p.news_error = str(e)
            logger.warning("report_news_failed", ticker=p.ticker, error=str(e))
            continue
        p.news = [
            NewsItem(
                title=getattr(a, "title", "") or "",
                source=getattr(a, "source", "") or "",
                published=_ago(getattr(a, "pub_date", None)),
                sentiment=getattr(a, "sentiment", None),
                url=getattr(a, "link", "") or "",
            )
            for a in articles[:max_items]
        ]


def _as_float(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None      # NaN 배제


async def attach_fundamentals(positions, *, fetch=None, min_interval: float = 1.0) -> None:
    """PER·PBR·EPS를 Kiwoom `ka10001`에서 다시 조회한다.

    저장돼 있지 않아 다시 부른다 — 값은 fundamental 에이전트의 자연어
    근거 안에만 있고, 그것을 파싱하면 LLM이 문구를 바꿀 때 조용히 깨진다.
    틀린 숫자를 싣는 것은 빈칸보다 나쁘다.

    `min_interval`은 Kiwoom 레이트리밋(~1.4 req/s) 때문이다 —
    2026-08-12에 0.8초로 돌렸다가 `ka10001` 유량 초과가 실제로 났다.
    """
    if fetch is None:
        return
    for i, p in enumerate(positions):
        if i and min_interval:
            await asyncio.sleep(min_interval)
        try:
            info = await fetch(p.ticker)
        except Exception as e:  # noqa: BLE001
            logger.warning("report_fundamentals_failed", ticker=p.ticker, error=str(e))
            continue
        if info is None:
            continue
        p.per = _as_float(getattr(info, "per", None))
        p.pbr = _as_float(getattr(info, "pbr", None))
        p.eps = _as_float(getattr(info, "eps", None))
