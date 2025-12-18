"""
LangGraph State Definitions for Trading Agent

Defines all state objects, data models, and type definitions
for the multi-agent trading workflow.
"""

import operator
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


# -------------------------------------------
# Enums
# -------------------------------------------


class SignalType(str, Enum):
    """Trading signal types."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class TradeAction(str, Enum):
    """Trade action types."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class AnalysisStage(str, Enum):
    """Workflow stages."""

    DECOMPOSITION = "decomposition"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    RISK = "risk"
    SYNTHESIS = "synthesis"
    APPROVAL = "approval"
    EXECUTION = "execution"
    COMPLETE = "complete"


# -------------------------------------------
# Analysis Models
# -------------------------------------------


class AnalysisResult(BaseModel):
    """Result from a subagent analysis."""

    agent_type: str = Field(description="Type of analyst agent")
    ticker: str = Field(description="Stock ticker symbol")
    signal: SignalType = Field(default=SignalType.HOLD, description="Trading signal")
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score (0-1)",
    )
    summary: str = Field(default="", description="Brief summary of analysis")
    reasoning: str = Field(default="", description="Detailed reasoning")
    key_factors: list[str] = Field(
        default_factory=list,
        description="Key factors influencing the analysis",
    )
    signals: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured signal data",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def to_context_string(self) -> str:
        """Convert to string for LLM context."""
        return f"""
=== {self.agent_type.upper()} ANALYSIS ===
Ticker: {self.ticker}
Signal: {self.signal.value} (Confidence: {self.confidence:.0%})

Summary: {self.summary}

Key Factors:
{chr(10).join(f'- {f}' for f in self.key_factors)}

Detailed Reasoning:
{self.reasoning}
"""


class TechnicalSignals(BaseModel):
    """Technical analysis specific signals."""

    trend: Literal["bullish", "bearish", "neutral"] = "neutral"
    trend_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    rsi: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    macd_signal: Literal["bullish_crossover", "bearish_crossover", "neutral"] = "neutral"
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    volume_trend: Literal["increasing", "decreasing", "stable"] = "stable"


class FundamentalSignals(BaseModel):
    """Fundamental analysis specific signals."""

    valuation: Literal["undervalued", "fair", "overvalued"] = "fair"
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    earnings_trend: Literal["improving", "stable", "declining"] = "stable"


class SentimentSignals(BaseModel):
    """Sentiment analysis specific signals."""

    news_sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    social_sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    analyst_rating: Literal["buy", "hold", "sell"] = "hold"
    insider_activity: Literal["buying", "neutral", "selling"] = "neutral"
    institutional_flow: Literal["inflow", "neutral", "outflow"] = "neutral"


# -------------------------------------------
# Trade Models
# -------------------------------------------


class TradeProposal(BaseModel):
    """Proposed trade awaiting approval."""

    id: str = Field(description="Unique proposal ID")
    ticker: str = Field(description="Stock ticker symbol")
    action: TradeAction = Field(description="Proposed action")
    quantity: int = Field(ge=1, description="Number of shares")

    # Price targets
    entry_price: Optional[float] = Field(default=None, ge=0.0)
    stop_loss: Optional[float] = Field(default=None, ge=0.0)
    take_profit: Optional[float] = Field(default=None, ge=0.0)

    # Risk metrics
    risk_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Risk score (0=low, 1=high)",
    )
    position_size_pct: float = Field(
        default=5.0,
        ge=0.0,
        le=100.0,
        description="Position size as % of portfolio",
    )

    # Analysis backing
    rationale: str = Field(default="", description="Decision rationale")
    bull_case: str = Field(default="", description="Bull case arguments")
    bear_case: str = Field(default="", description="Bear case arguments")

    # Metadata (analyses stored as dicts for serialization)
    analyses: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Position(BaseModel):
    """Active trading position."""

    ticker: str
    quantity: int
    entry_price: float
    current_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def pnl(self) -> float:
        """Calculate profit/loss."""
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def pnl_percent(self) -> float:
        """Calculate profit/loss percentage."""
        if self.entry_price == 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100


# -------------------------------------------
# Task Decomposition
# -------------------------------------------


class SubTask(BaseModel):
    """A subtask for agent delegation."""

    task: str = Field(description="Task description")
    assigned_to: str = Field(description="Agent type to handle this task")
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    priority: int = Field(default=1, ge=1, le=5)
    result: Optional[str] = None


# -------------------------------------------
# Custom Reducers
# -------------------------------------------


def replace_value(current: Any, new: Any) -> Any:
    """Replace current value with new value (default LangGraph behavior)."""
    return new if new is not None else current


def append_list(current: list, new: list) -> list:
    """Append new items to existing list."""
    if current is None:
        current = []
    if new is None:
        new = []
    return current + new


# -------------------------------------------
# Main Trading State (LangGraph TypedDict)
# -------------------------------------------


