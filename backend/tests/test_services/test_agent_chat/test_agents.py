"""
Tests for Discussion Agents

Unit tests for the discussion agents in the Agent Group Chat system.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services.agent_chat.models import (
    AgentType,
    MessageType,
    VoteType,
    MarketContext,
    AgentMessage,
)
from services.agent_chat.agents import (
    BaseDiscussionAgent,
    TechnicalDiscussionAgent,
    FundamentalDiscussionAgent,
    SentimentDiscussionAgent,
    RiskDiscussionAgent,
    ModeratorAgent,
)


# -------------------------------------------
# Fixtures
# -------------------------------------------


@pytest.fixture
def mock_market_context():
    """Create a mock market context for testing."""
    return MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=72500,
        price_change_pct=0.69,
        per=11.5,
        pbr=1.2,
        eps=6304,
        indicators={"rsi": 35.0, "macd": 150.0, "macd_signal": 120.0},
    )


# -------------------------------------------
# TechnicalDiscussionAgent Tests
# -------------------------------------------


class TestTechnicalDiscussionAgent:
    """Tests for TechnicalDiscussionAgent."""

    def test_agent_initialization(self):
        """Test agent initialization."""
        agent = TechnicalDiscussionAgent()

        assert agent.agent_type == AgentType.TECHNICAL
        assert agent.agent_name == "기술적 분석가"

    @pytest.mark.asyncio
    async def test_analyze_returns_message(self, mock_market_context):
        """Test that analyze returns an AgentMessage."""
        agent = TechnicalDiscussionAgent()

        result = await agent.analyze(mock_market_context)

        assert isinstance(result, AgentMessage)
        assert result.agent_type == AgentType.TECHNICAL
        assert result.message_type == MessageType.ANALYSIS
        assert result.content is not None
        assert 0 <= result.confidence <= 1

    @pytest.mark.asyncio
    async def test_vote_returns_valid_vote(self, mock_market_context):
        """Test that vote returns a valid AgentVote."""
        agent = TechnicalDiscussionAgent()

        result = await agent.vote(mock_market_context, [])

        assert result.agent_type == AgentType.TECHNICAL
        assert result.vote in [
            VoteType.BUY, VoteType.SELL, VoteType.HOLD,
            VoteType.STRONG_BUY, VoteType.STRONG_SELL, VoteType.ABSTAIN,
        ]
        assert 0 <= result.confidence <= 1

    @pytest.mark.asyncio
    async def test_respond_to_message(self, mock_market_context):
        """Test responding to another agent's message."""
        agent = TechnicalDiscussionAgent()

        other_message = AgentMessage(
            agent_type=AgentType.FUNDAMENTAL,
            agent_name="펀더멘털 분석가",
            message_type=MessageType.ANALYSIS,
            content="PER 저평가 상태입니다.",
        )

        result = await agent.respond(other_message, mock_market_context, [])

        # May return None or a message
        assert result is None or isinstance(result, AgentMessage)


# -------------------------------------------
# FundamentalDiscussionAgent Tests
# -------------------------------------------


class TestFundamentalDiscussionAgent:
    """Tests for FundamentalDiscussionAgent."""

    def test_agent_initialization(self):
        """Test agent initialization."""
        agent = FundamentalDiscussionAgent()

        assert agent.agent_type == AgentType.FUNDAMENTAL
        assert agent.agent_name == "펀더멘털 분석가"

    @pytest.mark.asyncio
    async def test_analyze_uses_valuation_data(self, mock_market_context):
        """Test that analyze considers valuation data."""
        agent = FundamentalDiscussionAgent()

        result = await agent.analyze(mock_market_context)

        assert isinstance(result, AgentMessage)
        assert result.agent_type == AgentType.FUNDAMENTAL

    @pytest.mark.asyncio
    async def test_vote_based_on_per(self, mock_market_context):
        """Test voting based on PER."""
        agent = FundamentalDiscussionAgent()

        result = await agent.vote(mock_market_context, [])

        assert result.agent_type == AgentType.FUNDAMENTAL
        assert result.vote in [
            VoteType.BUY, VoteType.SELL, VoteType.HOLD,
            VoteType.STRONG_BUY, VoteType.STRONG_SELL, VoteType.ABSTAIN,
        ]


