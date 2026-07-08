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
