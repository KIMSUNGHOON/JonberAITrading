"""
Analysis API Schemas

Pydantic models for analysis request/response validation.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# -------------------------------------------
# Request Schemas
# -------------------------------------------


class AnalysisRequest(BaseModel):
    """Request to start a new analysis."""

    ticker: str = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Stock ticker symbol (e.g., AAPL)",
        examples=["AAPL", "NVDA", "TSLA"],
    )
    query: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional analysis query",
        examples=["Should I buy AAPL for a swing trade?"],
    )


# -------------------------------------------
# Response Schemas
# -------------------------------------------


class AnalysisResponse(BaseModel):
    """Response after starting analysis."""

    session_id: str = Field(description="Unique session identifier")
    ticker: str = Field(description="Stock ticker symbol")
    status: str = Field(description="Current status")
    message: str = Field(description="Status message")


class AnalysisSignals(BaseModel):
    """Structured signals from analysis."""

    trend: Optional[str] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None


class AnalysisSummary(BaseModel):
    """Summary of a single analysis."""

    agent_type: str
    signal: str
    confidence: float
    summary: str
    key_factors: list[str] = Field(default_factory=list)


class TradeProposalResponse(BaseModel):
    """Trade proposal details."""

    id: str
    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    quantity: int
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_score: float
    position_size_pct: float
    rationale: str
    bull_case: str = ""
    bear_case: str = ""
    created_at: datetime


class AnalysisStatusResponse(BaseModel):
    """Full analysis status response."""

    session_id: str
    ticker: str
    status: Literal["running", "awaiting_approval", "completed", "cancelled", "error"]
    current_stage: Optional[str] = None
    awaiting_approval: bool = False
    trade_proposal: Optional[TradeProposalResponse] = None
    analyses: list[AnalysisSummary] = Field(default_factory=list)
    reasoning_log: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class SessionListItem(BaseModel):
    """Session list item."""

    session_id: str
    ticker: str
    status: str
    created_at: Optional[datetime] = None


class SessionListResponse(BaseModel):
    """List of sessions response."""

    sessions: list[SessionListItem]
    total: int
