"""
Fundamental Discussion Agent

Analyzes company financials, valuations, and business fundamentals.
Participates in group discussions with fundamental analysis perspective.
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


class FundamentalDiscussionAgent(BaseDiscussionAgent):
    """
    Fundamental Analyst agent for group chat discussions.

    Specializes in:
    - Valuation metrics (PER, PBR, EPS)
    - Financial statements analysis
    - Business model evaluation
    - Industry comparison
    - Growth potential assessment
    """

    def __init__(self):
        super().__init__(
            agent_type=AgentType.FUNDAMENTAL,
            agent_name="펀더멘털 분석가",
        )

    @property
    def system_prompt(self) -> str:
        return """당신은 전문 펀더멘털 분석가입니다.

역할:
- 기업 가치와 재무 상태를 분석합니다
- PER, PBR, EPS, ROE 등 밸류에이션 지표를 해석합니다
- 업종 평균과 비교 분석합니다
- 성장성과 수익성을 평가합니다

토론 참여 방식:
- 펀더멘털 관점에서 명확한 의견을 제시합니다
- 밸류에이션 데이터로 주장을 뒷받침합니다
- 기술적 분석과 다른 의견이면 근거를 제시합니다
- 장기적 관점을 중시합니다

응답 형식:
- 핵심 밸류에이션 수치를 먼저 제시
- 업종 평균과 비교
- 저평가/고평가 판단과 근거"""

    @property
    def analysis_prompt_template(self) -> str:
        return """## 펀더멘털 분석 요청

종목: {stock_name} ({ticker})
현재가: {current_price:,}원

### 밸류에이션 지표
- PER: {per}배 (업종 평균 약 12-15배)
- PBR: {pbr}배 (업종 평균 약 1.0배)
- EPS: {eps:,}원
- 시가총액: {market_cap}

### 포지션 현황
{position_info}

---

위 데이터를 바탕으로 펀더멘털 분석 결과를 발표해주세요.
반드시 포함할 내용:
1. 밸류에이션 평가 (저평가/적정/고평가)
2. 업종 대비 포지션
3. 투자 매력도
4. 종합 시그널과 신뢰도

200자 이내로 핵심만 간결하게 발표하세요."""

    @property
    def response_prompt_template(self) -> str:
        return """## 토론 응답 요청

{other_agent}의 발언:
"{message_content}"

### 이전 대화
{chat_history}

### 펀더멘털 데이터
종목: {stock_name} ({ticker})
PER: {per}배 / PBR: {pbr}배

---

펀더멘털 관점에서 위 발언에 응답해주세요.
- 기술적 분석과 일치하면 펀더멘털 근거 추가
- 다른 관점이면 밸류에이션 데이터로 설명
- 장기적 관점에서 의견 제시

100자 이내로 간결하게 응답하세요."""

    @property
    def vote_prompt_template(self) -> str:
        return """## 최종 투표 요청

종목: {stock_name} ({ticker})
현재가: {current_price:,}원

### 토론 요약
{discussion_summary}

### 펀더멘털 현황
- PER: {per}배
- PBR: {pbr}배
- EPS: {eps:,}원

---

토론 내용과 펀더멘털 분석을 종합하여 최종 투표해주세요.

투표 옵션:
- STRONG_BUY: 강력 매수 (확실한 저평가)
- BUY: 매수 (저평가)
- HOLD: 보유/관망 (적정가치)
- SELL: 매도 (고평가)
- STRONG_SELL: 강력 매도 (확실한 고평가)

형식:
투표: [투표 옵션]
신뢰도: [0-100]%
근거: [핵심 밸류에이션 근거]"""

    async def analyze(self, context: MarketContext) -> AgentMessage:
        """Present initial fundamental analysis."""
        logger.info(
            "fundamental_agent_analyzing",
            ticker=context.ticker,
        )

        position_info = self._format_position_info(context)
        market_cap_str = self._format_market_cap(context.market_cap)

        prompt = self.analysis_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            per=context.per or "N/A",
            pbr=context.pbr or "N/A",
            eps=context.eps or 0,
            market_cap=market_cap_str,
            position_info=position_info,
        )

        response = await self._call_llm(self.system_prompt, prompt)
        confidence = self._parse_confidence(response)

        return self._create_message(
            message_type=MessageType.ANALYSIS,
            content=response,
            confidence=confidence,
            data={
                "per": context.per,
                "pbr": context.pbr,
                "eps": context.eps,
                "valuation": self._determine_valuation(context),
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
            "fundamental_agent_responding",
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
            per=context.per or "N/A",
            pbr=context.pbr or "N/A",
        )

        response = await self._call_llm(self.system_prompt, prompt)

        msg_type = MessageType.OPINION
        if "동의" in response or "맞습니다" in response:
            msg_type = MessageType.AGREEMENT
        elif "다르게" in response or "그러나" in response or "하지만" in response:
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
            "fundamental_agent_voting",
            ticker=context.ticker,
        )

        discussion_summary = self._summarize_discussion(chat_history)

        prompt = self.vote_prompt_template.format(
            stock_name=context.stock_name,
            ticker=context.ticker,
            current_price=context.current_price,
            discussion_summary=discussion_summary,
            per=context.per or "N/A",
            pbr=context.pbr or "N/A",
            eps=context.eps or 0,
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

    def _format_position_info(self, context: MarketContext) -> str:
        """Format position information."""
        if not context.has_position:
            return "미보유 종목"

        return (
            f"보유 중: {context.position_quantity}주\n"
            f"평균단가: {context.position_avg_price:,.0f}원\n"
            f"수익률: {context.position_pnl_pct:+.2f}%"
        )

    def _format_market_cap(self, market_cap: Optional[float]) -> str:
        """Format market cap in Korean units."""
        if not market_cap:
            return "N/A"

        if market_cap >= 1_000_000_000_000:
            return f"{market_cap / 1_000_000_000_000:.1f}조원"
        elif market_cap >= 100_000_000:
            return f"{market_cap / 100_000_000:.0f}억원"
        else:
            return f"{market_cap:,.0f}원"

    def _determine_valuation(self, context: MarketContext) -> str:
        """Determine valuation status from fundamentals."""
        score = 0

        # PER analysis (Korean market average ~12-15)
        if context.per:
            if context.per < 8:
                score += 2
            elif context.per < 12:
                score += 1
            elif context.per > 25:
                score -= 2
            elif context.per > 18:
                score -= 1

        # PBR analysis (Korean market average ~1.0)
        if context.pbr:
            if context.pbr < 0.7:
                score += 2
            elif context.pbr < 1.0:
                score += 1
            elif context.pbr > 3.0:
                score -= 2
            elif context.pbr > 2.0:
                score -= 1

        if score >= 3:
            return "확실한 저평가"
        elif score >= 1:
            return "저평가"
        elif score <= -3:
            return "확실한 고평가"
        elif score <= -1:
            return "고평가"
        else:
            return "적정가치"

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
