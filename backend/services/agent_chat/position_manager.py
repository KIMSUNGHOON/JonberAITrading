"""
Position Manager

Real-time position monitoring with Agent Group Chat integration.
Triggers agent discussions for position management decisions.
"""

import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable, Any

import structlog
from pydantic import BaseModel, Field

from services.agent_chat.models import (
    MarketContext,
    DecisionAction,
)

logger = structlog.get_logger()


# -------------------------------------------
# Position Event Types
# -------------------------------------------


class PositionEventType(str, Enum):
    """Types of position events that can trigger discussions."""
    STOP_LOSS_NEAR = "stop_loss_near"          # Price approaching stop-loss
    STOP_LOSS_HIT = "stop_loss_hit"            # Stop-loss triggered
    TAKE_PROFIT_NEAR = "take_profit_near"      # Price approaching take-profit
    TAKE_PROFIT_HIT = "take_profit_hit"        # Take-profit triggered
    SIGNIFICANT_GAIN = "significant_gain"      # Significant unrealized gain
    SIGNIFICANT_LOSS = "significant_loss"      # Significant unrealized loss
    TRAILING_STOP_UPDATE = "trailing_stop"     # Trailing stop needs update
    HOLDING_PERIOD_LONG = "holding_long"       # Position held for extended period
    VOLATILITY_SPIKE = "volatility_spike"      # Sudden volatility increase
    NEWS_IMPACT = "news_impact"                # News affecting position


# Korean translations for position events
POSITION_EVENT_KOREAN = {
    PositionEventType.STOP_LOSS_NEAR: {
        "name": "손절가 근접",
        "description": "현재가가 손절 가격에 근접했습니다. 리스크 관리를 위해 포지션 점검이 필요합니다.",
    },
    PositionEventType.STOP_LOSS_HIT: {
        "name": "손절가 도달",
        "description": "손절 가격에 도달하여 손실 확대를 방지하기 위한 포지션 청산이 권고됩니다.",
    },
    PositionEventType.TAKE_PROFIT_NEAR: {
        "name": "익절가 근접",
        "description": "현재가가 목표 익절 가격에 근접했습니다. 수익 실현 타이밍을 고려해 주세요.",
    },
    PositionEventType.TAKE_PROFIT_HIT: {
        "name": "익절가 도달",
        "description": "목표 익절 가격에 도달했습니다. 수익 실현이 권고됩니다.",
    },
    PositionEventType.SIGNIFICANT_GAIN: {
        "name": "상당한 수익 발생",
        "description": "상당한 미실현 수익이 발생했습니다. 트레일링 스탑 설정 또는 부분 익절을 고려해 주세요.",
    },
    PositionEventType.SIGNIFICANT_LOSS: {
        "name": "상당한 손실 발생",
        "description": "상당한 미실현 손실이 발생했습니다. 포지션 재검토 및 리스크 관리가 필요합니다.",
    },
    PositionEventType.TRAILING_STOP_UPDATE: {
        "name": "트레일링 스탑 갱신",
        "description": "고점 갱신으로 트레일링 스탑이 상향 조정되었습니다.",
    },
    PositionEventType.HOLDING_PERIOD_LONG: {
        "name": "장기 보유",
        "description": "장기간 보유 중인 포지션입니다. 투자 전략 재검토를 권고합니다.",
    },
    PositionEventType.VOLATILITY_SPIKE: {
        "name": "변동성 급등",
        "description": "급격한 가격 변동이 감지되었습니다. 리스크 관리에 주의가 필요합니다.",
    },
    PositionEventType.NEWS_IMPACT: {
        "name": "뉴스 영향",
        "description": "관련 뉴스가 포지션에 영향을 줄 수 있습니다. 상황을 모니터링 해주세요.",
    },
}


def get_event_korean(event_type: PositionEventType) -> dict:
    """Get Korean translation for a position event type."""
    return POSITION_EVENT_KOREAN.get(event_type, {
        "name": event_type.value,
        "description": "",
    })


