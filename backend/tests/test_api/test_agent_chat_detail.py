"""Regression: session-detail must not 500 on sessions that have votes.

AgentVote has no `weight`/`weighted_score` fields; `_session_to_detail` used to
read them and raise AttributeError -> HTTP 500. The route now recomputes both
from the domain agent weights.
"""
from services.agent_chat.models import ChatSession, AgentVote, AgentType, VoteType
from app.api.routes.agent_chat import _session_to_detail


def test_session_to_detail_recomputes_vote_weight():
    s = ChatSession(ticker="005930", stock_name="Samsung")
    s.add_vote(AgentVote(agent_type=AgentType.TECHNICAL, vote=VoteType.BUY,
                         confidence=0.8, reasoning="uptrend"))
    detail = _session_to_detail(s)  # BEFORE fix: AttributeError
    vote = detail["votes"][0]
    assert vote["weight"] == 0.25
    assert vote["weighted_score"] == 0.2  # 0.25 * 0.8
