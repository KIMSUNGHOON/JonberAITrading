"""발굴 후보 재료 수집기 (2026-08-12).

승격 LLM이 종목명과 지표 4개만 보고 판단하던 것을 고치기 위한 수집 계층.
라이브 API를 쓰지 않는다 — `fetch` 주입으로 전부 테스트된다.
"""
import pytest

from services.discovery.enrich import enrich_fundamentals
from services.discovery.ranker import Candidate

pytestmark = pytest.mark.asyncio


def _cand(ticker: str, rank: int, composite: float = 0.6) -> Candidate:
    return Candidate(
        ticker=ticker, name=ticker, trade_date="2026-08-12",
        regime_label="neutral", threshold=0.55, daily_cap=5,
        weights={}, universe_fallback=False, quality_filter_passed=True,
        composite=composite, rank=rank,
    )


class _Info:
    def __init__(self, per=None, pbr=None, mc=None):
        self.per = per
        self.pbr = pbr
        self.mrkt_tot_amt = mc


class _CountingFetch:
    def __init__(self, table: dict, boom: bool = False):
        self.table = table
        self.calls: list[str] = []
        self.boom = boom

    async def __call__(self, ticker: str):
        self.calls.append(ticker)
        if self.boom:
            raise RuntimeError("kiwoom down")
        return self.table.get(ticker)


async def test_sets_per_pbr_market_cap():
    cands = [_cand("005930", 1)]
    fetch = _CountingFetch({"005930": _Info(per=12.5, pbr=1.02, mc=400_000_000_000)})

    await enrich_fundamentals(cands, fetch=fetch, min_interval=0.0)

    assert cands[0].per == pytest.approx(12.5)
    assert cands[0].pbr == pytest.approx(1.02)
    assert cands[0].market_cap == 400_000_000_000


async def test_only_top_n_are_fetched():
    """후보는 수천 개인데 Kiwoom은 ~1.4 req/s다. 상위 N만 조회한다."""
    cands = [_cand(f"{i:06d}", i) for i in range(1, 31)]
    fetch = _CountingFetch({})

    await enrich_fundamentals(cands, top_n=5, fetch=fetch, min_interval=0.0)

    assert fetch.calls == [f"{i:06d}" for i in range(1, 6)]


async def test_fetch_failure_leaves_none_and_does_not_raise():
    """수집 실패가 후보를 탈락시키지 않는다 — 재료 부재는 부정 신호가
    아니다. 그리고 EOD 체인 안에서 도니 예외가 새면 안 된다."""
    cands = [_cand("005930", 1)]
    fetch = _CountingFetch({}, boom=True)

    await enrich_fundamentals(cands, fetch=fetch, min_interval=0.0)

    assert cands[0].per is None
    assert cands[0].quality_filter_passed is True


async def test_no_fetch_means_no_work():
    """`fetch=None`이면 통째로 건너뛴다 — 기본 구현을 몰래 끌어오지
    않는다. 배선이 빠지면 조용히 도는 대신 아무것도 안 한 것이 드러나야 한다."""
    cands = [_cand("005930", 1)]

    await enrich_fundamentals(cands, fetch=None)

    assert cands[0].per is None


async def test_unranked_candidates_are_skipped():
    """quality filter에서 떨어진 행(composite None)은 LLM 리뷰 대상이
    아니므로 재료도 필요 없다."""
    c = _cand("005930", 1)
    c.composite = None
    c.rank = None
    fetch = _CountingFetch({"005930": _Info(per=1.0)})

    await enrich_fundamentals([c], fetch=fetch, min_interval=0.0)

    assert fetch.calls == []


# ---- U2: 뉴스 헤드라인 ----
#
# 감성 점수를 만들지 않는다. `analyze_stock_news_sentiment`는 종목당 LLM을
# 1회 더 태워 top 25면 +25회이고 EOD 체인(약 65분)이 그만큼 길어진다.
# 헤드라인을 승격 LLM이 직접 읽게 하면 호출이 늘지 않고 중간 요약으로
# 인한 정보 손실도 없다.

from services.discovery.enrich import enrich_news  # noqa: E402


class _NewsFetch:
    def __init__(self, table: dict, boom: bool = False):
        self.table = table
        self.calls: list[str] = []
        self.boom = boom

    async def __call__(self, ticker: str, name: str):
        self.calls.append(ticker)
        if self.boom:
            raise RuntimeError("naver down")
        return self.table.get(ticker, [])


async def test_news_headlines_are_attached():
    cands = [_cand("005930", 1)]
    fetch = _NewsFetch({"005930": ["삼성전자, HBM4 양산 개시", "2분기 영업익 +45%"]})

    await enrich_news(cands, fetch=fetch)

    assert cands[0].news_headlines == ["삼성전자, HBM4 양산 개시", "2분기 영업익 +45%"]


async def test_news_is_capped_at_max_items():
    """프롬프트가 무한정 길어지면 안 된다."""
    cands = [_cand("005930", 1)]
    fetch = _NewsFetch({"005930": [f"h{i}" for i in range(20)]})

    await enrich_news(cands, max_items=3, fetch=fetch)

    assert len(cands[0].news_headlines) == 3


async def test_news_failure_leaves_empty_and_does_not_raise():
    cands = [_cand("005930", 1)]
    fetch = _NewsFetch({}, boom=True)

    await enrich_news(cands, fetch=fetch)

    assert cands[0].news_headlines == []


async def test_news_only_top_n():
    cands = [_cand(f"{i:06d}", i) for i in range(1, 31)]
    fetch = _NewsFetch({})

    await enrich_news(cands, top_n=4, fetch=fetch)

    assert len(fetch.calls) == 4


async def test_news_no_fetch_means_no_work():
    cands = [_cand("005930", 1)]
    await enrich_news(cands, fetch=None)
    assert cands[0].news_headlines == []