class PositionAction(str, Enum):
    """Actions that can be taken on positions."""
    HOLD = "hold"                    # Keep position
    CLOSE_FULL = "close_full"        # Close entire position
    CLOSE_PARTIAL = "close_partial"  # Close part of position
    ADD = "add"                      # Add to position
    UPDATE_STOPS = "update_stops"    # Update stop-loss/take-profit
    TRAIL_STOP = "trail_stop"        # Enable/update trailing stop


# -------------------------------------------
# Position Models
# -------------------------------------------


class MonitoredPosition(BaseModel):
    """A position being monitored by the position manager."""
    ticker: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: float = 0

    # Stop levels
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    trailing_stop_price: Optional[float] = None

    # Tracking
    highest_price: float = 0  # For trailing stop
    lowest_price: float = 0
    entry_time: datetime = Field(default_factory=datetime.now)
    last_check: datetime = Field(default_factory=datetime.now)
    last_discussion: Optional[datetime] = None

    # Event tracking
    events_triggered: List[str] = Field(default_factory=list)
    discussion_count: int = 0

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_price == 0:
            return 0
        return ((self.current_price - self.avg_price) / self.avg_price) * 100

    @property
    def position_value(self) -> float:
        return self.current_price * self.quantity

    @property
    def holding_days(self) -> int:
        return (datetime.now() - self.entry_time).days


class PositionEvent(BaseModel):
    """An event triggered for a position."""
    id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S%f"))
    ticker: str
    event_type: PositionEventType
    timestamp: datetime = Field(default_factory=datetime.now)
    current_price: float
    trigger_value: float  # The value that triggered the event
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    requires_discussion: bool = True
    auto_execute: bool = False


class PositionDecision(BaseModel):
    """Decision made for a position by agent discussion."""
    ticker: str
    action: PositionAction
    quantity: Optional[int] = None  # For partial close
    new_stop_loss: Optional[float] = None
    new_take_profit: Optional[float] = None
    new_trailing_pct: Optional[float] = None
    confidence: float = 0.5
    consensus_level: float = 0.0
    rationale: str = ""
    key_factors: List[str] = Field(default_factory=list)


# -------------------------------------------
# Position Manager Configuration
# -------------------------------------------


class PositionManagerConfig(BaseModel):
    """Configuration for the position manager."""
    # Check intervals
    check_interval_seconds: int = 30

    # Threshold settings
    stop_loss_warning_pct: float = 2.0    # Warn when within 2% of stop-loss
    take_profit_warning_pct: float = 2.0  # Warn when within 2% of take-profit
    significant_gain_pct: float = 10.0    # Significant gain threshold
    significant_loss_pct: float = 5.0     # Significant loss threshold
    volatility_threshold_pct: float = 5.0 # Sudden move threshold

    # Trailing stop defaults
    default_trailing_pct: float = 5.0
    trailing_activation_pct: float = 5.0  # Activate trailing after 5% gain

    # Discussion limits
    min_discussion_interval_minutes: int = 30
    max_discussions_per_position: int = 5

    # Holding period
    long_holding_days: int = 30

    # Auto-execution settings
    auto_execute_stop_loss: bool = False
    auto_execute_take_profit: bool = False
    auto_update_trailing: bool = True


# -------------------------------------------
# Position Manager
# -------------------------------------------


