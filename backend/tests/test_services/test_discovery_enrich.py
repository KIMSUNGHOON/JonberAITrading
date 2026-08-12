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


# ---- T3: 시장경보 하드 차단 (2026-08-12) ----
#
# 밸류에이션 하드 필터는 기각됐다 — "강세장이면 무시하고 급등한다"는
# 반론을 데이터가 지지했다(PER 57.89 → 다음날 +30%).
#
# ⭐ **시장경보는 성질이 다르다.** 정리매매·투자위험에는 그 반론이
# 성립하지 않는다. 하드 차단이 정당한 유일한 신호다.

from services.discovery.enrich import enrich_warnings  # noqa: E402


class _WarnFetch:
    def __init__(self, table: dict, boom: bool = False):
        self.table = table
        self.calls: list[str] = []
        self.boom = boom

    async def __call__(self, ticker: str):
        self.calls.append(ticker)
        if self.boom:
            raise RuntimeError("toss 403")
        return self.table.get(ticker, [])


async def test_liquidation_trading_blocks_the_candidate():
    """정리매매 종목은 어떤 맥락에서도 신규 관심종목이 될 수 없다."""
    c = _cand("005930", 1)
    fetch = _WarnFetch({"005930": [{"type": "LIQUIDATION_TRADING"}]})

    await enrich_warnings([c], fetch=fetch)

    assert c.quality_filter_passed is False
    assert c.skip_reason is not None
    assert "LIQUIDATION_TRADING" in c.skip_reason


async def test_investment_risk_blocks():
    c = _cand("005930", 1)
    fetch = _WarnFetch({"005930": [{"type": "INVESTMENT_RISK"}]})

    await enrich_warnings([c], fetch=fetch)

    assert c.quality_filter_passed is False


async def test_overheating_is_recorded_but_not_blocking():
    """단기과열·VI는 관측만 한다 — 급등 자체가 배제 사유는 아니다."""
    c = _cand("005930", 1)
    fetch = _WarnFetch({"005930": [{"type": "SHORT_TERM_OVERHEATING"}]})

    await enrich_warnings([c], fetch=fetch)

    assert c.quality_filter_passed is True
    assert "SHORT_TERM_OVERHEATING" in (c.market_warnings or [])


async def test_no_warnings_is_normal():
    c = _cand("005930", 1)
    fetch = _WarnFetch({"005930": []})

    await enrich_warnings([c], fetch=fetch)

    assert c.quality_filter_passed is True
    assert c.market_warnings == []


async def test_fetch_failure_does_not_block_fail_open():
    """🔴 조회 실패로 후보를 차단하면 403 한 번에 그날 승격이 전멸한다.
    그것은 '안전'이 아니라 '발굴 정지'다 — fail-open."""
    c = _cand("005930", 1)
    fetch = _WarnFetch({}, boom=True)

    await enrich_warnings([c], fetch=fetch)

    assert c.quality_filter_passed is True
    assert c.skip_reason is None


async def test_string_warnings_are_handled():
    """응답이 dict가 아니라 문자열 리스트로 와도 동작해야 한다 —
    실호출에서는 빈 배열만 봐서 원소 모양을 확정하지 못했다."""
    c = _cand("005930", 1)
    fetch = _WarnFetch({"005930": ["LIQUIDATION_TRADING"]})

    await enrich_warnings([c], fetch=fetch)

    assert c.quality_filter_passed is False