# -------------------------------------------
# SentimentDiscussionAgent Tests
# -------------------------------------------


class TestSentimentDiscussionAgent:
    """Tests for SentimentDiscussionAgent."""

    def test_agent_initialization(self):
        """Test agent initialization."""
        agent = SentimentDiscussionAgent()

        assert agent.agent_type == AgentType.SENTIMENT
        assert agent.agent_name == "시장심리 분석가"

    @pytest.mark.asyncio
    async def test_analyze_considers_momentum(self, mock_market_context):
        """Test that analyze considers market momentum."""
        agent = SentimentDiscussionAgent()

        result = await agent.analyze(mock_market_context)

        assert isinstance(result, AgentMessage)
        assert result.agent_type == AgentType.SENTIMENT

    @pytest.mark.asyncio
    async def test_vote_returns_valid_vote(self, mock_market_context):
        """Test voting."""
        agent = SentimentDiscussionAgent()

        result = await agent.vote(mock_market_context, [])

        assert result.agent_type == AgentType.SENTIMENT


# -------------------------------------------
# RiskDiscussionAgent Tests
# -------------------------------------------


class TestRiskDiscussionAgent:
    """Tests for RiskDiscussionAgent."""

    def test_agent_initialization(self):
        """Test agent initialization."""
        agent = RiskDiscussionAgent()

        assert agent.agent_type == AgentType.RISK
        assert agent.agent_name == "리스크 관리자"

    @pytest.mark.asyncio
    async def test_analyze_evaluates_risk(self, mock_market_context):
        """Test that analyze evaluates risk factors."""
        agent = RiskDiscussionAgent()

        result = await agent.analyze(mock_market_context)

        assert isinstance(result, AgentMessage)
        assert result.agent_type == AgentType.RISK

    def test_calculate_position_size(self):
        """Test position size calculation based on risk level."""
        agent = RiskDiscussionAgent()

        # High risk = smaller position
        high_risk_size = agent._calculate_position_size("높음")
        assert high_risk_size <= 3.0

        # Low risk = larger position
        low_risk_size = agent._calculate_position_size("낮음")
        assert low_risk_size >= 3.0

    @pytest.mark.asyncio
    async def test_vote_returns_valid_vote(self, mock_market_context):
        """Test that vote returns a valid AgentVote."""
        agent = RiskDiscussionAgent()

        result = await agent.vote(mock_market_context, [])

        assert result.agent_type == AgentType.RISK
        assert result.vote in [
            VoteType.BUY, VoteType.SELL, VoteType.HOLD,
            VoteType.STRONG_BUY, VoteType.STRONG_SELL, VoteType.ABSTAIN,
        ]


# -------------------------------------------
# ModeratorAgent Tests
# -------------------------------------------


