"""
LangGraph State Definitions for Korean Stock Trading Agent

Defines all state objects, data models, and type definitions
for the Korean stock multi-agent trading workflow using Kiwoom Securities API.
"""

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

    BUY = "BUY"        # 신규 매수 (미보유 시)
    SELL = "SELL"      # 전량 매도 (보유 시)
    HOLD = "HOLD"      # 유지 (보유 시)
    ADD = "ADD"        # 추가 매수 (보유 시)
    REDUCE = "REDUCE"  # 부분 매도 (보유 시)
    AVOID = "AVOID"    # 매수 금지 (미보유 + SELL 시그널)
    WATCH = "WATCH"    # 관망 (미보유 + HOLD 시그널) - 매수 고려 가능


class KRStockAnalysisStage(str, Enum):
    """Korean stock workflow stages."""

    DATA_COLLECTION = "data_collection"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    RISK = "risk"
    SYNTHESIS = "synthesis"
    APPROVAL = "approval"
    EXECUTION = "execution"
    COMPLETE = "complete"


# -------------------------------------------
# Korean Stock Specific Models
# -------------------------------------------


class KRStockMarketData(BaseModel):
    """Korean stock market data from Kiwoom."""

    stk_cd: str = Field(description="Stock code (e.g., 005930)")
    stk_nm: str = Field(description="Stock name (e.g., 삼성전자)")
    cur_prc: int = Field(description="Current price (원)")
    prdy_vrss: int = Field(description="Change from previous day (원)")
    prdy_ctrt: float = Field(description="Change rate from previous day (%)")
    acml_vol: int = Field(description="Accumulated trading volume")
    acml_tr_pbmn: int = Field(description="Accumulated trading value (원)")
    strt_prc: int = Field(description="Opening price")
    high_prc: int = Field(description="Today's high")
    low_prc: int = Field(description="Today's low")
    stk_hgpr: int = Field(description="Upper limit price")
    stk_lwpr: int = Field(description="Lower limit price")
    per: Optional[float] = Field(default=None, description="PER")
    pbr: Optional[float] = Field(default=None, description="PBR")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class KRStockAnalysisResult(BaseModel):
    """Result from a Korean stock analysis subagent."""

    agent_type: str = Field(description="Type of analyst agent")
    stk_cd: str = Field(description="Stock code (e.g., 005930)")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
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
=== {self.agent_type.upper()} 분석 ===
종목: {self.stk_nm or self.stk_cd} ({self.stk_cd})
시그널: {self.signal.value} (신뢰도: {self.confidence:.0%})

요약: {self.summary}

주요 요인:
{chr(10).join(f'- {f}' for f in self.key_factors)}

