"""
Chat Room

Manages a single discussion session where agents debate a trading opportunity.
Handles message flow, round management, and session lifecycle.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

import structlog

from services.agent_chat.models import (
    AgentMessage,
    AgentType,
    AgentVote,
    ChatRound,
    ChatSession,
    DecisionAction,
    MarketContext,
    MessageType,
    SessionStatus,
    TradeDecision,
)
from services.agent_chat.agents import (
    TechnicalDiscussionAgent,
    FundamentalDiscussionAgent,
    SentimentDiscussionAgent,
    RiskDiscussionAgent,
    ModeratorAgent,
)

logger = structlog.get_logger()


class ChatRoom:
    """
    Agent discussion room for a single stock.

    Manages the complete discussion lifecycle:
    1. Initialize with market context
    2. Run analysis round (each agent presents)
    3. Run discussion rounds (agents debate)
    4. Run voting round (each agent votes)
    5. Moderator makes final decision
    """

    def __init__(
        self,
        ticker: str,
        stock_name: str,
        context: MarketContext,
        max_discussion_rounds: int = 2,
        consensus_threshold: float = 0.75,
    ):
        """
        Initialize chat room.

        Args:
            ticker: Stock ticker code
            stock_name: Stock name
            context: Market data context
            max_discussion_rounds: Maximum discussion rounds before voting
            consensus_threshold: Required consensus level (0.0-1.0)
        """
        self.ticker = ticker
        self.stock_name = stock_name
        self.context = context

        # Create session
        self.session = ChatSession(
            ticker=ticker,
            stock_name=stock_name,
            context=context,
            max_discussion_rounds=max_discussion_rounds,
            consensus_threshold=consensus_threshold,
        )

        # Initialize agents
        self.agents: Dict[AgentType, any] = {
            AgentType.TECHNICAL: TechnicalDiscussionAgent(),
            AgentType.FUNDAMENTAL: FundamentalDiscussionAgent(),
            AgentType.SENTIMENT: SentimentDiscussionAgent(),
            AgentType.RISK: RiskDiscussionAgent(),
            AgentType.MODERATOR: ModeratorAgent(),
        }

        # Discussion order (excluding moderator)
        self.discussion_order = [
            AgentType.TECHNICAL,
            AgentType.FUNDAMENTAL,
            AgentType.SENTIMENT,
            AgentType.RISK,
        ]

        # Callbacks for real-time updates
        self._message_callbacks: List[callable] = []
        self._status_callbacks: List[callable] = []

        logger.info(
            "chat_room_created",
            ticker=ticker,
            stock_name=stock_name,
        )

    def on_message(self, callback: callable) -> None:
        """Register callback for new messages."""
        self._message_callbacks.append(callback)

    def on_status_change(self, callback: callable) -> None:
        """Register callback for status changes."""
        self._status_callbacks.append(callback)

    async def _emit_message(self, message: AgentMessage) -> None:
        """Emit message to all registered callbacks."""
        for callback in self._message_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.warning("message_callback_failed", error=str(e))

    async def _emit_status(self, status: SessionStatus) -> None:
        """Emit status change to all registered callbacks."""
        for callback in self._status_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(status, self.session)
                else:
                    callback(status, self.session)
            except Exception as e:
                logger.warning("status_callback_failed", error=str(e))

    async def start(self) -> ChatSession:
        """
        Start and run the complete discussion.

        Returns:
            Completed ChatSession with decision
        """
        logger.info(
            "chat_room_starting",
            ticker=self.ticker,
            session_id=self.session.id,
        )

        self.session.started_at = datetime.now()
        self.session.status = SessionStatus.ANALYZING
        await self._emit_status(SessionStatus.ANALYZING)

        try:
            # Phase 1: Initial Analysis
            await self._run_analysis_round()

            # Phase 2: Discussion Rounds
            self.session.status = SessionStatus.DISCUSSING
            await self._emit_status(SessionStatus.DISCUSSING)

            for round_num in range(self.session.max_discussion_rounds):
                should_continue = await self._run_discussion_round(round_num + 1)
                if not should_continue:
                    break

            # Phase 3: Voting
            self.session.status = SessionStatus.VOTING
            await self._emit_status(SessionStatus.VOTING)
            await self._run_voting_round()

            # Phase 4: Final Decision
            decision = await self._make_decision()
            self.session.finalize(decision)

            await self._emit_status(SessionStatus.DECIDED)

            logger.info(
                "chat_room_completed",
                ticker=self.ticker,
                session_id=self.session.id,
                decision=decision.action.value,
                consensus=self.session.consensus_level,
                duration=self.session.total_duration_seconds,
            )

            return self.session

        except Exception as e:
            logger.error(
                "chat_room_failed",
                ticker=self.ticker,
                session_id=self.session.id,
                error=str(e),
            )
            self.session.status = SessionStatus.CANCELLED
            await self._emit_status(SessionStatus.CANCELLED)
            raise

    async def _run_analysis_round(self) -> None:
        """Run initial analysis round where each agent presents."""
        logger.info(
            "analysis_round_starting",
            ticker=self.ticker,
        )

        self.session.start_round("analysis")

        # Moderator opens the discussion
        moderator = self.agents[AgentType.MODERATOR]
        opening = await moderator.analyze(self.context)
        self.session.add_message(opening)
        await self._emit_message(opening)

        # Each agent presents analysis (in parallel for speed)
        analysis_tasks = []
        for agent_type in self.discussion_order:
            agent = self.agents[agent_type]
            analysis_tasks.append(agent.analyze(self.context))

        analyses = await asyncio.gather(*analysis_tasks, return_exceptions=True)

        for i, result in enumerate(analyses):
            if isinstance(result, Exception):
                logger.error(
                    "agent_analysis_failed",
                    agent=self.discussion_order[i].value,
                    error=str(result),
                )
                # Create error message
                error_msg = AgentMessage(
                    agent_type=self.discussion_order[i],
                    agent_name=f"{self.discussion_order[i].value} 분석가",
                    message_type=MessageType.ANALYSIS,
                    content=f"분석 중 오류 발생: {str(result)}",
                    confidence=0.0,
                )
                self.session.add_message(error_msg)
                await self._emit_message(error_msg)
            else:
                self.session.add_message(result)
                await self._emit_message(result)

        self.session.end_round()

        logger.info(
            "analysis_round_completed",
            ticker=self.ticker,
            message_count=len(self.session.rounds[-1].messages),
        )

    async def _run_discussion_round(self, round_number: int) -> bool:
        """
        Run a discussion round where agents can respond to each other.

        Args:
            round_number: Current round number

        Returns:
            True if discussion should continue, False if consensus reached
        """
        logger.info(
            "discussion_round_starting",
            ticker=self.ticker,
            round=round_number,
        )

        self.session.start_round("discussion")

        # Get recent messages to respond to
        recent_messages = self.session.all_messages[-8:]  # Last 8 messages

        # Each agent can respond to others
        responses = []
        for agent_type in self.discussion_order:
            agent = self.agents[agent_type]

            # Find messages from other agents to respond to
            other_messages = [
                m for m in recent_messages
                if m.agent_type != agent_type and m.agent_type != AgentType.MODERATOR
            ]

            if other_messages:
                # Respond to the most recent relevant message
                target_message = other_messages[-1]
                response = await agent.respond(
                    message=target_message,
                    context=self.context,
                    chat_history=self.session.all_messages,
                )

                if response:
                    responses.append(response)
                    self.session.add_message(response)
                    await self._emit_message(response)

        # Moderator summarizes if there were responses
        if responses and round_number < self.session.max_discussion_rounds:
            moderator = self.agents[AgentType.MODERATOR]
            summary = await moderator.summarize_round(
                messages=self.session.rounds[-1].messages,
                round_number=round_number,
            )
            self.session.add_message(summary)
            await self._emit_message(summary)

        self.session.end_round()

        logger.info(
            "discussion_round_completed",
            ticker=self.ticker,
            round=round_number,
            response_count=len(responses),
        )

        # Continue if there were meaningful exchanges
        return len(responses) >= 2

    async def _run_voting_round(self) -> None:
        """Run voting round where each agent votes."""
        logger.info(
            "voting_round_starting",
            ticker=self.ticker,
        )

        self.session.start_round("voting")

        # Moderator announces voting
        moderator = self.agents[AgentType.MODERATOR]
        announcement = await moderator.announce_voting(self.context)
        self.session.add_message(announcement)
        await self._emit_message(announcement)

        # Each agent votes (in parallel)
        vote_tasks = []
        for agent_type in self.discussion_order:
            agent = self.agents[agent_type]
            vote_tasks.append(
                agent.vote(
                    context=self.context,
                    chat_history=self.session.all_messages,
                )
            )

        votes = await asyncio.gather(*vote_tasks, return_exceptions=True)

        for i, vote in enumerate(votes):
            if isinstance(vote, Exception):
                logger.error(
                    "agent_vote_failed",
                    agent=self.discussion_order[i].value,
                    error=str(vote),
                )
            else:
                self.session.add_vote(vote)

                # Create vote message for chat
                vote_msg = AgentMessage(
                    agent_type=vote.agent_type,
                    agent_name=f"{vote.agent_type.value} 분석가",
                    message_type=MessageType.VOTE,
                    content=f"투표: {vote.vote.value} (신뢰도: {vote.confidence:.0%})\n근거: {vote.reasoning[:200]}",
                    confidence=vote.confidence,
                    data={"vote": vote.vote.value},
                )
                self.session.add_message(vote_msg)
                await self._emit_message(vote_msg)

        self.session.end_round()

        # Calculate consensus
        self.session.calculate_consensus()

        logger.info(
            "voting_round_completed",
            ticker=self.ticker,
            vote_count=len(self.session.votes),
            consensus=self.session.consensus_level,
        )

    async def _make_decision(self) -> TradeDecision:
        """Have moderator make final decision based on votes."""
        logger.info(
            "decision_making_starting",
            ticker=self.ticker,
            consensus=self.session.consensus_level,
        )

        self.session.start_round("decision")

        moderator = self.agents[AgentType.MODERATOR]
        decision = await moderator.make_decision(
            session=self.session,
            context=self.context,
        )

        # Announce decision
        announcement = await moderator.announce_decision(decision, self.context)
        self.session.add_message(announcement)
        await self._emit_message(announcement)

        self.session.end_round()

        logger.info(
            "decision_made",
            ticker=self.ticker,
            action=decision.action.value,
            confidence=decision.confidence,
        )

        return decision

    def get_session(self) -> ChatSession:
        """Get current session state."""
        return self.session

    def get_messages(self) -> List[AgentMessage]:
        """Get all messages in the session."""
        return self.session.all_messages

    def get_decision(self) -> Optional[TradeDecision]:
        """Get final decision if available."""
        return self.session.decision

    async def cancel(self) -> None:
        """Cancel the discussion."""
        logger.info(
            "chat_room_cancelled",
            ticker=self.ticker,
            session_id=self.session.id,
        )

        self.session.status = SessionStatus.CANCELLED
        self.session.ended_at = datetime.now()
        await self._emit_status(SessionStatus.CANCELLED)
