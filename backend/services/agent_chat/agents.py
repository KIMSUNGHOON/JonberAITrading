"""
Discussion Agents

Specialized AI agents for trading discussion and analysis.
Each agent has a unique perspective and expertise area.
"""

import re
from abc import ABC, abstractmethod
from typing import List, Optional

import structlog

from services.agent_chat.models import (
    AgentMessage,
    AgentType,
    AgentVote,
    ChatSession,
    DecisionAction,
    MarketContext,
    MessageType,
    TradeDecision,
    VoteType,
)

logger = structlog.get_logger()


# -------------------------------------------
# Base Agent
# -------------------------------------------


class BaseDiscussionAgent(ABC):
    """
    Base class for discussion agents.

    Each agent provides analysis from their specialized perspective.
    """

    agent_type: AgentType
    agent_name: str
    weight: float = 0.25  # Default voting weight

    def __init__(self):
        self.llm = None  # LLM provider (set during initialization)

    @abstractmethod
    async def analyze(self, context: MarketContext) -> AgentMessage:
        """
        Provide initial analysis of the market context.

        Args:
            context: Market data and context

        Returns:
            AgentMessage with analysis
        """
        pass

    @abstractmethod
    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """
        Cast a vote on the trading decision.

        Args:
            context: Market data and context
            chat_history: Previous messages in the discussion

        Returns:
            AgentVote with decision
        """
        pass

    async def respond(
        self,
        message: AgentMessage,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> Optional[AgentMessage]:
        """
        Respond to another agent's message (optional).

        Args:
            message: Message to respond to
            context: Market context
            chat_history: Full chat history

        Returns:
            Response message or None if no response needed
        """
        return None

    def _create_message(
        self,
        message_type: MessageType,
        content: str,
        confidence: float = 0.5,
        data: dict = None,
        in_response_to: str = None,
    ) -> AgentMessage:
        """Create a formatted agent message."""
        return AgentMessage(
            agent_type=self.agent_type,
            agent_name=self.agent_name,
            message_type=message_type,
            content=content,
            confidence=confidence,
            data=data,
            in_response_to=in_response_to,
        )

    def _parse_vote_from_text(self, text: str) -> tuple[VoteType, float]:
        """
        Parse vote and confidence from LLM response text.

        Args:
            text: LLM response text

        Returns:
            Tuple of (VoteType, confidence)
        """
        text_lower = text.lower()

        # Determine vote type
        if "strong_buy" in text_lower or "강력 매수" in text:
            vote = VoteType.STRONG_BUY
        elif "strong_sell" in text_lower or "강력 매도" in text:
            vote = VoteType.STRONG_SELL
        elif "buy" in text_lower or "매수" in text:
            vote = VoteType.BUY
        elif "sell" in text_lower or "매도" in text:
            vote = VoteType.SELL
        elif "hold" in text_lower or "보유" in text or "관망" in text:
            vote = VoteType.HOLD
        else:
            vote = VoteType.ABSTAIN

        # Parse confidence
        confidence = 0.5
        confidence_match = re.search(r'(\d+)%', text)
        if confidence_match:
            confidence = int(confidence_match.group(1)) / 100.0
            confidence = max(0.0, min(1.0, confidence))

        return vote, confidence


# -------------------------------------------
# Technical Analysis Agent
# -------------------------------------------


class TechnicalDiscussionAgent(BaseDiscussionAgent):
    """
    Technical analysis specialist.

    Focuses on price patterns, technical indicators, and chart analysis.
    """

    agent_type = AgentType.TECHNICAL
    agent_name = "기술적 분석가"
    weight = 0.25

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Analyze technical indicators and price patterns."""
        # In a real implementation, this would use an LLM
        indicators = context.indicators or {}

        analysis = f"{context.stock_name}({context.ticker}) 기술적 분석:\n"

        if context.per:
            analysis += f"- 현재가: {context.current_price:,.0f}원\n"

        if indicators.get("rsi"):
            rsi = indicators["rsi"]
            if rsi < 30:
                analysis += f"- RSI {rsi:.1f}: 과매도 구간 (매수 신호)\n"
            elif rsi > 70:
                analysis += f"- RSI {rsi:.1f}: 과매수 구간 (주의 필요)\n"
            else:
                analysis += f"- RSI {rsi:.1f}: 중립\n"

        # Determine confidence based on indicator clarity
        confidence = 0.7

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=analysis,
            confidence=confidence,
            data={"indicators": indicators},
        )

    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """Vote based on technical analysis."""
        indicators = context.indicators or {}

        # Simple rule-based voting for now
        rsi = indicators.get("rsi", 50)

        if rsi < 30:
            vote = VoteType.BUY
            confidence = 0.8
            reasoning = "RSI 과매도 구간으로 반등 가능성 높음"
        elif rsi > 70:
            vote = VoteType.SELL
            confidence = 0.7
            reasoning = "RSI 과매수 구간으로 조정 가능성"
        else:
            vote = VoteType.HOLD
            confidence = 0.5
            reasoning = "기술적 지표 중립"

        return AgentVote(
            agent_type=self.agent_type,
            vote=vote,
            confidence=confidence,
            reasoning=reasoning,
            key_factors=["RSI", "이동평균선", "거래량"],
        )

    async def respond(
        self,
        message: AgentMessage,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> Optional[AgentMessage]:
        """Respond to other agents from technical perspective."""
        # Only respond to certain message types
        if message.message_type not in [MessageType.ANALYSIS, MessageType.OPINION]:
            return None

        # Technical perspective on other agents' points
        response = f"{message.agent_name}의 의견에 대해: "
        response += "기술적 관점에서도 검토가 필요합니다."

        return self._create_message(
            message_type=MessageType.OPINION,
            content=response,
            confidence=0.6,
            in_response_to=message.id,
        )


# -------------------------------------------
# Fundamental Analysis Agent
# -------------------------------------------


class FundamentalDiscussionAgent(BaseDiscussionAgent):
    """
    Fundamental analysis specialist.

    Focuses on financial statements, valuations, and business metrics.
    """

    agent_type = AgentType.FUNDAMENTAL
    agent_name = "펀더멘털 분석가"
    weight = 0.25

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Analyze fundamental metrics and valuation."""
        analysis = f"{context.stock_name} 펀더멘털 분석:\n"

        if context.per:
            if context.per < 10:
                analysis += f"- PER {context.per:.1f}배: 저평가 상태\n"
            elif context.per > 30:
                analysis += f"- PER {context.per:.1f}배: 고평가 가능성\n"
            else:
                analysis += f"- PER {context.per:.1f}배: 적정 수준\n"

        if context.pbr:
            if context.pbr < 1.0:
                analysis += f"- PBR {context.pbr:.2f}배: 자산가치 대비 저평가\n"
            else:
                analysis += f"- PBR {context.pbr:.2f}배\n"

        confidence = 0.75

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=analysis,
            confidence=confidence,
            data={"per": context.per, "pbr": context.pbr, "eps": context.eps},
        )

    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """Vote based on fundamental analysis."""
        per = context.per or 15
        pbr = context.pbr or 1.0

        if per < 10 and pbr < 1.0:
            vote = VoteType.BUY
            confidence = 0.85
            reasoning = "PER, PBR 모두 저평가 상태로 매수 추천"
        elif per < 12:
            vote = VoteType.BUY
            confidence = 0.7
            reasoning = "PER 기준 저평가"
        elif per > 25:
            vote = VoteType.SELL
            confidence = 0.65
            reasoning = "PER 고평가 구간"
        else:
            vote = VoteType.HOLD
            confidence = 0.5
            reasoning = "밸류에이션 중립"

        return AgentVote(
            agent_type=self.agent_type,
            vote=vote,
            confidence=confidence,
            reasoning=reasoning,
            key_factors=["PER", "PBR", "EPS"],
        )