class PositionManager:
    """
    Manages positions with Agent Group Chat integration.

    Responsibilities:
    - Real-time position monitoring
    - Trigger agent discussions for position decisions
    - Execute position management actions
    - Trailing stop management
    - Position lifecycle tracking
    """

    def __init__(
        self,
        config: Optional[PositionManagerConfig] = None,
    ):
        """
        Initialize position manager.

        Args:
            config: Manager configuration
        """
        self.config = config or PositionManagerConfig()

        # Monitored positions
        self._positions: Dict[str, MonitoredPosition] = {}

        # Event history
        self._events: List[PositionEvent] = []
        self._pending_events: List[PositionEvent] = []

        # State
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Callbacks
        self._on_event_callbacks: List[Callable] = []
        self._on_decision_callbacks: List[Callable] = []

        # Chat coordinator reference (set by coordinator)
        self._chat_coordinator = None

        logger.info(
            "position_manager_initialized",
            check_interval=self.config.check_interval_seconds,
        )

    def set_chat_coordinator(self, coordinator) -> None:
        """Set reference to chat coordinator for triggering discussions."""
        self._chat_coordinator = coordinator

    def on_event(self, callback: Callable) -> None:
        """Register callback for position events."""
        self._on_event_callbacks.append(callback)

    def on_decision(self, callback: Callable) -> None:
        """Register callback for position decisions."""
        self._on_decision_callbacks.append(callback)

    # -------------------------------------------
    # Lifecycle
    # -------------------------------------------

    async def start(self) -> None:
        """Start position monitoring."""
        if self._running:
            logger.warning("position_manager_already_running")
            return

        logger.info("position_manager_starting")
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("position_manager_started")

    async def stop(self) -> None:
        """Stop position monitoring."""
        if not self._running:
            return

        logger.info("position_manager_stopping")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("position_manager_stopped")

    # -------------------------------------------
    # Position Management
    # -------------------------------------------

    def add_position(
        self,
        ticker: str,
        stock_name: str,
        quantity: int,
        avg_price: float,
        current_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop_pct: Optional[float] = None,
    ) -> MonitoredPosition:
        """
        Add a position to monitor.

        Args:
            ticker: Stock ticker
            stock_name: Stock name
            quantity: Position quantity
            avg_price: Average entry price
            current_price: Current price (optional)
            stop_loss: Stop-loss price
            take_profit: Take-profit price
            trailing_stop_pct: Trailing stop percentage

        Returns:
            Created MonitoredPosition
        """
        position = MonitoredPosition(
            ticker=ticker,
            stock_name=stock_name,
            quantity=quantity,
            avg_price=avg_price,
            current_price=current_price or avg_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop_pct=trailing_stop_pct,
            highest_price=current_price or avg_price,
            lowest_price=current_price or avg_price,
        )

        self._positions[ticker] = position

        logger.info(
            "position_added",
            ticker=ticker,
            quantity=quantity,
            avg_price=avg_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        return position

    def update_position(
        self,
        ticker: str,
        quantity: Optional[int] = None,
        current_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop_pct: Optional[float] = None,
    ) -> Optional[MonitoredPosition]:
        """Update a monitored position."""
        if ticker not in self._positions:
            return None

        position = self._positions[ticker]

        if quantity is not None:
            position.quantity = quantity

        if current_price is not None:
            position.current_price = current_price
            if current_price > position.highest_price:
                position.highest_price = current_price
            if current_price < position.lowest_price or position.lowest_price == 0:
                position.lowest_price = current_price

        if stop_loss is not None:
            position.stop_loss = stop_loss

        if take_profit is not None:
            position.take_profit = take_profit

        if trailing_stop_pct is not None:
            position.trailing_stop_pct = trailing_stop_pct

        position.last_check = datetime.now()

        return position

    def remove_position(self, ticker: str) -> bool:
        """Remove a position from monitoring."""
        if ticker in self._positions:
            del self._positions[ticker]
            logger.info("position_removed", ticker=ticker)
            return True
        return False

    def get_position(self, ticker: str) -> Optional[MonitoredPosition]:
        """Get a specific position."""
        return self._positions.get(ticker)

    def get_all_positions(self) -> List[MonitoredPosition]:
        """Get all monitored positions."""
        return list(self._positions.values())

    # -------------------------------------------
    # Monitoring Loop
    # -------------------------------------------

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_all_positions()
                await asyncio.sleep(self.config.check_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("position_monitor_error", error=str(e))
                await asyncio.sleep(5)

    async def _check_all_positions(self) -> None:
        """Check all positions for events."""
        if not self._positions:
            return

        # Update prices first
        await self._update_prices()

        # Check each position
        for ticker, position in list(self._positions.items()):
            try:
                await self._check_position(position)
            except Exception as e:
                logger.error(
                    "position_check_error",
                    ticker=ticker,
                    error=str(e),
                )

    async def _update_prices(self) -> None:
        """Update current prices for all positions."""
        try:
            from agents.tools.kr_market_data import get_kr_stock_info

            for ticker, position in self._positions.items():
                try:
                    info = await get_kr_stock_info(ticker)
                    if info and "cur_prc" in info:
                        new_price = info["cur_prc"]
                        self.update_position(ticker, current_price=new_price)
                except Exception as e:
                    logger.warning(
                        "price_update_failed",
                        ticker=ticker,
                        error=str(e),
                    )
        except ImportError:
            # Fallback: prices not updated
            pass

    async def _check_position(self, position: MonitoredPosition) -> None:
        """Check a single position for events."""
        events = []

        # Check stop-loss proximity
        if position.stop_loss:
            stop_distance_pct = (
                (position.current_price - position.stop_loss) / position.current_price * 100
            )

            if stop_distance_pct <= 0:
                # Stop-loss hit
                events.append(self._create_event(
                    position, PositionEventType.STOP_LOSS_HIT,
                    position.stop_loss,
                    f"손절가 도달: ₩{position.current_price:,.0f} <= ₩{position.stop_loss:,.0f}",
                    auto_execute=self.config.auto_execute_stop_loss,
                ))
            elif stop_distance_pct <= self.config.stop_loss_warning_pct:
                # Approaching stop-loss
                if PositionEventType.STOP_LOSS_NEAR.value not in position.events_triggered:
                    events.append(self._create_event(
                        position, PositionEventType.STOP_LOSS_NEAR,
                        stop_distance_pct,
                        f"손절가 근접: {stop_distance_pct:.1f}% 거리",
                    ))
                    position.events_triggered.append(PositionEventType.STOP_LOSS_NEAR.value)

        # Check take-profit proximity
        if position.take_profit:
            tp_distance_pct = (
                (position.take_profit - position.current_price) / position.current_price * 100
            )

            if tp_distance_pct <= 0:
                # Take-profit hit
                events.append(self._create_event(
                    position, PositionEventType.TAKE_PROFIT_HIT,
                    position.take_profit,
                    f"익절가 도달: ₩{position.current_price:,.0f} >= ₩{position.take_profit:,.0f}",
                    auto_execute=self.config.auto_execute_take_profit,
                ))
            elif tp_distance_pct <= self.config.take_profit_warning_pct:
                # Approaching take-profit
                if PositionEventType.TAKE_PROFIT_NEAR.value not in position.events_triggered:
                    events.append(self._create_event(
                        position, PositionEventType.TAKE_PROFIT_NEAR,
                        tp_distance_pct,
                        f"익절가 근접: {tp_distance_pct:.1f}% 거리",
                    ))
                    position.events_triggered.append(PositionEventType.TAKE_PROFIT_NEAR.value)

        # Check significant gain/loss
        pnl_pct = position.unrealized_pnl_pct

        if pnl_pct >= self.config.significant_gain_pct:
            if PositionEventType.SIGNIFICANT_GAIN.value not in position.events_triggered:
                events.append(self._create_event(
                    position, PositionEventType.SIGNIFICANT_GAIN,
                    pnl_pct,
                    f"상당한 수익: {pnl_pct:.1f}% (₩{position.unrealized_pnl:,.0f})",
                ))
                position.events_triggered.append(PositionEventType.SIGNIFICANT_GAIN.value)

        if pnl_pct <= -self.config.significant_loss_pct:
            if PositionEventType.SIGNIFICANT_LOSS.value not in position.events_triggered:
                events.append(self._create_event(
                    position, PositionEventType.SIGNIFICANT_LOSS,
                    pnl_pct,
                    f"상당한 손실: {pnl_pct:.1f}% (₩{position.unrealized_pnl:,.0f})",
                ))
                position.events_triggered.append(PositionEventType.SIGNIFICANT_LOSS.value)

        # Check trailing stop
        if position.trailing_stop_pct:
            await self._check_trailing_stop(position, events)
        elif pnl_pct >= self.config.trailing_activation_pct:
            # Auto-activate trailing stop
            if self.config.auto_update_trailing:
                position.trailing_stop_pct = self.config.default_trailing_pct
                logger.info(
                    "trailing_stop_activated",
                    ticker=position.ticker,
                    trailing_pct=position.trailing_stop_pct,
                )

        # Check long holding period
        if position.holding_days >= self.config.long_holding_days:
            if PositionEventType.HOLDING_PERIOD_LONG.value not in position.events_triggered:
                events.append(self._create_event(
                    position, PositionEventType.HOLDING_PERIOD_LONG,
                    position.holding_days,
                    f"장기 보유: {position.holding_days}일 경과",
                ))
                position.events_triggered.append(PositionEventType.HOLDING_PERIOD_LONG.value)

        # Process events
        for event in events:
            await self._handle_event(event, position)

    async def _check_trailing_stop(
        self,
        position: MonitoredPosition,
        events: List[PositionEvent],
    ) -> None:
        """Check and update trailing stop."""
        if not position.trailing_stop_pct:
            return

        # Calculate trailing stop price
        new_trailing_price = position.highest_price * (1 - position.trailing_stop_pct / 100)

        # Update if higher than current trailing stop
        if (
            position.trailing_stop_price is None or
            new_trailing_price > position.trailing_stop_price
        ):
            old_price = position.trailing_stop_price
            position.trailing_stop_price = new_trailing_price

            # Also update stop-loss if trailing stop is higher
            if position.stop_loss is None or new_trailing_price > position.stop_loss:
                position.stop_loss = new_trailing_price

            if old_price:
                events.append(self._create_event(
                    position, PositionEventType.TRAILING_STOP_UPDATE,
                    new_trailing_price,
                    f"트레일링 스탑 갱신: ₩{old_price:,.0f} → ₩{new_trailing_price:,.0f}",
                    requires_discussion=False,
                ))

    def _create_event(
        self,
        position: MonitoredPosition,
        event_type: PositionEventType,
        trigger_value: float,
        message: str,
        requires_discussion: bool = True,
        auto_execute: bool = False,
    ) -> PositionEvent:
        """Create a position event."""
        return PositionEvent(
            ticker=position.ticker,
            event_type=event_type,
            current_price=position.current_price,
            trigger_value=trigger_value,
            message=message,
            data={
                "stock_name": position.stock_name,
                "quantity": position.quantity,
                "avg_price": position.avg_price,
                "unrealized_pnl": position.unrealized_pnl,
                "unrealized_pnl_pct": position.unrealized_pnl_pct,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
            },
            requires_discussion=requires_discussion,
            auto_execute=auto_execute,
        )

    async def _handle_event(
        self,
        event: PositionEvent,
        position: MonitoredPosition,
    ) -> None:
        """Handle a position event."""
        logger.info(
            "position_event",
            ticker=event.ticker,
            event_type=event.event_type.value,
            message=event.message,
        )

        # Store event
        self._events.append(event)
        if len(self._events) > 500:
            self._events = self._events[-500:]

        # Notify callbacks
        for callback in self._on_event_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.warning("event_callback_failed", error=str(e))

        # Auto-execute if configured
        if event.auto_execute:
            await self._auto_execute_event(event, position)
            return

        # Check if discussion is needed
        if event.requires_discussion:
            # Check discussion limits
            if self._should_trigger_discussion(position):
                await self._trigger_discussion(event, position)

        # Send Telegram notification
        await self._notify_event(event)

    def _should_trigger_discussion(self, position: MonitoredPosition) -> bool:
        """Check if a discussion should be triggered."""
        # Check max discussions
        if position.discussion_count >= self.config.max_discussions_per_position:
            return False

        # Check discussion interval
        if position.last_discussion:
            min_interval = timedelta(minutes=self.config.min_discussion_interval_minutes)
            if datetime.now() - position.last_discussion < min_interval:
                return False

        return True

    async def _trigger_discussion(
        self,
        event: PositionEvent,
        position: MonitoredPosition,
    ) -> None:
        """Trigger an agent discussion for the position event."""
        if not self._chat_coordinator:
            logger.warning("no_chat_coordinator_for_discussion")
            return

        logger.info(
            "triggering_position_discussion",
            ticker=position.ticker,
            event_type=event.event_type.value,
        )

        try:
            # Start discussion via coordinator
            session = await self._chat_coordinator.start_manual_discussion(
                ticker=position.ticker,
                stock_name=position.stock_name,
            )

            position.discussion_count += 1
            position.last_discussion = datetime.now()

            # Handle decision
            if session.decision:
                await self._apply_decision(position, session.decision)

        except Exception as e:
            logger.error(
                "position_discussion_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _auto_execute_event(
        self,
        event: PositionEvent,
        position: MonitoredPosition,
    ) -> None:
        """Auto-execute based on event type."""
        logger.info(
            "auto_executing_event",
            ticker=event.ticker,
            event_type=event.event_type.value,
        )

        try:
            if event.event_type == PositionEventType.STOP_LOSS_HIT:
                await self._execute_close_position(position, "stop_loss")
            elif event.event_type == PositionEventType.TAKE_PROFIT_HIT:
                await self._execute_close_position(position, "take_profit")
        except Exception as e:
            logger.error(
                "auto_execute_failed",
                ticker=event.ticker,
                error=str(e),
            )

    async def _execute_close_position(
        self,
        position: MonitoredPosition,
        reason: str,
    ) -> None:
        """Execute position close via trading coordinator."""
        try:
            from app.dependencies import get_trading_coordinator
            trading_coord = await get_trading_coordinator()

            await trading_coord._close_position(position.ticker)

            # Remove from monitoring
            self.remove_position(position.ticker)

            logger.info(
                "position_closed",
                ticker=position.ticker,
                reason=reason,
            )

        except Exception as e:
            logger.error(
                "close_position_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _apply_decision(
        self,
        position: MonitoredPosition,
        decision,
    ) -> None:
        """Apply a decision from agent discussion to the position."""
        from services.agent_chat.models import DecisionAction

        logger.info(
            "applying_position_decision",
            ticker=position.ticker,
            action=decision.action.value if hasattr(decision.action, 'value') else decision.action,
        )

        try:
            if decision.action == DecisionAction.SELL:
                await self._execute_close_position(position, "agent_decision")

            elif decision.action == DecisionAction.REDUCE:
                # Partial close - calculate quantity
                if decision.quantity:
                    # Update position quantity
                    new_quantity = position.quantity - decision.quantity
                    if new_quantity <= 0:
                        await self._execute_close_position(position, "agent_decision_reduce")
                    else:
                        self.update_position(position.ticker, quantity=new_quantity)

            elif decision.action in (DecisionAction.HOLD, DecisionAction.ADD):
                # Update stops if provided
                if decision.stop_loss:
                    self.update_position(position.ticker, stop_loss=decision.stop_loss)
                if decision.take_profit:
                    self.update_position(position.ticker, take_profit=decision.take_profit)

            # Notify decision callbacks
            for callback in self._on_decision_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(position.ticker, decision)
                    else:
                        callback(position.ticker, decision)
                except Exception as e:
                    logger.warning("decision_callback_failed", error=str(e))

        except Exception as e:
            logger.error(
                "apply_decision_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _notify_event(self, event: PositionEvent) -> None:
        """Send Telegram notification for event."""
        try:
            from services.telegram import get_telegram_notifier
            telegram = await get_telegram_notifier()

            if not telegram.is_ready:
                return

            event_emoji = {
                PositionEventType.STOP_LOSS_HIT: "🔴",
                PositionEventType.STOP_LOSS_NEAR: "⚠️",
                PositionEventType.TAKE_PROFIT_HIT: "🟢",
                PositionEventType.TAKE_PROFIT_NEAR: "🎯",
                PositionEventType.SIGNIFICANT_GAIN: "📈",
                PositionEventType.SIGNIFICANT_LOSS: "📉",
                PositionEventType.TRAILING_STOP_UPDATE: "📊",
                PositionEventType.HOLDING_PERIOD_LONG: "📅",
                PositionEventType.VOLATILITY_SPIKE: "⚡",
                PositionEventType.NEWS_IMPACT: "📰",
            }

            emoji = event_emoji.get(event.event_type, "📋")

            # Get Korean translation for event type
            event_korean = get_event_korean(event.event_type)
            event_name = event_korean["name"]
            event_description = event_korean["description"]

            # Format PnL
            pnl_pct = event.data.get('unrealized_pnl_pct', 0)
            pnl_value = event.data.get('unrealized_pnl', 0)
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"

            message = f"""{emoji} *포지션 이벤트*

*종목:* {event.data.get('stock_name', event.ticker)} ({event.ticker})
*이벤트:* {event_name}
*현재가:* ₩{event.current_price:,.0f}

*상세:* {event.message}

*판단 근거:*
{event_description}

{pnl_emoji} *손익:* {pnl_pct:+.1f}% (₩{pnl_value:+,.0f})
"""
            # Add stop/take-profit info if available
            if event.data.get('stop_loss') or event.data.get('take_profit'):
                message += "\n*설정 현황:*\n"
                if event.data.get('stop_loss'):
                    message += f"  • 손절가: ₩{event.data['stop_loss']:,.0f}\n"
                if event.data.get('take_profit'):
                    message += f"  • 익절가: ₩{event.data['take_profit']:,.0f}\n"

            await telegram.send_message(message)

        except Exception as e:
            logger.warning("telegram_notification_failed", error=str(e))

    # -------------------------------------------
    # Public API
    # -------------------------------------------

    def get_events(
        self,
        ticker: Optional[str] = None,
        event_type: Optional[PositionEventType] = None,
        limit: int = 50,
    ) -> List[PositionEvent]:
        """Get position events."""
        events = self._events

        if ticker:
            events = [e for e in events if e.ticker == ticker]

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        return events[-limit:]

    def get_summary(self) -> Dict[str, Any]:
        """Get position manager summary."""
        positions = self.get_all_positions()

        total_value = sum(p.position_value for p in positions)
        total_pnl = sum(p.unrealized_pnl for p in positions)

        return {
            "is_running": self._running,
            "position_count": len(positions),
            "total_value": total_value,
            "total_unrealized_pnl": total_pnl,
            "total_unrealized_pnl_pct": (total_pnl / total_value * 100) if total_value else 0,
            "event_count": len(self._events),
            "positions": [
                {
                    "ticker": p.ticker,
                    "stock_name": p.stock_name,
                    "quantity": p.quantity,
                    "avg_price": p.avg_price,
                    "current_price": p.current_price,
                    "unrealized_pnl_pct": p.unrealized_pnl_pct,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "holding_days": p.holding_days,
                }
                for p in positions
            ],
        }

    async def sync_from_account(self) -> None:
        """Sync positions from account holdings."""
        try:
            from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

            client = await get_shared_kiwoom_client_async()
            account = await client.get_account_balance()

            # Update or add positions from holdings
            for holding in account.holdings:
                if holding.hldg_qty <= 0:
                    continue

                if holding.stk_cd in self._positions:
                    # Update existing
                    self.update_position(
                        ticker=holding.stk_cd,
                        quantity=holding.hldg_qty,
                        current_price=holding.cur_prc,
                    )
                else:
                    # Add new
                    self.add_position(
                        ticker=holding.stk_cd,
                        stock_name=holding.stk_nm,
                        quantity=holding.hldg_qty,
                        avg_price=holding.avg_buy_prc,
                        current_price=holding.cur_prc,
                    )

            # Remove positions no longer in holdings
            holding_tickers = {h.stk_cd for h in account.holdings if h.hldg_qty > 0}
            for ticker in list(self._positions.keys()):
                if ticker not in holding_tickers:
                    self.remove_position(ticker)

            logger.info(
                "positions_synced",
                count=len(self._positions),
            )

        except Exception as e:
            logger.error("position_sync_failed", error=str(e))


# -------------------------------------------
# Singleton Instance
# -------------------------------------------

_position_manager: Optional[PositionManager] = None


async def get_position_manager() -> PositionManager:
    """Get or create singleton position manager."""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager


def get_position_manager_sync() -> PositionManager:
    """Get position manager synchronously."""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager
