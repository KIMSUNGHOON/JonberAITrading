"""
Agent Group Chat Models

Core data models for the agent discussion and voting system.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# -------------------------------------------
# Enums
# -------------------------------------------


class AgentType(str, Enum):
    """Types of discussion agents."""
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    RISK = "risk"
    MODERATOR = "moderator"


class MessageType(str, Enum):
    """Types of chat messages."""
    ANALYSIS = "analysis"          # Initial analysis presentation
    OPINION = "opinion"            # General opinion statement
    QUESTION = "question"          # Question to another agent
    ANSWER = "answer"              # Answer to a question
    AGREEMENT = "agreement"        # Agreement with another agent
    DISAGREEMENT = "disagreement"  # Disagreement with reasoning
    PROPOSAL = "proposal"          # Trade proposal
    VOTE = "vote"                  # Final vote
    SUMMARY = "summary"            # Moderator summary
    DECISION = "decision"          # Final decision


class VoteType(str, Enum):
    """Vote options for agents."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"
    ABSTAIN = "abstain"


class SessionStatus(str, Enum):
    """Status of a chat session."""
    INITIALIZING = "initializing"  # Session created, waiting to start
    ANALYZING = "analyzing"        # Agents are presenting initial analysis
    DISCUSSING = "discussing"      # Agents are debating
    VOTING = "voting"              # Agents are voting
    DECIDED = "decided"            # Final decision made
    CANCELLED = "cancelled"        # Session cancelled
    TIMEOUT = "timeout"            # Session timed out


class DecisionAction(str, Enum):
    """Final decision actions."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    ADD = "ADD"
    REDUCE = "REDUCE"
    WATCH = "WATCH"
    NO_ACTION = "NO_ACTION"


# -------------------------------------------
# Core Models
# -------------------------------------------


class AgentMessage(BaseModel):
    """
    A single message in the agent chat.

    Represents what an agent says during the discussion.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)

    # Agent info
    agent_type: AgentType
    agent_name: str

    # Message content
    message_type: MessageType
    content: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    # Optional data payload
    data: Optional[Dict[str, Any]] = None

    # For replies
    in_response_to: Optional[str] = None  # ID of the message being responded to
    mentions: List[AgentType] = Field(default_factory=list)  # Agents mentioned

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )


class AgentVote(BaseModel):
    """
    An agent's vote on the trading decision.
    """
    agent_type: AgentType
    vote: VoteType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    key_factors: List[str] = Field(default_factory=list)

    # Risk-specific fields (only for risk agent)
    suggested_position_pct: Optional[float] = None
    suggested_stop_loss_pct: Optional[float] = None
    suggested_take_profit_pct: Optional[float] = None


class TradeDecision(BaseModel):
    """
    Final trading decision from the chat session.
    """
    action: DecisionAction
    confidence: float = Field(ge=0.0, le=1.0)
    consensus_level: float = Field(ge=0.0, le=1.0)

    # Trade parameters (if action is BUY/SELL/ADD/REDUCE)
    quantity: Optional[int] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_pct: Optional[float] = None

    # Decision reasoning
    rationale: str
    key_factors: List[str] = Field(default_factory=list)
    dissenting_opinions: List[str] = Field(default_factory=list)

    # Voting breakdown
    votes: Dict[str, str] = Field(default_factory=dict)  # agent_type -> vote


class MarketContext(BaseModel):
    """
    Market data context for the discussion.
    """
    ticker: str
    stock_name: str
    current_price: float
    price_change_pct: float

    # Technical data
    chart_data: Optional[List[Dict[str, Any]]] = None
    indicators: Optional[Dict[str, Any]] = None

    # Fundamental data
    per: Optional[float] = None
    pbr: Optional[float] = None
    eps: Optional[float] = None
    market_cap: Optional[float] = None

    # Sentiment data
    news_sentiment: Optional[str] = None
    news_count: Optional[int] = None

    # Position info (if already holding)
    has_position: bool = False
    position_quantity: Optional[int] = None
    position_avg_price: Optional[float] = None
    position_pnl_pct: Optional[float] = None

    # Portfolio context
    available_cash: Optional[float] = None
    total_portfolio_value: Optional[float] = None
    current_sector_exposure: Optional[float] = None


class ChatRound(BaseModel):
    """
    A single round of discussion.
    """
    round_number: int
    round_type: Literal["analysis", "discussion", "voting", "decision"]
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    messages: List[AgentMessage] = Field(default_factory=list)


