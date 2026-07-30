"""
Trading Models

Data models for the auto-trading system.
"""

from enum import Enum
from typing import Optional, List, Any, Dict
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# -------------------------------------------
# Enums
# -------------------------------------------

class TradingMode(str, Enum):
    """Trading system operation mode"""
    ACTIVE = "active"        # Normal operation
    PAUSED = "paused"        # Temporarily paused (can resume)
    STOPPED = "stopped"      # Completely stopped


class StopLossMode(str, Enum):
    """Stop-loss execution mode"""
    USER_APPROVAL = "user_approval"  # Requires user confirmation
    AGENT_AUTO = "agent_auto"        # Agent executes automatically


class PositionStatus(str, Enum):
    """Position lifecycle status"""
    PENDING = "pending"      # Order placed, waiting for fill
    PARTIAL = "partial"      # Partially filled
    FILLED = "filled"        # Fully filled, active position
    CLOSING = "closing"      # Close order in progress
    CLOSED = "closed"        # Position closed


class OrderType(str, Enum):
    """Order type"""
    MARKET = "market"        # Market order (immediate execution)
    LIMIT = "limit"          # Limit order (specific price)


class OrderSide(str, Enum):
    """Order side"""
    BUY = "buy"
    SELL = "sell"


class AlertType(str, Enum):
    """Trading alert types"""
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    SUDDEN_MOVE_UP = "sudden_move_up"
    SUDDEN_MOVE_DOWN = "sudden_move_down"
    TRADING_PAUSED = "trading_paused"
    TRADING_RESUMED = "trading_resumed"
    ORDER_FILLED = "order_filled"
    ORDER_FAILED = "order_failed"
    REBALANCE_SUGGESTED = "rebalance_suggested"
    NEWS_ALERT = "news_alert"


class ActivityType(str, Enum):
    """Activity log types for tracking agent decisions"""
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    SYSTEM_PAUSE = "system_pause"
    SYSTEM_RESUME = "system_resume"
    TRADE_APPROVED = "trade_approved"
    TRADE_REJECTED = "trade_rejected"
    TRADE_QUEUED = "trade_queued"
    TRADE_DEQUEUED = "trade_dequeued"
    ALLOCATION_CALCULATED = "allocation_calculated"
    ORDER_PLACED = "order_placed"
    ORDER_EXECUTED = "order_executed"
    ORDER_FAILED = "order_failed"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    RISK_ALERT = "risk_alert"
    MARKET_CLOSED = "market_closed"
    ACCOUNT_REFRESHED = "account_refreshed"
    STRATEGY_CHANGED = "strategy_changed"
    # Watch list activities
    WATCH_ADDED = "watch_added"
    WATCH_REMOVED = "watch_removed"
    WATCH_CONVERTED = "watch_converted"


class QueueStatus(str, Enum):
    """Trade queue status"""
    PENDING = "pending"        # Waiting for market open
    PROCESSING = "processing"  # Being executed
    COMPLETED = "completed"    # Successfully executed
    FAILED = "failed"          # Execution failed
    CANCELLED = "cancelled"    # Cancelled by user


class WatchStatus(str, Enum):
    """Watch list item status"""
    ACTIVE = "active"          # Actively monitoring
    TRIGGERED = "triggered"    # Conditions met, ready for action
    REMOVED = "removed"        # Removed from watch list
    CONVERTED = "converted"    # Converted to trade queue


class AgentStatus(str, Enum):
    """Individual agent status"""
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    ERROR = "error"


# -------------------------------------------
# Agent State Models
# -------------------------------------------

class AgentState(BaseModel):
    """State of an individual agent"""
    name: str
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[str] = None
    last_action: Optional[str] = None
    last_action_time: Optional[datetime] = None
    error_message: Optional[str] = None

    # Statistics
    tasks_completed: int = 0
    tasks_failed: int = 0

    # 세부 정보 (Sub Agent Status 개선)
    processing_stock: Optional[str] = None  # 현재 처리 중인 종목 (ticker)
    processing_stock_name: Optional[str] = None  # 종목명

    # 거래 세부 정보
    trade_details: Optional[Dict[str, Any]] = None
    # 예: {
    #   "action": "BUY",
    #   "quantity": 100,
    #   "entry_price": 55000,
    #   "stop_loss": 52000,
    #   "take_profit": 60000,
    #   "risk_score": 7,
    #   "position_pct": 10.5
    # }

    # 분석 결과 요약
    analysis_summary: Optional[Dict[str, Any]] = None
    # 예: {
    #   "technical": {"signal": "buy", "confidence": 0.75, "key_factors": ["RSI oversold", "MACD crossover"]},
    #   "fundamental": {"signal": "hold", "confidence": 0.6, "key_factors": ["P/E ratio high"]},
    #   "sentiment": {"signal": "buy", "confidence": 0.8, "key_factors": ["Positive news"]},
    #   "risk": {"level": "medium", "score": 6, "factors": ["High volatility"]}
    # }

    # 마지막 처리 결과
    last_result: Optional[Dict[str, Any]] = None
    # 예: {
    #   "success": True,
    #   "message": "Order placed successfully",
    #   "order_id": "ORD123",
    #   "filled_quantity": 100,
    #   "avg_price": 55100
    # }

    model_config = ConfigDict(use_enum_values=True)


# -------------------------------------------
# Risk Parameters
# -------------------------------------------

class RiskParameters(BaseModel):
    """Risk management parameters"""

    # Position limits
    max_single_position_pct: float = Field(
        default=0.15,
        ge=0.01, le=0.5,
        description="Maximum single position as % of total equity"
    )
    min_cash_ratio: float = Field(
        default=0.20,
        ge=0.0, le=0.9,
        description="Minimum cash reserve as % of total equity"
    )
    max_total_stock_pct: float = Field(
        default=0.80,
        ge=0.1, le=1.0,
        description="Maximum total stock allocation as % of total equity"
    )

    # Autonomy safety rails (R3 — enforced by services/autonomy/gate.py)
    max_daily_loss_pct: float = Field(
        default=3.0,
        ge=0.1, le=20.0,
        description="Daily realized-loss breaker %, autonomous mode (enforced via the gate seam; inert until a realized-P&L source is wired)"
    )
    max_open_positions: int = Field(
        default=5,
        ge=1, le=50,
        description="Maximum concurrent open positions for autonomous BUY/ADD"
    )
    max_trade_notional_pct: float = Field(
        default=15.0,
        ge=0.5, le=50.0,
        description="Per-trade notional cap as % of total account equity for autonomous BUY/ADD (전략이 [5,30] 바운드 내 적응)"
    )

    # Risk thresholds
    sudden_move_threshold_pct: float = Field(
        default=10.0,
        ge=1.0, le=30.0,
        description="% change to trigger sudden move alert"
    )

    # Sudden-move pause is PER-TICKER and auto-recovering (M1, C2 audit
    # 2026-07-13) — it does NOT use the global pause()/resume() kill-switch,
    # so one stock's dead-candle can no longer freeze stop-loss defense for
    # the whole book. See RiskMonitor._handle_sudden_move / _check_position.
    sudden_move_cooldown_ticks: int = Field(
        default=5,
        ge=1, le=100,
        description="Monitor ticks a ticker's stop-loss/take-profit stays "
                     "paused after a sudden move, before auto-recovering"
    )
    sudden_move_stabilization_pct: float = Field(
        default=3.0,
        ge=0.1, le=30.0,
        description="If a ticker's tick-to-tick price move falls at/under "
                     "this %% while cooling down, it auto-recovers early "
                     "(before sudden_move_cooldown_ticks elapses)"
    )

    # Trading limits
    max_daily_trades: int = Field(
        default=10,
        ge=1, le=100,
        description="Maximum trades per day"
    )

    # Stop-loss/Take-profit modes.
    #
    # S-2 (survival discipline, spec docs/superpowers/specs/
    # 2026-07-19-survival-discipline-design.md §2, decision D1): stop-loss
    # defaults to AGENT_AUTO — a stop-loss is never optional risk reduction,
    # so an autonomous account must not silently sit at a breached stop
    # waiting for a human click. take_profit_mode stays USER_APPROVAL
    # (decision D2 — profit-taking remains discussion-gated, unchanged).
    # This field is GATE_PROTECTED (strategy_apply.py) — a strategy
    # consensus can never move it; only a manual PUT /risk-params edit or
    # this model default can.
    stop_loss_mode: StopLossMode = StopLossMode.AGENT_AUTO
    take_profit_mode: StopLossMode = StopLossMode.USER_APPROVAL

    # Default stop/take levels applied to a newly tracked order when the
    # proposal didn't specify its own (F3 — PendingOrderTracker consumers)
    default_stop_loss_pct: float = Field(
        default=8.0,
        ge=0.5, le=30.0,
        description="Default stop-loss distance from entry, %"
    )
    default_take_profit_pct: float = Field(
        default=8.0,
        ge=0.5, le=50.0,
        description="Default take-profit distance from entry, %"
    )

    # S-4 (생존 규율 — docs/superpowers/specs/2026-07-19-survival-discipline-
    # design.md §2 S-4, decision D4): per-trade R risk budget as % of total
    # account equity. Both sizing sites (portfolio_agent
    # ._calculate_max_position_value, KR graph decision_nodes' quantity
    # calc) feed this into services.trading.r_sizing.r_cap_value and
    # min()-combine the result with their existing notional/cash caps — the
    # smaller of the two always wins, so this can only ever tighten sizing,
    # never loosen it. Hard Field bounds are deliberately loose (0.1-3.0);
    # the real ceiling is strategy_apply.STRATEGY_MAPPED_FIELDS' (0.25, 1.5)
    # EOD-consensus clamp. Not gate-protected (services/autonomy/gate.py
    # never reads it) — safe for a strategy to adapt.
    risk_budget_pct: float = Field(
        default=0.75,
        ge=0.1, le=3.0,
        description="Per-trade R risk budget as % of total equity — "
                     "position-value ceiling = equity*(risk_budget_pct/100)"
                     "/stop_distance_pct, min()-combined with existing caps"
    )


