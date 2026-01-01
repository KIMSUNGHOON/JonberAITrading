"""
Tests for ChatRoom

Unit tests for the ChatRoom class that manages discussion sessions.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from services.agent_chat.models import (
    AgentType,
    MessageType,
    VoteType,
    SessionStatus,
    DecisionAction,
    MarketContext,
    AgentMessage,
    AgentVote,
    TradeDecision,
)
from services.agent_chat.chat_room import ChatRoom


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


@pytest.fixture
def chat_room(mock_market_context):
    """Create a ChatRoom instance for testing."""
    return ChatRoom(
        ticker="005930",
        stock_name="삼성전자",
        context=mock_market_context,
        max_discussion_rounds=2,
        consensus_threshold=0.75,
    )


# -------------------------------------------
# Initialization Tests
# -------------------------------------------


class TestChatRoomInitialization:
    """Tests for ChatRoom initialization."""

    def test_create_chat_room(self, mock_market_context):
        """Test creating a chat room."""
        room = ChatRoom(
            ticker="005930",
            stock_name="삼성전자",
            context=mock_market_context,
        )

        assert room.ticker == "005930"
        assert room.stock_name == "삼성전자"
        assert room.context == mock_market_context
        assert room.session is not None

    def test_chat_room_has_all_agents(self, chat_room):
        """Test that chat room initializes all agents."""
        assert AgentType.TECHNICAL in chat_room.agents
        assert AgentType.FUNDAMENTAL in chat_room.agents
        assert AgentType.SENTIMENT in chat_room.agents
        assert AgentType.RISK in chat_room.agents
        assert AgentType.MODERATOR in chat_room.agents

    def test_discussion_order_excludes_moderator(self, chat_room):
        """Test that discussion order excludes moderator."""
        assert AgentType.MODERATOR not in chat_room.discussion_order
        assert len(chat_room.discussion_order) == 4

    def test_session_initial_status(self, chat_room):
        """Test that session starts in INITIALIZING status."""
        assert chat_room.session.status == SessionStatus.INITIALIZING


# -------------------------------------------
# Callback Tests
# -------------------------------------------


class TestChatRoomCallbacks:
    """Tests for ChatRoom callback functionality."""

    def test_register_message_callback(self, chat_room):
        """Test registering a message callback."""
        callback = MagicMock()
        chat_room.on_message(callback)

        assert callback in chat_room._message_callbacks

    def test_register_status_callback(self, chat_room):
        """Test registering a status callback."""
        callback = MagicMock()
        chat_room.on_status_change(callback)

        assert callback in chat_room._status_callbacks

    @pytest.mark.asyncio
    async def test_emit_message_calls_callbacks(self, chat_room):
        """Test that emit_message calls registered callbacks."""
        sync_callback = MagicMock()
        async_callback = AsyncMock()

        chat_room.on_message(sync_callback)
        chat_room.on_message(async_callback)

        msg = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술적 분석가",
            message_type=MessageType.ANALYSIS,
            content="테스트 메시지",
        )

        await chat_room._emit_message(msg)

        sync_callback.assert_called_once_with(msg)
        async_callback.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_emit_status_calls_callbacks(self, chat_room):
        """Test that emit_status calls registered callbacks."""
        callback = AsyncMock()
        chat_room.on_status_change(callback)

        await chat_room._emit_status(SessionStatus.ANALYZING)

        callback.assert_awaited_once()


# -------------------------------------------
# Session Accessors Tests
# -------------------------------------------


class TestChatRoomAccessors:
    """Tests for ChatRoom accessor methods."""

    def test_get_session(self, chat_room):
        """Test getting current session."""
        session = chat_room.get_session()

        assert session == chat_room.session
        assert session.ticker == "005930"

    def test_get_messages_empty(self, chat_room):
        """Test getting messages from empty session."""
        messages = chat_room.get_messages()

        assert messages == []

    def test_get_decision_none(self, chat_room):
        """Test getting decision when none made."""
        decision = chat_room.get_decision()

        assert decision is None


# -------------------------------------------
# Cancel Tests
# -------------------------------------------


class TestChatRoomCancel:
    """Tests for ChatRoom cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_sets_status(self, chat_room):
        """Test that cancel sets session status to CANCELLED."""
        await chat_room.cancel()

        assert chat_room.session.status == SessionStatus.CANCELLED
        assert chat_room.session.ended_at is not None

    @pytest.mark.asyncio
    async def test_cancel_emits_status(self, chat_room):
        """Test that cancel emits status change."""
        callback = AsyncMock()
        chat_room.on_status_change(callback)

        await chat_room.cancel()

        callback.assert_awaited_once()


# -------------------------------------------
# Integration Tests
# -------------------------------------------


class TestChatRoomIntegration:
    """Integration tests for ChatRoom."""

    @pytest.mark.asyncio
    async def test_full_discussion_flow(self, chat_room):
        """Test full discussion flow from start to decision."""
        # Mock all agent methods
        for agent_type, agent in chat_room.agents.items():
            agent.analyze = AsyncMock(return_value=AgentMessage(
                agent_type=agent_type,
                agent_name=agent.agent_name,
                message_type=MessageType.ANALYSIS,
                content=f"{agent_type.value} 분석 결과",
                confidence=0.8,
            ))

        for agent_type in chat_room.discussion_order:
            agent = chat_room.agents[agent_type]
            agent.respond = AsyncMock(return_value=None)
            agent.vote = AsyncMock(return_value=AgentVote(
                agent_type=agent_type,
                vote=VoteType.BUY,
                confidence=0.8,
                reasoning="매수 추천",
            ))

        moderator = chat_room.agents[AgentType.MODERATOR]
        moderator.summarize_round = AsyncMock(return_value=AgentMessage(
            agent_type=AgentType.MODERATOR,
            agent_name="토론 진행자",
            message_type=MessageType.SUMMARY,
            content="라운드 요약",
        ))
        moderator.announce_voting = AsyncMock(return_value=AgentMessage(
            agent_type=AgentType.MODERATOR,
            agent_name="토론 진행자",
            message_type=MessageType.ANALYSIS,
            content="투표 시작",
        ))
        moderator.make_decision = AsyncMock(return_value=TradeDecision(
            action=DecisionAction.BUY,
            confidence=0.85,
            consensus_level=0.9,
            entry_price=72500,
            stop_loss=68875,
            take_profit=79750,
            rationale="합의에 의한 매수 결정",
        ))
        moderator.announce_decision = AsyncMock(return_value=AgentMessage(
            agent_type=AgentType.MODERATOR,
            agent_name="토론 진행자",
            message_type=MessageType.DECISION,
            content="최종 결정: 매수",
        ))

        # Run the full discussion
        session = await chat_room.start()

        # Verify session completed
        assert session.status == SessionStatus.DECIDED
        assert session.decision is not None
        assert session.decision.action == DecisionAction.BUY
        assert len(session.rounds) >= 1
        assert len(session.votes) == 4
