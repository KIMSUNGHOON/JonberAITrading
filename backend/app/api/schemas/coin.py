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


class TickerListResponse(BaseModel):
    """List of ticker information for multiple markets."""

    tickers: list[TickerResponse]
    total: int


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


# -------------------------------------------
# Account Schemas
# -------------------------------------------


class AccountBalance(BaseModel):
    """Single account balance entry."""

    currency: str = Field(description="Currency code (e.g., KRW, BTC)")
    balance: float = Field(description="Available balance")
    locked: float = Field(description="Locked balance (in orders)")
    avg_buy_price: float = Field(description="Average buy price")
    avg_buy_price_modified: bool = Field(description="Whether avg_buy_price was modified")
    unit_currency: str = Field(description="Unit currency (e.g., KRW)")


class AccountListResponse(BaseModel):
    """Account balances response."""

    accounts: list[AccountBalance]
    total_krw_value: Optional[float] = Field(
        default=None, description="Total estimated KRW value"
    )


# -------------------------------------------
# Order Schemas
# -------------------------------------------


class OrderRequest(BaseModel):
    """Order creation request."""

    market: str = Field(
        ...,
        description="Market code (e.g., KRW-BTC)",
        examples=["KRW-BTC", "KRW-ETH"],
    )
    side: Literal["bid", "ask"] = Field(
        ...,
        description="Order side: bid (buy) or ask (sell)",
    )
    ord_type: Literal["limit", "price", "market"] = Field(
        ...,
        description="Order type: limit (지정가), price (시장가 매수), market (시장가 매도)",
    )
    price: Optional[float] = Field(
        default=None,
        description="Order price (required for limit/price orders)",
    )
    volume: Optional[float] = Field(
        default=None,
        description="Order volume (required for limit/market orders)",
    )


class OrderResponse(BaseModel):
    """Order response from Upbit API."""

    uuid: str = Field(description="Order UUID")
    side: str = Field(description="Order side (bid/ask)")
    ord_type: str = Field(description="Order type")
    price: Optional[float] = Field(default=None, description="Order price")
    state: str = Field(description="Order state (wait, watch, done, cancel)")
    market: str = Field(description="Market code")
    created_at: datetime = Field(description="Order creation time")
    volume: Optional[float] = Field(default=None, description="Order volume")
    remaining_volume: Optional[float] = Field(
        default=None, description="Remaining volume"
    )
    reserved_fee: Optional[float] = Field(default=None, description="Reserved fee")
    remaining_fee: Optional[float] = Field(default=None, description="Remaining fee")
    paid_fee: Optional[float] = Field(default=None, description="Paid fee")
    locked: Optional[float] = Field(default=None, description="Locked amount")
    executed_volume: Optional[float] = Field(
        default=None, description="Executed volume"
    )
    trades_count: Optional[int] = Field(default=None, description="Number of trades")


class OrderListResponse(BaseModel):
    """List of orders response."""

    orders: list[OrderResponse]
    total: int


class OrderCancelResponse(BaseModel):
    """Order cancellation response."""

    uuid: str = Field(description="Cancelled order UUID")
    side: str
    ord_type: str
    price: Optional[float] = None
    state: str = Field(description="Order state after cancellation")
    market: str
    volume: Optional[float] = None
    remaining_volume: Optional[float] = None
    executed_volume: Optional[float] = None


# -------------------------------------------
# Position Schemas
# -------------------------------------------


class CoinPosition(BaseModel):
    """Open coin position with P&L calculation."""

    market: str = Field(description="Market code (e.g., KRW-BTC)")
    currency: str = Field(description="Currency code (e.g., BTC)")
    quantity: float = Field(description="Position quantity")
    avg_entry_price: float = Field(description="Average entry price")
    current_price: float = Field(description="Current market price")
    unrealized_pnl: float = Field(description="Unrealized profit/loss in KRW")
    unrealized_pnl_pct: float = Field(description="Unrealized P&L percentage")
    stop_loss: Optional[float] = Field(default=None, description="Stop-loss price")
    take_profit: Optional[float] = Field(default=None, description="Take-profit price")
    session_id: Optional[str] = Field(
        default=None, description="Associated analysis session"
    )
    created_at: datetime = Field(description="Position creation time")


class CoinPositionListResponse(BaseModel):
    """List of positions with portfolio summary."""

    positions: list[CoinPosition]
    total_value_krw: float = Field(description="Total position value in KRW")
    total_pnl: float = Field(description="Total unrealized P&L in KRW")
    total_pnl_pct: float = Field(description="Total P&L percentage")


# -------------------------------------------
# Trade History Schemas
# -------------------------------------------


class CoinTradeRecord(BaseModel):
    """Executed trade record."""

    id: str = Field(description="Trade ID")
    session_id: Optional[str] = Field(
        default=None, description="Associated analysis session"
    )
    market: str = Field(description="Market code")
    side: Literal["bid", "ask"] = Field(description="Trade side (bid=buy, ask=sell)")
    order_type: str = Field(description="Order type (limit, market, price)")
    price: float = Field(description="Execution price")
    volume: float = Field(description="Order volume")
    executed_volume: float = Field(description="Executed volume")
    fee: float = Field(default=0, description="Trading fee")
    total_krw: float = Field(description="Total value in KRW")
    state: str = Field(description="Trade state (done, cancel)")
    order_uuid: Optional[str] = Field(default=None, description="Upbit order UUID")
    created_at: datetime = Field(description="Trade creation time")


class CoinTradeListResponse(BaseModel):
    """Paginated trade history response."""

    trades: list[CoinTradeRecord]
    total: int = Field(description="Total number of trades")
    page: int = Field(description="Current page (1-indexed)")
    limit: int = Field(description="Results per page")