상세 분석:
{self.reasoning}
"""


class KRStockTechnicalSignals(BaseModel):
    """Korean stock technical analysis signals."""

    trend: Literal["bullish", "bearish", "neutral"] = "neutral"
    trend_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    rsi: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    macd_signal: Literal["bullish_crossover", "bearish_crossover", "neutral"] = "neutral"
    support_level: Optional[int] = None
    resistance_level: Optional[int] = None
    volume_trend: Literal["increasing", "decreasing", "stable"] = "stable"
    # Korean market specific
    foreign_net_buying: Optional[int] = None  # 외국인 순매수량
    institutional_net_buying: Optional[int] = None  # 기관 순매수량
    golden_cross: bool = False
    dead_cross: bool = False


class KRStockFundamentalSignals(BaseModel):
    """Korean stock fundamental analysis signals."""

    valuation: Literal["undervalued", "fair", "overvalued"] = "fair"
    per: Optional[float] = None
    pbr: Optional[float] = None
    eps: Optional[int] = None
    bps: Optional[int] = None
    dividend_yield: Optional[float] = None
    roe: Optional[float] = None
    debt_ratio: Optional[float] = None
    earnings_trend: Literal["improving", "stable", "declining"] = "stable"


class KRStockSentimentSignals(BaseModel):
    """Korean stock sentiment analysis signals."""

    news_sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    disclosure_impact: Literal["positive", "neutral", "negative"] = "neutral"
    analyst_consensus: Literal["buy", "hold", "sell"] = "hold"
    target_price_avg: Optional[int] = None
    foreign_ownership_trend: Literal["increasing", "stable", "decreasing"] = "stable"
    short_interest: Literal["high", "normal", "low"] = "normal"


# -------------------------------------------
# Trade Models
# -------------------------------------------


class KRStockTradeProposal(BaseModel):
    """Proposed Korean stock trade awaiting approval."""

    id: str = Field(description="Unique proposal ID")
    stk_cd: str = Field(description="Stock code (e.g., 005930)")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
    action: TradeAction = Field(description="Proposed action")
    quantity: int = Field(ge=0, description="Number of shares")

    # Price targets (in KRW)
    entry_price: Optional[int] = Field(default=None, ge=0)
    stop_loss: Optional[int] = Field(default=None, ge=0)
    take_profit: Optional[int] = Field(default=None, ge=0)

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


class KRStockPosition(BaseModel):
    """Active Korean stock trading position."""

    stk_cd: str
    stk_nm: Optional[str] = None
    quantity: int
    entry_price: int
    current_price: int
    stop_loss: Optional[int] = None
    take_profit: Optional[int] = None
    opened_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def pnl(self) -> int:
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
# Main Korean Stock Trading State (LangGraph TypedDict)
# -------------------------------------------


class KRStockTradingState(TypedDict, total=False):
    """
    Main state object for the LangGraph Korean stock trading workflow.

    This state flows through all nodes in the graph and accumulates
    results from each analysis stage.
    """

    # Input
    stk_cd: str  # e.g., "005930"
    stk_nm: Optional[str]  # e.g., "삼성전자"
    user_query: str

    # Session tracking
    session_id: Optional[str]

    # Messages for conversation tracking
    messages: Annotated[list, add_messages]

    # Market data (fetched from Kiwoom)
    market_data: Optional[dict]  # KRStockMarketData as dict
    chart_df: Optional[list[dict]]  # Daily chart data as list of dicts
    orderbook: Optional[dict]  # Orderbook data

    # Portfolio context (NEW - fetched during data collection)
    existing_position: Optional[dict]  # User's current position in this stock
    portfolio_summary: Optional[dict]  # Overall portfolio summary

    # Analysis results (stored as dicts for serialization)
    technical_analysis: Optional[dict]
    fundamental_analysis: Optional[dict]
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
    order_response: Optional[dict]

    # Reasoning trace - accumulates across nodes
    reasoning_log: Annotated[list[str], append_list]

    # Error handling
    error: Optional[str]

    # Workflow control
    current_stage: KRStockAnalysisStage


def create_kr_stock_initial_state(
    stk_cd: str,
    stk_nm: Optional[str] = None,
    user_query: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict:
    """
    Create initial state for a new Korean stock trading analysis workflow.

    Args:
        stk_cd: Stock code (e.g., "005930")
        stk_nm: Stock name (e.g., "삼성전자")
        user_query: Optional user query
        session_id: Optional session ID for tracking

    Returns:
        Initial state dictionary for LangGraph
    """
    return {
        # Input
        "stk_cd": stk_cd,
        "stk_nm": stk_nm,
        "user_query": user_query or f"{stk_nm or stk_cd} 종목 분석 및 매매 기회 탐색",

        # Session
        "session_id": session_id,

        # Messages for conversation tracking
        "messages": [],

        # Market data
        "market_data": None,
        "chart_df": None,
        "orderbook": None,

        # Portfolio context
        "existing_position": None,
        "portfolio_summary": None,

        # Analysis results
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

        # Re-analysis state
        "re_analyze_count": 0,
        "re_analyze_feedback": None,

        # Execution state
        "execution_status": None,
        "active_position": None,
        "order_response": None,

        # Reasoning trace
        "reasoning_log": [],

        # Error handling
        "error": None,

        # Workflow control
        "current_stage": KRStockAnalysisStage.DATA_COLLECTION,
    }


# -------------------------------------------
# State Update Helpers
# -------------------------------------------


def add_kr_stock_reasoning_log(state: dict, message: str) -> list[str]:
    """Add a message to the reasoning log."""
    current_log = state.get("reasoning_log", [])
    return current_log + [f"[{datetime.utcnow().strftime('%H:%M:%S')}] {message}"]


def get_all_kr_stock_analyses(state: dict) -> list[dict]:
    """Get all completed analyses from state (as dicts)."""
    analyses = []
    for key in ["technical_analysis", "fundamental_analysis", "sentiment_analysis", "risk_assessment"]:
        if state.get(key) is not None:
            analyses.append(state[key])
    return analyses


def kr_stock_analysis_dict_to_context_string(analysis: dict) -> str:
    """Convert Korean stock analysis dict to string for LLM context."""
    agent_type = analysis.get("agent_type", "unknown")
    stk_cd = analysis.get("stk_cd", "N/A")
    stk_nm = analysis.get("stk_nm", "")
    signal = analysis.get("signal", "hold")
    confidence = analysis.get("confidence", 0.5)
    summary = analysis.get("summary", "")
    key_factors = analysis.get("key_factors", [])
    reasoning = analysis.get("reasoning", "")

    stock_display = f"{stk_nm} ({stk_cd})" if stk_nm else stk_cd

    return f"""
=== {agent_type.upper()} 분석 ===
종목: {stock_display}
시그널: {signal} (신뢰도: {confidence:.0%})

요약: {summary}

주요 요인:
{chr(10).join(f'- {f}' for f in key_factors)}

상세 분석:
{reasoning}
"""


def _parse_kr_stock_signal(signal_value) -> SignalType:
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


def calculate_kr_stock_consensus_signal(analyses: list[dict]) -> tuple[SignalType, float]:
    """
    Calculate consensus signal from multiple Korean stock analyses.

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
        signal_values[_parse_kr_stock_signal(a.get("signal", "hold"))] * a.get("confidence", 0.5)
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
