"""
Korean Stock (Kiwoom) Analysis API Schemas

Pydantic models for Kiwoom REST API request/response validation.
Follows the same patterns as coin.py for consistency.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# -------------------------------------------
# Market Data Schemas
# -------------------------------------------


class KRStockInfo(BaseModel):
    """Korean stock basic information."""

    stk_cd: str = Field(description="Stock code (e.g., 005930)")
    stk_nm: str = Field(description="Stock name (e.g., 삼성전자)")
    cur_prc: int = Field(description="Current price (KRW)")
    prdy_ctrt: float = Field(description="Previous day change rate (%)")
    prdy_vrss: int = Field(description="Previous day price change")
    trde_qty: int = Field(description="Trading volume")
    trde_prica: int = Field(description="Trading value (KRW)")


class KRStockListResponse(BaseModel):
    """List of Korean stocks."""

    stocks: list[KRStockInfo]
    total: int


class KRStockTickerResponse(BaseModel):
    """Current ticker information for a Korean stock."""

    stk_cd: str = Field(description="Stock code")
    stk_nm: str = Field(description="Stock name")
    cur_prc: int = Field(description="Current price (KRW)")
    prdy_vrss: int = Field(description="Change from previous day")
    prdy_ctrt: float = Field(description="Change rate (%)")
    opng_prc: int = Field(description="Opening price")
    high_prc: int = Field(description="Day high")
    low_prc: int = Field(description="Day low")
    trde_qty: int = Field(description="Trading volume")
    trde_prica: int = Field(description="Trading value (KRW)")
    per: Optional[float] = Field(default=None, description="PER (Price Earnings Ratio)")
    pbr: Optional[float] = Field(default=None, description="PBR (Price Book Ratio)")
    eps: Optional[int] = Field(default=None, description="EPS (Earnings Per Share)")
    bps: Optional[int] = Field(default=None, description="BPS (Book-value Per Share)")
    timestamp: datetime = Field(description="Data timestamp")


class KRStockCandleData(BaseModel):
    """Single candle (OHLCV) data for Korean stock."""

    stck_bsop_date: str = Field(description="Trading date (YYYYMMDD)")
    stck_oprc: int = Field(description="Opening price")
    stck_hgpr: int = Field(description="High price")
    stck_lwpr: int = Field(description="Low price")
    stck_clpr: int = Field(description="Closing price")
    acml_vol: int = Field(description="Accumulated volume")
    acml_tr_pbmn: int = Field(description="Accumulated trading value")


class KRStockCandlesResponse(BaseModel):
    """List of candle data."""

    stk_cd: str = Field(description="Stock code")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
    candles: list[KRStockCandleData]
    period: str = Field(default="D", description="Period type (D=daily)")


class KRStockOrderbookUnit(BaseModel):
    """Single orderbook entry."""

    price: int = Field(description="Price level (KRW)")
    volume: int = Field(description="Volume at this price")
    change_rate: Optional[float] = Field(default=None, description="Price change rate from base")


class KRStockOrderbookResponse(BaseModel):
    """Orderbook data for Korean stock."""

    stk_cd: str = Field(description="Stock code")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
    asks: list[KRStockOrderbookUnit] = Field(description="Ask orders (매도호가)")
    bids: list[KRStockOrderbookUnit] = Field(description="Bid orders (매수호가)")
    total_ask_volume: int = Field(description="Total ask volume")
    total_bid_volume: int = Field(description="Total bid volume")
    bid_ask_ratio: float = Field(description="Bid/Ask ratio")
    timestamp: datetime = Field(description="Data timestamp")


# -------------------------------------------
# Analysis Request/Response Schemas
# -------------------------------------------


class KRStockAnalysisRequest(BaseModel):
    """Request to start Korean stock analysis."""

    stk_cd: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Stock code (e.g., 005930)",
        examples=["005930", "000660", "035420"],
    )
    query: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional analysis query",
        examples=["삼성전자 지금 매수해도 될까요?"],
    )


class KRStockAnalysisResponse(BaseModel):
    """Response after starting Korean stock analysis."""

    session_id: str = Field(description="Unique session identifier")
    stk_cd: str = Field(description="Stock code")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
    status: str = Field(description="Current status")
    message: str = Field(description="Status message")


class KRStockAnalysisSummary(BaseModel):
    """Summary of Korean stock analysis from each agent."""

    agent_type: str = Field(description="Agent type (technical, fundamental, sentiment, risk)")
    signal: str = Field(description="Signal (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL)")
    confidence: float = Field(description="Confidence score (0.0-1.0)")
    summary: str = Field(description="Analysis summary")
    key_factors: list[str] = Field(default_factory=list, description="Key factors")


class KRStockTradeProposalResponse(BaseModel):
    """Korean stock trade proposal details."""

    id: str = Field(description="Proposal ID")
    stk_cd: str = Field(description="Stock code")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
    action: Literal["BUY", "SELL", "HOLD"] = Field(description="Recommended action")
    quantity: int = Field(description="Recommended quantity (shares)")
    entry_price: Optional[int] = Field(default=None, description="Entry price (KRW)")
    stop_loss: Optional[int] = Field(default=None, description="Stop-loss price (KRW)")
    take_profit: Optional[int] = Field(default=None, description="Take-profit price (KRW)")
    risk_score: float = Field(description="Risk score (0.0-1.0)")
    position_size_pct: float = Field(description="Position size as % of portfolio")
    rationale: str = Field(description="Decision rationale")
    bull_case: str = Field(default="", description="Bull case scenario")
    bear_case: str = Field(default="", description="Bear case scenario")
    created_at: datetime = Field(description="Proposal creation time")


class KRStockAnalysisStatusResponse(BaseModel):
    """Full Korean stock analysis status response."""

    session_id: str = Field(description="Session ID")
    stk_cd: str = Field(description="Stock code")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
    status: Literal["running", "awaiting_approval", "completed", "cancelled", "error"] = Field(
        description="Session status"
    )
    current_stage: Optional[str] = Field(default=None, description="Current analysis stage")
    awaiting_approval: bool = Field(default=False, description="Whether awaiting HITL approval")
    trade_proposal: Optional[KRStockTradeProposalResponse] = Field(
        default=None, description="Trade proposal if available"
    )
    analyses: list[KRStockAnalysisSummary] = Field(
        default_factory=list, description="Analysis results"
    )
    reasoning_log: list[str] = Field(default_factory=list, description="Reasoning log entries")
    error: Optional[str] = Field(default=None, description="Error message if any")


# -------------------------------------------
# Stock Search Schema
# -------------------------------------------


class KRStockSearchRequest(BaseModel):
    """Stock search request."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Search query (stock code or name)",
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


