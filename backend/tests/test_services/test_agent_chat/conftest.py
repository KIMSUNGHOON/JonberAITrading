"""
Agent Chat Test Fixtures

Shared fixtures for agent chat tests.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta

from services.agent_chat.models import (
    AgentType,
    MessageType,
    VoteType,
    SessionStatus,
    DecisionAction,
    MarketContext,
    ChatSession,
    TradeDecision,
    AgentMessage,
    AgentVote,
)


# -------------------------------------------
# Market Context Fixtures
# -------------------------------------------


@pytest.fixture
def sample_market_context():
    """Create a sample market context for testing."""
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
def bullish_market_context():
    """Create a bullish market context."""
    return MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=75000,
        price_change_pct=4.17,
        per=11.5,
        pbr=1.2,
        eps=6304,
        indicators={"rsi": 65.0, "macd": 200.0, "macd_signal": 150.0},
    )


@pytest.fixture
def bearish_market_context():
    """Create a bearish market context."""
    return MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=68000,
        price_change_pct=-5.56,
        per=11.5,
        pbr=1.2,
        eps=6304,
        indicators={"rsi": 25.0, "macd": -100.0, "macd_signal": 50.0},
    )


# -------------------------------------------
# Session Fixtures
# -------------------------------------------


@pytest.fixture
def sample_chat_session(sample_market_context):
    """Create a sample chat session."""
    return ChatSession(
        ticker="005930",
        stock_name="삼성전자",
        context=sample_market_context,
    )


@pytest.fixture
def completed_session(sample_market_context):
    """Create a completed session with decision."""
    session = ChatSession(
        ticker="005930",
        stock_name="삼성전자",
        context=sample_market_context,
    )
    session.status = SessionStatus.DECIDED
    session.started_at = datetime.now() - timedelta(minutes=10)
    session.ended_at = datetime.now()
    session.decision = TradeDecision(
        action=DecisionAction.BUY,
        confidence=0.85,
        consensus_level=0.8,
        entry_price=72500,
        stop_loss=68875,
        take_profit=79750,
        rationale="강한 기술적 신호와 긍정적 펀더멘털",
        key_factors=["RSI 과매도", "MACD 골든크로스", "PER 저평가"],
    )
    return session


# -------------------------------------------
# Message Fixtures
# -------------------------------------------


@pytest.fixture
def sample_technical_message():
    """Create a sample technical analysis message."""
    return AgentMessage(
        agent_type=AgentType.TECHNICAL,
        agent_name="기술적 분석가",
        message_type=MessageType.ANALYSIS,
        content="RSI 35로 과매도 구간입니다. MACD 골든크로스 임박.",
        confidence=0.8,
        data={"rsi": 35.0, "macd": 150.0, "signal": "BUY"},
    )


@pytest.fixture
def sample_fundamental_message():
    """Create a sample fundamental analysis message."""
    return AgentMessage(
        agent_type=AgentType.FUNDAMENTAL,
        agent_name="펀더멘털 분석가",
        message_type=MessageType.ANALYSIS,
        content="PER 11.5배로 업종 평균 대비 저평가 상태입니다.",
        confidence=0.75,
        data={"per": 11.5, "pbr": 1.2, "eps": 6304},
    )


@pytest.fixture
def sample_risk_message():
    """Create a sample risk analysis message."""
    return AgentMessage(
        agent_type=AgentType.RISK,
        agent_name="리스크 관리자",
        message_type=MessageType.ANALYSIS,
        content="변동성 중간 수준. 포지션 사이즈 5% 이하 권장.",
        confidence=0.85,
        data={"risk_level": "medium", "position_size": 5.0},
    )


# -------------------------------------------
# Vote Fixtures
# -------------------------------------------


@pytest.fixture
def sample_buy_votes():
    """Create sample BUY votes from all agents."""
    return [
        AgentVote(
            agent_type=AgentType.TECHNICAL,
            vote=VoteType.BUY,
            confidence=0.8,
            reasoning="RSI 과매도, MACD 골든크로스",
        ),
        AgentVote(
            agent_type=AgentType.FUNDAMENTAL,
            vote=VoteType.BUY,
            confidence=0.75,
            reasoning="PER 저평가",
        ),
        AgentVote(
            agent_type=AgentType.SENTIMENT,
            vote=VoteType.BUY,
            confidence=0.7,
            reasoning="긍정적 뉴스",
        ),
        AgentVote(
            agent_type=AgentType.RISK,
            vote=VoteType.BUY,
            confidence=0.8,
            reasoning="리스크 수용 가능",
        ),
    ]


@pytest.fixture
def sample_mixed_votes():
    """Create mixed votes from agents."""
    return [
        AgentVote(
            agent_type=AgentType.TECHNICAL,
            vote=VoteType.BUY,
            confidence=0.8,
            reasoning="기술적 신호 긍정적",
        ),
        AgentVote(
            agent_type=AgentType.FUNDAMENTAL,
            vote=VoteType.HOLD,
            confidence=0.6,
            reasoning="밸류에이션 중립",
        ),
        AgentVote(
            agent_type=AgentType.SENTIMENT,
            vote=VoteType.HOLD,
            confidence=0.5,
            reasoning="시장 불확실성",
        ),
        AgentVote(
            agent_type=AgentType.RISK,
            vote=VoteType.SELL,
            confidence=0.7,
            reasoning="리스크 높음",
        ),
    ]


# -------------------------------------------
# Decision Fixtures
# -------------------------------------------


@pytest.fixture
def sample_buy_decision():
    """Create a sample BUY decision."""
    return TradeDecision(
        action=DecisionAction.BUY,
        confidence=0.85,
        consensus_level=0.8,
        entry_price=72500,
        stop_loss=68875,
        take_profit=79750,
        quantity=100,
        rationale="강한 기술적 신호와 긍정적 펀더멘털",
        key_factors=["RSI 과매도", "PER 저평가", "MACD 골든크로스"],
        dissenting_opinions=[],
    )


@pytest.fixture
def sample_hold_decision():
    """Create a sample HOLD decision."""
    return TradeDecision(
        action=DecisionAction.HOLD,
        confidence=0.6,
        consensus_level=0.5,
        rationale="합의 부족으로 관망",
        key_factors=["기술적 신호 긍정적", "펀더멘털 중립"],
        dissenting_opinions=["리스크 관리자: 매도 추천"],
    )


# -------------------------------------------
# Mock LLM Fixtures
# -------------------------------------------


@pytest.fixture
def mock_llm():
    """Create a mock LLM for agent tests."""
    mock = MagicMock()
    mock.generate = AsyncMock(return_value=MagicMock(
        content="분석 결과입니다."
    ))
    return mock


@pytest.fixture
def mock_llm_buy_signal():
    """Create a mock LLM that returns buy signals."""
    mock = MagicMock()
    mock.generate = AsyncMock(return_value=MagicMock(
        content="투표: BUY\n신뢰도: 80%\n근거: RSI 과매도, MACD 상승 전환"
    ))
    return mock


@pytest.fixture
def mock_llm_sell_signal():
    """Create a mock LLM that returns sell signals."""
    mock = MagicMock()
    mock.generate = AsyncMock(return_value=MagicMock(
        content="투표: SELL\n신뢰도: 75%\n근거: 고점 근접, 리스크 높음"
    ))
    return mock
