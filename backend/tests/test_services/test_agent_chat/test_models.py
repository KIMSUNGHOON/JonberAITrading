"""
Tests for Agent Chat Models

Unit tests for data models used in the Agent Group Chat system.
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from services.agent_chat.models import (
    AgentType,
    MessageType,
    SessionStatus,
    VoteType,
    DecisionAction,
    AgentMessage,
    AgentVote,
    ChatRound,
    ChatSession,
    TradeDecision,
    MarketContext,
)


# -------------------------------------------
# AgentMessage Tests
# -------------------------------------------


class TestAgentMessage:
    """Tests for AgentMessage model."""

    def test_create_message_with_defaults(self):
        """Test creating message with minimal required fields."""
        msg = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술적 분석가",
            message_type=MessageType.ANALYSIS,
            content="RSI가 30 이하로 과매도 구간입니다.",
        )

        assert msg.agent_type == AgentType.TECHNICAL
        assert msg.agent_name == "기술적 분석가"
        assert msg.message_type == MessageType.ANALYSIS
        assert msg.content == "RSI가 30 이하로 과매도 구간입니다."
        assert msg.confidence == 0.5  # default
        assert msg.id is not None
        assert msg.timestamp is not None

    def test_create_message_with_all_fields(self):
        """Test creating message with all fields."""
        msg = AgentMessage(
            agent_type=AgentType.FUNDAMENTAL,
            agent_name="펀더멘털 분석가",
            message_type=MessageType.OPINION,
            content="PER이 저평가 상태입니다.",
            confidence=0.85,
            data={"per": 8.5, "pbr": 1.2},
            in_response_to="msg-123",
            mentions=[AgentType.TECHNICAL],
        )

        assert msg.confidence == 0.85
        assert msg.data == {"per": 8.5, "pbr": 1.2}
        assert msg.in_response_to == "msg-123"
        assert AgentType.TECHNICAL in msg.mentions

    def test_confidence_validation(self):
        """Test confidence value validation."""
        # Valid confidence
        msg = AgentMessage(
            agent_type=AgentType.RISK,
            agent_name="리스크 관리자",
            message_type=MessageType.ANALYSIS,
            content="리스크 평가",
            confidence=1.0,
        )
        assert msg.confidence == 1.0

        # Confidence at boundary
        msg2 = AgentMessage(
            agent_type=AgentType.RISK,
            agent_name="리스크 관리자",
            message_type=MessageType.ANALYSIS,
            content="리스크 평가",
            confidence=0.0,
        )
        assert msg2.confidence == 0.0


# -------------------------------------------
# AgentVote Tests
# -------------------------------------------


class TestAgentVote:
    """Tests for AgentVote model."""

    def test_create_vote(self):
        """Test creating a vote."""
        vote = AgentVote(
            agent_type=AgentType.TECHNICAL,
            vote=VoteType.BUY,
            confidence=0.75,
            reasoning="기술적 지표가 매수를 가리킵니다.",
        )

        assert vote.agent_type == AgentType.TECHNICAL
        assert vote.vote == VoteType.BUY
        assert vote.confidence == 0.75
        assert vote.reasoning == "기술적 지표가 매수를 가리킵니다."

    def test_vote_with_key_factors(self):
        """Test vote with key factors."""
        vote = AgentVote(
            agent_type=AgentType.TECHNICAL,
            vote=VoteType.BUY,
            confidence=0.8,
            reasoning="매수 추천",
            key_factors=["RSI 과매도", "MACD 골든크로스"],
        )

        assert len(vote.key_factors) == 2
        assert "RSI 과매도" in vote.key_factors

    def test_vote_with_risk_suggestions(self):
        """Test vote with risk-specific fields."""
        vote = AgentVote(
            agent_type=AgentType.RISK,
            vote=VoteType.BUY,
            confidence=0.7,
            reasoning="리스크 수용 가능",
            suggested_position_pct=5.0,
            suggested_stop_loss_pct=5.0,
            suggested_take_profit_pct=10.0,
        )

        assert vote.suggested_position_pct == 5.0
        assert vote.suggested_stop_loss_pct == 5.0
        assert vote.suggested_take_profit_pct == 10.0


# -------------------------------------------
# ChatRound Tests
# -------------------------------------------


class TestChatRound:
    """Tests for ChatRound model."""

    def test_create_round(self):
        """Test creating a chat round."""
        chat_round = ChatRound(
            round_number=1,
            round_type="analysis",
        )

        assert chat_round.round_number == 1
        assert chat_round.round_type == "analysis"
        assert chat_round.messages == []
        # started_at has a default value
        assert chat_round.started_at is not None
        assert chat_round.ended_at is None

    def test_round_with_messages(self):
        """Test round with messages."""
        msg1 = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술적 분석가",
            message_type=MessageType.ANALYSIS,
            content="분석 내용",
        )

        chat_round = ChatRound(
            round_number=1,
            round_type="analysis",
            messages=[msg1],
        )

        assert len(chat_round.messages) == 1
        assert chat_round.messages[0].agent_type == AgentType.TECHNICAL


# -------------------------------------------
# ChatSession Tests
# -------------------------------------------


class TestChatSession:
    """Tests for ChatSession model."""

    def test_create_session(self):
        """Test creating a chat session."""
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.5,
        )

        session = ChatSession(
            ticker="005930",
            stock_name="삼성전자",
            context=context,
        )

        assert session.ticker == "005930"
        assert session.stock_name == "삼성전자"
        assert session.status == SessionStatus.INITIALIZING
        assert session.rounds == []
        assert session.votes == []
        assert session.consensus_level == 0.0
        assert session.decision is None

    def test_session_add_message(self):
        """Test adding message to session."""
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.5,
        )

        session = ChatSession(
            ticker="005930",
            stock_name="삼성전자",
            context=context,
        )

        # Start a round first
        session.start_round("analysis")

        msg = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술적 분석가",
            message_type=MessageType.ANALYSIS,
            content="분석 결과",
        )

        session.add_message(msg)

        assert len(session.all_messages) == 1
        assert len(session.rounds[-1].messages) == 1

    def test_session_add_vote(self):
        """Test adding vote to session."""
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.5,
        )

        session = ChatSession(
            ticker="005930",
            stock_name="삼성전자",
            context=context,
        )

        vote = AgentVote(
            agent_type=AgentType.TECHNICAL,
            vote=VoteType.BUY,
            confidence=0.8,
            reasoning="매수 추천",
        )

        session.add_vote(vote)

        assert len(session.votes) == 1
        assert session.votes[0].vote == VoteType.BUY

    def test_calculate_consensus_all_buy(self):
        """Test consensus calculation with all BUY votes."""
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.5,
        )

        session = ChatSession(
            ticker="005930",
            stock_name="삼성전자",
            context=context,
        )

        # Add 4 BUY votes
        agents = [
            AgentType.TECHNICAL,
            AgentType.FUNDAMENTAL,
            AgentType.SENTIMENT,
            AgentType.RISK,
        ]

        for agent_type in agents:
            vote = AgentVote(
                agent_type=agent_type,
                vote=VoteType.BUY,
                confidence=0.8,
                reasoning="매수 추천",
            )
            session.add_vote(vote)

        session.calculate_consensus()

        # All BUY with 0.8 confidence = high consensus
        assert session.consensus_level > 0.7

    def test_calculate_consensus_mixed_votes(self):
        """Test consensus calculation with mixed votes."""
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.5,
        )

        session = ChatSession(
            ticker="005930",
            stock_name="삼성전자",
            context=context,
        )

        # Mixed votes
        votes_data = [
            (AgentType.TECHNICAL, VoteType.BUY),
            (AgentType.FUNDAMENTAL, VoteType.BUY),
            (AgentType.SENTIMENT, VoteType.HOLD),
            (AgentType.RISK, VoteType.SELL),
        ]

        for agent_type, vote_type in votes_data:
            vote = AgentVote(
                agent_type=agent_type,
                vote=vote_type,
                confidence=0.7,
                reasoning="분석 결과",
            )
            session.add_vote(vote)

        session.calculate_consensus()

        # Mixed votes = lower consensus
        assert session.consensus_level < 0.7

    def test_session_finalize(self):
        """Test finalizing session with decision."""
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.5,
        )

        session = ChatSession(
            ticker="005930",
            stock_name="삼성전자",
            context=context,
        )

        decision = TradeDecision(
            action=DecisionAction.BUY,
            confidence=0.85,
            consensus_level=0.8,
            entry_price=72500,
            stop_loss=68875,
            take_profit=79750,
            rationale="합의에 의한 매수 결정",
        )

        session.finalize(decision)

        assert session.status == SessionStatus.DECIDED
        assert session.decision == decision
        assert session.ended_at is not None


# -------------------------------------------
# TradeDecision Tests
# -------------------------------------------


class TestTradeDecision:
    """Tests for TradeDecision model."""

    def test_create_decision(self):
        """Test creating a trade decision."""
        decision = TradeDecision(
            action=DecisionAction.BUY,
            confidence=0.85,
            consensus_level=0.8,
            entry_price=72500,
            stop_loss=68875,
            take_profit=79750,
            rationale="강한 기술적 신호와 긍정적 펀더멘털",
        )

        assert decision.action == DecisionAction.BUY
        assert decision.confidence == 0.85
        assert decision.consensus_level == 0.8
        assert decision.entry_price == 72500
        assert decision.stop_loss == 68875
        assert decision.take_profit == 79750

    def test_decision_with_details(self):
        """Test decision with all details."""
        decision = TradeDecision(
            action=DecisionAction.BUY,
            confidence=0.85,
            consensus_level=0.8,
            entry_price=72500,
            stop_loss=68875,
            take_profit=79750,
            quantity=100,
            rationale="합의에 의한 결정",
            key_factors=["RSI 과매도", "PER 저평가", "기관 순매수"],
            dissenting_opinions=["변동성 우려"],
        )

        assert decision.quantity == 100
        assert len(decision.key_factors) == 3
        assert len(decision.dissenting_opinions) == 1


# -------------------------------------------
# MarketContext Tests
# -------------------------------------------


class TestMarketContext:
    """Tests for MarketContext model."""

    def test_create_context_minimal(self):
        """Test creating context with minimal fields."""
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.5,
        )

        assert context.ticker == "005930"
        assert context.stock_name == "삼성전자"
        assert context.current_price == 72500
        assert context.price_change_pct == 0.5

    def test_create_context_full(self):
        """Test creating context with all fields."""
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500,
            price_change_pct=0.69,
            market_cap=432000000000000,
            per=11.5,
            pbr=1.2,
            eps=6304,
        )

        assert context.per == 11.5
        assert context.pbr == 1.2
        assert context.eps == 6304