# -------------------------------------------
# Order Models
# -------------------------------------------

class OrderRequest(BaseModel):
    """Order request to be executed"""
    ticker: str
    stock_name: Optional[str] = None
    side: OrderSide
    quantity: int = Field(ge=1)
    price: Optional[float] = Field(default=None, ge=0)
    order_type: OrderType = OrderType.LIMIT

    # Metadata
    session_id: Optional[str] = None
    reason: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


class OrderResult(BaseModel):
    """Result of order execution"""
    order_id: str
    ticker: str
    side: OrderSide
    requested_quantity: int
    filled_quantity: int = 0
    avg_price: float = 0

    status: str  # pending, partial, filled, rejected, cancelled
    message: Optional[str] = None

    # F3: split orders place SEVERAL broker orders, each with its own ord_no —
    # the aggregate's order_id alone cannot drive per-order fill tracking
    # (ka10076 matches by ord_no). Set by OrderAgent._aggregate_results so the
    # fill tracker can register each part individually. None for single orders.
    parts: Optional[List["OrderResult"]] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None

    @property
    def is_filled(self) -> bool:
        return self.filled_quantity >= self.requested_quantity

    @property
    def total_value(self) -> float:
        return self.filled_quantity * self.avg_price


# -------------------------------------------
# Position Models
# -------------------------------------------

