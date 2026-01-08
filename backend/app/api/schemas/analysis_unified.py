"""
Unified Analysis Schemas

Provides unified request/response schemas for all market types:
- stock: US/international stocks
- kr_stock: Korean stocks (Kiwoom)
- coin: Cryptocurrency (Upbit)
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Market Types
# =============================================================================

MarketType = Literal["stock", "kr_stock", "coin"]


# =============================================================================
# Unified Request Schemas
# =============================================================================


class UnifiedAnalysisRequest(BaseModel):
    """
    Unified analysis request for all market types.

    Automatically routes to the appropriate analysis graph based on market_type.

    Examples:
        - stock: {"market_type": "stock", "ticker": "AAPL"}
        - kr_stock: {"market_type": "kr_stock", "ticker": "005930"}
        - coin: {"market_type": "coin", "ticker": "KRW-BTC"}
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"market_type": "stock", "ticker": "AAPL", "query": "Should I buy?"},
                {"market_type": "kr_stock", "ticker": "005930"},
                {"market_type": "coin", "ticker": "KRW-BTC"},
            ]
        }
    )

    market_type: MarketType = Field(
        ...,
        description="Market type: stock, kr_stock, or coin",
    )
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Ticker symbol (e.g., AAPL, 005930, KRW-BTC)",
    )
    query: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional analysis query",
    )
    # Additional fields for specific market types
    name: Optional[str] = Field(
        default=None,
        description="Asset name (optional, auto-fetched if not provided)",
    )


# =============================================================================
# Unified Response Schemas
# =============================================================================


class UnifiedAnalysisSummary(BaseModel):
    """Summary of a single analysis (technical, fundamental, sentiment)."""

    type: str = Field(..., description="Analysis type (technical, fundamental, sentiment)")
    signal: str = Field(..., description="Signal (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL)")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score (0-1)")
    summary: str = Field(..., description="Brief analysis summary")
    key_factors: list[str] = Field(default_factory=list, description="Key factors")


class UnifiedTradeProposal(BaseModel):
    """Trade proposal from analysis."""

    action: str = Field(..., description="Trade action (BUY, SELL, HOLD, ADD, REDUCE, WATCH, AVOID)")
    confidence: float = Field(..., ge=0, le=1, description="Overall confidence")
    target_price: Optional[float] = Field(default=None, description="Target price")
    stop_loss: Optional[float] = Field(default=None, description="Stop loss price")
    take_profit: Optional[float] = Field(default=None, description="Take profit price")
    position_size: Optional[float] = Field(default=None, description="Suggested position size")
    reasoning: str = Field(..., description="Reasoning for the proposal")


class UnifiedAnalysisStatusResponse(BaseModel):
    """
    Unified analysis status response.

    Works for all market types with market-specific metadata.
    """

    model_config = ConfigDict(from_attributes=True)

    session_id: str = Field(..., description="Unique session ID")
    market_type: MarketType = Field(..., description="Market type")
    ticker: str = Field(..., description="Ticker symbol")
    name: Optional[str] = Field(default=None, description="Asset name")
    status: str = Field(..., description="Status (pending, running, completed, failed, cancelled)")

    # Analysis results
    analyses: list[UnifiedAnalysisSummary] = Field(
        default_factory=list,
        description="List of completed analyses",
    )
    trade_proposal: Optional[UnifiedTradeProposal] = Field(
        default=None,
        description="Trade proposal (if analysis completed)",
    )

    # Progress tracking
    current_stage: Optional[str] = Field(default=None, description="Current analysis stage")
    reasoning_log: list[str] = Field(default_factory=list, description="Reasoning log")

    # Timestamps
    created_at: Optional[datetime] = Field(default=None, description="Session creation time")
    updated_at: Optional[datetime] = Field(default=None, description="Last update time")

    # Market-specific metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Market-specific additional data",
    )

    # Error handling
    error: Optional[str] = Field(default=None, description="Error message if failed")


class UnifiedSessionListResponse(BaseModel):
    """List of analysis sessions."""

    sessions: list[UnifiedAnalysisStatusResponse] = Field(
        default_factory=list,
        description="List of sessions",
    )
    total: int = Field(default=0, description="Total count")
    by_market_type: dict[str, int] = Field(
        default_factory=dict,
        description="Count by market type",
    )


class UnifiedAnalysisResponse(BaseModel):
    """Response when starting a new analysis."""

    session_id: str = Field(..., description="New session ID")
    market_type: MarketType = Field(..., description="Market type")
    ticker: str = Field(..., description="Ticker symbol")
    status: str = Field(default="pending", description="Initial status")
    message: str = Field(..., description="Status message")
