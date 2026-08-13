"""보유 종목에 그날의 4에이전트 리서치를 붙인다."""
import json
import pytest
from unittest.mock import AsyncMock

from services.reports.collect import attach_research
from services.reports.models import PositionResearch

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _pos(ticker="028670") -> PositionResearch:
    return PositionResearch(
        ticker=ticker, name="팬오션", quantity=3115, avg_price=5969.0,
        current_price=5710.0, pnl_pct=-5.13, stop_loss=5520.0,
        stop_loss_source="coordinator",
    )


def _storage(decisions, votes):
    s = AsyncMock()
    s.get_ticker_day_decisions_full = AsyncMock(return_value=decisions)
    s.get_agent_chat_votes = AsyncMock(return_value=votes)
    return s


@pytest.mark.asyncio
async def test_attaches_latest_decision_and_votes():
    decisions = [
        {"id": "d1", "action": "HOLD", "consensus_level": 0.70,
         "behavioral_signals": None, "news_count": 10, "news_sentiment": "neutral"},
        {"id": "d2", "action": "HOLD", "consensus_level": 0.7425,
         "behavioral_signals": json.dumps({"rsi": 57.19, "volume_ratio": 0.6,
                                           "trend": "bullish", "cross": "none"}),
         "news_count": 50, "news_sentiment": "neutral"},
    ]
    votes = [
        {"agent_type": "technical", "vote": "hold", "confidence": 0.58,
         "reasoning": "정배열 유지" * 40,
         "key_factors": json.dumps(["가격이 20·60일선 위에서 정배열"])},
        {"agent_type": "fundamental", "vote": "buy", "confidence": 0.62,
         "reasoning": "저평가", "key_factors": json.dumps(["PER 10.11배 저평가"])},
    ]
    p = _pos()
    await attach_research([p], "2026-08-13", _storage(decisions, votes))

    assert p.discussion_count == 2
    assert p.action == "HOLD"                 # 최신(d2) 기준
    assert round(p.consensus, 4) == 0.7425
    assert p.signals["rsi"] == 57.19
    assert [v.agent_type for v in p.votes] == ["technical", "fundamental"]
    assert p.votes[0].headline == "가격이 20·60일선 위에서 정배열"   # key_factors 우선
    assert p.votes[1].is_dissent is True       # buy != HOLD
    assert p.dissent_count == 1


@pytest.mark.asyncio
async def test_headline_falls_back_to_truncated_reasoning():
    votes = [{"agent_type": "risk", "vote": "hold", "confidence": 0.62,
              "reasoning": "가" * 300, "key_factors": None}]
    p = _pos()
    await attach_research(
        [p], "2026-08-13",
        _storage([{"id": "d1", "action": "HOLD", "consensus_level": 0.9,
                   "behavioral_signals": None}], votes),
    )
    assert len(p.votes[0].headline) == 121      # 120자 + '…'
    assert p.votes[0].headline.endswith("…")


@pytest.mark.asyncio
async def test_no_decisions_leaves_position_intact():
    """신규 편입 종목의 정상 상태 — 빈 카드가 되어야지 예외가 되면 안 된다."""
    p = _pos()
    await attach_research([p], "2026-08-13", _storage([], []))
    assert p.discussion_count == 0
    assert p.action is None
    assert p.votes == []


@pytest.mark.asyncio
async def test_storage_error_does_not_raise():
    s = AsyncMock()
    s.get_ticker_day_decisions_full = AsyncMock(side_effect=RuntimeError("db down"))
    p = _pos()
    await attach_research([p], "2026-08-13", s)     # 예외가 나면 실패
    assert p.discussion_count == 0


@pytest.mark.asyncio
async def test_malformed_behavioral_signals_is_ignored():
    p = _pos()
    await attach_research(
        [p], "2026-08-13",
        _storage([{"id": "d1", "action": "HOLD", "consensus_level": 0.9,
                   "behavioral_signals": "not json"}], []),
    )
    assert p.signals == {}
