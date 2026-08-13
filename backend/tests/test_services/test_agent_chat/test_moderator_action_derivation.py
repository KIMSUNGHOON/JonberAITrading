"""Moderator final-action must come from the structured vote consensus, not a
free-text regex scan (audit C-series, confirmed live on 009150: all-SELL
votes → moderator wrote 'SELL / 신규진입 시 고위험', but _parse_action saw the
substring '진입' and returned BUY — an action inversion).

#1 action derivation, #2 no-execution invariant, #3 sizing-before-gate.
"""
from unittest.mock import MagicMock, patch

from services.agent_chat.agents.moderator_agent import ModeratorAgent
from services.agent_chat.models import (
    ChatSession, MarketContext, AgentVote, AgentType, VoteType, DecisionAction,
)

_EXECUTABLE = {DecisionAction.BUY, DecisionAction.SELL,
               DecisionAction.ADD, DecisionAction.REDUCE}


def _unanimous(vote, has_position, available_cash=None, risk_pct=None):
    ctx = MarketContext(ticker="009150", stock_name="삼성전기",
                        current_price=100000, price_change_pct=-9.0,
                        has_position=has_position, available_cash=available_cash)
    s = ChatSession(ticker="009150", stock_name="삼성전기", context=ctx,
                    consensus_threshold=0.75)
    for at in (AgentType.TECHNICAL, AgentType.FUNDAMENTAL, AgentType.SENTIMENT):
        s.add_vote(AgentVote(agent_type=at, vote=vote, confidence=0.8, reasoning="x"))
    s.add_vote(AgentVote(agent_type=AgentType.RISK, vote=vote, confidence=0.8,
                         reasoning="x", suggested_position_pct=risk_pct))
    s.calculate_consensus()
    return s, ctx


# The exact free-text that fooled the live parser: a SELL decision whose prose
# contains the substring '진입' (in '신규진입 시 고위험' = entry is high-risk).
_BEARISH_TEXT = "결정: SELL. 4개 분석가 전원 매도. 신규진입 시 고위험."


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_bearish_no_position_yields_no_action(_llm):
    session, ctx = _unanimous(VoteType.SELL, has_position=False, risk_pct=0.0)
    assert session.consensus_level >= 0.75  # not overridden by the consensus gate
    decision = ModeratorAgent()._parse_decision(_BEARISH_TEXT, session, ctx)
    assert decision.action == DecisionAction.NO_ACTION  # was BUY (the bug)


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_bearish_no_position_never_reaches_execution(_llm):
    session, ctx = _unanimous(VoteType.SELL, has_position=False, risk_pct=0.0)
    decision = ModeratorAgent()._parse_decision(_BEARISH_TEXT, session, ctx)
    # #2: a bearish no-position decision must not be an executable action.
    assert decision.action not in _EXECUTABLE


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_bullish_no_position_yields_buy(_llm):
    session, ctx = _unanimous(VoteType.BUY, has_position=False,
                              available_cash=10_000_000, risk_pct=10.0)
    decision = ModeratorAgent()._parse_decision("결정: BUY.", session, ctx)
    assert decision.action == DecisionAction.BUY


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_bullish_buy_is_sized_when_risk_supplies_position_pct(_llm):
    # Normal path: risk agent supplies a size -> quantity is computed, so the
    # pre-execution notional gate checks a real notional.
    session, ctx = _unanimous(VoteType.BUY, has_position=False,
                              available_cash=10_000_000, risk_pct=10.0)
    decision = ModeratorAgent()._parse_decision("결정: BUY.", session, ctx)
    assert decision.action == DecisionAction.BUY
    assert decision.quantity is not None and decision.quantity > 0


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_bullish_buy_unsized_stays_none_fail_closed(_llm):
    # #3 is fail-closed BY DESIGN, not a bug: when the risk agent supplies no
    # position size, quantity stays None and the downstream autonomy gate
    # denies the BUY (don't trade blind). Auto-sizing a default here would
    # loosen a live safety control, so it is deliberately NOT done.
    session, ctx = _unanimous(VoteType.BUY, has_position=False,
                              available_cash=10_000_000, risk_pct=None)
    decision = ModeratorAgent()._parse_decision("결정: BUY.", session, ctx)
    assert decision.action == DecisionAction.BUY
    assert decision.quantity is None