class ManagedPosition(BaseModel):
    """Active managed position"""
    ticker: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: float = 0

    # P&L
    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_price == 0:
            return 0
        return ((self.current_price - self.avg_price) / self.avg_price) * 100

    # Stop-loss / Take-profit
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss_mode: StopLossMode = StopLossMode.USER_APPROVAL

    # Status
    status: PositionStatus = PositionStatus.FILLED

    # Metadata
    entry_time: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    analysis_session_id: Optional[str] = None
    risk_score: Optional[int] = None

    # Set once when an AGENT_AUTO defensive sell (RiskMonitor stop-loss /
    # take-profit) is blocked by the autonomy gate, so the human is notified
    # ONCE per denied episode instead of on every monitor tick (mirrors
    # agent_chat.position_manager.MonitoredPosition.close_gate_denied_notified,
    # A2). Reset when the gate next allows. Defaults False so old persisted
    # positions restore cleanly.
    monitor_gate_denied_notified: bool = False

    # 통지 광역화 최종 리뷰 Important 4: 방어적 SELL(_close_position/
    # _reduce_position/_execute_order_from_monitor)이 브로커에서 거부되면
    # 예외가 아니라 정상 OrderResult(status="rejected")로 돌아온다 — 위
    # monitor_gate_denied_notified와 같은 형태로, 거부가 매 감시 틱마다
    # 반복돼도 사람에게는 거부 에피소드당 한 번만 통지한다(동일 이유로
    # 기본 False — 구 영속 포지션도 깨끗이 복원).
    close_order_rejected_notified: bool = False

    model_config = ConfigDict(use_enum_values=True)


# -------------------------------------------
# Allocation Models
# -------------------------------------------

class AllocationPlan(BaseModel):
    """Planned allocation for a trade"""
    ticker: str
    stock_name: Optional[str] = None
    side: OrderSide

    # Calculated values
    quantity: int
    entry_price: float
    estimated_amount: float
    position_pct: float  # % of total equity

    # Risk levels
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_score: Optional[int] = None

    # Adjustments (if any positions need to be reduced)
    rebalance_orders: List["OrderRequest"] = Field(default_factory=list)

    # Reason/rationale
    rationale: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


# -------------------------------------------
# Trade Queue Models
# -------------------------------------------

class QueuedTrade(BaseModel):
    """Trade waiting in queue for market open"""
    id: str = Field(default_factory=lambda: f"queue_{datetime.now().strftime('%Y%m%d%H%M%S%f')}")
    session_id: str
    ticker: str
    stock_name: Optional[str] = None

    # Trade details
    action: str  # BUY or SELL
    entry_price: float
    quantity: Optional[int] = None  # If None, calculate at execution time
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_score: int = 5

    # Queue status
    status: QueueStatus = QueueStatus.PENDING
    reason: str = ""  # Why it was queued (e.g., "Market closed")

    # R3: True when this trade originated from an autonomous engine — the
    # queue processor must RE-check the autonomy gate before executing it
    # (mode flips / breaker trips between queueing and execution must win).
    autonomous: bool = False

    # Timestamps
    queued_at: datetime = Field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None

    # Execution result
    allocation: Optional[AllocationPlan] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


# -------------------------------------------
# Watch List Models
# -------------------------------------------

class WatchedStock(BaseModel):
    """Stock in watch list for monitoring"""
    id: str = Field(default_factory=lambda: f"watch_{datetime.now().strftime('%Y%m%d%H%M%S%f')}")
    session_id: str
    ticker: str
    stock_name: Optional[str] = None

    # Analysis summary
    action: str = "WATCH"  # Original recommendation (WATCH)
    signal: str = "hold"  # Analysis signal (e.g., hold, sell)
    confidence: float = 0.5  # Analysis confidence (0-1)

    # Price information
    current_price: float = 0
    target_entry_price: Optional[float] = None  # Suggested entry price
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # Analysis summary
    analysis_summary: str = ""  # Brief summary of why it's on watch list
    key_factors: List[str] = Field(default_factory=list)

    # Status
    status: WatchStatus = WatchStatus.ACTIVE

    # Timestamps
    added_at: datetime = Field(default_factory=datetime.now)
    last_checked: Optional[datetime] = None
    triggered_at: Optional[datetime] = None

    # Metadata
    risk_score: int = 5  # 1-10

    # Provenance (DS-4): 'manual' (user/analysis-flow add, the historical
    # default) vs 'discovery' (regime-weighted ranking auto-promotion). Drives
    # the watch-total-cap eviction gate in services/discovery/ranker.py — only
    # 'discovery' entries are ever auto-evicted, manual entries are always
    # protected. A field default (not a migration) gives backward
    # compatibility for free: existing persisted blobs written before this
    # field existed simply lack the key, and `WatchedStock.model_validate(...)`
    # falls back to 'manual' for them.
    source: str = "manual"

    model_config = ConfigDict(use_enum_values=True)


