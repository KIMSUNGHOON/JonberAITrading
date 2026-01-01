"""
Technical Discussion Agent

Analyzes price patterns, technical indicators, and chart formations.
Participates in group discussions with technical analysis perspective.
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


class TechnicalDiscussionAgent(BaseDiscussionAgent):
    """
    Technical Analyst agent for group chat discussions.

    Specializes in:
    - Price pattern recognition
    - Technical indicators (RSI, MACD, Bollinger Bands)
    - Support/resistance levels
    - Volume analysis
    - Trend identification
    """

    def __init__(self):
        super().__init__(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술적 분석가",
        )

    @property
    def system_prompt(self) -> str:
        return """당신은 전문 기술적 분석가입니다.

역할:
- 차트 패턴과 기술적 지표를 분석합니다
- RSI, MACD, 이동평균선, 볼린저밴드 등을 해석합니다
- 지지선/저항선을 파악합니다
- 거래량 패턴을 분석합니다

토론 참여 방식:
- 기술적 관점에서 명확한 의견을 제시합니다
- 다른 분석가의 의견에 기술적 근거로 동의하거나 반박합니다
- 불확실한 부분은 인정하되, 가능한 시나리오를 제시합니다
- 간결하고 명확하게 말합니다 (200자 이내)

응답 형식:
- 핵심 포인트를 먼저 말합니다
- 구체적인 수치를 포함합니다 (예: RSI 35, 20일선 75,000원)
- 시그널 강도를 표시합니다 (강력/보통/약함)"""

    @property
    def analysis_prompt_template(self) -> str:
        return """## 기술적 분석 요청

종목: {stock_name} ({ticker})
현재가: {current_price:,}원 ({price_change_pct:+.2f}%)

### 기술적 지표
{indicators}

### 차트 데이터 (최근 10일)
{chart_summary}

---

위 데이터를 바탕으로 기술적 분석 결과를 발표해주세요.
반드시 포함할 내용:
1. 현재 추세 (상승/하락/횡보)
2. 주요 지표 해석 (RSI, MACD 등)
3. 지지선/저항선
4. 거래량 분석
5. 종합 시그널 (매수/매도/보유)와 신뢰도

200자 이내로 핵심만 간결하게 발표하세요."""

    @property
    def response_prompt_template(self) -> str:
        return """## 토론 응답 요청

{other_agent}의 발언:
"{message_content}"

### 이전 대화
{chat_history}

### 시장 데이터
종목: {stock_name} ({ticker})
현재가: {current_price:,}원
기술적 지표: {indicators_summary}

---

기술적 분석 관점에서 위 발언에 응답해주세요.
- 동의하면 기술적 근거를 추가로 제시
- 반박하면 기술적 데이터로 반박
- 질문이면 기술적 관점에서 답변

100자 이내로 간결하게 응답하세요."""

    @property
    def vote_prompt_template(self) -> str:
        return """## 최종 투표 요청

종목: {stock_name} ({ticker})
현재가: {current_price:,}원

### 토론 요약
{discussion_summary}

### 기술적 지표 현황
{indicators}

---

토론 내용과 기술적 분석을 종합하여 최종 투표해주세요.

투표 옵션:
- STRONG_BUY: 강력 매수 (기술적으로 매우 유리)
- BUY: 매수 (기술적으로 유리)
- HOLD: 보유/관망 (중립적)
- SELL: 매도 (기술적으로 불리)
- STRONG_SELL: 강력 매도 (기술적으로 매우 불리)

