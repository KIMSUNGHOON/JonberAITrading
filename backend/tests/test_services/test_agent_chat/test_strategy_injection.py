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


def test_moderator_with_position_and_no_risk_vote_leaves_stops_none():
    """Final-review Fix1: 보유 포지션 재평가(has_position=True)에서 risk 투표가
    없으면 전략 스탑도 채우지 않는다 — 채우면 합의 미달 시 HOLD 경유로 그
    스탑이 기존 포지션에 재앵커돼 방어가 완화되는 회귀였다. 신규 진입
    (has_position=False, 위 test_moderator_without_risk_vote_fills_stops_from_strategy)
    에서만 전략 폴백을 채운다."""
    moderator = ModeratorAgent()
    ctx = _context(strategy_knobs=dict(KNOBS), has_position=True)
    session = _session([AgentVote(agent_type=AgentType.TECHNICAL, vote=VoteType.BUY,
                                  confidence=0.8, reasoning="r")])
    decision = moderator._parse_decision("보유 (HOLD)", session, ctx)
    assert decision.stop_loss is None
    assert decision.take_profit is None


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
        directive, knobs, consensus_threshold = await coordinator._build_strategy_context()
    assert directive is None and knobs is None
    # E-3: 조회 실패 = 기존 하드코딩 0.75와 동일값(거동 불변) — None이 아니라
    # 항상 구체적 float를 반환해 호출부가 or-폴백 없이 그대로 쓸 수 있다.
    assert consensus_threshold == pytest.approx(0.75)


async def test_build_strategy_context_no_strategy_defaults_to_0_75():
    """E-3 ②: 전략 자체가 부재(get_strategy() -> None)인 경우도 실패 케이스와
    동일하게 0.75 폴백 — 세션 문턱이 하드코딩과 다르게 흔들리지 않는다."""
    from services.agent_chat.coordinator import ChatCoordinator

    trading = MagicMock()
    trading.get_strategy.return_value = None

    coordinator = ChatCoordinator()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        directive, knobs, consensus_threshold = await coordinator._build_strategy_context()
    assert directive is None and knobs is None
    assert consensus_threshold == pytest.approx(0.75)


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
        directive, knobs, consensus_threshold = await coordinator._build_strategy_context()
    assert knobs["stop_loss_pct"] == pytest.approx(6.0)     # 분율→퍼센트
    assert knobs["max_position_pct"] == pytest.approx(8.0)
    assert "테스트 전략" in directive and "6.0%" in directive
    assert consensus_threshold == pytest.approx(0.75)  # 미조정 기본값


async def test_build_strategy_context_clamps_extreme_knobs():
    """Final-review Fix2: 수동 PUT /strategy는 KNOB_BOUNDS를 우회해 Pydantic
    필드 범위(stop_loss_pct 최대 0.50)까지 값을 허용한다 — 이 소비 경로가
    T2(strategy_apply)와 같은 클램프(0.03-0.15)를 적용하는지 확인."""
    from services.agent_chat.coordinator import ChatCoordinator
    from services.trading.strategy import TradingStrategy

    strategy = TradingStrategy(name="극단 전략")
    strategy.exit_conditions.stop_loss_pct = 0.50  # KNOB_BOUNDS hi=0.15
    trading = MagicMock()
    trading.get_strategy.return_value = strategy

    coordinator = ChatCoordinator()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        _, knobs, _ = await coordinator._build_strategy_context()
    assert knobs["stop_loss_pct"] == pytest.approx(15.0)  # 0.15 클램프 × 100


# ---------- E-3: consensus_threshold 전략화 + entry_conditions soft guidance ----------

async def test_build_strategy_context_reflects_active_strategy_consensus_threshold():
    """E-3 ①: 전략 consensus_threshold=0.68 -> 세션 문턱 0.68 (현행 RED은
    하드코딩 0.75 고정이라 이 테스트가 실패했다)."""
    from services.agent_chat.coordinator import ChatCoordinator
    from services.trading.strategy import TradingStrategy

    strategy = TradingStrategy(name="완화 전략")
    strategy.entry_conditions.consensus_threshold = 0.68
    trading = MagicMock()
    trading.get_strategy.return_value = strategy

    coordinator = ChatCoordinator()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        _, _, consensus_threshold = await coordinator._build_strategy_context()
    assert consensus_threshold == pytest.approx(0.68)


async def test_build_strategy_context_consensus_threshold_clamped_to_knob_bounds():
    """E-3 ④: KNOB_BOUNDS[0.60,0.85] 클램프 왕복 — 수동 PUT이 Field 범위
    (0.5-0.9)까지 극단값을 허용해도 이 소비 경로는 더 좁은 안전 레일 안에서만
    세션에 주입한다(stop_loss_pct와 동일 방어 패턴)."""
    from services.agent_chat.coordinator import ChatCoordinator
    from services.trading.strategy import TradingStrategy

    strategy = TradingStrategy(name="극단 전략")
    strategy.entry_conditions.consensus_threshold = 0.9  # Field 상한, KNOB hi=0.85
    trading = MagicMock()
    trading.get_strategy.return_value = strategy

    coordinator = ChatCoordinator()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        _, _, consensus_threshold = await coordinator._build_strategy_context()
    assert consensus_threshold == pytest.approx(0.85)


async def test_build_strategy_context_includes_entry_conditions_soft_guidance_section():
    """E-3 ③: entry_conditions가 "진입 기준(참고)" 섹션으로 프롬프트에
    주입되고, 하드 게이트가 아님을 명시하는 문구를 포함한다 — 값 스냅샷은
    min_technical_score를 포함."""
    from services.agent_chat.coordinator import ChatCoordinator
    from services.trading.strategy import TradingStrategy

    strategy = TradingStrategy(name="기준 전략")
    strategy.entry_conditions.min_technical_score = 63
    trading = MagicMock()
    trading.get_strategy.return_value = strategy

    coordinator = ChatCoordinator()
    with patch("app.dependencies.get_trading_coordinator",
               new=AsyncMock(return_value=trading)):
        directive, _, _ = await coordinator._build_strategy_context()
    assert "진입 기준" in directive
    assert "하드 게이트 아님" in directive
    assert "63" in directive  # min_technical_score 스냅샷
