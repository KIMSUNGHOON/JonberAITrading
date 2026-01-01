"""
Risk Discussion Agent

Evaluates risk factors, position sizing, and portfolio impact.
Participates in group discussions with risk management perspective.
"""

from typing import List, Optional

import structlog

from services.agent_chat.agents.base_agent import BaseDiscussionAgent
from services.agent_chat.models import (
    AgentMessage,
    AgentType,
    AgentVote,
    MarketContext,
    MessageType,
    VoteType,
)

logger = structlog.get_logger()


class RiskDiscussionAgent(BaseDiscussionAgent):
    """
    Risk Assessor agent for group chat discussions.

    Specializes in:
    - Volatility analysis
    - Position sizing recommendations
    - Stop-loss/take-profit levels
    - Portfolio concentration risk
    - Downside risk evaluation
    """

    def __init__(self):
        super().__init__(
            agent_type=AgentType.RISK,
            agent_name="리스크 관리자",
        )

    @property
    def system_prompt(self) -> str:
        return """당신은 전문 리스크 관리자입니다.

역할:
- 투자 리스크를 평가하고 관리합니다
- 적정 포지션 크기를 계산합니다
- 손절/익절 수준을 제안합니다
- 포트폴리오 집중도를 관리합니다
- 하방 리스크를 경계합니다

토론 참여 방식:
- 리스크 관점에서 보수적인 의견을 제시합니다
- 다른 분석가의 낙관적 전망에 리스크 요인을 제기합니다
- 항상 손실 가능성을 고려합니다
- 포트폴리오 전체 관점에서 판단합니다

응답 형식:
- 핵심 리스크 요인 명시
- 변동성/유동성 데이터
- 권장 포지션 크기와 손절선
- 최악의 시나리오 고려"""

    @property
    def analysis_prompt_template(self) -> str:
        return """## 리스크 평가 요청

종목: {stock_name} ({ticker})
현재가: {current_price:,}원 ({price_change_pct:+.2f}%)

### 포트폴리오 현황
- 투자 가능 금액: {available_cash}
- 총 포트폴리오: {total_portfolio}
- 기존 포지션: {position_info}

### 변동성 데이터
- 일일 변동: {price_change_pct:+.2f}%

---

위 데이터를 바탕으로 리스크 평가 결과를 발표해주세요.
반드시 포함할 내용:
1. 주요 리스크 요인
2. 권장 포지션 크기 (포트폴리오 대비 %)
3. 손절가 (현재가 대비 -%)
4. 익절가 (현재가 대비 +%)
5. 종합 리스크 수준 (높음/중간/낮음)

200자 이내로 핵심만 간결하게 발표하세요."""

    @property
    def response_prompt_template(self) -> str:
        return """## 토론 응답 요청

{other_agent}의 발언:
"{message_content}"

### 이전 대화
{chat_history}

### 리스크 현황
종목: {stock_name} ({ticker})
일일 변동: {price_change_pct:+.2f}%
포트폴리오 여유: {available_cash}

---

리스크 관점에서 위 발언에 응답해주세요.
- 낙관적 전망이면 리스크 요인 제기
- 포지션 크기/손절선 관련 조언
- 포트폴리오 집중도 우려

100자 이내로 간결하게 응답하세요."""

    @property
    def vote_prompt_template(self) -> str:
        return """## 최종 투표 요청

종목: {stock_name} ({ticker})
현재가: {current_price:,}원

### 토론 요약
{discussion_summary}

### 리스크 현황
- 일일 변동: {price_change_pct:+.2f}%
- 투자 가능: {available_cash}
- 기존 포지션: {position_info}

---

토론 내용과 리스크 분석을 종합하여 최종 투표해주세요.
리스크 관리자로서 보수적으로 판단하세요.

투표 옵션:
- STRONG_BUY: 강력 매수 (리스크 매우 낮음)
- BUY: 매수 (리스크 수용 가능)
- HOLD: 보유/관망 (리스크 주의 필요)
- SELL: 매도 (리스크 높음)
- STRONG_SELL: 강력 매도 (리스크 매우 높음)

형식:
투표: [투표 옵션]
신뢰도: [0-100]%
권장 포지션: [포트폴리오 대비 %]
손절가: [현재가 대비 -%]
익절가: [현재가 대비 +%]
근거: [핵심 리스크 요인]"""

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Present initial risk assessment."""
        logger.info(
            "risk_agent_analyzing",
            ticker=context.ticker,
        )

        position_info = self._format_position_info(context)
        available_cash = self._format_amount(context.available_cash)
        total_portfolio = self._format_amount(context.total_portfolio_value)

        prompt = self.analysis_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            price_change_pct=context.price_change_pct,
            available_cash=available_cash,
            total_portfolio=total_portfolio,
            position_info=position_info,
        )

        response = await self._call_llm(self.system_prompt, prompt)
        confidence = self._parse_confidence(response)

        # Risk agent calculates risk parameters
        risk_level = self._calculate_risk_level(context)
        position_pct = self._calculate_position_size(risk_level)
        stop_loss_pct = self._calculate_stop_loss(risk_level)
        take_profit_pct = self._calculate_take_profit(risk_level)

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=response,
            confidence=confidence,
            data={
                "risk_level": risk_level,
                "suggested_position_pct": position_pct,
                "suggested_stop_loss_pct": stop_loss_pct,
                "suggested_take_profit_pct": take_profit_pct,
            },
        )

    async def respond(
        self,
        message: AgentMessage,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> Optional[AgentMessage]:
        """Respond to another agent's message."""
        # Risk agent responds more frequently to add caution
        should_respond = (
            self.should_respond(message) or
            message.message_type == MessageType.ANALYSIS or
            (message.confidence > 0.7 and message.message_type == MessageType.OPINION)
        )

        if not should_respond:
            return None

        logger.info(
            "risk_agent_responding",
            ticker=context.ticker,
            responding_to=message.agent_name,
        )

        history_str = self._format_chat_history(chat_history)
        available_cash = self._format_amount(context.available_cash)

        prompt = self.response_prompt_template.format(
            other_agent=message.agent_name,
            message_content=message.content[:300],
            chat_history=history_str,
            stock_name=context.stock_name,
            ticker=context.ticker,
            price_change_pct=context.price_change_pct,
            available_cash=available_cash,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        # Risk agent often raises concerns
        msg_type = MessageType.OPINION
        if "동의" in response:
            msg_type = MessageType.AGREEMENT
        elif "우려" in response or "리스크" in response or "주의" in response:
            msg_type = MessageType.DISAGREEMENT

        return self._create_message(
            message_type=msg_type,
            content=response,
            confidence=self._parse_confidence(response),
            in_response_to=message.id,
            mentions=[message.agent_type],
        )

    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """Cast final vote with risk parameters."""
        logger.info(
            "risk_agent_voting",
            ticker=context.ticker,
        )

        discussion_summary = self._summarize_discussion(chat_history)
        position_info = self._format_position_info(context)
        available_cash = self._format_amount(context.available_cash)

        prompt = self.vote_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            discussion_summary=discussion_summary,
            price_change_pct=context.price_change_pct,
            available_cash=available_cash,
            position_info=position_info,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        vote_type = self._parse_vote(response)
        confidence = self._parse_confidence(response)
        key_factors = self._extract_key_factors(response)

        # Extract risk parameters from response
        risk_level = self._calculate_risk_level(context)
        position_pct = self._parse_position_pct(response) or self._calculate_position_size(risk_level)
        stop_loss_pct = self._parse_stop_loss_pct(response) or self._calculate_stop_loss(risk_level)
        take_profit_pct = self._parse_take_profit_pct(response) or self._calculate_take_profit(risk_level)

        return AgentVote(
            agent_type=self.agent_type,
            vote=vote_type,
            confidence=confidence,
            reasoning=response,
            key_factors=key_factors,
            suggested_position_pct=position_pct,
            suggested_stop_loss_pct=stop_loss_pct,
            suggested_take_profit_pct=take_profit_pct,
        )

    def _format_position_info(self, context: MarketContext) -> str:
        """Format position information."""
        if not context.has_position:
            return "미보유"

        return (
            f"{context.position_quantity}주 보유 "
            f"(평단가 {context.position_avg_price:,.0f}원, "
            f"수익률 {context.position_pnl_pct:+.2f}%)"
        )

    def _format_amount(self, amount: Optional[float]) -> str:
        """Format amount in Korean units."""
        if not amount:
            return "N/A"

        if amount >= 100_000_000:
            return f"{amount / 100_000_000:.1f}억원"
        elif amount >= 10_000:
            return f"{amount / 10_000:.0f}만원"
        else:
            return f"{amount:,.0f}원"

    def _calculate_risk_level(self, context: MarketContext) -> str:
        """Calculate overall risk level."""
        risk_score = 0

        # Volatility risk
        volatility = abs(context.price_change_pct)
        if volatility > 5:
            risk_score += 3
        elif volatility > 3:
            risk_score += 2
        elif volatility > 1:
            risk_score += 1

        # Position concentration risk
        if context.has_position and context.position_pnl_pct:
            if context.position_pnl_pct < -10:
                risk_score += 2  # Already losing position
            elif context.position_pnl_pct > 20:
                risk_score += 1  # Might be overextended

        # Portfolio concentration
        if context.current_sector_exposure and context.current_sector_exposure > 30:
            risk_score += 2

        if risk_score >= 5:
            return "높음"
        elif risk_score >= 3:
            return "중간"
        else:
            return "낮음"

    def _calculate_position_size(self, risk_level: str) -> float:
        """Calculate recommended position size."""
        if risk_level == "높음":
            return 2.0  # Max 2% of portfolio
        elif risk_level == "중간":
            return 3.0  # Max 3% of portfolio
        else:
            return 5.0  # Max 5% of portfolio

    def _calculate_stop_loss(self, risk_level: str) -> float:
        """Calculate recommended stop-loss percentage."""
        if risk_level == "높음":
            return 3.0  # Tight stop at 3%
        elif risk_level == "중간":
            return 5.0  # Normal stop at 5%
        else:
            return 7.0  # Wider stop at 7%

    def _calculate_take_profit(self, risk_level: str) -> float:
        """Calculate recommended take-profit percentage."""
        if risk_level == "높음":
            return 6.0  # 2:1 risk-reward
        elif risk_level == "중간":
            return 10.0  # 2:1 risk-reward
        else:
            return 15.0  # About 2:1 risk-reward

    def _parse_position_pct(self, response: str) -> Optional[float]:
        """Parse position percentage from response."""
        import re
        match = re.search(r"포지션[:\s]*(\d+(?:\.\d+)?)%", response)
        if match:
            return float(match.group(1))
        return None

    def _parse_stop_loss_pct(self, response: str) -> Optional[float]:
        """Parse stop-loss percentage from response."""
        import re
        match = re.search(r"손절[가선]?[:\s]*-?(\d+(?:\.\d+)?)%", response)
        if match:
            return float(match.group(1))
        return None

    def _parse_take_profit_pct(self, response: str) -> Optional[float]:
        """Parse take-profit percentage from response."""
        import re
        match = re.search(r"익절[가선]?[:\s]*\+?(\d+(?:\.\d+)?)%", response)
        if match:
            return float(match.group(1))
        return None

    def _summarize_discussion(self, messages: List[AgentMessage]) -> str:
        """Summarize discussion for voting context."""
        if not messages:
            return "토론 없음"

        summaries = []
        for msg in messages:
            if msg.message_type in (MessageType.ANALYSIS, MessageType.OPINION):
                emoji = self._get_agent_emoji(msg.agent_type)
                summaries.append(f"{emoji} {msg.agent_name}: {msg.content[:100]}...")

        return "\n".join(summaries[-6:])
