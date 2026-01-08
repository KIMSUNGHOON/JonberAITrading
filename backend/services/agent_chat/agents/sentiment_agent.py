"""
Sentiment Discussion Agent

Analyzes market sentiment, news, and investor psychology.
Participates in group discussions with sentiment analysis perspective.
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


class SentimentDiscussionAgent(BaseDiscussionAgent):
    """
    Sentiment Analyst agent for group chat discussions.

    Specializes in:
    - News sentiment analysis
    - Social media monitoring
    - Investor psychology
    - Market momentum
    - Institutional/foreign investor trends
    """

    def __init__(self):
        super().__init__(
            agent_type=AgentType.SENTIMENT,
            agent_name="시장심리 분석가",
        )

    @property
    def system_prompt(self) -> str:
        return """당신은 전문 시장심리 분석가입니다.

역할:
- 뉴스와 공시를 분석하여 시장 심리를 파악합니다
- 투자자 심리와 수급 동향을 분석합니다
- 외국인/기관 매매 동향을 해석합니다
- 시장 모멘텀을 평가합니다

토론 참여 방식:
- 시장 심리 관점에서 의견을 제시합니다
- 뉴스/공시 내용을 근거로 활용합니다
- 단기 모멘텀과 투자자 심리를 분석합니다
- 군중 심리의 함정도 경계합니다

응답 형식:
- 뉴스/공시 기반 핵심 포인트
- 수급 동향 (외국인, 기관)
- 시장 심리 온도 (긍정/중립/부정)"""

    @property
    def analysis_prompt_template(self) -> str:
        return """## 시장심리 분석 요청

종목: {stock_name} ({ticker})
현재가: {current_price:,}원 ({price_change_pct:+.2f}%)

### 뉴스 분석
- 뉴스 감성: {news_sentiment}
- 분석 뉴스 수: {news_count}건

### 가격 모멘텀
- 전일 대비: {price_change_pct:+.2f}%

---

위 데이터를 바탕으로 시장심리 분석 결과를 발표해주세요.
반드시 포함할 내용:
1. 뉴스/공시 기반 심리 분석
2. 단기 모멘텀 평가
3. 시장 관심도
4. 종합 시그널과 신뢰도

200자 이내로 핵심만 간결하게 발표하세요."""

    @property
    def response_prompt_template(self) -> str:
        return """## 토론 응답 요청

{other_agent}의 발언:
"{message_content}"

### 이전 대화
{chat_history}

### 시장 심리 데이터
종목: {stock_name} ({ticker})
뉴스 감성: {news_sentiment}
가격 변동: {price_change_pct:+.2f}%

---

시장심리 관점에서 위 발언에 응답해주세요.
- 심리적 요인이 기술적/펀더멘털 분석을 지지하는지
- 군중 심리의 함정은 없는지
- 모멘텀 관점의 의견

100자 이내로 간결하게 응답하세요."""

    @property
    def vote_prompt_template(self) -> str:
        return """## 최종 투표 요청

종목: {stock_name} ({ticker})
현재가: {current_price:,}원

### 토론 요약
{discussion_summary}

### 심리 현황
- 뉴스 감성: {news_sentiment}
- 분석 뉴스: {news_count}건
- 가격 모멘텀: {price_change_pct:+.2f}%

---

토론 내용과 시장심리 분석을 종합하여 최종 투표해주세요.

투표 옵션:
- STRONG_BUY: 강력 매수 (매우 긍정적 심리)
- BUY: 매수 (긍정적 심리)
- HOLD: 보유/관망 (중립적 심리)
- SELL: 매도 (부정적 심리)
- STRONG_SELL: 강력 매도 (매우 부정적 심리)

형식:
투표: [투표 옵션]
신뢰도: [0-100]%
근거: [핵심 심리 요인]"""

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Present initial sentiment analysis."""
        logger.info(
            "sentiment_agent_analyzing",
            ticker=context.ticker,
        )

        prompt = self.analysis_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            price_change_pct=context.price_change_pct,
            news_sentiment=context.news_sentiment or "분석 중",
            news_count=context.news_count or 0,
        )

        response = await self._call_llm(self.system_prompt, prompt)
        confidence = self._parse_confidence(response)

        # Adjust confidence based on data availability
        if not context.news_sentiment or context.news_count == 0:
            confidence = min(confidence, 0.5)  # Lower confidence without news data

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=response,
            confidence=confidence,
            data={
                "news_sentiment": context.news_sentiment,
                "news_count": context.news_count,
                "momentum": "positive" if context.price_change_pct > 2 else (
                    "negative" if context.price_change_pct < -2 else "neutral"
                ),
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
            "sentiment_agent_responding",
            ticker=context.ticker,
            responding_to=message.agent_name,
        )

        history_str = self._format_chat_history(chat_history)

        prompt = self.response_prompt_template.format(
            other_agent=message.agent_name,
            message_content=message.content[:300],
            chat_history=history_str,
            stock_name=context.stock_name,
            ticker=context.ticker,
            news_sentiment=context.news_sentiment or "N/A",
            price_change_pct=context.price_change_pct,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        msg_type = MessageType.OPINION
        if "동의" in response or "지지" in response:
            msg_type = MessageType.AGREEMENT
        elif "우려" in response or "주의" in response or "그러나" in response:
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
            "sentiment_agent_voting",
            ticker=context.ticker,
        )

        discussion_summary = self._summarize_discussion(chat_history)

        prompt = self.vote_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            discussion_summary=discussion_summary,
            news_sentiment=context.news_sentiment or "N/A",
            news_count=context.news_count or 0,
            price_change_pct=context.price_change_pct,
        )

        response = await self._call_llm(self.system_prompt, prompt)

        vote_type = self._parse_vote(response)
        confidence = self._parse_confidence(response)
        key_factors = self._extract_key_factors(response)

        # Adjust confidence if no news data
        if not context.news_sentiment or context.news_count == 0:
            confidence = min(confidence, 0.5)

        return AgentVote(
            agent_type=self.agent_type,
            vote=vote_type,
            confidence=confidence,
            reasoning=response,
            key_factors=key_factors,
        )

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
