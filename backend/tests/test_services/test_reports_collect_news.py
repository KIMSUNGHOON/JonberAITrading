"""뉴스·펀더멘탈 수집 — 조회 실패가 리포트를 죽이지 않는다."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.reports.collect import attach_fundamentals, attach_news
from services.reports.models import PositionResearch

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _pos(ticker="028670") -> PositionResearch:
    return PositionResearch(
        ticker=ticker, name="팬오션", quantity=1, avg_price=1.0,
        current_price=5710.0, pnl_pct=0.0, stop_loss=None, stop_loss_source=None,
    )


@pytest.mark.asyncio
async def test_attaches_news_newest_first_capped():
    now = datetime.now()
    articles = [
        SimpleNamespace(title=f"기사{i}", source="한국경제", link=f"http://x/{i}",
                        pub_date=now - timedelta(hours=i), sentiment="neutral")
        for i in range(5)
    ]

    async def fetch(ticker):
        return articles

    p = _pos()
    await attach_news([p], fetch=fetch, max_items=3)
    assert [n.title for n in p.news] == ["기사0", "기사1", "기사2"]
    assert p.news[1].published == "1시간 전"
    assert p.news_error is None


@pytest.mark.asyncio
async def test_news_failure_records_reason_and_keeps_going():
    async def fetch(ticker):
        raise RuntimeError("quota exceeded")

    p1, p2 = _pos("028670"), _pos("004370")
    await attach_news([p1, p2], fetch=fetch)
    assert p1.news == [] and p1.news_error == "quota exceeded"
    assert p2.news_error == "quota exceeded"      # 첫 실패로 중단하지 않는다


@pytest.mark.asyncio
async def test_news_fetch_none_is_a_silent_skip():
    p = _pos()
    await attach_news([p], fetch=None)
    assert p.news == [] and p.news_error is None


@pytest.mark.asyncio
async def test_attaches_fundamentals():
    async def fetch(ticker):
        return SimpleNamespace(per=10.11, pbr=0.53, eps=564)

    p = _pos()
    await attach_fundamentals([p], fetch=fetch, min_interval=0)
    assert (p.per, p.pbr, p.eps) == (10.11, 0.53, 564.0)


@pytest.mark.asyncio
async def test_fundamentals_failure_leaves_none():
    """PER 칸이 비는 것이 틀린 숫자가 들어가는 것보다 낫다."""
    async def fetch(ticker):
        raise RuntimeError("유량 초과")

    p = _pos()
    await attach_fundamentals([p], fetch=fetch, min_interval=0)
    assert p.per is None and p.pbr is None and p.eps is None
