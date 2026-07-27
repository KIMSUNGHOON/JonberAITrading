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
from services.trading.market_hours import is_krx_open_cached

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
    STRATEGIC_REEVAL = "strategic_reeval"      # Periodic/price-change proactive re-judgment (P3)


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
    PositionEventType.STRATEGIC_REEVAL: {
        "name": "전략 재평가",
        "description": "일정 시간 경과 또는 유의미한 가격 변동으로 포지션을 능동적으로 재평가합니다 "
                        "(추가매수/축소/청산/유지를 다시 판단합니다).",
    },
}


def get_event_korean(event_type: PositionEventType) -> dict:
    """Get Korean translation for a position event type."""
    return POSITION_EVENT_KOREAN.get(event_type, {
        "name": event_type.value,
        "description": "",
    })


# Minor review fix (S-2): `_execute_close_position`/`_execute_reduce_position`
# pass one of these `reason` strings through. Used by
# `_fallback_to_discussion_on_hitl_deny` to label its reconstructed event
# with the type that actually matches WHY the close/reduce was attempted,
# instead of defaulting every non-take_profit reason to STOP_LOSS_HIT.
# "agent_decision"/"agent_decision_reduce"/"agent_decision_reduce_partial"
# (a plain discussion SELL/REDUCE, not a mechanical stop trigger) are
# intentionally absent here -- they fall through to the caller's
# STRATEGIC_REEVAL default.
_EXIT_REASON_TO_EVENT_TYPE: Dict[str, PositionEventType] = {
    "stop_loss": PositionEventType.STOP_LOSS_HIT,
    "take_profit": PositionEventType.TAKE_PROFIT_HIT,
}


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

    # Provenance (L3, 2026-07-19,
    # docs/superpowers/specs/2026-07-19-decision-lineage-design.md Task L3):
    # the durable agent_chat_decisions.id of the discussion that established
    # this position's ENTRY, when one exists. Set once at add_position()
    # time and never overwritten by a later merge/update (mirrors
    # ExecutionCoordinator._add_position's analysis_session_id, whose own
    # merge branch never touches it either once a position already exists).
    # In-memory only (pydantic model, no schema/persistence needed here) — a
    # broker-sync-discovered position (sync_from_account) has no discussion
    # behind it, so this stays None. That is the normal, expected case (spec
    # D2), not a gap.
    entry_decision_id: Optional[str] = None

    # Strategic re-evaluation tracking (P3, 2026-07-15,
    # docs/superpowers/plans/2026-07-15-position-mgmt-execution.md). When
    # this position was last proactively re-judged (interval OR
    # price-change trigger — see PositionManager._check_strategic_reeval)
    # and the price it was measured against. Seeded at add_position() time
    # (monitoring-start baseline, so a freshly-synced position doesn't
    # immediately fire) and reset every time a strategic re-eval fires.
    last_reeval_at: Optional[datetime] = None
    last_reeval_price: Optional[float] = None

    # Event tracking
    events_triggered: List[str] = Field(default_factory=list)
    discussion_count: int = 0

    # Set once when an autonomous defensive close is blocked by the gate, so the
    # human is notified once per denied episode instead of every monitor cycle
    # (the *_HIT events are not de-duped). Reset when the gate next allows.
    close_gate_denied_notified: bool = False

    # S-5 (survival discipline, 2026-07-19,
    # docs/superpowers/specs/2026-07-19-survival-discipline-design.md §2):
    # timestamp of the FIRST tick this position's take-profit was reached
    # (current_price >= take_profit) -- fire-once (a later tick where it's
    # still true does NOT overwrite it) and never reset once set, even after
    # price falls back below take_profit. Deliberately separate from the
    # TAKE_PROFIT_HIT event, which intentionally keeps refiring every tick
    # it's still true (existing semantics, unchanged by this task). Drives
    # `_apply_take_profit_lock_in`'s breakeven+lock-in stop ratchet on a
    # post-TP retracement. Included in the persisted stops overlay blob (see
    # `_persist_stops`/`restore_stop_overlay`) so a restart mid-retracement
    # doesn't forget a profit was ever reached; a pre-S-5 blob simply has no
    # such key, which restores as None (backward compatible).
    take_profit_reached_at: Optional[datetime] = None

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

    # S-5 (survival discipline, 2026-07-19,
    # docs/superpowers/specs/2026-07-19-survival-discipline-design.md §2):
    # fraction of the take-profit's profit distance above entry (avg_price)
    # to lock in as a raised stop-loss once take_profit has been reached at
    # least once and price has since retraced back below it. 0.3 = lock in
    # 30% of the (take_profit - entry) gain, e.g. entry 70,000 / TP 77,000
    # -> lock-in stop = 70,000 * (1 + 0.3 * 0.1) = 72,100.
    trailing_lock_in_ratio: float = 0.3

    # Discussion limits
    min_discussion_interval_minutes: int = 15
    max_discussions_per_position: int = 8

    # Holding period
    long_holding_days: int = 30

    # Auto-execution settings.
    #
    # S-2 (survival discipline, spec docs/superpowers/specs/
    # 2026-07-19-survival-discipline-design.md §2, decision D1):
    # auto_execute_stop_loss now defaults to True — a stop-loss is never
    # optional risk reduction, so an AUTONOMOUS account must not silently
    # sit at a breached stop waiting for a human click. This is safe for a
    # HITL account too: the autonomy gate re-checked inside
    # `_execute_close_position`/`_execute_reduce_position` denies with
    # check="market_mode" whenever the account isn't actually autonomous,
    # and that specific denial now falls back to the SAME agent-discussion
    # path pre-S-2 HITL behavior used (see `_execute_close_position`'s deny
    # branch) — so HITL accounts keep getting a debate + notification, not
    # silence. auto_execute_take_profit stays False (decision D2 —
    # profit-taking remains discussion-gated, unchanged).
    auto_execute_stop_loss: bool = True
    auto_execute_take_profit: bool = False
    auto_update_trailing: bool = True

    # ADD (increase) sizing policy (P2, 2026-07-15,
    # docs/superpowers/plans/2026-07-15-position-mgmt-execution.md). An
    # autonomous decision to ADD to an already-held position sizes the buy
    # as a percentage of the CURRENTLY held quantity —
    # round(held_quantity * add_position_pct) — rather than trusting a
    # free-text quantity from the discussion. Conservative default: at most
    # a quarter of the current holding per ADD decision (mirrors the
    # conservatism of max_single_position_pct=0.15 and the 8% default
    # stop/take distances in services.trading.models.RiskParameters).
    add_position_pct: float = Field(
        default=0.25,
        ge=0.0, le=1.0,
        description="Fraction of the currently held quantity to buy on an "
                     "autonomous ADD decision (e.g. 0.25 = add 25% of "
                     "current holding). 0 disables autonomous ADD sizing.",
    )

    # Strategic re-evaluation trigger (P3, 2026-07-15,
    # docs/superpowers/plans/2026-07-15-position-mgmt-execution.md Task P3).
    # The 30s loop above only reacts to DEFENSIVE conditions (stop/take
    # proximity, big P&L swings, long holding). Without this, a held
    # position is never proactively re-judged for ADD/REDUCE — it's only
    # ever reacted to. When NO defensive event fires this cycle, a position
    # becomes due for a STRATEGIC_REEVAL event (see
    # PositionManager._check_strategic_reeval) once EITHER: enough
    # wall-clock time has passed since its last re-eval, OR its price has
    # moved enough since that re-eval's price baseline. STRATEGIC_REEVAL
    # then flows through the SAME min_discussion_interval_minutes /
    # max_discussions_per_position throttle as defensive events, so this
    # bounds LLM-discussion volume/cost exactly like the existing events do
    # — it does not bypass or duplicate that throttle. Tuned (2026-07-15,
    # monitoring-cadence-tuning arc) for faster-market responsiveness so a
    # held position is never silent for a full day: at most a
    # half-hourly re-judgment (sooner on a real move).
    reeval_interval_minutes: int = Field(
        default=30,
        ge=1,
        description="Minutes since a position's last strategic re-eval "
                     "before it becomes due again (periodic trigger).",
    )
    reeval_price_change_pct: float = Field(
        default=2.0,
        ge=0.0,
        description="Absolute price move (%) from the last re-eval's price "
                     "baseline that makes a position due for strategic "
                     "re-eval immediately, independent of the interval "
                     "timer (change-based trigger).",
    )


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

        # E2-1: market-gate last-known state, for the transition-only log
        # helper below (None = not yet observed this process).
        self._market_gate_closed: Optional[bool] = None

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
        entry_decision_id: Optional[str] = None,
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
            entry_decision_id: durable agent_chat_decisions.id that decided
                this entry (L3) — optional, defaults to None so every
                existing call site (sync_from_account, direct test/manual
                calls) is byte-for-byte unchanged.

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
            entry_decision_id=entry_decision_id,
            highest_price=current_price or avg_price,
            lowest_price=current_price or avg_price,
            # Strategic re-eval baseline starts at monitoring-start (P3) —
            # NOT None — so a position that just began being monitored
            # (fresh entry, or re-synced from the broker on restart) doesn't
            # immediately count as "due" and fire a re-eval discussion on
            # the very next 30s tick.
            last_reeval_at=datetime.now(),
            last_reeval_price=current_price or avg_price,
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
        avg_price: Optional[float] = None,
        current_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop_pct: Optional[float] = None,
        trailing_stop_price: Optional[float] = None,
        entry_decision_id: Optional[str] = None,
    ) -> Optional[MonitoredPosition]:
        """Update a monitored position.

        ``avg_price`` (P2, 2026-07-15): distinct from ``current_price`` — the
        cost basis, only ever recomputed by an ADD's weighted-average merge
        (`_execute_add_position`). No other caller passes it.
        """
        if ticker not in self._positions:
            return None

        position = self._positions[ticker]

        if quantity is not None:
            position.quantity = quantity

        if avg_price is not None:
            position.avg_price = avg_price

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

        if trailing_stop_price is not None:
            # S-5 bug fix: previously `_check_trailing_stop` assigned this
            # attribute directly, bypassing this method entirely (and thus
            # `_schedule_persist_stops`). Now routed through here like every
            # other stop-level field.
            position.trailing_stop_price = trailing_stop_price

        if entry_decision_id is not None:
            position.entry_decision_id = entry_decision_id

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

    def _log_market_gate_once(self, closed: bool) -> None:
        """Log a market-gate state transition once (E2-1) — never every
        cycle. Small per-file helper shared by this file's two gate points
        (_check_all_positions, _check_strategic_reeval); duplicated in
        coordinator.py by design — YAGNI, not worth a shared util."""
        if self._market_gate_closed == closed:
            return
        self._market_gate_closed = closed
        if closed:
            logger.info("market_gate_closed", component="position_manager")
        else:
            logger.info("market_gate_reopened", component="position_manager")

    async def _check_all_positions(self) -> None:
        """Check all positions for events."""
        # E2: 장외에는 자동 토론/감시 사이클 전체를 쉬게 한다(완전 idle 결정).
        # 방어 감시(손절/익절 등) 포함 전체 skip — 장외엔 체결 불가라 안전.
        if not is_krx_open_cached():
            self._log_market_gate_once(closed=True)
            return
        self._log_market_gate_once(closed=False)

        if not self._positions:
            return

        # Update prices first. get_kr_stock_info now returns None on any
        # fetch failure instead of a fabricated random-mock price (CRITICAL
        # safety fix, 2026-07-14) — stale_tickers collects positions whose
        # price could NOT be refreshed this cycle, so the stop-loss/take-
        # profit check below is skipped for them rather than evaluated
        # against a random number that could trigger a real defensive sell.
        stale_tickers = await self._update_prices()

        # Check each position
        for ticker, position in list(self._positions.items()):
            if ticker in stale_tickers:
                logger.warning(
                    "position_check_skipped_stale_price",
                    ticker=ticker,
                    current_price=position.current_price,
                )
                continue
            try:
                await self._check_position(position)
            except Exception as e:
                logger.error(
                    "position_check_error",
                    ticker=ticker,
                    error=str(e),
                )

    async def _update_prices(self) -> set:
        """Update current prices for all positions.

        Returns the set of tickers whose price could NOT be refreshed this
        cycle (get_kr_stock_info returned None/incomplete data, i.e. a real
        fetch failure — never a fabricated mock price since the 2026-07-14
        CRITICAL fix). Callers must skip stop-loss/take-profit evaluation
        for those tickers this cycle and keep the last known price.
        """
        stale: set = set()
        try:
            from agents.tools.kr_market_data import get_kr_stock_info

            for ticker, position in self._positions.items():
                try:
                    info = await get_kr_stock_info(ticker)
                    if info and "cur_prc" in info:
                        new_price = info["cur_prc"]
                        self.update_position(ticker, current_price=new_price)
                    else:
                        stale.add(ticker)
                        logger.warning(
                            "price_update_stale",
                            ticker=ticker,
                            reason="fetch_returned_none_or_incomplete",
                        )
                except Exception as e:
                    stale.add(ticker)
                    logger.warning(
                        "price_update_failed",
                        ticker=ticker,
                        error=str(e),
                    )
        except ImportError:
            # Fallback: prices not updated for anyone this cycle.
            stale.update(self._positions.keys())

        return stale

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
                # Take-profit hit. Auto-execution stays OFF here
                # (auto_execute_take_profit defaults False, decision D2,
                # unchanged by S-5) -- this is a pure bookkeeping mark, not
                # an execution trigger. Fire-once (S-5): an already-set
                # timestamp is left alone, even though the *_HIT event below
                # intentionally keeps refiring every tick this stays true
                # (existing semantics -- spec §1).
                if position.take_profit_reached_at is None:
                    position.take_profit_reached_at = datetime.now()

                events.append(self._create_event(
                    position, PositionEventType.TAKE_PROFIT_HIT,
                    position.take_profit,
                    f"익절가 도달: ₩{position.current_price:,.0f} >= ₩{position.take_profit:,.0f}",
                    auto_execute=self.config.auto_execute_take_profit,
                ))
            else:
                if tp_distance_pct <= self.config.take_profit_warning_pct:
                    # Approaching take-profit
                    if PositionEventType.TAKE_PROFIT_NEAR.value not in position.events_triggered:
                        events.append(self._create_event(
                            position, PositionEventType.TAKE_PROFIT_NEAR,
                            tp_distance_pct,
                            f"익절가 근접: {tp_distance_pct:.1f}% 거리",
                        ))
                        position.events_triggered.append(PositionEventType.TAKE_PROFIT_NEAR.value)

                # S-5: profit-lock trailing after a take-profit retracement.
                # `tp_distance_pct > 0` here means current_price < take_profit
                # -- once take_profit has been reached at least once
                # (take_profit_reached_at set), every tick it stays below TP
                # is a candidate to ratchet the stop up toward
                # breakeven+lock-in. This only ever raises the STOP; it never
                # sells -- profit-taking EXECUTION stays discussion-gated
                # (D2/auto_execute_take_profit unchanged).
                if position.take_profit_reached_at is not None:
                    self._apply_take_profit_lock_in(position, events)

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

        # Strategic re-evaluation trigger (P3, 2026-07-15,
        # docs/superpowers/plans/2026-07-15-position-mgmt-execution.md Task
        # P3). Everything above is DEFENSIVE — it reacts to a threat that's
        # already crystallizing. This is the proactive counterpart: only
        # when NOTHING defensive fired this cycle do we check whether the
        # position is due for a periodic/change-based strategic re-judgment
        # (ADD/REDUCE/HOLD/SELL), so one tick never double-triggers both a
        # defensive AND a strategic discussion (dedup — the defensive event
        # takes priority; the throttle below still bounds cross-tick
        # firing).
        if not events:
            reeval_event = self._check_strategic_reeval(position)
            if reeval_event:
                events.append(reeval_event)

        # Process events
        for event in events:
            await self._handle_event(event, position)

    def _check_strategic_reeval(self, position: MonitoredPosition) -> Optional[PositionEvent]:
        """Return a STRATEGIC_REEVAL event if `position` is due for a
        proactive strategic re-evaluation, else None (P3).

        Hybrid OR trigger: due once EITHER enough wall-clock time has
        passed since the last re-eval (``reeval_interval_minutes``), OR the
        price has moved far enough from the last re-eval's price baseline
        (``reeval_price_change_pct``). Only ever called from
        `_check_position` when no defensive event fired this cycle.

        The returned event flows through the exact same
        `_handle_event` -> `_should_trigger_discussion` -> `_trigger_discussion`
        -> `_apply_decision` chain the defensive events already use, so the
        resulting ADD/REDUCE/HOLD/SELL decision reaches the SAME real,
        gated execution paths (P0/P1/P2) — this method only decides
        WHETHER a re-eval discussion is due, never how it executes.

        The time/price baseline is reset here, at detection time,
        regardless of whether the downstream discussion throttle
        (`_should_trigger_discussion`) ends up allowing an actual
        discussion this cycle. Otherwise a throttled position would
        re-detect "due" on every single 30s monitor tick until the throttle
        window passes — spamming the event log/Telegram once per
        `check_interval_seconds` instead of once per
        `reeval_interval_minutes`/price-move, and burning the interval
        immediately rather than preserving it for the next attempt.
        """
        # E2: 장외에는 자동 토론/감시 사이클 전체를 쉬게 한다(완전 idle 결정).
        if not is_krx_open_cached():
            self._log_market_gate_once(closed=True)
            return None
        self._log_market_gate_once(closed=False)

        now = datetime.now()

        interval_due = (
            position.last_reeval_at is None
            or (now - position.last_reeval_at)
            >= timedelta(minutes=self.config.reeval_interval_minutes)
        )

        price_change_pct = 0.0
        price_due = False
        if position.last_reeval_price:
            price_change_pct = (
                abs(position.current_price - position.last_reeval_price)
                / position.last_reeval_price
                * 100
            )
            price_due = price_change_pct >= self.config.reeval_price_change_pct

        if not (interval_due or price_due):
            return None

        if price_due:
            message = (
                f"전략 재평가(가격변동): {price_change_pct:.1f}% 변동 "
                f"(기준 ₩{position.last_reeval_price:,.0f} → "
                f"현재 ₩{position.current_price:,.0f})"
            )
            trigger_value = price_change_pct
        else:
            elapsed_minutes = (
                (now - position.last_reeval_at).total_seconds() / 60
                if position.last_reeval_at is not None else 0.0
            )
            message = f"전략 재평가(주기): 마지막 재평가 이후 {elapsed_minutes:.0f}분 경과"
            trigger_value = elapsed_minutes

        # Reset baseline NOW (see docstring) — before the event even reaches
        # _handle_event/the discussion throttle.
        position.last_reeval_at = now
        position.last_reeval_price = position.current_price

        return self._create_event(
            position,
            PositionEventType.STRATEGIC_REEVAL,
            trigger_value,
            message,
        )

    def _apply_take_profit_lock_in(
        self, position: MonitoredPosition, events: List[PositionEvent]
    ) -> None:
        """Ratchet the stop-loss up to a breakeven+lock-in level after a
        take-profit retracement (S-5, docs/superpowers/specs/
        2026-07-19-survival-discipline-design.md §2 D2/S-5).

        Only meaningful once `position.take_profit_reached_at` is set (the
        caller in `_check_position` already gates on that) -- current price
        being below take_profit is the caller's other precondition. Computes:

            new_stop = max(current stop_loss, entry * (1 + lock_in_ratio * (tp - entry) / entry))

        i.e. locks in `trailing_lock_in_ratio` (default 30%) of the take
        profit's gain distance above the entry price (avg_price) -- never
        below the position's CURRENT stop (the `max()`: a stop this hook, or
        anything else, has already raised can never be lowered by it).

        Routed through `update_position` so both `_stops_sane` (reject an
        insane level outright rather than apply it -- mirrors the
        `_apply_decision` HOLD/ADD stop-adjustment path) and
        `_schedule_persist_stops` (survive a restart) apply -- the SAME fix
        applied to `_check_trailing_stop` below for the pre-existing
        trailing stop, which had the identical direct-assignment bug.

        No-op guarded: recomputes to the exact same value every tick the
        retracement condition holds (it only depends on avg_price/
        take_profit/config, never on the fluctuating current_price), so once
        applied this returns immediately on every subsequent tick without
        calling `update_position` (and rescheduling a persist) again.

        Observability (G-3, spec docs/superpowers/specs/
        2026-07-20-gap-discipline-design.md §2): a successful ratchet logs
        `take_profit_lock_in_applied` and appends a TRAILING_STOP_UPDATE
        event into the caller's `events` list -- the SAME event type and
        `requires_discussion=False` convention `_check_trailing_stop` below
        already uses for its own stop-loss raise (this hook is the
        semantically identical "raise the stop, never sell" ratchet, just
        triggered by a take-profit retracement instead of a new high). No
        new PositionEventType needed; the message text is what
        distinguishes a lock-in raise from a %-trailing raise in event
        history/notifications.
        """
        if position.avg_price <= 0 or position.take_profit is None:
            return

        profit_distance_ratio = (
            (position.take_profit - position.avg_price) / position.avg_price
        )
        lock_in_price = position.avg_price * (
            1 + self.config.trailing_lock_in_ratio * profit_distance_ratio
        )

        current_stop = position.stop_loss if position.stop_loss is not None else 0.0
        new_stop = max(current_stop, lock_in_price)

        if new_stop == position.stop_loss:
            return  # nothing would change -- skip the update_position round-trip

        if not self._stops_sane(position.current_price, new_stop, None):
            logger.warning(
                "take_profit_lock_in_rejected",
                ticker=position.ticker,
                candidate_stop=new_stop,
                current_price=position.current_price,
            )
            return

        self.update_position(position.ticker, stop_loss=new_stop)

        logger.info(
            "take_profit_lock_in_applied",
            ticker=position.ticker,
            old_stop=current_stop,
            new_stop=new_stop,
        )

        events.append(self._create_event(
            position, PositionEventType.TRAILING_STOP_UPDATE,
            new_stop,
            f"익절 후 락인 스탑 상향: ₩{current_stop:,.0f} → ₩{new_stop:,.0f}",
            requires_discussion=False,
        ))

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

            # S-5 bug fix (docs/superpowers/specs/
            # 2026-07-19-survival-discipline-design.md §1/§2): both of these
            # used to be direct attribute assignments
            # (`position.trailing_stop_price = ...` / `position.stop_loss =
            # ...`), bypassing BOTH the `_stops_sane` sanity gate AND
            # `_schedule_persist_stops` -- a raised trailing stop-loss
            # silently vanished on the next restart. Routed through
            # `update_position` now, mirroring the `_apply_decision`
            # stop-setting path (~L1827/`_apply_take_profit_lock_in` above).
            # `trailing_stop_price` is a pure internal tracking value (not a
            # live order level), so it always updates on this branch same as
            # before; the actual stop_loss raise is additionally
            # sanity-gated -- if the current price has already fallen
            # through the computed level, the raise is skipped (existing
            # stop_loss kept) rather than creating an immediate
            # stop_loss_hit spin.
            update_kwargs: Dict[str, float] = {"trailing_stop_price": new_trailing_price}

            raise_stop = position.stop_loss is None or new_trailing_price > position.stop_loss
            if raise_stop:
                if self._stops_sane(position.current_price, new_trailing_price, None):
                    update_kwargs["stop_loss"] = new_trailing_price
                else:
                    logger.warning(
                        "trailing_stop_raise_rejected",
                        ticker=position.ticker,
                        candidate_stop=new_trailing_price,
                        current_price=position.current_price,
                    )

            self.update_position(position.ticker, **update_kwargs)

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

            # Handle decision. session.id is the REAL, persisted
            # agent_chat_decisions.id (decision_log.persist_session writes
            # it verbatim as decision_id on both the decision and vote
            # rows) — the only place a genuine discussion-issued exit
            # decision id exists (L3, spec
            # docs/superpowers/specs/2026-07-19-decision-lineage-design.md).
            if session.decision:
                await self._apply_decision(
                    position, session.decision, decision_id=session.id
                )

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

        # decision_id intentionally omitted here (defaults to None):
        # mechanical stop-loss/take-profit auto-execution has no upstream
        # discussion decision to cite — spec D2 says NULL is correct here,
        # not a gap. Do not thread one in.
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
        decision_id: Optional[str] = None,
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
                # S-2 HITL fallback: a market_mode denial (account not
                # actually autonomous) escalates to the same discussion path
                # any other position event uses — see
                # `_fallback_to_discussion_on_hitl_deny`.
                await self._fallback_to_discussion_on_hitl_deny(position, reason, gate)
                return

            # Gate allowed: clear the denied-notice latch so a future denial for
            # this position notifies again.
            position.close_gate_denied_notified = False

            from app.dependencies import get_trading_coordinator
            trading_coord = await get_trading_coordinator()

            result = await trading_coord._close_position(
                position.ticker, decision_id=decision_id
            )

            if result is None:
                # N3 (spec docs/superpowers/specs/2026-07-20-gap-discipline-
                # design.md §2 G-3): the coordinator returns None when it
                # SKIPPED this close outright -- a concurrent in-flight
                # defensive exit already owns this ticker (S-2 guard), or
                # the position was already gone broker-side -- NOT when an
                # order was placed and merely unfilled/rejected (that still
                # returns an OrderResult). Dropping PM's own watch here
                # would leave a monitoring gap until the next
                # add_position/reconciler pass (up to ~60s) with nothing
                # else defending the position in the meantime. Keep
                # watching; the owning engine (or the next monitor tick)
                # handles it.
                logger.warning(
                    "close_position_skipped_kept_monitored",
                    ticker=position.ticker,
                    reason=reason,
                )
                return

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

    async def _fallback_to_discussion_on_hitl_deny(
        self,
        position: MonitoredPosition,
        reason: str,
        gate,
    ) -> None:
        """S-2 HITL fallback (spec docs/superpowers/specs/2026-07-19-
        survival-discipline-design.md §2, decision D1).

        `auto_execute_stop_loss` now defaults to True (autonomous mode must
        never sit at a breached stop), but a HITL account's autonomous
        defensive SELL/REDUCE is still correctly denied by the autonomy gate
        on every monitor tick (check_autonomy re-reads the live mode — see
        `_execute_close_position`/`_execute_reduce_position`). Before this
        fix that denial was notify-only: a HITL account would never again
        see the pre-S-2 discussion/notification UX for a stopped-out
        position, just a repeated (latched-once) Telegram notice with no
        path to act. This restores it by escalating to the SAME
        agent-discussion path any other position event uses
        (`_trigger_discussion`), so a human still gets a debate + a real
        chance to decide.

        Deliberately scoped to `gate.check == "market_mode"` only:
        paper-only / daily-loss-breaker / master-gate denials are hard stops
        the existing notify-only branch already covers correctly — those are
        not "ask a human" situations, escalating them would just be noise.

        Reuses the EXISTING discussion throttle
        (`_should_trigger_discussion` — max_discussions_per_position /
        min_discussion_interval_minutes) unconditionally, so this is not a
        new spam vector: a position stuck at its stop price still gets at
        most one discussion per interval, exactly like any other event
        (independent of the caller's own once-per-episode notify latch).
        This also bounds the recursion risk from a discussion re-deciding
        SELL/REDUCE (which routes back through `_apply_decision` into this
        SAME close/reduce path, and could re-deny with the SAME
        `market_mode` check): `_trigger_discussion` sets
        `position.last_discussion` to "now" BEFORE `_apply_decision` even
        runs, so any same-tick re-entry into this method is blocked by
        `_should_trigger_discussion`'s interval check, not by call depth —
        no infinite loop.
        """
        if gate.check != "market_mode":
            return
        if not self._should_trigger_discussion(position):
            return

        # Minor review fix (S-2): reconstructed event_type must reflect the
        # ACTUAL trigger, not default every non-take_profit reason to
        # STOP_LOSS_HIT. `_execute_close_position`/`_execute_reduce_position`
        # pass `reason` through as one of "stop_loss", "take_profit", or an
        # "agent_decision*" family (a plain discussion SELL/REDUCE, not a
        # mechanical stop trigger) — the latter maps to STRATEGIC_REEVAL, the
        # closest existing event type for "a decision is being re-applied",
        # so the reconstructed event's log/notification accurately describes
        # what actually happened.
        event_type = _EXIT_REASON_TO_EVENT_TYPE.get(
            reason, PositionEventType.STRATEGIC_REEVAL
        )
        event = self._create_event(
            position,
            event_type,
            position.current_price,
            f"자율 매도 게이트 거부(HITL 모드, {reason}) — 토론 재개: {gate.reason}",
        )
        logger.info(
            "hitl_deny_discussion_fallback",
            ticker=position.ticker,
            reason=reason,
        )
        await self._trigger_discussion(event, position)

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

    async def _notify_reduce_not_executed(
        self, position: MonitoredPosition, requested_quantity: int
    ) -> None:
        """Best-effort Telegram notice when a discussion decided REDUCE
        (partial close) but the requested quantity clamps to zero or less
        against the currently monitored quantity (P1, 2026-07-15) — e.g. the
        position is already effectively closed on this manager's own ledger.
        Distinct from `_notify_reduce_gate_denied` (a real, executable
        request blocked by the autonomy gate, not a quantity problem)."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"⏸ 부분청산 미실행 ({position.ticker}): "
                    f"에이전트가 {requested_quantity}주 축소를 결정했으나 유효 매도 수량이 "
                    f"0 이하로 계산되어 미실행. 보유 수량 {position.quantity}주 그대로 유지됩니다."
                )
        except Exception as e:
            logger.warning(
                "reduce_not_executed_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _notify_reduce_gate_denied(
        self, position: MonitoredPosition, requested_quantity: int, gate_reason: str
    ) -> None:
        """Best-effort Telegram notice when the autonomy gate blocks a
        quantity-specified partial REDUCE (P1, 2026-07-15) — mirrors
        `_notify_close_gate_denied` for the full-close path. The human must
        know the reduce did NOT execute and the position quantity is
        unchanged."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"🚫 자율 부분매도 게이트 거부 ({position.ticker}, "
                    f"{requested_quantity}주): {gate_reason}. "
                    f"보유 수량 {position.quantity}주 그대로 유지되며 수동 조치가 필요합니다."
                )
        except Exception as e:
            logger.warning(
                "reduce_gate_denied_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _notify_reduce_ledger_desync(
        self, position: MonitoredPosition, requested_quantity: int
    ) -> None:
        """Best-effort Telegram notice when a gate-allowed partial REDUCE
        finds NO matching position on the trading coordinator's own ledger
        (P1/P2 review MEDIUM, 2026-07-15) — a genuine desync between this
        manager's `_positions` and `ExecutionCoordinator._state.positions`,
        not a quantity or gate problem. Previously this branch only logged a
        warning, leaving the operator with no out-of-band signal that the
        two ledgers have diverged."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"🚨 부분청산 실패 — 코디네이터 원장 불일치 ({position.ticker}): "
                    f"에이전트가 {requested_quantity}주 축소를 결정했으나 코디네이터 "
                    f"원장에 해당 종목 포지션이 없어 주문이 접수되지 않았습니다. "
                    f"이 매니저의 보유 수량({position.quantity}주)과 코디네이터 원장이 "
                    f"어긋났을 수 있어 수동 확인이 필요합니다."
                )
        except Exception as e:
            logger.warning(
                "reduce_ledger_desync_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _notify_reduce_unfilled(
        self, position: MonitoredPosition, requested_quantity: int
    ) -> None:
        """Best-effort Telegram notice when a gate-allowed, coordinator-placed
        partial REDUCE order fills zero shares (P1/P2 review MEDIUM,
        2026-07-15). The order was accepted but nothing executed — the
        position quantity is left unchanged and the operator needs to know
        the reduce did NOT happen."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"⏸ 부분청산 미체결 ({position.ticker}): "
                    f"{requested_quantity}주 매도 주문이 게이트를 통과해 접수되었으나 "
                    f"체결되지 않았습니다. 보유 수량 {position.quantity}주 그대로 "
                    f"유지됩니다."
                )
        except Exception as e:
            logger.warning(
                "reduce_unfilled_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _execute_reduce_position(
        self,
        position: MonitoredPosition,
        requested_quantity: int,
        reason: str,
        decision_id: Optional[str] = None,
    ) -> None:
        """Execute a quantity-specified partial sell via the trading
        coordinator (P1, 2026-07-15,
        docs/superpowers/plans/2026-07-15-position-mgmt-execution.md).

        Replaces P0's "부분청산 미지원" notification with real execution: a
        partial REDUCE now places an ACTUAL SELL order for the requested
        quantity (not the full position), through the SAME autonomy gate
        (`check_autonomy`) the full-close path (`_execute_close_position`)
        already enforces — master gate, market mode, paper-only, daily-loss
        breaker, notional cap.

        Oversell-proof at two layers: clamped here against this manager's own
        tracked quantity before the gate check (so the gate never evaluates a
        request larger than what this manager believes is held), and
        re-clamped inside `ExecutionCoordinator._reduce_position` against ITS
        OWN tracked quantity — a separate ledger that can diverge from this
        one. Either clamp collapsing the request into a full close delegates
        to the existing full-close machinery rather than duplicating it.

        On any real fill, the monitored quantity is decremented by the
        ACTUAL filled amount (not the requested one) — this is now backed by
        a real broker order, unlike the P0-removed silent shadow-ledger
        decrement.
        """
        try:
            from services.autonomy import check_autonomy

            clamped_quantity = min(requested_quantity, position.quantity)
            if clamped_quantity <= 0:
                logger.warning(
                    "reduce_requested_non_positive",
                    ticker=position.ticker,
                    requested_quantity=requested_quantity,
                    current_quantity=position.quantity,
                )
                await self._notify_reduce_not_executed(position, requested_quantity)
                return

            gate = await check_autonomy(
                "kiwoom",
                action="SELL",
                quantity=clamped_quantity,
                entry_price=position.current_price,
            )
            if not gate.allowed:
                logger.warning(
                    "partial_reduce_gate_denied",
                    ticker=position.ticker,
                    reason=reason,
                    check=gate.check,
                    gate_reason=gate.reason,
                )
                await self._notify_reduce_gate_denied(
                    position, clamped_quantity, gate.reason
                )
                # S-2 HITL fallback (mirrors _execute_close_position's).
                await self._fallback_to_discussion_on_hitl_deny(position, reason, gate)
                return

            from app.dependencies import get_trading_coordinator

            trading_coord = await get_trading_coordinator()
            result = await trading_coord._reduce_position(
                position.ticker, clamped_quantity, decision_id=decision_id
            )

            if result is None:
                # Coordinator had no matching position (a divergent/desynced
                # ledger, or a zero/negative clamp on its own side) — nothing
                # was placed. Leave this manager's quantity untouched rather
                # than guess at what happened.
                logger.warning(
                    "partial_reduce_no_coordinator_position",
                    ticker=position.ticker,
                )
                await self._notify_reduce_ledger_desync(position, clamped_quantity)
                return

            filled = result.filled_quantity
            if filled <= 0:
                logger.warning(
                    "partial_reduce_unfilled",
                    ticker=position.ticker,
                    requested_quantity=clamped_quantity,
                )
                await self._notify_reduce_unfilled(position, clamped_quantity)
                return

            new_quantity = position.quantity - filled
            if new_quantity <= 0:
                # The ACTUAL fill consumed this manager's whole tracked
                # quantity (e.g. the coordinator's own clamp collapsed this
                # into a real full close on its side) — mirror
                # _execute_close_position's cleanup.
                self.remove_position(position.ticker)
                logger.info(
                    "position_reduced_to_full_close",
                    ticker=position.ticker,
                    filled=filled,
                )
            else:
                self.update_position(position.ticker, quantity=new_quantity)
                logger.info(
                    "position_reduced",
                    ticker=position.ticker,
                    filled=filled,
                    remaining=new_quantity,
                )

        except Exception as e:
            logger.error(
                "execute_reduce_position_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _notify_add_not_executed(
        self, position: MonitoredPosition, computed_quantity: int
    ) -> None:
        """Best-effort Telegram notice when a discussion decided ADD
        (increase position) but the sizing policy
        (``add_position_pct`` × held quantity) computes to zero or less —
        e.g. a very small existing holding (P2, 2026-07-15,
        docs/superpowers/plans/2026-07-15-position-mgmt-execution.md).
        Superseded P0's "no execution path exists" notice now that ADD has
        real execution — this is the sizing-clamps-to-zero case, distinct
        from `_notify_add_gate_denied` (a real, executable request blocked
        by the autonomy gate, not a sizing problem)."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"⏸ 추가매수 미실행 ({position.ticker}): "
                    f"에이전트가 추가매수(ADD)를 결정했으나 사이징 결과 매수 수량이 "
                    f"{computed_quantity}주로 계산되어(보유 {position.quantity}주 기준) "
                    f"미실행되었습니다."
                )
        except Exception as e:
            logger.warning(
                "add_not_executed_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _notify_add_gate_denied(
        self, position: MonitoredPosition, add_quantity: int, gate_reason: str
    ) -> None:
        """Best-effort Telegram notice when the autonomy gate blocks an
        autonomous ADD (percentage-of-holding BUY) — mirrors
        `_notify_reduce_gate_denied` for the exposure-increasing side (P2,
        2026-07-15). The human must know the add did NOT execute and the
        position quantity is unchanged."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"🚫 자율 추가매수 게이트 거부 ({position.ticker}, "
                    f"{add_quantity}주): {gate_reason}. "
                    f"보유 수량 {position.quantity}주 그대로 유지됩니다."
                )
        except Exception as e:
            logger.warning(
                "add_gate_denied_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _notify_add_ledger_desync(
        self, position: MonitoredPosition, add_quantity: int
    ) -> None:
        """Best-effort Telegram notice when a gate-allowed ADD finds NO
        matching position on the trading coordinator's own ledger (P1/P2
        review MEDIUM, 2026-07-15) — mirrors
        `_notify_reduce_ledger_desync` for the exposure-increasing side. A
        genuine desync between this manager's `_positions` and
        `ExecutionCoordinator._state.positions`, not a sizing or gate
        problem."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"🚨 추가매수 실패 — 코디네이터 원장 불일치 ({position.ticker}): "
                    f"에이전트가 {add_quantity}주 추가매수를 결정했으나 코디네이터 "
                    f"원장에 해당 종목 포지션이 없어 주문이 접수되지 않았습니다. "
                    f"이 매니저의 보유 수량({position.quantity}주)과 코디네이터 원장이 "
                    f"어긋났을 수 있어 수동 확인이 필요합니다."
                )
        except Exception as e:
            logger.warning(
                "add_ledger_desync_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _notify_add_unfilled(
        self, position: MonitoredPosition, add_quantity: int
    ) -> None:
        """Best-effort Telegram notice when a gate-allowed, coordinator-placed
        ADD (BUY) order fills zero shares (P1/P2 review MEDIUM,
        2026-07-15) — mirrors `_notify_reduce_unfilled`. The order was
        accepted but nothing executed — the position quantity/avg_price is
        left unchanged and the operator needs to know the add did NOT
        happen."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"⏸ 추가매수 미체결 ({position.ticker}): "
                    f"{add_quantity}주 매수 주문이 게이트를 통과해 접수되었으나 "
                    f"체결되지 않았습니다. 보유 수량 {position.quantity}주 그대로 "
                    f"유지됩니다."
                )
        except Exception as e:
            logger.warning(
                "add_unfilled_notify_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _execute_add_position(
        self,
        position: MonitoredPosition,
        add_quantity: int,
        reason: str,
        decision_id: Optional[str] = None,
    ) -> None:
        """Execute a percentage-of-holding ADD (increase) via the trading
        coordinator (P2, 2026-07-15,
        docs/superpowers/plans/2026-07-15-position-mgmt-execution.md).

        Replaces P0's "추가매수 미실행 — 보류" notify-only stand-in with real
        execution: an ADD decision now places an ACTUAL BUY order for
        ``add_quantity`` — computed by the caller as
        ``round(held_quantity * add_position_pct)``, a percentage of the
        CURRENTLY held quantity, NOT the discussion's own free-text quantity
        — through the SAME autonomy gate (`check_autonomy`) the full-close /
        partial-reduce SELL paths already enforce: master gate, market mode,
        paper-only, daily-loss breaker, max-open-positions, and — because
        this is a BUY/ADD — the per-trade notional cap. Identical safety
        level to the entry BUY path (`on_trade_approved`).

        On any real fill, the monitored quantity is incremented by the
        ACTUAL filled amount (never the requested one) and avg_entry_price
        is recomputed as the cost-weighted average of the old holding and
        the new fill — the same average-in math
        `ExecutionCoordinator._add_position` already applies on its own
        (separate) ledger for an entry BUY.
        """
        try:
            if add_quantity <= 0:
                logger.warning(
                    "add_quantity_non_positive",
                    ticker=position.ticker,
                    add_quantity=add_quantity,
                )
                await self._notify_add_not_executed(position, add_quantity)
                return

            from services.autonomy import check_autonomy

            gate = await check_autonomy(
                "kiwoom",
                action="BUY",
                quantity=add_quantity,
                entry_price=position.current_price,
            )
            if not gate.allowed:
                logger.warning(
                    "add_gate_denied",
                    ticker=position.ticker,
                    reason=reason,
                    check=gate.check,
                    gate_reason=gate.reason,
                )
                await self._notify_add_gate_denied(
                    position, add_quantity, gate.reason
                )
                return

            from app.dependencies import get_trading_coordinator
            from services.trading.coordinator import (
                ORDER_STATUS_REJECTED_LIQUIDITY_CAP,
            )

            trading_coord = await get_trading_coordinator()
            result = await trading_coord._add_to_position(
                position.ticker, add_quantity, decision_id=decision_id
            )

            if result is None:
                # Coordinator had no matching position (a divergent/desynced
                # ledger) — nothing was placed. Leave this manager's
                # quantity/avg untouched rather than guess at what happened
                # (mirrors _execute_reduce_position's same-shaped guard).
                logger.warning(
                    "add_no_coordinator_position",
                    ticker=position.ticker,
                )
                await self._notify_add_ledger_desync(position, add_quantity)
                return

            if result.status == ORDER_STATUS_REJECTED_LIQUIDITY_CAP:
                # 유동성 천장에 막혀 0주 — 원장은 멀쩡하다. desync 통지를
                # 보내면 안 된다(이미 캡을 초과 보유한 종목은 ADD가 매번
                # 0이라 토론 주기마다 허위 🚨가 반복되고, 진짜 desync 신호를
                # 덮는다). 정상 억제이므로 로그만 남기고 조용히 끝낸다.
                logger.info(
                    "add_blocked_by_liquidity_cap",
                    ticker=position.ticker,
                    requested=add_quantity,
                    held_quantity=position.quantity,
                )
                return

            filled = result.filled_quantity
            if filled <= 0:
                logger.warning(
                    "add_unfilled",
                    ticker=position.ticker,
                    requested_quantity=add_quantity,
                )
                await self._notify_add_unfilled(position, add_quantity)
                return

            old_quantity = position.quantity
            old_avg_price = position.avg_price
            new_quantity = old_quantity + filled
            new_avg_price = (
                (old_quantity * old_avg_price) + (filled * result.avg_price)
            ) / new_quantity

            self.update_position(
                position.ticker, quantity=new_quantity, avg_price=new_avg_price
            )

            logger.info(
                "position_added_to",
                ticker=position.ticker,
                filled=filled,
                new_quantity=new_quantity,
                new_avg_price=new_avg_price,
            )

        except Exception as e:
            logger.error(
                "execute_add_position_failed",
                ticker=position.ticker,
                error=str(e),
            )

    async def _apply_decision(
        self,
        position: MonitoredPosition,
        decision,
        decision_id: Optional[str] = None,
    ) -> None:
        """Apply a decision from agent discussion to the position.

        P1 (2026-07-15, docs/superpowers/plans/2026-07-15-position-mgmt-execution.md
        Task P1): partial REDUCE now has a real execution path
        (`_execute_reduce_position`) — it places a quantity-specified SELL
        through the SAME autonomy gate (`check_autonomy`) the full-close path
        already enforces, then updates the monitored quantity by the ACTUAL
        filled amount (oversell-proof, clamped against both this manager's
        and the coordinator's own tracked quantity). This replaces P0's
        notify-only "부분청산 미지원" stand-in
        (docs/superpowers/audits/2026-07-14-autonomous-position-mgmt-audit.md).
        The full-close REDUCE path (new_quantity <= 0 -> _execute_close_position)
        and plain SELL are real execution and remain unaffected.

        P2 (2026-07-15, Task P2): ADD now also has a real execution path
        (`_execute_add_position`) — the buy quantity is sized as a
        configurable percentage of the CURRENTLY held quantity
        (``round(position.quantity * config.add_position_pct)``), then
        placed through the SAME autonomy gate (`check_autonomy(BUY)`) the
        SELL paths already enforce, with the same identical safety level as
        the entry BUY path. A sizing result of zero or less keeps P0's
        not-executed notice (no buy execution attempted, no gate call).
        """
        from services.agent_chat.models import DecisionAction

        logger.info(
            "applying_position_decision",
            ticker=position.ticker,
            action=decision.action.value if hasattr(decision.action, 'value') else decision.action,
        )

        try:
            if decision.action == DecisionAction.SELL:
                await self._execute_close_position(
                    position, "agent_decision", decision_id=decision_id
                )

            elif decision.action == DecisionAction.REDUCE:
                # Partial close - calculate quantity
                if decision.quantity:
                    new_quantity = position.quantity - decision.quantity
                    if new_quantity <= 0:
                        # Full close: the REAL executing path. Unchanged.
                        await self._execute_close_position(
                            position, "agent_decision_reduce", decision_id=decision_id
                        )
                    else:
                        # Partial reduce: real execution path (P1,
                        # 2026-07-15) — a quantity-specified SELL through the
                        # SAME autonomy gate the full-close path uses.
                        # Replaces P0's notify-only stand-in.
                        await self._execute_reduce_position(
                            position, decision.quantity, "agent_decision_reduce_partial",
                            decision_id=decision_id,
                        )

            elif decision.action in (DecisionAction.HOLD, DecisionAction.ADD):
                if decision.action == DecisionAction.ADD:
                    # P2 (2026-07-15): ADD now has a real execution path — a
                    # BUY sized as a percentage of the CURRENTLY held
                    # quantity (config.add_position_pct), gated the SAME way
                    # the SELL paths already are (check_autonomy). The
                    # stop/take adjustment below still applies same as for
                    # HOLD regardless of the add's own outcome.
                    add_qty = round(position.quantity * self.config.add_position_pct)
                    await self._execute_add_position(
                        position, add_qty, "agent_decision_add", decision_id=decision_id
                    )

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
                PositionEventType.STRATEGIC_REEVAL: "🔄",
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
                            # S-5: schema extension. isoformat/None -- a
                            # pre-S-5 blob simply lacks this key, which
                            # `.get()` on restore reads back as None (see
                            # restore_stop_overlay), matching a fresh
                            # position's own default.
                            "take_profit_reached_at": (
                                position.take_profit_reached_at.isoformat()
                                if position.take_profit_reached_at is not None
                                else None
                            ),
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

    @staticmethod
    def _restore_stop_is_structurally_insane(
        current_price: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> bool:
        """Restore-path-only sanity gate (G-1/D1, extended D1b — docs/
        superpowers/specs/2026-07-20-gap-discipline-design.md §0) —
        deliberately NOT `_stops_sane`, which stays byte-invariant for the
        intraday stop-SETTING paths (`_apply_decision`,
        `_apply_take_profit_lock_in`, `_check_trailing_stop`): a stop or
        take-profit being newly set at-or-through the current price must
        still be rejected there, or it fires stop_loss_hit/take_profit_hit
        on the very same tick (the 2026-07-12 15:40 CPU-spin hang this repo
        already fixed once).

        A RESTORED level is different: it is not being newly set, it already
        existed and survived a restart. The 2026-07-20 00:02 incident
        (`restore_stops_insane_dropped ticker=000660 stop_loss=1,807,923
        current_price=1,782,000`) showed the old shared `_stops_sane` gate
        dropping an already-raised protective stop just because a pre-open
        gap pushed price through it — discarding real discipline instead of
        enforcing it. D1: a gap-through stop is not corrupted data, it's the
        ordinary shape stop discipline takes at a gap open. Preserve it
        verbatim; `_check_position`'s existing STOP_LOSS_HIT detection (fully
        unchanged by this method) fires on it normally on the next monitor
        tick, exactly like any other price crossing.

        D1b (this method, 2026-07-20 follow-up): the SAME reasoning extends
        to a restored take_profit gapping through the current price
        (`take_profit <= current_price`) — G-1 originally kept that shape
        classified as structurally insane (drop the WHOLE entry, including
        its accompanying stop_loss and S-5 lock-in trigger), which was an
        asymmetry: a favorable gap-up lost its protective stop while an
        adverse gap-through-stop kept it. Take-profit has no auto-sell
        behind it either way (`auto_execute_take_profit=False`,
        `take_profit_mode=user_approval` — TAKE_PROFIT_HIT only ever opens a
        discussion or marks `take_profit_reached_at`), so preserving it is
        harmless and keeps the S-5 lock-in ratchet chain alive. See
        `restore_stop_overlay` for the accompanying `gap_through_tp_restored`
        log, symmetric with `gap_through_stop_restored` below.

        Classification (only two ways an entry is dropped now — everything
        else, INCLUDING stop_loss at-or-above current_price and take_profit
        at-or-below current_price, restores normally):
        - current_price unknown/non-positive: cannot validate at all,
          fail-closed.
        - stop_loss and take_profit both set with stop_loss >= take_profit:
          the two saved levels contradict each other independent of the
          current price — never a legitimate gap, always corrupted data
          (this also catches a gap-through-shaped stop_loss or take_profit
          whose paired level sits on the wrong side of it, which would
          otherwise look like a preservable gap).
        """
        if not current_price or current_price <= 0:
            return True
        if (
            stop_loss is not None
            and take_profit is not None
            and stop_loss >= take_profit
        ):
            return True
        return False

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
        - An entry that is structurally insane per
          `_restore_stop_is_structurally_insane` (P0-2b: polluted/stale
          blob — NOT the same gate as `_stops_sane`, see that method's
          docstring) is skipped entirely and its values dropped from the
          blob by the re-save.
        - An entry whose stop_loss alone is at-or-above the current price
          (a pre-open gap ran through an already-raised stop) is preserved
          verbatim instead of dropped (G-1/D1) — a `gap_through_stop_restored`
          info log fires and the normal monitor loop fires STOP_LOSS_HIT on
          it next tick, same as any other price crossing.
        - An entry whose take_profit alone is at-or-below the current price
          (a favorable gap-up ran through an already-set target) is likewise
          preserved verbatim, accompanying stop_loss included (D1b) — a
          `gap_through_tp_restored` info log fires and the normal monitor
          loop fires TAKE_PROFIT_HIT on it next tick (still no auto-sell —
          auto_execute_take_profit stays False), keeping the S-5 lock-in
          ratchet chain intact for a later retracement.

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
                current_price = position.current_price
                restored_this_ticker = False

                if self._restore_stop_is_structurally_insane(
                    current_price, saved_stop, saved_take
                ):
                    # Structural violation (P0-2b: polluted/stale blob) —
                    # see `_restore_stop_is_structurally_insane`'s docstring
                    # for the exact classification. Skip stop_loss/
                    # take_profit/trailing_stop_pct entirely; the re-save
                    # below drops the insane values from the blob.
                    # take_profit_reached_at is handled separately below,
                    # independent of this drop (G-1).
                    logger.warning(
                        "restore_stops_insane_dropped",
                        ticker=ticker,
                        stop_loss=saved_stop,
                        take_profit=saved_take,
                        current_price=current_price,
                    )
                    await self._notify_restore_stops_dropped(
                        ticker, saved_stop, saved_take, current_price
                    )
                else:
                    # G-1/D1: a saved stop_loss at-or-above the current price
                    # is a pre-open gap that ran through an already-raised
                    # stop, not corrupted data — preserve it verbatim and let
                    # `_check_position`'s ordinary STOP_LOSS_HIT detection
                    # (unchanged) fire on it the next monitor tick.
                    if (
                        saved_stop is not None
                        and current_price is not None
                        and saved_stop >= current_price
                    ):
                        logger.info(
                            "gap_through_stop_restored",
                            ticker=ticker,
                            stop_loss=saved_stop,
                            current_price=current_price,
                        )

                    # D1b: the symmetric favorable case — a saved take_profit
                    # at-or-below the current price is a gap-up that ran
                    # through an already-set target, not corrupted data.
                    # Preserve it verbatim and let `_check_position`'s
                    # ordinary TAKE_PROFIT_HIT detection (unchanged, and
                    # still no auto-sell — auto_execute_take_profit=False)
                    # fire on it the next monitor tick, which is also what
                    # keeps the S-5 lock-in ratchet chain alive on a later
                    # retracement.
                    if (
                        saved_take is not None
                        and current_price is not None
                        and saved_take <= current_price
                    ):
                        logger.info(
                            "gap_through_tp_restored",
                            ticker=ticker,
                            take_profit=saved_take,
                            current_price=current_price,
                        )

                    kwargs: Dict[str, float] = {}
                    if position.stop_loss is None and saved_stop is not None:
                        kwargs["stop_loss"] = saved_stop
                    if position.take_profit is None and saved_take is not None:
                        kwargs["take_profit"] = saved_take
                    if (
                        position.trailing_stop_pct is None
                        and saved.get("trailing_stop_pct") is not None
                    ):
                        kwargs["trailing_stop_pct"] = saved["trailing_stop_pct"]

                    if kwargs:
                        self.update_position(ticker, **kwargs)
                        restored_this_ticker = True

                # take_profit_reached_at (S-5, independent since G-1): a
                # plain bookkeeping timestamp, not a live order level --
                # restored unconditionally, regardless of whether the
                # stop_loss/take_profit fields above were structurally
                # dropped, preserved as a gap-through, or restored normally
                # (the field has no sanity concept of its own — it never
                # bears on "was TP ever reached in the past"). A pre-S-5
                # blob has no such key -- `saved.get(...)` is None -> no-op,
                # field stays None exactly like a fresh position's default
                # (backward compatible).
                if (
                    position.take_profit_reached_at is None
                    and saved.get("take_profit_reached_at") is not None
                ):
                    try:
                        position.take_profit_reached_at = datetime.fromisoformat(
                            saved["take_profit_reached_at"]
                        )
                        restored_this_ticker = True
                    except (TypeError, ValueError):
                        logger.warning(
                            "restore_take_profit_reached_at_invalid",
                            ticker=ticker,
                            value=saved.get("take_profit_reached_at"),
                        )

                if restored_this_ticker:
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