class TestModeratorAgent:
    """Tests for ModeratorAgent."""

    def test_agent_initialization(self):
        """Test agent initialization."""
        agent = ModeratorAgent()

        assert agent.agent_type == AgentType.MODERATOR
        assert agent.agent_name == "토론 진행자"

    @pytest.mark.asyncio
    async def test_analyze_opens_discussion(self, mock_market_context):
        """Test that moderator opens the discussion."""
        agent = ModeratorAgent()

        result = await agent.analyze(mock_market_context)

        assert isinstance(result, AgentMessage)
        assert result.agent_type == AgentType.MODERATOR
        assert result.message_type == MessageType.SUMMARY  # Moderator uses SUMMARY type

    @pytest.mark.asyncio
    async def test_summarize_round(self, mock_market_context):
        """Test that moderator summarizes discussion round."""
        agent = ModeratorAgent()

        messages = [
            AgentMessage(
                agent_type=AgentType.TECHNICAL,
                agent_name="기술적 분석가",
                message_type=MessageType.ANALYSIS,
                content="RSI 과매도",
            ),
            AgentMessage(
                agent_type=AgentType.FUNDAMENTAL,
                agent_name="펀더멘털 분석가",
                message_type=MessageType.ANALYSIS,
                content="PER 저평가",
            ),
        ]

        result = await agent.summarize_round(messages, 1)

        assert isinstance(result, AgentMessage)
        assert result.message_type == MessageType.SUMMARY

    @pytest.mark.asyncio
    async def test_announce_voting(self, mock_market_context):
        """Test voting announcement."""
        agent = ModeratorAgent()

        result = await agent.announce_voting(mock_market_context)

        assert isinstance(result, AgentMessage)
        assert result.agent_type == AgentType.MODERATOR

    @pytest.mark.asyncio
    async def test_moderator_vote_raises_error(self, mock_market_context):
        """Test that moderator vote raises NotImplementedError."""
        agent = ModeratorAgent()

        with pytest.raises(NotImplementedError, match="Moderator does not vote"):
            await agent.vote(mock_market_context, [])


# -------------------------------------------
# Agent Respond Tests
# -------------------------------------------


class TestAgentRespond:
    """Tests for agent respond functionality."""

    @pytest.mark.asyncio
    async def test_technical_responds_to_fundamental(self, mock_market_context):
        """Test technical agent responding to fundamental."""
        tech_agent = TechnicalDiscussionAgent()

        fundamental_msg = AgentMessage(
            agent_type=AgentType.FUNDAMENTAL,
            agent_name="펀더멘털 분석가",
            message_type=MessageType.ANALYSIS,
            content="PER이 높아 고평가 상태입니다.",
            confidence=0.7,
        )

        result = await tech_agent.respond(
            fundamental_msg,
            mock_market_context,
            [],
        )

        # Technical agent may or may not respond
        assert result is None or isinstance(result, AgentMessage)
        if result:
            assert result.in_response_to is not None

    @pytest.mark.asyncio
    async def test_risk_responds_to_buy_signal(self, mock_market_context):
        """Test risk agent responding to buy signals."""
        risk_agent = RiskDiscussionAgent()

        buy_msg = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술적 분석가",
            message_type=MessageType.ANALYSIS,
            content="강력한 매수 신호입니다.",
            confidence=0.9,
        )

        result = await risk_agent.respond(
            buy_msg,
            mock_market_context,
            [],
        )

        # Risk agent should provide input on risk
        assert result is None or isinstance(result, AgentMessage)


# -------------------------------------------
# Agent Properties Tests
# -------------------------------------------


class TestAgentProperties:
    """Tests for agent properties."""

    def test_all_agents_have_system_prompt(self):
        """Test that all agents have system prompts."""
        agents = [
            TechnicalDiscussionAgent(),
            FundamentalDiscussionAgent(),
            SentimentDiscussionAgent(),
            RiskDiscussionAgent(),
            ModeratorAgent(),
        ]

        for agent in agents:
            assert agent.system_prompt is not None
            assert len(agent.system_prompt) > 0

    def test_all_agents_have_analysis_prompt(self):
        """Test that all agents have analysis prompt templates."""
        agents = [
            TechnicalDiscussionAgent(),
            FundamentalDiscussionAgent(),
            SentimentDiscussionAgent(),
            RiskDiscussionAgent(),
            ModeratorAgent(),
        ]

        for agent in agents:
            assert agent.analysis_prompt_template is not None
            assert len(agent.analysis_prompt_template) > 0

    def test_all_agents_have_vote_prompt(self):
        """Test that all agents have vote prompt templates."""
        agents = [
            TechnicalDiscussionAgent(),
            FundamentalDiscussionAgent(),
            SentimentDiscussionAgent(),
            RiskDiscussionAgent(),
            ModeratorAgent(),
        ]

        for agent in agents:
            assert agent.vote_prompt_template is not None
            assert len(agent.vote_prompt_template) > 0