# -------------------------------------------
# Sentiment Analysis Agent
# -------------------------------------------


class SentimentDiscussionAgent(BaseDiscussionAgent):
    """
    Market sentiment specialist.

    Focuses on news, social media, and market psychology.
    """

    agent_type = AgentType.SENTIMENT
    agent_name = "시장 심리 분석가"
    weight = 0.20

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Analyze market sentiment and news."""
        analysis = f"{context.stock_name} 시장 심리 분석:\n"

        if context.news_sentiment:
            analysis += f"- 뉴스 심리: {context.news_sentiment}\n"

        if context.news_count:
            analysis += f"- 최근 뉴스 수: {context.news_count}건\n"

        # Analyze price change for momentum
        if context.price_change_pct > 3:
            analysis += "- 강한 상승 모멘텀\n"
        elif context.price_change_pct < -3:
            analysis += "- 하락 압력 존재\n"

        confidence = 0.6

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=analysis,
            confidence=confidence,
            data={"sentiment": context.news_sentiment},
        )

    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """Vote based on sentiment analysis."""
        sentiment = context.news_sentiment or "neutral"

        if sentiment.lower() in ["positive", "긍정적"]:
            vote = VoteType.BUY
            confidence = 0.7
            reasoning = "시장 심리 긍정적"
        elif sentiment.lower() in ["negative", "부정적"]:
            vote = VoteType.SELL
            confidence = 0.65
            reasoning = "시장 심리 부정적"
        else:
            vote = VoteType.HOLD
            confidence = 0.5
            reasoning = "시장 심리 중립"

        return AgentVote(
            agent_type=self.agent_type,
            vote=vote,
            confidence=confidence,
            reasoning=reasoning,
            key_factors=["뉴스 심리", "거래량", "모멘텀"],
        )


# -------------------------------------------
# Risk Management Agent
# -------------------------------------------


class RiskDiscussionAgent(BaseDiscussionAgent):
    """
    Risk management specialist.

    Focuses on risk evaluation, position sizing, and stop-loss levels.
    """

    agent_type = AgentType.RISK
    agent_name = "리스크 관리자"
    weight = 0.30

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Analyze risk factors."""
        analysis = f"{context.stock_name} 리스크 분석:\n"

        # Position exposure check
        if context.current_sector_exposure:
            if context.current_sector_exposure > 30:
                analysis += f"- 섹터 집중도 {context.current_sector_exposure:.1f}%: 높음 (분산 필요)\n"
            else:
                analysis += f"- 섹터 집중도 {context.current_sector_exposure:.1f}%: 적정\n"

        # Existing position check
        if context.has_position:
            analysis += f"- 기존 보유량: {context.position_quantity}주\n"
            if context.position_pnl_pct:
                analysis += f"- 평가손익: {context.position_pnl_pct:+.2f}%\n"

        # Position sizing recommendation
        position_size = self._calculate_position_size("중간")
        analysis += f"- 권장 포지션 사이즈: 포트폴리오의 {position_size}% 이하\n"

        confidence = 0.8

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=analysis,
            confidence=confidence,
            data={"risk_level": "중간", "suggested_size": position_size},
        )

    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """Vote from risk management perspective."""
        # Check for high risk factors
        high_risk = False

        if context.current_sector_exposure and context.current_sector_exposure > 40:
            high_risk = True

        if context.has_position and context.position_pnl_pct and context.position_pnl_pct < -10:
            high_risk = True

        if high_risk:
            vote = VoteType.HOLD
            confidence = 0.75
            reasoning = "리스크 요인 존재, 신중한 접근 필요"
        else:
            vote = VoteType.BUY
            confidence = 0.6
            reasoning = "리스크 수용 가능 범위"

        return AgentVote(
            agent_type=self.agent_type,
            vote=vote,
            confidence=confidence,
            reasoning=reasoning,
            key_factors=["포지션 사이즈", "손절선", "섹터 비중"],
            suggested_position_pct=self._calculate_position_size("중간"),
            suggested_stop_loss_pct=5.0,
            suggested_take_profit_pct=10.0,
        )

    def _calculate_position_size(self, risk_level: str) -> float:
        """Calculate suggested position size based on risk level."""
        sizes = {
            "높음": 2.0,
            "중간": 5.0,
            "낮음": 8.0,
        }
        return sizes.get(risk_level, 5.0)