class ChatSession(BaseModel):
    """
    Complete agent group chat session.

    Tracks all messages, votes, and the final decision.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Stock being discussed
    ticker: str
    stock_name: str

    # Session state
    status: SessionStatus = SessionStatus.INITIALIZING
    current_round: int = 0

    # Market context
    context: Optional[MarketContext] = None

    # Discussion content
    rounds: List[ChatRound] = Field(default_factory=list)
    all_messages: List[AgentMessage] = Field(default_factory=list)

    # Voting
    votes: List[AgentVote] = Field(default_factory=list)
    consensus_level: float = 0.0

    # Final decision
    decision: Optional[TradeDecision] = None

    # Timing
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    total_duration_seconds: Optional[float] = None

    # Configuration
    max_discussion_rounds: int = 3
    consensus_threshold: float = 0.75  # 75% agreement required

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    def add_message(self, message: AgentMessage) -> None:
        """Add a message to the session."""
        self.all_messages.append(message)
        self.updated_at = datetime.now()

        # Also add to current round if exists
        if self.rounds:
            self.rounds[-1].messages.append(message)

    def start_round(self, round_type: str) -> ChatRound:
        """Start a new discussion round."""
        self.current_round += 1
        new_round = ChatRound(
            round_number=self.current_round,
            round_type=round_type,
        )
        self.rounds.append(new_round)
        self.updated_at = datetime.now()
        return new_round

    def end_round(self) -> None:
        """End the current round."""
        if self.rounds:
            self.rounds[-1].ended_at = datetime.now()
        self.updated_at = datetime.now()

    def add_vote(self, vote: AgentVote) -> None:
        """Add an agent's vote."""
        # Remove existing vote from same agent
        self.votes = [v for v in self.votes if v.agent_type != vote.agent_type]
        self.votes.append(vote)
        self.updated_at = datetime.now()

    def calculate_consensus(self) -> float:
        """
        Calculate consensus level from votes.

        Returns:
            Consensus level between 0.0 and 1.0
        """
        if not self.votes:
            return 0.0

        # Agent weights
        weights = {
            AgentType.TECHNICAL: 0.25,
            AgentType.FUNDAMENTAL: 0.25,
            AgentType.SENTIMENT: 0.20,
            AgentType.RISK: 0.30,
        }

        # Count weighted votes by direction
        bullish_weight = 0.0
        bearish_weight = 0.0
        neutral_weight = 0.0

        for vote in self.votes:
            if vote.agent_type == AgentType.MODERATOR:
                continue  # Moderator doesn't vote

            weight = weights.get(vote.agent_type, 0.25)
            weighted_confidence = weight * vote.confidence

            if vote.vote in (VoteType.STRONG_BUY, VoteType.BUY):
                bullish_weight += weighted_confidence
            elif vote.vote in (VoteType.STRONG_SELL, VoteType.SELL):
                bearish_weight += weighted_confidence
            elif vote.vote == VoteType.HOLD:
                neutral_weight += weighted_confidence

        total_weight = bullish_weight + bearish_weight + neutral_weight
        if total_weight == 0:
            return 0.0

        # Consensus is the proportion of the dominant direction
        max_direction = max(bullish_weight, bearish_weight, neutral_weight)
        self.consensus_level = max_direction / total_weight

        return self.consensus_level

    def get_majority_direction(self) -> VoteType:
        """Get the majority vote direction."""
        if not self.votes:
            return VoteType.HOLD

        # Weighted vote counting
        weights = {
            AgentType.TECHNICAL: 0.25,
            AgentType.FUNDAMENTAL: 0.25,
            AgentType.SENTIMENT: 0.20,
            AgentType.RISK: 0.30,
        }

        direction_weights = {
            "bullish": 0.0,
            "bearish": 0.0,
            "neutral": 0.0,
        }

        for vote in self.votes:
            if vote.agent_type == AgentType.MODERATOR:
                continue

            weight = weights.get(vote.agent_type, 0.25) * vote.confidence

            if vote.vote in (VoteType.STRONG_BUY, VoteType.BUY):
                direction_weights["bullish"] += weight
            elif vote.vote in (VoteType.STRONG_SELL, VoteType.SELL):
                direction_weights["bearish"] += weight
            else:
                direction_weights["neutral"] += weight

        # Find dominant direction
        max_dir = max(direction_weights, key=direction_weights.get)

        if max_dir == "bullish":
            # Check if it's strong
            strong_count = sum(1 for v in self.votes if v.vote == VoteType.STRONG_BUY)
            return VoteType.STRONG_BUY if strong_count >= 2 else VoteType.BUY
        elif max_dir == "bearish":
            strong_count = sum(1 for v in self.votes if v.vote == VoteType.STRONG_SELL)
            return VoteType.STRONG_SELL if strong_count >= 2 else VoteType.SELL
        else:
            return VoteType.HOLD

    def finalize(self, decision: TradeDecision) -> None:
        """Finalize the session with a decision."""
        self.decision = decision
        self.status = SessionStatus.DECIDED
        self.ended_at = datetime.now()

        if self.started_at:
            self.total_duration_seconds = (self.ended_at - self.started_at).total_seconds()

        self.updated_at = datetime.now()


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def vote_to_action(vote: VoteType, has_position: bool) -> DecisionAction:
    """Convert a vote to a trading action considering position status."""
    if has_position:
        if vote in (VoteType.STRONG_BUY, VoteType.BUY):
            return DecisionAction.ADD
        elif vote == VoteType.STRONG_SELL:
            return DecisionAction.SELL
        elif vote == VoteType.SELL:
            return DecisionAction.REDUCE
        else:
            return DecisionAction.HOLD
    else:
        if vote in (VoteType.STRONG_BUY, VoteType.BUY):
            return DecisionAction.BUY
        elif vote in (VoteType.STRONG_SELL, VoteType.SELL):
            return DecisionAction.NO_ACTION
        else:
            return DecisionAction.WATCH


def calculate_weighted_confidence(votes: List[AgentVote]) -> float:
    """Calculate weighted average confidence from votes."""
    if not votes:
        return 0.0

    weights = {
        AgentType.TECHNICAL: 0.25,
        AgentType.FUNDAMENTAL: 0.25,
        AgentType.SENTIMENT: 0.20,
        AgentType.RISK: 0.30,
    }

    total_weight = 0.0
    weighted_sum = 0.0

    for vote in votes:
        if vote.agent_type == AgentType.MODERATOR:
            continue

        weight = weights.get(vote.agent_type, 0.25)
        total_weight += weight
        weighted_sum += weight * vote.confidence

    return weighted_sum / total_weight if total_weight > 0 else 0.0
