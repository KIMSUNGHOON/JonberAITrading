"""
Moderator Agent

Facilitates discussion, summarizes consensus, and makes final decisions.
Does not vote but synthesizes all agent inputs into actionable decisions.
"""

from typing import List, Optional

import structlog

from services.agent_chat.agents.base_agent import BaseDiscussionAgent
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
    vote_to_action,
    calculate_weighted_confidence,
)

logger = structlog.get_logger()


class ModeratorAgent(BaseDiscussionAgent):
    """
    Moderator agent for group chat discussions.

    Responsibilities:
    - Facilitate orderly discussion
    - Summarize key points
    - Identify areas of agreement/disagreement
    - Calculate consensus
    - Make final trading decision
    """

    def __init__(self):
        super().__init__(
            agent_type=AgentType.MODERATOR,
            agent_name="토론 진행자",
        )

    @property
    def system_prompt(self) -> str:
        return """당신은 투자 토론 진행자입니다.

역할:
- 토론을 원활하게 진행합니다
- 각 분석가의 의견을 객관적으로 요약합니다
- 합의점과 이견을 파악합니다
- 최종 결정을 내립니다

진행 방식:
- 중립적인 입장을 유지합니다
- 모든 의견을 공정하게 고려합니다
- 합의 수준을 계산합니다
- 명확한 결정과 근거를 제시합니다

응답 형식:
- 각 분석가 의견 요약
- 합의 수준 (%)
- 최종 결정과 근거
- 실행 계획"""

    @property
    def analysis_prompt_template(self) -> str:
        return """## 토론 개시

종목: {stock_name} ({ticker})
현재가: {current_price:,}원

이제 {stock_name}에 대한 투자 토론을 시작합니다.
각 분석가께서 순서대로 분석 결과를 발표해주세요.

1. 기술적 분석가
2. 펀더멘털 분석가
3. 시장심리 분석가
4. 리스크 관리자

발표 후 자유 토론을 진행하고, 최종 투표를 실시하겠습니다."""

    @property
    def response_prompt_template(self) -> str:
        return """## 토론 진행

### 현재까지 발언
{chat_history}

---

토론을 진행해주세요.
- 의견이 대립되면 각자 근거를 제시하도록 유도
- 중요한 포인트를 정리
- 다음 발언자 안내"""

    @property
    def vote_prompt_template(self) -> str:
        return """## 토론 마무리 및 결정

종목: {stock_name} ({ticker})
현재가: {current_price:,}원

### 투표 결과
{vote_summary}

### 합의 수준
{consensus_level:.0%}

### 토론 핵심 요약
{discussion_summary}

---

투표 결과와 토론 내용을 종합하여 최종 결정을 내려주세요.

결정 옵션:
- BUY: 신규 매수
- SELL: 전량 매도
- ADD: 추가 매수 (보유 시)
- REDUCE: 일부 매도 (보유 시)
- HOLD: 보유 유지
- WATCH: 관망 (진입점 대기)
- NO_ACTION: 행동 없음

형식:
## 최종 결정
결정: [결정 옵션]
신뢰도: [0-100]%

## 결정 근거
[각 분석가 의견 요약 및 결정 이유]

## 실행 계획 (BUY/SELL/ADD/REDUCE 시)
- 포지션 크기: 포트폴리오의 X%
- 진입가: XXX원
- 손절가: XXX원
- 익절가: XXX원

## 소수 의견
[반대 의견 있으면 기록]"""

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Open the discussion."""
        logger.info(
            "moderator_opening_discussion",
            ticker=context.ticker,
        )

        prompt = self.analysis_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        return self._create_message(
            message_type=MessageType.SUMMARY,
            content=response,
            confidence=1.0,
        )

    async def respond(
        self,
        message: AgentMessage,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> Optional[AgentMessage]:
        """Moderate the discussion if needed."""
        # Moderator responds less frequently - only to keep discussion on track
        if len(chat_history) % 4 != 0:  # Every 4 messages
            return None

        logger.info(
            "moderator_intervening",
            ticker=context.ticker,
            message_count=len(chat_history),
        )

        history_str = self._format_chat_history(chat_history)

        prompt = self.response_prompt_template.format(
            chat_history=history_str,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        return self._create_message(
            message_type=MessageType.SUMMARY,
            content=response,
            confidence=1.0,
        )

    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """Moderator doesn't vote - this should not be called."""
        raise NotImplementedError("Moderator does not vote")

    async def make_decision(
        self,
        session: ChatSession,
        context: MarketContext,
    ) -> TradeDecision:
        """
        Make final trading decision based on votes and discussion.

        Args:
            session: The chat session with all votes
            context: Market data context

        Returns:
            TradeDecision with final decision and parameters
        """
        logger.info(
            "moderator_making_decision",
            ticker=context.ticker,
            vote_count=len(session.votes),
            consensus=session.consensus_level,
        )

        # Format vote summary
        vote_summary = self._format_vote_summary(session.votes)
        discussion_summary = self._format_discussion_summary(session.all_messages)
        consensus_level = session.calculate_consensus()

        prompt = self.vote_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            vote_summary=vote_summary,
            consensus_level=consensus_level,
            discussion_summary=discussion_summary,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        # Parse decision from response
        decision = self._parse_decision(response, session, context)

        # Log decision
        logger.info(
            "moderator_decision_made",
            ticker=context.ticker,
            action=decision.action.value,
            confidence=decision.confidence,
            consensus=decision.consensus_level,
        )

        return decision

    def _format_vote_summary(self, votes: List[AgentVote]) -> str:
        """Format votes for moderator prompt."""
        if not votes:
            return "투표 없음"

        lines = []
        for vote in votes:
            emoji = self._get_agent_emoji(vote.agent_type)
            agent_name = self._get_agent_name(vote.agent_type)
            lines.append(
                f"{emoji} {agent_name}: {vote.vote.value} "
                f"(신뢰도: {vote.confidence:.0%})"
            )
            if vote.key_factors:
                lines.append(f"   근거: {', '.join(vote.key_factors[:2])}")

        return "\n".join(lines)

    def _format_discussion_summary(self, messages: List[AgentMessage]) -> str:
        """Format discussion summary for decision."""
        if not messages:
            return "토론 없음"

        # Group messages by agent
        by_agent = {}
        for msg in messages:
            if msg.agent_type not in by_agent:
                by_agent[msg.agent_type] = []
            by_agent[msg.agent_type].append(msg)

        lines = []
        for agent_type, agent_messages in by_agent.items():
            if agent_type == AgentType.MODERATOR:
                continue

            emoji = self._get_agent_emoji(agent_type)
            name = self._get_agent_name(agent_type)

            # Get key analysis message
            analysis = next(
                (m for m in agent_messages if m.message_type == MessageType.ANALYSIS),
                None,
            )
            if analysis:
                lines.append(f"{emoji} {name}: {analysis.content[:150]}...")

        return "\n".join(lines)

    def _get_agent_name(self, agent_type: AgentType) -> str:
        """Get human-readable agent name."""
        names = {
            AgentType.TECHNICAL: "기술적 분석가",
            AgentType.FUNDAMENTAL: "펀더멘털 분석가",
            AgentType.SENTIMENT: "시장심리 분석가",
            AgentType.RISK: "리스크 관리자",
            AgentType.MODERATOR: "토론 진행자",
        }
        return names.get(agent_type, str(agent_type))

    def _parse_decision(
        self,
        response: str,
        session: ChatSession,
        context: MarketContext,
    ) -> TradeDecision:
        """Parse decision from moderator response."""
        # Parse action
        action = self._parse_action(response, context.has_position)

        # Get weighted confidence
        confidence = calculate_weighted_confidence(session.votes)

        # Get risk parameters from risk agent's vote
        risk_vote = next(
            (v for v in session.votes if v.agent_type == AgentType.RISK),
            None,
        )

        # Calculate trade parameters
        quantity = None
        entry_price = context.current_price
        stop_loss = None
        take_profit = None
        position_pct = None

        if risk_vote:
            position_pct = risk_vote.suggested_position_pct
            stop_loss_pct = risk_vote.suggested_stop_loss_pct or 5.0
            take_profit_pct = risk_vote.suggested_take_profit_pct or 10.0

            stop_loss = int(entry_price * (1 - stop_loss_pct / 100))
            take_profit = int(entry_price * (1 + take_profit_pct / 100))

            # Calculate quantity if we have portfolio info
            if context.available_cash and position_pct:
                investment = context.available_cash * (position_pct / 100)
                quantity = int(investment / entry_price)

        # Collect key factors from all votes
        key_factors = []
        for vote in session.votes:
            key_factors.extend(vote.key_factors[:2])
        key_factors = key_factors[:5]  # Max 5 factors

        # Collect dissenting opinions
        majority_direction = session.get_majority_direction()
        dissenting = []
        for vote in session.votes:
            if self._is_opposite_direction(vote.vote, majority_direction):
                dissenting.append(
                    f"{self._get_agent_name(vote.agent_type)}: {vote.reasoning[:100]}"
                )

        # Build vote breakdown
        vote_breakdown = {
            v.agent_type.value: v.vote.value for v in session.votes
        }

        return TradeDecision(
            action=action,
            confidence=confidence,
            consensus_level=session.consensus_level,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_pct=position_pct,
            rationale=response,
            key_factors=key_factors,
            dissenting_opinions=dissenting,
            votes=vote_breakdown,
        )

    def _parse_action(self, response: str, has_position: bool) -> DecisionAction:
        """Parse decision action from response."""
        response_lower = response.lower()

        # Check for specific actions
        if "add" in response_lower or "추가 매수" in response_lower:
            return DecisionAction.ADD
        elif "reduce" in response_lower or "일부 매도" in response_lower:
            return DecisionAction.REDUCE
        elif "buy" in response_lower or "매수" in response_lower or "진입" in response_lower:
            return DecisionAction.BUY if not has_position else DecisionAction.ADD
        elif "sell" in response_lower or "매도" in response_lower or "청산" in response_lower:
            return DecisionAction.SELL if has_position else DecisionAction.NO_ACTION
        elif "hold" in response_lower or "보유" in response_lower or "유지" in response_lower:
            return DecisionAction.HOLD
        elif "watch" in response_lower or "관망" in response_lower or "대기" in response_lower:
            return DecisionAction.WATCH
        else:
            return DecisionAction.NO_ACTION

    def _is_opposite_direction(self, vote: VoteType, majority: VoteType) -> bool:
        """Check if a vote is opposite to majority direction."""
        bullish = (VoteType.STRONG_BUY, VoteType.BUY)
        bearish = (VoteType.STRONG_SELL, VoteType.SELL)

        if majority in bullish:
            return vote in bearish
        elif majority in bearish:
            return vote in bullish
        else:
            return vote in bullish or vote in bearish

    async def summarize_round(
        self,
        messages: List[AgentMessage],
        round_number: int,
    ) -> AgentMessage:
        """Summarize a discussion round."""
        summary_prompt = f"""## Round {round_number} 요약

### 발언 내용
{self._format_chat_history(messages)}

---

이번 라운드의 핵심 포인트를 간단히 요약해주세요.
- 주요 합의점
- 이견 사항
- 다음 라운드에서 논의할 점"""

        response = await self._call_llm(self.system_prompt, summary_prompt)

        return self._create_message(
            message_type=MessageType.SUMMARY,
            content=response,
            confidence=1.0,
        )

    async def announce_voting(self, context: MarketContext) -> AgentMessage:
        """Announce start of voting phase."""
        return self._create_message(
            message_type=MessageType.SUMMARY,
            content=(
                f"토론을 마무리하고 {context.stock_name} ({context.ticker})에 대한 "
                f"최종 투표를 시작합니다. 각 분석가께서 투표해주세요."
            ),
            confidence=1.0,
        )

    async def announce_decision(
        self,
        decision: TradeDecision,
        context: MarketContext,
    ) -> AgentMessage:
        """Announce final decision."""
        action_str = {
            DecisionAction.BUY: "매수",
            DecisionAction.SELL: "매도",
            DecisionAction.ADD: "추가 매수",
            DecisionAction.REDUCE: "일부 매도",
            DecisionAction.HOLD: "보유 유지",
            DecisionAction.WATCH: "관망",
            DecisionAction.NO_ACTION: "행동 없음",
        }.get(decision.action, str(decision.action))

        content = f"""## 최종 결정 발표

**{context.stock_name} ({context.ticker})**

### 결정: {action_str}
- 신뢰도: {decision.confidence:.0%}
- 합의 수준: {decision.consensus_level:.0%}
"""

        if decision.action in (DecisionAction.BUY, DecisionAction.ADD):
            content += f"""
### 매수 계획
- 수량: {decision.quantity or 'TBD'}주
- 진입가: ₩{decision.entry_price:,}
- 손절가: ₩{decision.stop_loss:,}
- 익절가: ₩{decision.take_profit:,}
"""

        if decision.dissenting_opinions:
            content += "\n### 소수 의견\n"
            for opinion in decision.dissenting_opinions[:2]:
                content += f"- {opinion}\n"

        return self._create_message(
            message_type=MessageType.DECISION,
            content=content,
            confidence=decision.confidence,
            data={
                "action": decision.action.value,
                "consensus": decision.consensus_level,
                "quantity": decision.quantity,
                "entry_price": decision.entry_price,
                "stop_loss": decision.stop_loss,
                "take_profit": decision.take_profit,
            },
        )
