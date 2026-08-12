"""발굴 후보에 승격 판단 재료를 붙인다 (2026-08-12).

지표 4개만 보던 승격 LLM에게 펀더멘탈과 최근 뉴스를 준다.

**왜 필요한가**: `_build_llm_messages`가 만드는 프롬프트에는 종목명·레짐·
전략 점수 4개·종가·랭킹뿐이고, 시스템 프롬프트가 "정량 팩터 요약만 근거로
판단하라"고 명시적으로 제약한다. 펀더멘탈(Kiwoom PER/PBR)과 뉴스는 이미
시스템에 있는데 승격 **후** 토론에서야 쓰인다 — 게이트가 걸러야 할 것을
토론이 매일 다시 거른다(475150은 21일간 24회 전부 HOLD/NO_ACTION).

**설계 원칙 셋**:

1. **never-raise.** EOD 체인 안에서 돈다. 예외가 새면 뒤 단계가 통째로 죽는다.
2. **재료 부재 ≠ 부정 신호.** 수집 실패는 `None`/빈 리스트로 남기고 후보를
   탈락시키지 않는다(`flow`가 이미 쓰는 "미가용 — 부정신호 아님" 관행).
3. **`fetch=None`이면 통째로 스킵.** 기본 구현을 몰래 끌어오지 않는다 —
   배선이 빠졌을 때 조용히 도는 대신 아무것도 안 한 것이 드러나야 한다
   (`ledger._catch_up_missed_slots`의 `close_on_date=None`과 같은 관행).

수집기가 주입형인 덕에 라이브 API 없이 테스트되고, 나중에 소스를
(예: 토스 Open API) 갈아끼울 때 여기만 바꾸면 된다.

설계: docs/superpowers/specs/2026-08-12-discovery-promotion-evidence-design.md
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# Kiwoom은 ~1.4 req/s. 2026-08-12에 22종을 0.8초 간격으로 조회했다가
# `ka10001 허용된 요청 개수를 초과` 가 실제로 났다.
_DEFAULT_MIN_INTERVAL = 1.0


def _reviewable(candidates: list, top_n: int) -> list:
    """LLM 리뷰 대상과 **같은 집합**을 고른다.

    `ranker.llm_review_top`의 선정 규칙을 그대로 따른다(composite가 있는
    것만, rank 오름차순, 상위 `top_n`). 두 집합이 어긋나면 재료를 모은
    종목과 프롬프트를 받는 종목이 달라져 조회가 통째로 낭비된다.
    """
    rows = [c for c in candidates if getattr(c, "composite", None) is not None]
    rows.sort(key=lambda c: c.rank if getattr(c, "rank", None) is not None else 10**9)
    return rows[:top_n]


def _as_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def enrich_fundamentals(
    candidates: list,
    *,
    top_n: int = 25,
    fetch=None,
    min_interval: float = _DEFAULT_MIN_INTERVAL,
) -> None:
    """상위 `top_n` 후보에 PER/PBR/시가총액을 붙인다 (in-place).

    Args:
        candidates: `ranker.Candidate` 리스트. 제자리에서 수정된다.
        top_n: 조회할 상위 후보 수. `llm_review_top`의 기본값과 같아야 한다.
        fetch: `async (ticker) -> 객체 | None`. 반환 객체에서 `per`/`pbr`/
            `mrkt_tot_amt` 속성을 읽는다(Kiwoom `StockInfo` 모양).
            `None`이면 수집을 통째로 건너뛴다.
        min_interval: 종목 사이 대기(초). 레이트리밋 보호.
    """
    if fetch is None:
        return

    for i, c in enumerate(_reviewable(candidates, top_n)):
        if i and min_interval:
            await asyncio.sleep(min_interval)
        try:
            info = await fetch(c.ticker)
        except Exception as e:
            logger.warning(
                "discovery_fundamentals_failed", ticker=c.ticker, error=str(e)
            )
            continue
        if info is None:
            continue
        c.per = _as_float(getattr(info, "per", None))
        c.pbr = _as_float(getattr(info, "pbr", None))
        mc = getattr(info, "mrkt_tot_amt", None)
        c.market_cap = int(mc) if isinstance(mc, (int, float)) and mc else None


async def enrich_news(
    candidates: list,
    *,
    top_n: int = 25,
    max_items: int = 5,
    fetch=None,
) -> None:
    """상위 `top_n` 후보에 최근 뉴스 헤드라인을 붙인다 (in-place).

    **감성 점수를 만들지 않는다.** `services/news/sentiment.py`의
    `analyze_stock_news_sentiment`는 종목당 LLM을 1회 더 태운다 — top 25면
    **+25회**이고 EOD 체인(현재 약 65분)이 그만큼 길어진다. 헤드라인을
    승격 LLM이 직접 읽게 하면 호출이 늘지 않고, 중간 요약을 거치지 않아
    정보 손실도 없다.

    Args:
        candidates: `ranker.Candidate` 리스트. 제자리에서 수정된다.
        top_n: 조회할 상위 후보 수.
        max_items: 후보당 헤드라인 상한. 프롬프트가 무한정 길어지는 것을 막는다.
        fetch: `async (ticker, name) -> list[str]`. `None`이면 통째로 스킵.
    """
    if fetch is None:
        return

    for c in _reviewable(candidates, top_n):
        try:
            items = await fetch(c.ticker, getattr(c, "name", None) or c.ticker)
        except Exception as e:
            logger.warning("discovery_news_failed", ticker=c.ticker, error=str(e))
            continue
        c.news_headlines = [str(h) for h in (items or [])][:max_items]
