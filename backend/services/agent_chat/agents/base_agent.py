"""
Base Discussion Agent

Abstract base class for all discussion agents in the group chat.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

import structlog

from agents.llm.tasks import TaskType
from agents.llm_provider import get_llm_provider
from services.agent_chat.models import (
    AgentMessage,
    AgentType,
    AgentVote,
    ChatSession,
    MarketContext,
    MessageType,
    VoteType,
)

logger = structlog.get_logger()


class BaseDiscussionAgent(ABC):
    """
    Abstract base class for discussion agents.

    Each agent can:
    1. Present initial analysis
    2. Respond to other agents
    3. Ask questions
    4. Vote on the final decision
    """

    def __init__(self, agent_type: AgentType, agent_name: str):
        self.agent_type = agent_type
        self.agent_name = agent_name
        self.llm = get_llm_provider()

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt for this agent's persona."""
        pass

    @property
    @abstractmethod
    def analysis_prompt_template(self) -> str:
        """Template for initial analysis prompt."""
        pass

    @property
    @abstractmethod
    def response_prompt_template(self) -> str:
        """Template for responding to other agents."""
        pass

    @property
    @abstractmethod
    def vote_prompt_template(self) -> str:
        """Template for final vote."""
        pass

    def _create_message(
        self,
        message_type: MessageType,
        content: str,
        confidence: float = 0.5,
        data: Optional[dict] = None,
        in_response_to: Optional[str] = None,
        mentions: Optional[List[AgentType]] = None,
    ) -> AgentMessage:
        """Create a message from this agent."""
        return AgentMessage(
            agent_type=self.agent_type,
            agent_name=self.agent_name,
            message_type=message_type,
            content=content,
            confidence=confidence,
            data=data,
            in_response_to=in_response_to,
            mentions=mentions or [],
        )

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call LLM with given prompts."""
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = await self.llm.generate(messages)
            return response
        except Exception as e:
            logger.error(
                "llm_call_failed",
                agent=self.agent_name,
                error=str(e),
            )
            return f"분석 중 오류 발생: {str(e)}"

    async def _structured_vote(self, messages, *, schema: dict, task=TaskType.GROUP_CHAT):
        """Return the validated structured-vote dict, or None on any failure
        (the caller then uses the regex fallback path). `self.llm` is the shared
        provider facade; generate_structured raises ValueError on parse/missing keys.
        """
        try:
            return await self.llm.generate_structured(messages, schema, task=task)
        except (ValueError, KeyError) as e:
            logger.warning("structured_vote_failed", agent=self.agent_type.value, error=str(e))
            return None

    @abstractmethod
    async def analyze(self, context: MarketContext) -> AgentMessage:
        """
        Present initial analysis based on market context.

        Args:
            context: Market data and portfolio context

        Returns:
            AgentMessage with analysis results
        """
        pass

    @abstractmethod
    async def respond(
        self,
        message: AgentMessage,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> Optional[AgentMessage]:
        """
        Respond to another agent's message.

        Args:
            message: The message to respond to
            context: Market data context
            chat_history: Previous messages in the chat

        Returns:
            Response message, or None if no response needed
        """
        pass

    @abstractmethod
    async def vote(
        self,
        context: MarketContext,
        chat_history: List[AgentMessage],
    ) -> AgentVote:
        """
        Cast final vote on the trading decision.

        Args:
            context: Market data context
            chat_history: All messages from the discussion

        Returns:
            AgentVote with the agent's final decision
        """
        pass

    def should_respond(self, message: AgentMessage) -> bool:
        """
        Determine if this agent should respond to a message.

        Args:
            message: The message to potentially respond to

        Returns:
            True if this agent should respond
        """
        # Always respond if directly mentioned
        if self.agent_type in message.mentions:
            return True

        # Respond to questions
        if message.message_type == MessageType.QUESTION:
            return True

        # Respond to disagreements that might need clarification
        if message.message_type == MessageType.DISAGREEMENT:
            return True

        return False

    def _format_chat_history(self, messages: List[AgentMessage]) -> str:
        """Format chat history for LLM context."""
        if not messages:
            return "이전 대화 없음"

        lines = []
        for msg in messages[-10:]:  # Last 10 messages for context
            emoji = self._get_agent_emoji(msg.agent_type)
            lines.append(f"{emoji} {msg.agent_name}: {msg.content[:300]}")

        return "\n".join(lines)

    def _get_agent_emoji(self, agent_type: AgentType) -> str:
        """Get emoji for agent type."""
        emoji_map = {
            AgentType.TECHNICAL: "📊",
            AgentType.FUNDAMENTAL: "📈",
            AgentType.SENTIMENT: "📰",
            AgentType.RISK: "⚠️",
            AgentType.MODERATOR: "👔",
        }
        return emoji_map.get(agent_type, "🤖")

    def _parse_confidence(self, response: str) -> float:
        """Extract confidence from LLM response."""
        import re

        # Try to find confidence percentage
        patterns = [
            r"신뢰도[:\s]*(\d+)%",
            r"confidence[:\s]*(\d+)%",
            r"(\d+)%\s*신뢰",
        ]

        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                return min(int(match.group(1)) / 100.0, 1.0)

        # Default confidence based on signal strength words
        if any(word in response for word in ["강력", "확실", "명확", "strong"]):
            return 0.85
        elif any(word in response for word in ["약한", "불확실", "weak"]):
            return 0.45
        else:
            return 0.65

    def _parse_vote(self, response: str) -> VoteType:
        """Extract vote from LLM response."""
        response_lower = response.lower()

        # Check for strong signals first
        if any(word in response_lower for word in ["strong_buy", "강력 매수", "강력매수", "적극 매수"]):
            return VoteType.STRONG_BUY
        elif any(word in response_lower for word in ["strong_sell", "강력 매도", "강력매도", "즉시 매도"]):
            return VoteType.STRONG_SELL
        elif any(word in response_lower for word in ["buy", "매수", "진입"]):
            return VoteType.BUY
        elif any(word in response_lower for word in ["sell", "매도", "청산"]):
            return VoteType.SELL
        elif any(word in response_lower for word in ["hold", "보유", "유지", "관망"]):
            return VoteType.HOLD
        else:
            return VoteType.ABSTAIN

    def _extract_key_factors(self, response: str) -> List[str]:
        """Extract key factors from response."""
        factors = []
        lines = response.split("\n")

        for line in lines:
            line = line.strip()
            # Look for bullet points or numbered items
            if line.startswith(("-", "•", "*", "·")) or (line and line[0].isdigit() and "." in line[:3]):
                clean = line.lstrip("-•*·0123456789. ").strip()
                if clean and len(clean) > 5:
                    factors.append(clean[:150])

        return factors[:5]  # Max 5 factors