# -------------------------------------------
# E-2: Vote Direction Bias Removal (편향 3종 제거)
# -------------------------------------------


class TestRiskPromptSymmetry:
    """E-2 편향①: risk_agent의 일방 하방 지시('보수적으로 판단하세요' 등)를
    손실 리스크/기회비용 양면 평가로 대칭화했는지 스냅샷 검증한다. 리스크
    관리자로서 '다른 분석가의 낙관에 리스크 요인을 제기'하는 악마의 변호인
    역할은 유지되어야 한다(spec P2-D2 — 편향 제거이지 매수 강제가 아님)."""

    ONE_SIDED_PHRASES = [
        "보수적으로 판단하세요",
        "리스크 관점에서 보수적인 의견을 제시합니다",
        "항상 손실 가능성을 고려합니다",
        "하방 리스크를 경계합니다",
    ]
    UPWARD_FORCING_PHRASES = [
        "적극 매수",
        "매수를 적극",
        "공격적으로 매수",
    ]

    def test_system_prompt_has_no_one_sided_downside_directive(self):
        agent = RiskDiscussionAgent()
        for phrase in self.ONE_SIDED_PHRASES:
            assert phrase not in agent.system_prompt, f"일방 하방 지시 잔존: {phrase!r}"

    def test_vote_prompt_has_no_one_sided_downside_directive(self):
        agent = RiskDiscussionAgent()
        for phrase in self.ONE_SIDED_PHRASES:
            assert phrase not in agent.vote_prompt_template, f"일방 하방 지시 잔존: {phrase!r}"

    def test_prompts_contain_dual_sided_evaluation_phrase(self):
        agent = RiskDiscussionAgent()
        assert "기회비용" in agent.system_prompt
        assert "기회비용" in agent.vote_prompt_template
        assert "양면" in agent.system_prompt or "양면" in agent.vote_prompt_template

    def test_prompts_have_no_upward_forcing_phrase(self):
        """편향 제거 != 매수 강제 (spec P2-D2) — 상방 편향 문구 삽입 금지."""
        agent = RiskDiscussionAgent()
        combined = "\n".join([
            agent.system_prompt,
            agent.analysis_prompt_template,
            agent.response_prompt_template,
            agent.vote_prompt_template,
        ])
        for phrase in self.UPWARD_FORCING_PHRASES:
            assert phrase not in combined, f"상방 강제 문구 유입: {phrase!r}"

    def test_devils_advocate_role_preserved(self):
        """리스크 관리 역할 자체는 유지 — 낙관적 전망에 리스크 요인을
        제기하는 문구는 남아 있어야 한다(spec E-2 ①)."""
        agent = RiskDiscussionAgent()
        assert "다른 분석가의 낙관적 전망에 리스크 요인을 제기합니다" in agent.system_prompt


class TestSentimentMomentumRelabelRemoved:
    """E-2 편향②: sentiment_agent의 momentum 재라벨(technical과 등락률
    메아리)이 제거됐는지 확인. price_change_pct는 프롬프트에 별도 필드로
    이미 노출되므로 message.data의 momentum 키는 중복이었다."""

    @pytest.mark.asyncio
    async def test_analyze_message_data_has_no_momentum_key(self, mock_market_context):
        agent = SentimentDiscussionAgent()
        # 실 네트워크/실 LLM 금지 — analyze()가 내부적으로 호출하는
        # self.llm.generate만 목 처리(에이전트 로직 자체는 실행).
        agent.llm.generate = AsyncMock(return_value="분석 결과: 중립적 심리")

        result = await agent.analyze(mock_market_context)

        assert result.data is not None
        assert "momentum" not in result.data

    def test_no_momentum_relabel_source_in_module(self):
        """정적 확인: sentiment_agent.py 소스에 momentum 재라벨 딕셔너리
        키가 잔존하지 않는지(소비처 grep 잔존 0)."""
        import inspect
        import services.agent_chat.agents.sentiment_agent as sentiment_module

        source = inspect.getsource(sentiment_module)
        assert '"momentum"' not in source