형식:
투표: [투표 옵션]
신뢰도: [0-100]%
근거: [핵심 근거 1-2개]"""

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Present initial technical analysis."""
        logger.info(
            "technical_agent_analyzing",
            ticker=context.ticker,
        )

        # Format indicators
        indicators_str = self._format_indicators(context.indicators)
        chart_summary = self._format_chart_summary(context.chart_data)

        prompt = self.analysis_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            price_change_pct=context.price_change_pct,
            indicators=indicators_str,
            chart_summary=chart_summary,
        )

        response = await self._call_llm(self.system_prompt, prompt)
        confidence = self._parse_confidence(response)

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=response,
            confidence=confidence,
            data={
                "indicators": context.indicators,
                "signal": self._parse_vote(response).value,
            },
        )

    async def respond(
        self,
        message: AgentMessage,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> Optional[AgentMessage]:
        """Respond to another agent's message."""
        if not self.should_respond(message):
            return None

        logger.info(
            "technical_agent_responding",
            ticker=context.ticker,
            responding_to=message.agent_name,
        )

        indicators_summary = self._format_indicators_summary(context.indicators)
        history_str = self._format_chat_history(chat_history)

        prompt = self.response_prompt_template.format(
            other_agent=message.agent_name,
            message_content=message.content[:300],
            chat_history=history_str,
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            indicators_summary=indicators_summary,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        # Determine message type based on content
        msg_type = MessageType.OPINION
        if "동의" in response or "맞습니다" in response:
            msg_type = MessageType.AGREEMENT
        elif "반박" in response or "다르게" in response or "그러나" in response:
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
        """Cast final vote."""
        logger.info(
            "technical_agent_voting",
            ticker=context.ticker,
        )

        discussion_summary = self._summarize_discussion(chat_history)
        indicators_str = self._format_indicators(context.indicators)

        prompt = self.vote_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            discussion_summary=discussion_summary,
            indicators=indicators_str,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        vote_type = self._parse_vote(response)
        confidence = self._parse_confidence(response)
        key_factors = self._extract_key_factors(response)

        return AgentVote(
            agent_type=self.agent_type,
            vote=vote_type,
            confidence=confidence,
            reasoning=response,
            key_factors=key_factors,
        )

    def _format_indicators(self, indicators: Optional[dict]) -> str:
        """Format technical indicators for prompt."""
        if not indicators:
            return "기술적 지표 데이터 없음"

        lines = []

        # RSI
        if "rsi" in indicators:
            rsi = indicators["rsi"]
            status = "과매도" if rsi < 30 else ("과매수" if rsi > 70 else "중립")
            lines.append(f"- RSI: {rsi:.1f} ({status})")

        # MACD
        if "macd" in indicators:
            macd = indicators["macd"]
            if isinstance(macd, dict):
                hist = macd.get("histogram", 0)
                signal = "상승" if hist > 0 else "하락"
                lines.append(f"- MACD 히스토그램: {hist:.2f} ({signal} 모멘텀)")

        # Moving averages
        if "sma_20" in indicators:
            lines.append(f"- 20일 이동평균: {indicators['sma_20']:,.0f}원")
        if "sma_60" in indicators:
            lines.append(f"- 60일 이동평균: {indicators['sma_60']:,.0f}원")

        # Trend
        if "trend" in indicators:
            lines.append(f"- 추세: {indicators['trend']}")

        # Cross signals
        if "cross" in indicators and indicators["cross"] != "none":
            lines.append(f"- 크로스: {indicators['cross']}")

        # Volume
        if "volume_ratio" in indicators:
            lines.append(f"- 거래량 비율: {indicators['volume_ratio']:.2f}x")

        return "\n".join(lines) if lines else "기술적 지표 데이터 없음"

    def _format_indicators_summary(self, indicators: Optional[dict]) -> str:
        """Format brief indicators summary."""
        if not indicators:
            return "N/A"

        parts = []
        if "rsi" in indicators:
            parts.append(f"RSI {indicators['rsi']:.0f}")
        if "trend" in indicators:
            parts.append(f"추세 {indicators['trend']}")

        return ", ".join(parts) if parts else "N/A"

    def _format_chart_summary(self, chart_data: Optional[list]) -> str:
        """Format chart data summary."""
        if not chart_data:
            return "차트 데이터 없음"

        recent = chart_data[-10:] if len(chart_data) >= 10 else chart_data
        lines = []

        for day in recent[-5:]:  # Last 5 days
            date = day.get("date", "N/A")
            close = day.get("close", 0)
            volume = day.get("volume", 0)
            lines.append(f"{date}: 종가 {close:,}원, 거래량 {volume:,}")

        return "\n".join(lines)

    def _summarize_discussion(self, messages: List[AgentMessage]) -> str:
        """Summarize discussion for voting context."""
        if not messages:
            return "토론 없음"

        summaries = []
        for msg in messages:
            if msg.message_type in (MessageType.ANALYSIS, MessageType.OPINION):
                emoji = self._get_agent_emoji(msg.agent_type)
                summaries.append(f"{emoji} {msg.agent_name}: {msg.content[:100]}...")

        return "\n".join(summaries[-6:])  # Last 6 key messages