# -------------------------------------------
# Alert Models
# -------------------------------------------

class TradingAlert(BaseModel):
    """Trading system alert"""
    id: str
    alert_type: AlertType
    ticker: Optional[str] = None

    # Alert data
    title: str
    message: str
    data: dict = Field(default_factory=dict)

    # Action options for user
    action_required: bool = False
    options: List[str] = Field(default_factory=list)

    # Status
    acknowledged: bool = False
    resolved: bool = False

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    acknowledged_at: Optional[datetime] = None

    model_config = ConfigDict(use_enum_values=True)


class ActivityLog(BaseModel):
    """Activity log entry for tracking agent decisions and actions"""
    id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S%f"))
    activity_type: ActivityType
    agent: str = "system"  # Which agent: system, portfolio, order, risk
    ticker: Optional[str] = None
    message: str
    details: Optional[dict] = None
    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict(use_enum_values=True)


# -------------------------------------------
# Trading State
# -------------------------------------------

class AccountInfo(BaseModel):
    """Account balance information"""
    total_equity: float = 0  # Total account value (cash + positions)
    available_cash: float = 0  # Available for trading
    total_stock_value: float = 0  # Current value of all positions

    @property
    def cash_ratio(self) -> float:
        if self.total_equity == 0:
            return 1.0
        return self.available_cash / self.total_equity

    @property
    def stock_ratio(self) -> float:
        if self.total_equity == 0:
            return 0.0
        return self.total_stock_value / self.total_equity


class TradingState(BaseModel):
    """Complete trading system state"""
    mode: TradingMode = TradingMode.STOPPED

    # Account
    account: AccountInfo = Field(default_factory=AccountInfo)

    # Positions
    positions: List[ManagedPosition] = Field(default_factory=list)
    pending_orders: List[OrderRequest] = Field(default_factory=list)

    # Trade Queue (for market-closed orders)
    trade_queue: List["QueuedTrade"] = Field(default_factory=list)

    # Watch List (for WATCH recommendations)
    watch_list: List["WatchedStock"] = Field(default_factory=list)

    # Today's activity
    daily_trades_count: int = 0
    daily_pnl: float = 0

    # Risk parameters
    risk_params: RiskParameters = Field(default_factory=RiskParameters)

    # Alerts
    pending_alerts: List[TradingAlert] = Field(default_factory=list)

    # Activity log (recent agent decisions)
    activity_log: List[ActivityLog] = Field(default_factory=list)

    # Agent states (for status display)
    agent_states: Dict[str, AgentState] = Field(default_factory=lambda: {
        "portfolio": AgentState(name="Portfolio Agent"),
        "order": AgentState(name="Order Agent"),
        "risk": AgentState(name="Risk Monitor"),
    })

    # Timestamps
    last_updated: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions)

    @property
    def total_unrealized_pnl_pct(self) -> float:
        total_cost = sum(p.avg_price * p.quantity for p in self.positions)
        if total_cost == 0:
            return 0.0
        return (self.total_unrealized_pnl / total_cost) * 100

    @property
    def max_single_position_value(self) -> float:
        if not self.positions:
            return 0
        return max(p.current_price * p.quantity for p in self.positions)

    @property
    def can_trade(self) -> bool:
        return (
            self.mode == TradingMode.ACTIVE and
            self.daily_trades_count < self.risk_params.max_daily_trades
        )

    model_config = ConfigDict(use_enum_values=True)
