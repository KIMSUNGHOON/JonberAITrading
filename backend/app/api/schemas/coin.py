"""
Coin Analysis API Schemas

Pydantic models for Upbit coin analysis request/response validation.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# -------------------------------------------
# Market Data Schemas
# -------------------------------------------


class MarketInfo(BaseModel):
    """Market information."""

    market: str = Field(description="Market code (e.g., KRW-BTC)")
    korean_name: str = Field(description="Korean name")
    english_name: str = Field(description="English name")
    market_warning: Optional[str] = Field(default=None, description="Market warning type")


class MarketListResponse(BaseModel):
    """List of available markets."""

    markets: list[MarketInfo]
    total: int


class TickerResponse(BaseModel):
    """Current ticker information."""

    market: str
    trade_price: float = Field(description="Current price")
    change: str = Field(description="Change type (RISE, EVEN, FALL)")
    change_rate: float = Field(description="24h change rate")
    change_price: float = Field(description="24h price change")
    high_price: float = Field(description="24h high")
    low_price: float = Field(description="24h low")
    trade_volume: float = Field(description="24h trade volume")
    acc_trade_price_24h: float = Field(description="24h accumulated trade value (KRW)")
    timestamp: datetime


class CandleData(BaseModel):
    """Candle (OHLCV) data."""

    datetime: str = Field(description="Candle datetime (KST)")
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleListResponse(BaseModel):
    """List of candles."""

    market: str
    candles: list[CandleData]
    interval: str = Field(description="Candle interval (1m, 5m, 15m, 1h, 4h, 1d)")


class OrderbookUnit(BaseModel):
    """Single orderbook entry."""

    price: float
    size: float


class OrderbookResponse(BaseModel):
    """Orderbook data."""

    market: str
    total_ask_size: float = Field(description="Total ask volume")
    total_bid_size: float = Field(description="Total bid volume")
    bid_ask_ratio: float = Field(description="Bid/Ask ratio")
    asks: list[OrderbookUnit] = Field(description="Ask orders (sell)")
    bids: list[OrderbookUnit] = Field(description="Bid orders (buy)")
    timestamp: datetime


# -------------------------------------------
# Analysis Request/Response Schemas
# -------------------------------------------


class CoinAnalysisRequest(BaseModel):
    """Request to start coin analysis."""

    market: str = Field(
        ...,
        min_length=5,
        max_length=15,
        description="Market code (e.g., KRW-BTC)",
        examples=["KRW-BTC", "KRW-ETH", "KRW-XRP"],
    )
    query: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional analysis query",
        examples=["Should I buy BTC now?"],
    )


class CoinAnalysisResponse(BaseModel):
    """Response after starting coin analysis."""

    session_id: str = Field(description="Unique session identifier")
    market: str = Field(description="Market code")
    status: str = Field(description="Current status")
    message: str = Field(description="Status message")


class CoinAnalysisSummary(BaseModel):
    """Summary of coin analysis."""

    agent_type: str
    signal: str
    confidence: float
    summary: str
    key_factors: list[str] = Field(default_factory=list)


class CoinTradeProposalResponse(BaseModel):
    """Coin trade proposal details."""

    id: str
    market: str
    korean_name: Optional[str] = None
    action: Literal["BUY", "SELL", "HOLD"]
    quantity: float = Field(description="Coin quantity")
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_score: float
    position_size_pct: float
    rationale: str
    bull_case: str = ""
    bear_case: str = ""
    created_at: datetime


class CoinAnalysisStatusResponse(BaseModel):
    """Full coin analysis status response."""

    session_id: str
    market: str
    korean_name: Optional[str] = None
    status: Literal["running", "awaiting_approval", "completed", "cancelled", "error"]
    current_stage: Optional[str] = None
    awaiting_approval: bool = False
    trade_proposal: Optional[CoinTradeProposalResponse] = None
    analyses: list[CoinAnalysisSummary] = Field(default_factory=list)
    reasoning_log: list[str] = Field(default_factory=list)
    error: Optional[str] = None


# -------------------------------------------
# Market Search Schema
# -------------------------------------------


class MarketSearchRequest(BaseModel):
    """Market search request."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Search query (Korean/English name or market code)",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum results",
    )
