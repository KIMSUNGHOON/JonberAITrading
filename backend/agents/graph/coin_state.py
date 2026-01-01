"""
LangGraph State Definitions for Coin Trading Agent

Defines all state objects, data models, and type definitions
for the cryptocurrency multi-agent trading workflow using Upbit API.
"""

import operator
from datetime import datetime, timezone
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


class CoinAnalysisStage(str, Enum):
    """Coin workflow stages."""

    DATA_COLLECTION = "data_collection"
    TECHNICAL = "technical"
    MARKET_ANALYSIS = "market_analysis"
    SENTIMENT = "sentiment"
    RISK = "risk"
    SYNTHESIS = "synthesis"
    APPROVAL = "approval"
    EXECUTION = "execution"
    COMPLETE = "complete"


# -------------------------------------------
# Cryptocurrency Specific Models
# -------------------------------------------


class CryptoMarketData(BaseModel):
    """Cryptocurrency market data from Upbit."""

    market: str = Field(description="Market code (e.g., KRW-BTC)")
    korean_name: Optional[str] = Field(default=None, description="Korean name")
    current_price: float = Field(description="Current trading price")
    change_rate_24h: float = Field(description="24h change rate (%)")
    volume_24h: float = Field(description="24h trading volume")
    high_24h: float = Field(description="24h high price")
    low_24h: float = Field(description="24h low price")
    bid_ask_ratio: float = Field(description="Bid/Ask volume ratio")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CoinAnalysisResult(BaseModel):
    """Result from a coin analysis subagent."""

    agent_type: str = Field(description="Type of analyst agent")
    market: str = Field(description="Market code (e.g., KRW-BTC)")
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
Market: {self.market}
Signal: {self.signal.value} (Confidence: {self.confidence:.0%})

Summary: {self.summary}

Key Factors:
{chr(10).join(f'- {f}' for f in self.key_factors)}

