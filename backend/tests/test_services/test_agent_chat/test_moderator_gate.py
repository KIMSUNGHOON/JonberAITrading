"""A sub-threshold (50/50) consensus must be forced to HOLD/NO_ACTION.

consensus_threshold (0.75) previously had no comparison site, so a split vote
still traded. The moderator now gates the action below threshold.
"""
from unittest.mock import MagicMock, patch

from services.agent_chat.agents.moderator_agent import ModeratorAgent
from services.agent_chat.models import (
    ChatSession, MarketContext, AgentVote, AgentType, VoteType, DecisionAction,
)


def _split_5050_session(has_position):
    ctx = MarketContext(ticker="005930", stock_name="삼성전자",
                        current_price=72500, price_change_pct=0.0,
                        has_position=has_position)
    s = ChatSession(ticker="005930", stock_name="삼성전자", context=ctx,
                    consensus_threshold=0.75)
    s.add_vote(AgentVote(agent_type=AgentType.TECHNICAL,   vote=VoteType.BUY,  confidence=0.8, reasoning="x"))
    s.add_vote(AgentVote(agent_type=AgentType.FUNDAMENTAL, vote=VoteType.BUY,  confidence=0.8, reasoning="x"))
    s.add_vote(AgentVote(agent_type=AgentType.SENTIMENT,   vote=VoteType.SELL, confidence=0.8, reasoning="x"))
    s.add_vote(AgentVote(agent_type=AgentType.RISK,        vote=VoteType.SELL, confidence=0.8, reasoning="x"))
    s.calculate_consensus()  # sets consensus_level = 0.5
    return s, ctx


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_5050_forces_no_action_when_flat(_llm):
    session, ctx = _split_5050_session(has_position=False)
    assert session.consensus_level == 0.5
    decision = ModeratorAgent()._parse_decision("최종 결정: 매수 (BUY)", session, ctx)
    assert decision.action == DecisionAction.NO_ACTION


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_5050_forces_hold_when_holding(_llm):
    session, ctx = _split_5050_session(has_position=True)
    decision = ModeratorAgent()._parse_decision("최종 결정: 매수", session, ctx)
    assert decision.action == DecisionAction.HOLD