class TradingState(TypedDict, total=False):
    """
    Main state object for the LangGraph trading workflow.

    This state flows through all nodes in the graph and accumulates
    results from each analysis stage.

    Using TypedDict with Annotated reducers for proper state accumulation.
    - Fields without reducers are replaced on each update
    - Fields with append_list reducer accumulate across nodes
    - messages uses add_messages for proper conversation handling
    """

    # Input - these are passed through unchanged
    ticker: str
    user_query: str

    # Messages for conversation tracking (uses LangGraph's add_messages)
    messages: Annotated[list, add_messages]

    # Task decomposition (replaced on update)
    todos: list[dict]

    # Analysis results (stored as dicts for serialization)
    technical_analysis: Optional[dict]
    fundamental_analysis: Optional[dict]
    sentiment_analysis: Optional[dict]
    risk_assessment: Optional[dict]

    # Synthesis for debate pattern
    synthesis: Optional[dict]

    # Strategic decision (stored as dict for serialization)
    trade_proposal: Optional[dict]

    # HITL state
    awaiting_approval: bool
    approval_status: Optional[str]
    user_feedback: Optional[str]

    # Execution state
    execution_status: Optional[str]
    active_position: Optional[dict]  # Position as dict for serialization

    # Reasoning trace - accumulates across nodes
    reasoning_log: Annotated[list[str], append_list]

    # Error handling
    error: Optional[str]

    # Workflow control
    current_stage: AnalysisStage


def create_initial_state(ticker: str, user_query: Optional[str] = None) -> dict:
    """
    Create initial state for a new trading analysis workflow.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        user_query: Optional user query, defaults to standard analysis request

    Returns:
        Initial state dictionary for LangGraph
    """
    return {
        # Input
        "ticker": ticker.upper(),
        "user_query": user_query or f"Analyze {ticker.upper()} for trading opportunity",

        # Messages for conversation tracking
        "messages": [],

        # Task decomposition
        "todos": [],

        # Analysis results (populated by subagents)
        "technical_analysis": None,
        "fundamental_analysis": None,
        "sentiment_analysis": None,
        "risk_assessment": None,

        # Synthesis
        "synthesis": None,

        # Strategic decision
        "trade_proposal": None,

        # HITL state
        "awaiting_approval": False,
        "approval_status": None,
        "user_feedback": None,

        # Execution state
        "execution_status": None,
        "active_position": None,

        # Reasoning trace
        "reasoning_log": [],

        # Error handling
        "error": None,

        # Workflow control
        "current_stage": AnalysisStage.DECOMPOSITION,
    }


# -------------------------------------------
# State Update Helpers
# -------------------------------------------


def add_reasoning_log(state: dict, message: str) -> list[str]:
    """Add a message to the reasoning log."""
    current_log = state.get("reasoning_log", [])
    return current_log + [f"[{datetime.utcnow().strftime('%H:%M:%S')}] {message}"]


def get_all_analyses(state: dict) -> list[dict]:
    """Get all completed analyses from state (as dicts)."""
    analyses = []
    for key in ["technical_analysis", "fundamental_analysis", "sentiment_analysis", "risk_assessment"]:
        if state.get(key) is not None:
            analyses.append(state[key])
    return analyses


def analysis_dict_to_context_string(analysis: dict) -> str:
    """Convert analysis dict to string for LLM context."""
    agent_type = analysis.get("agent_type", "unknown")
    ticker = analysis.get("ticker", "N/A")
    signal = analysis.get("signal", "hold")
    confidence = analysis.get("confidence", 0.5)
    summary = analysis.get("summary", "")
    key_factors = analysis.get("key_factors", [])
    reasoning = analysis.get("reasoning", "")

    return f"""
=== {agent_type.upper()} ANALYSIS ===
Ticker: {ticker}
Signal: {signal} (Confidence: {confidence:.0%})

Summary: {summary}

Key Factors:
{chr(10).join(f'- {f}' for f in key_factors)}

Detailed Reasoning:
{reasoning}
"""


def _parse_signal(signal_value) -> SignalType:
    """Parse signal from string or enum to SignalType."""
    if isinstance(signal_value, SignalType):
        return signal_value
    if isinstance(signal_value, str):
        # Handle string values
        signal_map = {
            "strong_buy": SignalType.STRONG_BUY,
            "buy": SignalType.BUY,
            "hold": SignalType.HOLD,
            "sell": SignalType.SELL,
            "strong_sell": SignalType.STRONG_SELL,
        }
        return signal_map.get(signal_value.lower(), SignalType.HOLD)
    return SignalType.HOLD


def calculate_consensus_signal(analyses: list[dict]) -> tuple[SignalType, float]:
    """
    Calculate consensus signal from multiple analyses (now dicts).

    Uses confidence-weighted voting.

    Returns:
        Tuple of (consensus_signal, average_confidence)
    """
    if not analyses:
        return SignalType.HOLD, 0.0

    # Signal to numeric mapping
    signal_values = {
        SignalType.STRONG_BUY: 2,
        SignalType.BUY: 1,
        SignalType.HOLD: 0,
        SignalType.SELL: -1,
        SignalType.STRONG_SELL: -2,
    }

    # Confidence-weighted average
    total_weight = sum(a.get("confidence", 0.5) for a in analyses)
    if total_weight == 0:
        return SignalType.HOLD, 0.0

    weighted_sum = sum(
        signal_values[_parse_signal(a.get("signal", "hold"))] * a.get("confidence", 0.5)
        for a in analyses
    )
    avg_signal = weighted_sum / total_weight
    avg_confidence = total_weight / len(analyses)

    # Map back to signal type
    if avg_signal >= 1.5:
        consensus = SignalType.STRONG_BUY
    elif avg_signal >= 0.5:
        consensus = SignalType.BUY
    elif avg_signal >= -0.5:
        consensus = SignalType.HOLD
    elif avg_signal >= -1.5:
        consensus = SignalType.SELL
    else:
        consensus = SignalType.STRONG_SELL

    return consensus, avg_confidence