Detailed Reasoning:
{self.reasoning}
"""


class CryptoTechnicalSignals(BaseModel):
    """Crypto-specific technical analysis signals."""

    trend: Literal["bullish", "bearish", "neutral"] = "neutral"
    trend_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    rsi: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    macd_signal: Literal["bullish_crossover", "bearish_crossover", "neutral"] = "neutral"
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    volume_trend: Literal["increasing", "decreasing", "stable"] = "stable"
    # Crypto-specific
    volume_24h_change: Optional[float] = None
    bid_ask_imbalance: Optional[float] = None  # >1 = more buyers
    trade_velocity: Optional[float] = None  # trades per minute


class CryptoMarketSignals(BaseModel):
    """Crypto market analysis signals (replaces Fundamental for crypto)."""

    btc_correlation: Optional[float] = None  # Correlation with BTC
    market_dominance: Optional[float] = None  # % of total crypto market
    exchange_inflow: Literal["high", "normal", "low"] = "normal"
    exchange_outflow: Literal["high", "normal", "low"] = "normal"
    whale_activity: Literal["accumulating", "neutral", "distributing"] = "neutral"


class CryptoSentimentSignals(BaseModel):
    """Crypto sentiment analysis signals."""

    fear_greed_index: Optional[int] = Field(default=None, ge=0, le=100)
    social_sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    news_sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    twitter_volume: Literal["high", "normal", "low"] = "normal"
    reddit_sentiment: Literal["bullish", "neutral", "bearish"] = "neutral"


# -------------------------------------------
# Trade Models
# -------------------------------------------


class CoinTradeProposal(BaseModel):
    """Proposed coin trade awaiting approval."""

    id: str = Field(description="Unique proposal ID")
    market: str = Field(description="Market code (e.g., KRW-BTC)")
    korean_name: Optional[str] = Field(default=None, description="Korean name")
    action: TradeAction = Field(description="Proposed action")
    quantity: float = Field(ge=0, description="Coin quantity")

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

    # Metadata
    analyses: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CoinPosition(BaseModel):
    """Active coin trading position."""

    market: str
    quantity: float
    entry_price: float
    current_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def pnl(self) -> float:
        """Calculate profit/loss in KRW."""
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def pnl_percent(self) -> float:
        """Calculate profit/loss percentage."""
        if self.entry_price == 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100


# -------------------------------------------
# Custom Reducers
# -------------------------------------------


def append_list(current: list, new: list) -> list:
    """Append new items to existing list."""
    if current is None:
        current = []
    if new is None:
        new = []
    return current + new


# -------------------------------------------
# Main Coin Trading State (LangGraph TypedDict)
# -------------------------------------------


class CoinTradingState(TypedDict, total=False):
    """
    Main state object for the LangGraph coin trading workflow.

    This state flows through all nodes in the graph and accumulates
    results from each analysis stage.
    """

    # Input
    market: str  # e.g., "KRW-BTC"
    korean_name: Optional[str]
    user_query: str

    # Messages for conversation tracking
    messages: Annotated[list, add_messages]

    # Market data (fetched from Upbit)
    market_data: Optional[dict]  # CryptoMarketData as dict
    candles: Optional[list[dict]]  # List of candle data
    orderbook: Optional[dict]  # Orderbook data
    trades: Optional[list[dict]]  # Recent trades

    # Analysis results (stored as dicts for serialization)
    technical_analysis: Optional[dict]
    market_analysis: Optional[dict]  # Replaces fundamental for crypto
    sentiment_analysis: Optional[dict]
    risk_assessment: Optional[dict]

    # Synthesis
    synthesis: Optional[dict]

    # Strategic decision
    trade_proposal: Optional[dict]

    # HITL state
    awaiting_approval: bool
    approval_status: Optional[str]
    user_feedback: Optional[str]

    # Re-analysis state
    re_analyze_count: int
    re_analyze_feedback: Optional[str]

    # Execution state
    execution_status: Optional[str]
    active_position: Optional[dict]

    # Reasoning trace - accumulates across nodes
    reasoning_log: Annotated[list[str], append_list]

    # Error handling
    error: Optional[str]

    # Workflow control
    current_stage: CoinAnalysisStage


def create_coin_initial_state(
    market: str,
    korean_name: Optional[str] = None,
    user_query: Optional[str] = None,
) -> dict:
    """
    Create initial state for a new coin trading analysis workflow.

    Args:
        market: Market code (e.g., "KRW-BTC")
        korean_name: Korean name of the coin
        user_query: Optional user query

    Returns:
        Initial state dictionary for LangGraph
    """
    return {
        # Input
        "market": market.upper(),
        "korean_name": korean_name,
        "user_query": user_query or f"Analyze {market.upper()} for trading opportunity",

        # Messages for conversation tracking
        "messages": [],

        # Market data
        "market_data": None,
        "candles": None,
        "orderbook": None,
        "trades": None,

        # Analysis results
        "technical_analysis": None,
        "market_analysis": None,
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

        # Re-analysis state
        "re_analyze_count": 0,
        "re_analyze_feedback": None,

        # Execution state
        "execution_status": None,
        "active_position": None,

        # Reasoning trace
        "reasoning_log": [],

        # Error handling
        "error": None,

        # Workflow control
        "current_stage": CoinAnalysisStage.DATA_COLLECTION,
    }


# -------------------------------------------
# State Update Helpers
# -------------------------------------------


def add_coin_reasoning_log(state: dict, message: str) -> list[str]:
    """Add a message to the reasoning log."""
    current_log = state.get("reasoning_log", [])
    return current_log + [f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}"]


def get_all_coin_analyses(state: dict) -> list[dict]:
    """Get all completed analyses from state (as dicts)."""
    analyses = []
    for key in ["technical_analysis", "market_analysis", "sentiment_analysis", "risk_assessment"]:
        if state.get(key) is not None:
            analyses.append(state[key])
    return analyses


def coin_analysis_dict_to_context_string(analysis: dict) -> str:
    """Convert coin analysis dict to string for LLM context."""
    agent_type = analysis.get("agent_type", "unknown")
    market = analysis.get("market", "N/A")
    signal = analysis.get("signal", "hold")
    confidence = analysis.get("confidence", 0.5)
    summary = analysis.get("summary", "")
    key_factors = analysis.get("key_factors", [])
    reasoning = analysis.get("reasoning", "")

    return f"""
=== {agent_type.upper()} ANALYSIS ===
Market: {market}
Signal: {signal} (Confidence: {confidence:.0%})

Summary: {summary}

Key Factors:
{chr(10).join(f'- {f}' for f in key_factors)}

Detailed Reasoning:
{reasoning}
"""


def _parse_coin_signal(signal_value) -> SignalType:
    """Parse signal from string or enum to SignalType."""
    if isinstance(signal_value, SignalType):
        return signal_value
    if isinstance(signal_value, str):
        signal_map = {
            "strong_buy": SignalType.STRONG_BUY,
            "buy": SignalType.BUY,
            "hold": SignalType.HOLD,
            "sell": SignalType.SELL,
            "strong_sell": SignalType.STRONG_SELL,
        }
        return signal_map.get(signal_value.lower(), SignalType.HOLD)
    return SignalType.HOLD


def calculate_coin_consensus_signal(analyses: list[dict]) -> tuple[SignalType, float]:
    """
    Calculate consensus signal from multiple coin analyses.

    Uses confidence-weighted voting.

    Returns:
        Tuple of (consensus_signal, average_confidence)
    """
    if not analyses:
        return SignalType.HOLD, 0.0

    signal_values = {
        SignalType.STRONG_BUY: 2,
        SignalType.BUY: 1,
        SignalType.HOLD: 0,
        SignalType.SELL: -1,
        SignalType.STRONG_SELL: -2,
    }

    total_weight = sum(a.get("confidence", 0.5) for a in analyses)
    if total_weight == 0:
        return SignalType.HOLD, 0.0

    weighted_sum = sum(
        signal_values[_parse_coin_signal(a.get("signal", "hold"))] * a.get("confidence", 0.5)
        for a in analyses
    )
    avg_signal = weighted_sum / total_weight
    avg_confidence = total_weight / len(analyses)

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
