"""Phase4 T3: strategy context injection into the tactical debate.

- context assembly is best-effort: a failing trading coordinator never
  blocks the debate (no is_stale promotion)
- agents' effective system prompt carries the directive
- moderator consumes strategy knobs: fallback stops (with and WITHOUT a
  risk vote) + position_pct cap
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent_chat.models import (
    AgentType, AgentVote, ChatSession, MarketContext, VoteType,
)
from services.agent_chat.agents.moderator_agent import ModeratorAgent
from services.agent_chat.agents.technical_agent import TechnicalDiscussionAgent

pytestmark = pytest.mark.asyncio


def _context(**kw):
    return MarketContext(ticker="005930", stock_name="삼성전자",
                         current_price=70000, price_change_pct=1.0, **kw)


def _session(votes, consensus=0.9):
    session = ChatSession(ticker="005930", stock_name="삼성전자")
    session.votes = votes
    session.consensus_level = consensus
    session.consensus_threshold = 0.75
    return session


KNOBS = {"stop_loss_pct": 6.0, "take_profit_pct": 18.0,
         "max_position_pct": 8.0, "min_cash_ratio": 20.0}


# ---------- MarketContext fields ----------

def test_market_context_strategy_fields_default_none():
    ctx = _context()
    assert ctx.strategy_directive is None
    assert ctx.strategy_knobs is None


# ---------- effective system prompt ----------

def test_agent_effective_prompt_without_directive_is_unchanged():
    agent = TechnicalDiscussionAgent()
    assert agent._effective_system_prompt() == agent.system_prompt


def test_agent_effective_prompt_appends_directive():
    agent = TechnicalDiscussionAgent()
    agent.strategy_directive = "방어적 스탠스. 손절 6%."
    combined = agent._effective_system_prompt()
    assert combined.startswith(agent.system_prompt)
    assert "활성 전략 지침" in combined and "방어적 스탠스" in combined


def test_chat_room_distributes_directive_to_all_agents():
    from services.agent_chat.chat_room import ChatRoom

    ctx = _context(strategy_directive="공격적 스탠스")
    room = ChatRoom("005930", "삼성전자", ctx)
    for agent in room.agents.values():
        assert agent.strategy_directive == "공격적 스탠스"


def test_chat_room_without_directive_leaves_agents_clean():
    from services.agent_chat.chat_room import ChatRoom

    room = ChatRoom("005930", "삼성전자", _context())
    for agent in room.agents.values():
        assert agent.strategy_directive is None


# ---------- moderator strategy consumption ----------

def _risk_vote(stop=None, take=None, pos=None):
    return AgentVote(agent_type=AgentType.RISK, vote=VoteType.BUY, confidence=0.8,
                     reasoning="r", suggested_position_pct=pos,
                     suggested_stop_loss_pct=stop, suggested_take_profit_pct=take)


def test_moderator_fallback_stops_use_strategy_knobs():
    moderator = ModeratorAgent()
    ctx = _context(strategy_knobs=dict(KNOBS), available_cash=10_000_000)
    session = _session([_risk_vote(pos=5.0)])  # stop/take 미제안 → 전략 폴백
    decision = moderator._parse_decision("매수 (BUY)", session, ctx)
    assert decision.stop_loss == int(70000 * (1 - 6.0 / 100))
    assert decision.take_profit == int(70000 * (1 + 18.0 / 100))


def test_moderator_without_risk_vote_fills_stops_from_strategy():
    """기존엔 risk_vote 부재 시 스탑 None으로 결정 — 전략이 있으면 채운다."""
    moderator = ModeratorAgent()
    ctx = _context(strategy_knobs=dict(KNOBS))
    session = _session([AgentVote(agent_type=AgentType.TECHNICAL, vote=VoteType.BUY,
                                  confidence=0.8, reasoning="r")])
    decision = moderator._parse_decision("매수 (BUY)", session, ctx)
    assert decision.stop_loss == int(70000 * 0.94)
    assert decision.take_profit == int(70000 * 1.18)


def test_moderator_without_any_strategy_keeps_legacy_behavior():
    moderator = ModeratorAgent()
    ctx = _context(available_cash=10_000_000)
    session = _session([_risk_vote(pos=5.0)])
    decision = moderator._parse_decision("매수 (BUY)", session, ctx)
    assert decision.stop_loss == int(70000 * (1 - 5.0 / 100))    # 기존 5% 폴백
    assert decision.take_profit == int(70000 * (1 + 10.0 / 100)) # 기존 10% 폴백


def test_moderator_caps_position_pct_at_strategy_max():
    moderator = ModeratorAgent()
    ctx = _context(strategy_knobs=dict(KNOBS), available_cash=10_000_000)
    session = _session([_risk_vote(stop=5.0, take=10.0, pos=15.0)])  # 제안 15% > 캡 8%
    decision = moderator._parse_decision("매수 (BUY)", session, ctx)
    assert decision.position_pct == pytest.approx(8.0)
    assert decision.quantity == int(10_000_000 * 0.08 / 70000)


# ---------- context assembly (best-effort) ----------

async def test_build_strategy_context_failure_is_none_not_stale():
    from services.agent_chat.coordinator import ChatCoordinator

    coordinator = ChatCoordinator()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(side_effect=RuntimeError("down"))):
        directive, knobs = await coordinator._build_strategy_context()
    assert directive is None and knobs is None


async def test_build_strategy_context_formats_percent_units():
    from services.agent_chat.coordinator import ChatCoordinator
    from services.trading.strategy import TradingStrategy

    strategy = TradingStrategy(name="테스트 전략")
    strategy.exit_conditions.stop_loss_pct = 0.06
    strategy.position_sizing.max_position_pct = 0.08
    trading = MagicMock()
    trading.get_strategy.return_value = strategy

    coordinator = ChatCoordinator()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        directive, knobs = await coordinator._build_strategy_context()
    assert knobs["stop_loss_pct"] == pytest.approx(6.0)     # 분율→퍼센트
    assert knobs["max_position_pct"] == pytest.approx(8.0)
    assert "테스트 전략" in directive and "6.0%" in directive
