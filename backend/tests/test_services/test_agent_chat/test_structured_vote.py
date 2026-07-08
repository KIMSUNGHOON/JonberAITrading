from unittest.mock import AsyncMock, MagicMock, patch

from services.agent_chat.vote_schema import VOTE_SCHEMA, RISK_VOTE_SCHEMA


def test_schemas_shape():
    assert VOTE_SCHEMA["properties"]["vote"]["enum"] == [
        "strong_buy", "buy", "hold", "sell", "strong_sell", "abstain",
    ]
    assert "reasoning" in VOTE_SCHEMA["properties"]
    for f in ("suggested_position_pct", "suggested_stop_loss_pct", "suggested_take_profit_pct"):
        assert f in RISK_VOTE_SCHEMA["properties"]


@patch("services.agent_chat.agents.base_agent.get_llm_provider")
async def test_structured_vote_returns_dict_on_success(mock_get):
    provider = MagicMock()
    provider.generate_structured = AsyncMock(return_value={"vote": "buy", "confidence": 0.8})
    mock_get.return_value = provider
    from services.agent_chat.agents.technical_agent import TechnicalDiscussionAgent
    agent = TechnicalDiscussionAgent()
    result = await agent._structured_vote([], schema=VOTE_SCHEMA)
    assert result == {"vote": "buy", "confidence": 0.8}


@patch("services.agent_chat.agents.base_agent.get_llm_provider")
async def test_structured_vote_returns_none_on_valueerror(mock_get):
    provider = MagicMock()
    provider.generate_structured = AsyncMock(side_effect=ValueError("bad json"))
    mock_get.return_value = provider
    from services.agent_chat.agents.technical_agent import TechnicalDiscussionAgent
    agent = TechnicalDiscussionAgent()
    result = await agent._structured_vote([], schema=VOTE_SCHEMA)
    assert result is None


import pytest
from services.agent_chat.models import MarketContext, VoteType


def _ctx():
    return MarketContext(ticker="005930", stock_name="삼성전자",
                         current_price=72500.0, price_change_pct=0.5,
                         news_sentiment="긍정", news_count=5)


ANALYSTS = [
    ("services.agent_chat.agents.technical_agent", "TechnicalDiscussionAgent"),
    ("services.agent_chat.agents.fundamental_agent", "FundamentalDiscussionAgent"),
    ("services.agent_chat.agents.sentiment_agent", "SentimentDiscussionAgent"),
]


@pytest.mark.parametrize("module,cls", ANALYSTS)
@patch("services.agent_chat.agents.base_agent.get_llm_provider")
async def test_analyst_vote_uses_structured(mock_get, module, cls):
    import importlib
    provider = MagicMock()
    provider.generate_structured = AsyncMock(
        return_value={"vote": "buy", "confidence": 0.82, "reasoning": "R", "key_factors": ["f1"]})
    provider.generate = AsyncMock(return_value="should-not-be-used")
    mock_get.return_value = provider
    agent = getattr(importlib.import_module(module), cls)()
    vote = await agent.vote(_ctx(), [])
    assert vote.vote == VoteType.BUY          # structured, not silent ABSTAIN
    assert vote.confidence == 0.82
    assert vote.key_factors == ["f1"]


@pytest.mark.parametrize("module,cls", ANALYSTS)
@patch("services.agent_chat.agents.base_agent.get_llm_provider")
async def test_analyst_vote_falls_back_to_regex(mock_get, module, cls):
    import importlib
    provider = MagicMock()
    provider.generate_structured = AsyncMock(side_effect=ValueError("bad"))
    provider.generate = AsyncMock(return_value="최종 판단: 매수 (BUY), 신뢰도: 70%")
    mock_get.return_value = provider
    agent = getattr(importlib.import_module(module), cls)()
    vote = await agent.vote(_ctx(), [])
    assert vote.vote == VoteType.BUY          # regex fallback still works


@patch("services.agent_chat.agents.base_agent.get_llm_provider")
async def test_sentiment_structured_caps_confidence_without_news(mock_get):
    provider = MagicMock()
    provider.generate_structured = AsyncMock(return_value={"vote": "buy", "confidence": 0.9})
    mock_get.return_value = provider
    from services.agent_chat.agents.sentiment_agent import SentimentDiscussionAgent
    ctx_no_news = MarketContext(ticker="005930", stock_name="삼성전자",
                                current_price=72500.0, price_change_pct=0.5)  # no news
    vote = await SentimentDiscussionAgent().vote(ctx_no_news, [])
    assert vote.confidence == 0.5  # structured confidence 0.9 capped to 0.5 (no news)


@patch("services.agent_chat.agents.base_agent.get_llm_provider")
async def test_risk_vote_uses_structured_with_risk_fields(mock_get):
    provider = MagicMock()
    provider.generate_structured = AsyncMock(return_value={
        "vote": "hold", "confidence": 0.6, "reasoning": "R", "key_factors": ["k"],
        "suggested_position_pct": 4.0, "suggested_stop_loss_pct": 5.0,
        "suggested_take_profit_pct": 9.0,
    })
    provider.generate = AsyncMock(return_value="unused")
    mock_get.return_value = provider
    from services.agent_chat.agents.risk_agent import RiskDiscussionAgent
    vote = await RiskDiscussionAgent().vote(_ctx(), [])
    assert vote.vote == VoteType.HOLD
    assert vote.suggested_position_pct == 4.0
    assert vote.suggested_stop_loss_pct == 5.0
    assert vote.suggested_take_profit_pct == 9.0


@patch("services.agent_chat.agents.base_agent.get_llm_provider")
async def test_risk_vote_falls_back_to_regex(mock_get):
    provider = MagicMock()
    provider.generate_structured = AsyncMock(side_effect=ValueError("bad"))
    provider.generate = AsyncMock(return_value="위험도 판단: 보유 (HOLD), 신뢰도: 60%")
    mock_get.return_value = provider
    from services.agent_chat.agents.risk_agent import RiskDiscussionAgent
    vote = await RiskDiscussionAgent().vote(_ctx(), [])
    assert vote.vote == VoteType.HOLD
    assert vote.suggested_position_pct is not None  # _calculate_* fallback populated it