# -------------------------------------------
# Moderator Agent
# -------------------------------------------


class ModeratorAgent(BaseDiscussionAgent):
    """
    Discussion moderator.

    Facilitates discussion and makes final trading decision.
    """

    agent_type = AgentType.MODERATOR
    agent_name = "토론 진행자"
    weight = 0.0  # Moderator doesn't vote

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Open the discussion with context summary."""
        opening = f"## {context.stock_name}({context.ticker}) 분석 토론을 시작합니다.\n\n"
        opening += f"현재가: {context.current_price:,.0f}원 ({context.price_change_pct:+.2f}%)\n"
        opening += "\n각 분석가의 의견을 듣겠습니다.\n"

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=opening,
            confidence=1.0,
        )

    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """Moderator doesn't vote."""
        return AgentVote(
            agent_type=self.agent_type,
            vote=VoteType.ABSTAIN,
            confidence=0.0,
            reasoning="진행자는 투표에 참여하지 않습니다.",
        )

    async def summarize_round(
        self,
        messages: List[AgentMessage],
        round_number: int,
    ) -> AgentMessage:
        """Summarize a discussion round."""
        summary = f"## {round_number}라운드 요약\n\n"

        for msg in messages:
            if msg.agent_type != AgentType.MODERATOR:
                summary += f"- {msg.agent_name}: {msg.content[:100]}...\n"

        return self._create_message(
            message_type=MessageType.SUMMARY,
            content=summary,
            confidence=1.0,
        )

    async def announce_voting(self, context: MarketContext) -> AgentMessage:
        """Announce the start of voting."""
        announcement = "## 투표를 시작합니다.\n\n"
        announcement += "각 분석가는 매수/매도/보유 중 하나를 선택하고 "
        announcement += "신뢰도와 근거를 제시해 주세요.\n"

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=announcement,
            confidence=1.0,
        )

    async def make_decision(
        self,
        session: ChatSession,
        context: MarketContext,
    ) -> TradeDecision:
        """Make final trading decision based on votes."""
        # Get majority direction
        majority = session.get_majority_direction()
        consensus = session.consensus_level

        # Convert vote to action
        has_position = context.has_position

        if majority in (VoteType.STRONG_BUY, VoteType.BUY):
            action = DecisionAction.ADD if has_position else DecisionAction.BUY
            entry_price = context.current_price
            stop_loss = entry_price * 0.95
            take_profit = entry_price * 1.10
        elif majority in (VoteType.STRONG_SELL, VoteType.SELL):
            action = DecisionAction.SELL if has_position else DecisionAction.NO_ACTION
            entry_price = None
            stop_loss = None
            take_profit = None
        else:
            action = DecisionAction.HOLD if has_position else DecisionAction.WATCH
            entry_price = None
            stop_loss = None
            take_profit = None

        # Collect key factors and dissenting opinions
        key_factors = []
        dissenting = []
        votes_dict = {}

        for vote in session.votes:
            if vote.agent_type == AgentType.MODERATOR:
                continue

            votes_dict[vote.agent_type.value] = vote.vote.value
            key_factors.extend(vote.key_factors[:2])

            # Check for dissent
            if majority in (VoteType.STRONG_BUY, VoteType.BUY):
                if vote.vote in (VoteType.SELL, VoteType.STRONG_SELL):
                    dissenting.append(f"{vote.agent_type.value}: {vote.reasoning}")
            elif majority in (VoteType.STRONG_SELL, VoteType.SELL):
                if vote.vote in (VoteType.BUY, VoteType.STRONG_BUY):
                    dissenting.append(f"{vote.agent_type.value}: {vote.reasoning}")

        # Calculate weighted confidence
        confidence = sum(v.confidence for v in session.votes if v.agent_type != AgentType.MODERATOR) / max(len(session.votes) - 1, 1)

        return TradeDecision(
            action=action,
            confidence=confidence,
            consensus_level=consensus,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rationale=f"합의수준 {consensus:.0%}로 {action.value} 결정",
            key_factors=list(set(key_factors))[:5],
            dissenting_opinions=dissenting,
            votes=votes_dict,
        )

    async def announce_decision(
        self,
        decision: TradeDecision,
        context: MarketContext,
    ) -> AgentMessage:
        """Announce the final decision."""
        announcement = f"## 최종 결정: {decision.action.value}\n\n"
        announcement += f"- 합의 수준: {decision.consensus_level:.0%}\n"
        announcement += f"- 신뢰도: {decision.confidence:.0%}\n"

        if decision.entry_price:
            announcement += f"- 진입가: {decision.entry_price:,.0f}원\n"
        if decision.stop_loss:
            announcement += f"- 손절가: {decision.stop_loss:,.0f}원\n"
        if decision.take_profit:
            announcement += f"- 목표가: {decision.take_profit:,.0f}원\n"

        announcement += f"\n**근거**: {decision.rationale}\n"

        if decision.dissenting_opinions:
            announcement += "\n**소수 의견**:\n"
            for opinion in decision.dissenting_opinions:
                announcement += f"- {opinion}\n"

        return self._create_message(
            message_type=MessageType.DECISION,
            content=announcement,
            confidence=decision.confidence,
            data={
                "action": decision.action.value,
                "consensus": decision.consensus_level,
            },
        )
