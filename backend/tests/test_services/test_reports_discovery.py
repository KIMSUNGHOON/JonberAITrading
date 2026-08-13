"""발굴 리포트 — 승격 근거와 차단 사유를 함께 보여준다."""
import pytest

from services.reports.models import ReportContext
from services.reports.render import render

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _ctx(candidates) -> ReportContext:
    return ReportContext(
        kind="discovery", trade_date="2026-08-13",
        generated_at="2026-08-13 16:35", extra={"candidates": candidates},
    )


def test_shows_score_breakdown_and_llm_rationale():
    html = render(_ctx([{
        "ticker": "119850", "name": "지엔씨에너지", "rank": 3, "composite": 0.6031,
        "strategies": {"momentum": 0.712, "pullback": 0.588, "flow": 0.443,
                       "meanrev": 0.201},
        "per": 21.4, "pbr": 1.8, "market_cap": 480000000000, "news_count": 7,
        "llm_rationale": "수주 잔고 증가와 거래대금 확대가 동반됐다",
        "llm_confidence": 0.71, "skip_reason": None,
    }]))
    for needle in ("지엔씨에너지", "momentum", "0.712",
                   "수주 잔고 증가", "21.4"):
        assert needle in html, needle


def test_blocked_candidate_shows_reason_not_hidden():
    """무엇이 걸러졌는지가 게이트가 일한다는 증거다."""
    html = render(_ctx([{
        "ticker": "999999", "name": "정리매매종목", "rank": 5, "composite": 0.61,
        "strategies": {}, "skip_reason": "market_warning:LIQUIDATION_TRADING",
    }]))
    assert "정리매매종목" in html
    assert "LIQUIDATION_TRADING" in html
    assert "차단" in html


def test_no_candidates_says_so():
    html = render(_ctx([]))
    assert "승격 0종" in html


def test_title_counts_promoted_and_blocked_separately():
    """제목이 `승격 {{ cands|length }}종`으로 차단된 후보까지 세면
    오해를 만든다(Task 9 fix 3). `skip_reason`이 없는 것만 승격으로,
    있는 것은 차단으로 따로 세야 한다."""
    html = render(_ctx([
        {
            "ticker": "005930", "name": "삼성전자", "rank": 1, "composite": 0.62,
            "strategies": {}, "skip_reason": None,
        },
        {
            "ticker": "999999", "name": "정리매매종목", "rank": 5, "composite": 0.61,
            "strategies": {}, "skip_reason": "market_warning:LIQUIDATION_TRADING",
        },
        {
            "ticker": "888888", "name": "투자위험종목", "rank": 6, "composite": 0.58,
            "strategies": {}, "skip_reason": "market_warning:INVESTMENT_RISK",
        },
    ]))
    assert "승격 1종" in html
    assert "차단 2종" in html


@pytest.mark.asyncio
async def test_discovery_report_skips_position_and_fundamentals_collection(monkeypatch):
    """레이트리밋 사고 방지 -- 발굴 승격 심사가 이미 top-25에 ka10001을
    25회 건다. 같은 시각에 보유 종목 펀더멘탈로 5회를 더 걸면 Kiwoom
    유량(~1.4 req/s)을 넘긴다(2026-08-12에 실제로 ka10001 유량 초과가
    났다). 발굴 리포트는 ctx.extra["candidates"]만 쓰므로 포지션/리서치/
    뉴스/펀더멘탈 수집을 전부 건너뛰어야 한다."""
    from services.reports import build_and_send_report, collect

    called: dict[str, bool] = {}

    async def _spy_collect_positions(*a, **kw):
        called["collect_positions"] = True
        return []

    async def _spy_attach_research(*a, **kw):
        called["attach_research"] = True

    async def _spy_attach_fundamentals(*a, **kw):
        called["attach_fundamentals"] = True

    async def _spy_attach_news(*a, **kw):
        called["attach_news"] = True

    monkeypatch.setattr(collect, "collect_positions", _spy_collect_positions)
    monkeypatch.setattr(collect, "attach_research", _spy_attach_research)
    monkeypatch.setattr(collect, "attach_fundamentals", _spy_attach_fundamentals)
    monkeypatch.setattr(collect, "attach_news", _spy_attach_news)

    await build_and_send_report("discovery", "2026-08-13", candidates=[])

    assert not called.get("collect_positions")
    assert not called.get("attach_research")
    assert not called.get("attach_fundamentals")
    assert not called.get("attach_news")