class KRStockCashBalance(BaseModel):
    """Cash balance (예수금) information."""

    deposit: int = Field(description="Total deposit (예수금)")
    orderable_amount: int = Field(description="Orderable amount (주문가능금액)")
    withdrawable_amount: int = Field(description="Withdrawable amount (출금가능금액)")


class KRStockHolding(BaseModel):
    """Single stock holding in account."""

    stk_cd: str = Field(description="Stock code")
    stk_nm: str = Field(description="Stock name")
    quantity: int = Field(description="Holding quantity")
    avg_buy_price: int = Field(description="Average buy price")
    current_price: int = Field(description="Current price")
    eval_amount: int = Field(description="Evaluation amount")
    profit_loss: int = Field(description="Profit/Loss amount")
    profit_loss_rate: float = Field(description="Profit/Loss rate (%)")


class KRStockAccountResponse(BaseModel):
    """Account information response."""

    cash: KRStockCashBalance = Field(description="Cash balance")
    holdings: list[KRStockHolding] = Field(description="Stock holdings")
    total_eval_amount: int = Field(description="Total evaluation amount")
    total_profit_loss: int = Field(description="Total profit/loss")
    total_profit_loss_rate: float = Field(description="Total profit/loss rate (%)")


# -------------------------------------------
# Order Schemas
# -------------------------------------------


class KRStockOrderRequest(BaseModel):
    """Order creation request for Korean stock."""

    stk_cd: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Stock code (e.g., 005930)",
    )
    side: Literal["buy", "sell"] = Field(
        ...,
        description="Order side: buy or sell",
    )
    ord_type: Literal["limit", "market"] = Field(
        ...,
        description="Order type: limit (지정가) or market (시장가)",
    )
    price: Optional[int] = Field(
        default=None,
        description="Order price (required for limit orders)",
    )
    quantity: int = Field(
        ...,
        gt=0,
        description="Order quantity (number of shares)",
    )


class KRStockOrderResponse(BaseModel):
    """Order response from Kiwoom API."""

    order_id: str = Field(description="Order ID (주문번호)")
    stk_cd: str = Field(description="Stock code")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
    side: Literal["buy", "sell"] = Field(description="Order side")
    ord_type: str = Field(description="Order type")
    price: Optional[int] = Field(default=None, description="Order price")
    quantity: int = Field(description="Order quantity")
    executed_quantity: int = Field(default=0, description="Executed quantity")
    remaining_quantity: int = Field(description="Remaining quantity")
    status: Literal["pending", "partial", "completed", "cancelled"] = Field(
        description="Order status"
    )
    created_at: datetime = Field(description="Order creation time")


