"""
Position Manager

Real-time position monitoring with Agent Group Chat integration.
Triggers agent discussions for position management decisions.
"""

import asyncio
import json
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

    # Set once when an autonomous defensive close is blocked by the gate, so the
    # human is notified once per denied episode instead of every monitor cycle
    # (the *_HIT events are not de-duped). Reset when the gate next allows.
    close_gate_denied_notified: bool = False

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

        # Stop-persistence single-writer state (T7 review C1). One DB write at
        # a time; stale scheduled writes dropped by generation; identical
        # payloads skipped. See _persist_stops.
        self._persist_lock = asyncio.Lock()
        self._persist_generation = 0
        self._last_persisted_payload: Optional[str] = None

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
        self._schedule_persist_stops()

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
        self._schedule_persist_stops()

        return position

    def remove_position(self, ticker: str) -> bool:
        """Remove a position from monitoring."""
        if ticker in self._positions:
            del self._positions[ticker]
            self._schedule_persist_stops()
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
            # Start discussion via coordinator. wait=True: block until the
            # debate completes — session.decision is read right below, so the
            # async default (returns a still-running session, decision=None)
            # would make _apply_decision dead code.
            session = await self._chat_coordinator.start_manual_discussion(
                ticker=position.ticker,
                stock_name=position.stock_name,
                wait=True,
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
        """Execute an autonomous defensive close via the trading coordinator.

        Stop-loss / take-profit / agent-decision SELLs are autonomous actions, so
        they MUST pass the shared autonomy gate — the same one the offensive BUY
        path enforces (master env → mode → paper-only → daily-loss breaker).
        Before this fix the close went straight to the broker, bypassing the gate
        entirely (audit A2, 2026-07-12). A denied close leaves the position
        monitored so a human can act on it.
        """
        try:
            from services.autonomy import check_autonomy

            gate = await check_autonomy(
                "kiwoom",
                action="SELL",
                quantity=position.quantity,
                entry_price=position.current_price,
            )
            if not gate.allowed:
                logger.warning(
                    "defensive_close_gate_denied",
                    ticker=position.ticker,
                    reason=reason,
                    check=gate.check,
                    gate_reason=gate.reason,
                )
                # Notify once per denied episode, not on every monitor cycle —
                # the *_HIT events re-fire each cycle and the denied position
                # stays monitored, so an un-throttled notice would flood the
                # channel (matches the gate's once-per-day breaker throttle).
                if not position.close_gate_denied_notified:
                    position.close_gate_denied_notified = True
                    await self._notify_close_gate_denied(position, reason, gate.reason)
                return

            # Gate allowed: clear the denied-notice latch so a future denial for
            # this position notifies again.
            position.close_gate_denied_notified = False

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

    async def _notify_close_gate_denied(
        self, position: MonitoredPosition, reason: str, gate_reason: str
    ) -> None:
        """Best-effort Telegram notice when the autonomy gate blocks a defensive
        close — the human must know a stop-loss/take-profit did NOT execute and
        the position is still open."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"🚫 자율 청산 게이트 거부 ({position.ticker}, {reason}): {gate_reason}. "
                    f"포지션은 유지되며 수동 조치가 필요합니다."
                )
        except Exception as e:
            logger.warning(
                "close_gate_denied_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    @staticmethod
    def _stops_sane(
        current_price: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> bool:
        """Sanity-validate proposed stop levels against the current price (P0-2).

        Insane iff: price unknown/non-positive (cannot validate → fail-closed),
        stop_loss at-or-above the current price (stop_loss_hit would fire on the
        very next monitor cycle — the 2026-07-12 15:40 CPU-spin hang), or
        take_profit at-or-below the current price (instant take-profit storm).

        Shared by BOTH stop-setting paths: agent-decision stops
        (_apply_decision) and blob restore (restore_stop_overlay).
        """
        if not current_price or current_price <= 0:
            return False
        if stop_loss is not None and stop_loss >= current_price:
            return False
        if take_profit is not None and take_profit <= current_price:
            return False
        return True

    async def _notify_decision_stops_rejected(
        self,
        position: MonitoredPosition,
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> None:
        """Best-effort Telegram notice when a discussion decision proposed an
        insane stop level — the human must know the stop change was NOT applied
        and the existing stops remain in force."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                parts = []
                if stop_loss is not None:
                    parts.append(f"손절 ₩{stop_loss:,.0f}")
                if take_profit is not None:
                    parts.append(f"익절 ₩{take_profit:,.0f}")
                await notifier.send_message(
                    f"⚠️ 결정 스탑 기각 ({position.ticker}): {' / '.join(parts)} — "
                    f"현재가 ₩{position.current_price:,.0f} 기준 sanity 위반 "
                    f"(손절 ≥ 현재가 또는 익절 ≤ 현재가). 기존 스탑 유지."
                )
        except Exception as e:
            logger.warning(
                "decision_stops_rejected_notify_failed",
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
                # Update stops if provided — after sanity validation (P0-2a).
                new_stop = decision.stop_loss or None
                new_take = decision.take_profit or None
                if new_stop is not None or new_take is not None:
                    if not self._stops_sane(position.current_price, new_stop, new_take):
                        # Root cause of the 2026-07-12 15:40 hang: a decision
                        # set stop_loss 1,993,680 ABOVE the price 1,845,000 →
                        # stop_loss_hit fired every monitor cycle → CPU spin.
                        # An insane proposal is rejected wholesale; existing
                        # stops are kept and the human is notified.
                        logger.warning(
                            "decision_stops_rejected",
                            ticker=position.ticker,
                            stop_loss=new_stop,
                            take_profit=new_take,
                            current_price=position.current_price,
                        )
                        await self._notify_decision_stops_rejected(
                            position, new_stop, new_take
                        )
                    else:
                        if new_stop is not None:
                            self.update_position(position.ticker, stop_loss=new_stop)
                        if new_take is not None:
                            self.update_position(position.ticker, take_profit=new_take)

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
    # Stop-Level Persistence (F3 Task 7)
    # -------------------------------------------
    #
    # Stop-loss / take-profit / trailing-stop levels lived only in memory, so a
    # backend restart silently dropped all of them — the operator had to
    # manually re-register stops after every restart before defense resumed.
    # These levels are agent-chat's own data (the broker doesn't know them), so
    # local state IS the source of truth to persist — mirrors the R5-P1
    # ExecutionCoordinator._persist_state/_schedule_persist pattern
    # (services/trading/coordinator.py).

    _STOPS_KEY = "agent_chat:position_manager_state"

    def _schedule_persist_stops(self) -> None:
        """Fire-and-forget persist from a (possibly sync) mutator. No-op without
        a running event loop — e.g. a PositionManager built directly in a unit
        test, or a sync caller invoked outside any async context (reconciler /
        sync_from_account call add/update/remove_position synchronously). Never
        raises.

        Each scheduled write carries the generation current at schedule time;
        a write that reaches the lock after a newer one was scheduled is stale
        and gets dropped (see _persist_stops)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._persist_generation += 1
        generation = self._persist_generation
        try:
            loop.create_task(self._persist_stops(generation=generation))
        except Exception as e:
            logger.warning("position_manager_persist_schedule_failed", error=str(e))

    async def _persist_stops(self, generation: Optional[int] = None) -> None:
        """Persist stop levels for all currently-monitored positions.

        Single-writer discipline (T7 review C1): every DB write happens under
        one lock and the payload is serialized UNDER that lock, so a write can
        never carry state older than its critical-section entry and writes land
        in critical-section order. Additionally:
        - generation guard: a scheduled write whose captured generation is
          older than the newest scheduled one is dropped (its successor carries
          fresher state);
        - dirty-check: a payload identical to the last-written one is skipped.

        Without this, two set_app_setting calls — each opening its own
        aiosqlite connection — could land out of order, letting the None-stops
        blob scheduled by sync_from_account silently revert the stops that
        restore_stop_overlay had just saved.

        ``generation=None`` marks a direct (never-stale) call: tests and
        restore_stop_overlay's corrective save.

        Best-effort — never raises, since it also runs from the fire-and-forget
        hook above where there is nothing to catch the exception.
        """
        try:
            from services.storage_service import get_storage_service

            async with self._persist_lock:
                if generation is not None and generation < self._persist_generation:
                    return  # stale scheduled write — a newer one is pending/done
                payload = json.dumps({
                    "stops": {
                        ticker: {
                            "stop_loss": position.stop_loss,
                            "take_profit": position.take_profit,
                            "trailing_stop_pct": position.trailing_stop_pct,
                        }
                        for ticker, position in self._positions.items()
                    }
                })
                if payload == self._last_persisted_payload:
                    return
                storage = await get_storage_service()
                await storage.set_app_setting(self._STOPS_KEY, payload)
                self._last_persisted_payload = payload
        except Exception as e:
            logger.error("position_manager_persist_failed", error=str(e))

    async def _notify_restore_stops_dropped(
        self,
        ticker: str,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        current_price: Optional[float],
    ) -> None:
        """Best-effort Telegram notice when a restart-restore blob entry fails
        _stops_sane and is dropped (P0-2b/M1) — mirrors
        _notify_decision_stops_rejected. Without this, a position could come
        back up from a restart with NO stop-loss/take-profit protection and
        nothing would surface that silently to the human."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                sl = f"{stop_loss:,.0f}" if stop_loss is not None else "-"
                tp = f"{take_profit:,.0f}" if take_profit is not None else "-"
                price = f"{current_price:,.0f}" if current_price else "알수없음"
                await notifier.send_message(
                    f"⚠️ 복원 스탑 기각: {ticker} 손절 {sl}/익절 {tp} — "
                    f"현재가 {price} 기준 무효, 보호 미설정 상태"
                )
        except Exception as e:
            logger.warning(
                "restore_stops_dropped_notify_failed",
                ticker=ticker,
                error=str(e),
            )

    async def restore_stop_overlay(self) -> int:
        """Restore persisted stop levels onto currently-monitored positions.

        Meant to be called once, right after `sync_from_account()`, so
        `self._positions` already reflects the current broker holdings:
        - A ticker in the blob that is no longer held is dropped (never
          resurrected as a position) — the final re-save below rewrites the
          blob from `self._positions`, which naturally excludes it.
        - A ticker still held has its stop fields restored ONLY where the
          field is currently None — a value already set this session (by a
          fresher broker sync or a manual update) wins over the stale blob.
        - An entry whose saved stops fail _stops_sane against the position's
          current price (P0-2b: polluted/stale blob) is skipped entirely and
          its values dropped from the blob by the re-save.

        Returns the number of tickers whose stops were restored.
        """
        # Final-review CRITICAL (C1): sync_from_account's add_position calls
        # (synchronous, called right before this coroutine with no yield in
        # between per ChatCoordinator.start()) schedule fire-and-forget
        # None-stops persists. Those pending writers get their FIRST chance
        # to run at this coroutine's own first await — if one reached the DB
        # before the read just below, we'd read an all-None blob, "restore"
        # nothing, and the unconditional re-save at the end would cement
        # that loss. Bumping the generation HERE, before any await, retires
        # every writer scheduled before this call synchronously (no
        # interleaving is possible before the first await) — the same
        # generation-check gate _persist_stops already applies (~L1209).
        self._persist_generation += 1
        try:
            from services.storage_service import get_storage_service

            # Belt-and-braces (verified): do NOT additionally hold
            # _persist_lock across this read. A writer that is already
            # mid-critical-section when this call starts (e.g. sleeping
            # inside its own `async with self._persist_lock` before its DB
            # write, as in the sibling delayed-WRITE race test below) has
            # already passed its generation check — serializing this read
            # behind that lock would make it wait for that stale write to
            # LAND and release the lock first, so the read would observe the
            # very corruption this fix prevents, one step removed. The
            # generation bump above is what closes the race: a writer
            # scheduled before this point is retired by the check inside its
            # own `_persist_stops` (~L1209) regardless of DB timing. The
            # corrective `_persist_stops()` call below still goes through the
            # lock and always wins because generation=None is never stale.
            storage = await get_storage_service()
            blob = await storage.get_app_setting(self._STOPS_KEY)
            if not blob:
                return 0

            data = json.loads(blob)
            stops = data.get("stops") or {}
            if not stops:
                return 0

            restored = 0
            for ticker, saved in stops.items():
                position = self._positions.get(ticker)
                if position is None:
                    # Not among the synced holdings — no resurrection; dropped
                    # from the blob by the unconditional re-save below.
                    continue

                saved_stop = saved.get("stop_loss")
                saved_take = saved.get("take_profit")
                if not self._stops_sane(position.current_price, saved_stop, saved_take):
                    # P0-2b: polluted/stale blob entry — e.g. a take_profit at
                    # or below the current price would fire an instant
                    # take-profit storm on the first monitor cycle after
                    # restore. Skip the whole entry; the re-save below drops
                    # the insane values from the blob.
                    logger.warning(
                        "restore_stops_insane_dropped",
                        ticker=ticker,
                        stop_loss=saved_stop,
                        take_profit=saved_take,
                        current_price=position.current_price,
                    )
                    await self._notify_restore_stops_dropped(
                        ticker, saved_stop, saved_take, position.current_price
                    )
                    continue

                kwargs: Dict[str, float] = {}
                if position.stop_loss is None and saved.get("stop_loss") is not None:
                    kwargs["stop_loss"] = saved["stop_loss"]
                if position.take_profit is None and saved.get("take_profit") is not None:
                    kwargs["take_profit"] = saved["take_profit"]
                if (
                    position.trailing_stop_pct is None
                    and saved.get("trailing_stop_pct") is not None
                ):
                    kwargs["trailing_stop_pct"] = saved["trailing_stop_pct"]

                if kwargs:
                    self.update_position(ticker, **kwargs)
                    restored += 1

            # Unconditional re-save: reflects the restores above and drops any
            # blob ticker no longer present in self._positions.
            await self._persist_stops()

            logger.info("position_manager_stops_restored", count=restored)
            return restored
        except Exception as e:
            logger.error("position_manager_restore_failed", error=str(e))
            return 0


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
