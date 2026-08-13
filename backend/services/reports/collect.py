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


async def collect_positions(coordinator=None) -> list[PositionResearch]:
    """코디네이터 스냅샷에서 보유 종목을 뽑는다. 실패하면 빈 리스트.

    ⚠️ `ExecutionCoordinator`에는 `.positions`(dict)가 없다 — 보유 종목은
    `coordinator.state.positions`(`list[ManagedPosition]`, `state`는
    `self._state`를 돌려주는 프로퍼티)에 있다. `services/trading/eod_digest.py`·
    `services/telegram/briefing.py::collect_brief`가 같은 경로를 쓴다.
    """
    try:
        if coordinator is None:
            from app.dependencies import get_trading_coordinator
            coordinator = await get_trading_coordinator()
        out: list[PositionResearch] = []
        positions = getattr(getattr(coordinator, "state", None), "positions", None) or []
        for pos in positions:
            out.append(
                PositionResearch(
                    ticker=getattr(pos, "ticker", "") or "",
                    name=getattr(pos, "stock_name", "") or getattr(pos, "ticker", ""),
                    quantity=int(getattr(pos, "quantity", 0) or 0),
                    avg_price=float(getattr(pos, "avg_price", 0) or 0),
                    current_price=float(getattr(pos, "current_price", 0) or 0),
                    pnl_pct=float(getattr(pos, "unrealized_pnl_pct", 0) or 0),
                    stop_loss=getattr(pos, "stop_loss", None),
                    stop_loss_source="coordinator",
                )
            )
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("report_positions_failed", error=str(e))
        return []


def make_fundamentals_fetch():
    """`attach_fundamentals(fetch=...)`에 넣을 Kiwoom `ka10001` 조회기.

    `services/discovery/orchestrator.py::_make_stock_info_fetch`와 같은
    형태이지만, 그쪽은 이미 있는 코디네이터의 `_kiwoom`을 넘겨받는 반면
    여기는 인자 없이 불려서(`collect.make_fundamentals_fetch()`) 공유
    Kiwoom 클라이언트 싱글턴을 직접, 그것도 첫 조회 때 지연 확보한다.
    클라이언트를 못 구해도 `None`을 던지지 않는다 — 종목별 `_fetch` 호출이
    이미 `attach_fundamentals`의 try/except 안에서 개별 실패로 흡수된다.
    """
    holder: dict = {}

    async def _fetch(ticker: str):
        if "client" not in holder:
            try:
                from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
                holder["client"] = await get_shared_kiwoom_client_async()
            except Exception as e:  # noqa: BLE001
                logger.warning("report_fundamentals_client_unavailable", error=str(e))
                holder["client"] = None
        client = holder["client"]
        if client is None:
            return None
        return await client.get_stock_info(ticker)

    return _fetch


def make_news_fetch():
    """`attach_news(fetch=...)`에 넣을 종목별 뉴스 조회기.

    `services/discovery/orchestrator.py::_make_news_fetch`와 같은 형태이되
    두 가지가 다르다: ①발굴 쪽은 제목 문자열만 돌려주지만 여기는
    `NewsArticle` 객체 그대로 돌려준다(리포트에 출처·발행시각·감성이
    필요하다) ②`attach_news`는 `fetch`가 돌려준 순서를 그대로 쓰고 자체
    정렬을 하지 않으므로, 여기서 최신순(`pub_date` 내림차순)을 보장한다.
    서비스를 못 만들면 `None` -- 수집을 건너뛸 뿐 리포트는 계속 렌더된다.
    """
    try:
        from services.news import create_news_service
    except Exception as e:  # noqa: BLE001 -- import 실패도 "수집 불가"일 뿐
        logger.warning("report_news_service_unavailable", error=str(e))
        return None

    holder: dict = {}

    async def _fetch(ticker: str):
        if "svc" not in holder:
            holder["svc"] = await create_news_service()
        result = await holder["svc"].search_stock_news(stock_code=ticker, count=5)
        articles = list(getattr(result, "articles", None) or [])
        articles.sort(
            key=lambda a: getattr(a, "pub_date", None) or datetime.min, reverse=True
        )
        return articles

    return _fetch


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
