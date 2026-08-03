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

    def test_session_consensus_threshold_matches_constructor_arg(self, mock_market_context):
        """E-3: ChatRoom(consensus_threshold=...)가 session.consensus_threshold
        에 그대로 반영된다 — coordinator가 활성 전략 값(예 0.68)을 전달하면
        기존 하드코딩 0.75가 아니라 그 값으로 세션이 생성돼야 한다."""
        room = ChatRoom(
            ticker="005930",
            stock_name="삼성전자",
            context=mock_market_context,
            consensus_threshold=0.68,
        )
        assert room.session.consensus_threshold == pytest.approx(0.68)

    def test_session_consensus_threshold_default_is_0_75(self, mock_market_context):
        """인자 미지정 시 기존 하드코딩과 동일한 기본값 — 배포 직후 거동 불변."""
        room = ChatRoom(
            ticker="005930",
            stock_name="삼성전자",
            context=mock_market_context,
        )
        assert room.session.consensus_threshold == pytest.approx(0.75)


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
# Analysis Round Failure Handling
#
# 2026-08-03 회귀 방지: analyze()가 실패해도 에러 텍스트가 AgentMessage로
# 세션에 쌓이면 안 된다(정상 의견처럼 토론에 흘러들어 가짜 NO_ACTION이 된다).
# 부분 실패는 생존자만으로 계속 진행하고(voting round와 같은 계약), 전원
# 실패면 투표로 넘어가지 않고 예외를 전파한다.
# -------------------------------------------


class TestAnalysisRoundFailureHandling:
    """_run_analysis_round이 agent.analyze() 실패를 다루는 방식."""

    @staticmethod
    def _mock_moderator_opening(chat_room):
        moderator = chat_room.agents[AgentType.MODERATOR]
        moderator.analyze = AsyncMock(return_value=AgentMessage(
            agent_type=AgentType.MODERATOR,
            agent_name="토론 진행자",
            message_type=MessageType.ANALYSIS,
            content="토론을 시작합니다",
        ))
        return moderator

    @pytest.mark.asyncio
    async def test_failed_agent_contributes_no_message(self, chat_room):
        """일부 에이전트만 실패하면: 실패한 에이전트는 메시지를 남기지 않고,
        생존한 에이전트의 분석만으로 라운드가 정상 종료된다(부분 실패는 진행)."""
        self._mock_moderator_opening(chat_room)

        failing = chat_room.agents[AgentType.TECHNICAL]
        failing.analyze = AsyncMock(side_effect=RuntimeError("llm down"))

        for agent_type in (AgentType.FUNDAMENTAL, AgentType.SENTIMENT, AgentType.RISK):
            agent = chat_room.agents[agent_type]
            agent.analyze = AsyncMock(return_value=AgentMessage(
                agent_type=agent_type,
                agent_name=agent.agent_name,
                message_type=MessageType.ANALYSIS,
                content=f"{agent_type.value} 분석 결과",
                confidence=0.8,
            ))

        await chat_room._run_analysis_round()

        contents = [m.content for m in chat_room.session.all_messages]
        # 에러 텍스트가 "정상 의견"으로 세션에 들어가면 안 된다.
        assert not any("분석 중 오류" in c for c in contents)
        # 실패한 에이전트 이름으로 만들어진 메시지가 없어야 한다.
        assert not any(m.agent_type == AgentType.TECHNICAL for m in chat_room.session.all_messages)
        # 모더레이터 오프닝 1개 + 생존한 3개 에이전트 분석만 남는다.
        assert len(chat_room.session.all_messages) == 4

    @pytest.mark.asyncio
    async def test_all_agents_failed_raises_and_skips_voting(self, chat_room):
        """전원 분석 실패면: 투표 라운드로 넘어가지 않고 예외가 전파돼야 한다.
        chat_room.start()가 이를 잡아 세션을 CANCELLED로 표시한다(새 상태값 없음)."""
        self._mock_moderator_opening(chat_room)

        for agent_type in chat_room.discussion_order:
            agent = chat_room.agents[agent_type]
            agent.analyze = AsyncMock(
                side_effect=RuntimeError(f"{agent_type.value} llm down")
            )
            # 투표까지 도달하면 안 된다 — 호출 여부로 검증한다.
            agent.vote = AsyncMock(return_value=AgentVote(
                agent_type=agent_type,
                vote=VoteType.HOLD,
                confidence=0.5,
                reasoning="도달하면 안 됨",
            ))

        with pytest.raises(RuntimeError):
            await chat_room.start()

        assert chat_room.session.status == SessionStatus.CANCELLED
        assert len(chat_room.session.votes) == 0
        for agent_type in chat_room.discussion_order:
            chat_room.agents[agent_type].vote.assert_not_called()


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


# -------------------------------------------
# 토론 단위 사용량 예산 배선 (2026-08-03 최종 리뷰 Finding 3)
# -------------------------------------------


class TestUsageBudgetWiring:
    """`start()`가 토론 1건에 사용량 한도 대기 예산을 걸고 끝나면 반드시 푸는지.

    예산이 걸리지 않으면 라우터는 종전대로 **호출당** 300초를 기다린다 — 토론
    한 번이 LLM을 약 15회 부르므로 한도 지속 시 토론 하나가 한 시간을 넘기고,
    wait=True 경로에서는 그 대기가 PositionManager 감시 루프를 그대로 멈춘다.
    예산을 풀지 못하면 반대로 그 토론이 끝난 뒤의 스캐너·발굴 호출까지 남은
    예산에 묶인다.
    """

    @staticmethod
    def _fake_router(now_value: float):
        router = MagicMock()
        router.now = MagicMock(return_value=now_value)
        return router

    @pytest.mark.asyncio
    async def test_budget_is_set_during_discussion_and_reset_after(self, chat_room):
        from agents.llm import usage_budget

        seen = {}

        moderator = chat_room.agents[AgentType.MODERATOR]

        async def _observing_analyze(_context):
            # 토론 **안쪽**에서 본 예산 — 라우터가 실제로 읽는 그 값이다.
            seen["inside"] = usage_budget.get_deadline()
            raise RuntimeError("여기서 끊는다 — 예산 관측이 목적이다")

        moderator.analyze = AsyncMock(side_effect=_observing_analyze)

        assert usage_budget.get_deadline() is None
        with patch(
            "services.agent_chat.chat_room.get_router",
            return_value=self._fake_router(1000.0),
        ):
            with pytest.raises(RuntimeError):
                await chat_room.start()

        # 라우터와 같은 시계 위의 절대 시각으로 잡혔다(1000 + 300).
        assert seen["inside"] == 1000.0 + usage_budget.USAGE_LIMIT_WAIT_SECONDS
        # 실패로 끝나도 예산은 반드시 풀린다 — 안 그러면 다음 스캐너 호출이
        # 남의 토론 예산에 묶인다.
        assert usage_budget.get_deadline() is None

    @pytest.mark.asyncio
    async def test_budget_reset_on_success_path_too(self, chat_room):
        from agents.llm import usage_budget

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

        with patch(
            "services.agent_chat.chat_room.get_router",
            return_value=self._fake_router(1000.0),
        ):
            session = await chat_room.start()

        assert session.status == SessionStatus.DECIDED
        assert usage_budget.get_deadline() is None