class KRStockOrderListResponse(BaseModel):
    """List of orders response."""

    orders: list[KRStockOrderResponse]
    total: int


class KRStockOrderCancelResponse(BaseModel):
    """Order cancellation response."""

    order_id: str = Field(description="Cancelled order ID")
    stk_cd: str = Field(description="Stock code")
    status: str = Field(description="Order status after cancellation")
    cancelled_quantity: int = Field(description="Cancelled quantity")


# -------------------------------------------
# Position Schemas
# -------------------------------------------


class KRStockPosition(BaseModel):
    """Open Korean stock position with P&L calculation."""

    stk_cd: str = Field(description="Stock code")
    stk_nm: str = Field(description="Stock name")
    quantity: int = Field(description="Position quantity")
    avg_entry_price: int = Field(description="Average entry price")
    current_price: int = Field(description="Current market price")
    unrealized_pnl: int = Field(description="Unrealized profit/loss (KRW)")
    unrealized_pnl_pct: float = Field(description="Unrealized P&L percentage")
    stop_loss: Optional[int] = Field(default=None, description="Stop-loss price")
    take_profit: Optional[int] = Field(default=None, description="Take-profit price")
    session_id: Optional[str] = Field(
        default=None, description="Associated analysis session"
    )
    created_at: datetime = Field(description="Position creation time")


class KRStockPositionListResponse(BaseModel):
    """List of positions with portfolio summary."""

    positions: list[KRStockPosition]
    total_value_krw: int = Field(description="Total position value (KRW)")
    total_pnl: int = Field(description="Total unrealized P&L (KRW)")
    total_pnl_pct: float = Field(description="Total P&L percentage")


# -------------------------------------------
# Trade History Schemas
# -------------------------------------------


class KRStockTradeRecord(BaseModel):
    """Executed trade record."""

    id: str = Field(description="Trade ID")
    session_id: Optional[str] = Field(
        default=None, description="Associated analysis session"
    )
    stk_cd: str = Field(description="Stock code")
    stk_nm: Optional[str] = Field(default=None, description="Stock name")
    side: Literal["buy", "sell"] = Field(description="Trade side")
    order_type: str = Field(description="Order type (limit, market)")
    price: int = Field(description="Execution price")
    quantity: int = Field(description="Order quantity")
    executed_quantity: int = Field(description="Executed quantity")
    fee: int = Field(default=0, description="Trading fee + tax")
    total_krw: int = Field(description="Total value (KRW)")
    status: str = Field(description="Trade status (completed, cancelled)")
    order_id: Optional[str] = Field(default=None, description="Kiwoom order ID")
    created_at: datetime = Field(description="Trade creation time")


class KRStockTradeListResponse(BaseModel):
    """Paginated trade history response."""

    trades: list[KRStockTradeRecord]
    total: int = Field(description="Total number of trades")
    page: int = Field(description="Current page (1-indexed)")
    limit: int = Field(description="Results per page")


# -------------------------------------------
# Settings Schemas
# -------------------------------------------


class KiwoomApiKeyRequest(BaseModel):
    """Kiwoom API key update request."""

    app_key: str = Field(
        ...,
        min_length=10,
        description="Kiwoom App Key",
    )
    app_secret: str = Field(
        ...,
        min_length=10,
        description="Kiwoom App Secret",
    )
    account_number: str = Field(
        ...,
        min_length=8,
        max_length=20,
        description="Account number (계좌번호)",
    )
    is_mock: bool = Field(
        default=True,
        description="True for mock trading, False for live trading",
    )


class KiwoomApiKeyStatus(BaseModel):
    """Kiwoom API configuration status."""

    is_configured: bool = Field(description="Whether API keys are configured")
    account_masked: Optional[str] = Field(
        default=None, description="Masked account number"
    )
    trading_mode: Literal["live", "paper"] = Field(
        default="paper", description="Trading mode"
    )
    is_valid: Optional[bool] = Field(
        default=None, description="Whether keys are valid (after validation)"
    )
    last_validated: Optional[datetime] = Field(
        default=None, description="Last validation timestamp"
    )


class KiwoomApiKeyResponse(BaseModel):
    """Response after updating Kiwoom API keys."""

    success: bool = Field(description="Whether update was successful")
    message: str = Field(description="Status message")
    status: KiwoomApiKeyStatus = Field(description="Current configuration status")


class KiwoomValidationResponse(BaseModel):
    """Kiwoom API key validation response."""

    is_valid: bool = Field(description="Whether keys are valid")
    message: str = Field(description="Validation message")
    account_info: Optional[dict] = Field(
        default=None, description="Account info if valid"
    )
