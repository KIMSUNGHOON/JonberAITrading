"""
Execution Coordinator

Orchestrates the trading workflow:
Analysis → Approval → Portfolio → Order → Monitor
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, date
from typing import Optional, List, Callable, Awaitable

from .models import (
    TradingMode,
    TradingState,
    AccountInfo,
    ManagedPosition,
    OrderRequest,
    OrderResult,
    AllocationPlan,
    TradingAlert,
    AlertType,
    RiskParameters,
    PositionStatus,
    OrderSide,
    StopLossMode,
    ActivityType,
    ActivityLog,
    QueueStatus,
    QueuedTrade,
    AgentStatus,
    WatchedStock,
    WatchStatus,
)
from .portfolio_agent import PortfolioAgent
from .order_agent import OrderAgent, KiwoomRateLimiter
from .risk_monitor import RiskMonitor
from .market_hours import MarketType, get_market_hours_service
from .strategy import TradingStrategy
from .strategy_engine import StrategyEngine
from .pending_order_tracker import PendingOrderTracker, TrackedOrder
from .position_registration import register_fill_as_position
from .reconciler import reconcile
from .trade_log import record_trade_fill

logger = logging.getLogger(__name__)


# Actions that grow exposure map to a BUY order; everything else reduces it and
# maps to SELL. An ADD mis-mapped to SELL reverses an autonomous add-to-position
# into a liquidation — audit finding A1 (2026-07-12). Mirrors the gate's
# POSITION_INCREASING_ACTIONS so side and cap logic stay in agreement.
_BUY_SIDE_ACTIONS = {"BUY", "ADD"}


def _order_side_for_action(action: str) -> OrderSide:
    """Resolve the order side for a trade action.

    BUY/ADD increase exposure → BUY side. SELL/REDUCE decrease it → SELL side.
    """
    return OrderSide.BUY if action in _BUY_SIDE_ACTIONS else OrderSide.SELL


class ExecutionCoordinator:
    """
    Central coordinator for the auto-trading system.

    Orchestrates:
    1. Trade approval → Portfolio allocation
    2. Portfolio allocation → Order execution
    3. Order execution → Risk monitoring

    Provides unified interface for:
    - Starting/stopping auto-trading
    - Handling approved trades
    - Managing alerts and user actions
    """

    def __init__(
        self,
        kiwoom_client=None,
        redis_client=None,
        risk_params: Optional[RiskParameters] = None,
    ):
        """
        Initialize Execution Coordinator.

        Args:
            kiwoom_client: Kiwoom API client
            redis_client: Redis client for rate limiting
            risk_params: Risk parameters
        """
        self.risk_params = risk_params or RiskParameters()

        # Initialize agents
        self.portfolio_agent = PortfolioAgent(self.risk_params)
        self.order_agent = OrderAgent(
            kiwoom_client=kiwoom_client,
            rate_limiter=KiwoomRateLimiter(redis_client),
        )
        self.risk_monitor = RiskMonitor(
            risk_params=self.risk_params,
            price_fetcher=self._get_current_price,
            alert_sender=self._on_alert,
            order_executor=self._execute_order_from_monitor,
            price_sink=self._on_price_update,
        )

        # State
        self._state = TradingState(risk_params=self.risk_params)
        self._kiwoom = kiwoom_client

        # Market hours service
        self._market_hours = get_market_hours_service()

        # Callbacks
        self._alert_callback: Optional[Callable[[TradingAlert], Awaitable[None]]] = None
        self._state_callback: Optional[Callable[[TradingState], Awaitable[None]]] = None

        # Strategy
        self._strategy: Optional[TradingStrategy] = None
        self._strategy_engine: Optional[StrategyEngine] = None

        # Open-queue scheduler (R5-P1): auto-process the queue on the KRX
        # closed→open transition while the system is already running.
        self._market_was_open = False
        self._queue_scheduler_task: Optional[asyncio.Task] = None
        self._queue_scheduler_interval = 30.0
        # Re-entrancy guard: process_trade_queue is now reachable from start(),
        # the scheduler, and manual API calls — concurrent runs would double-
        # execute PENDING/PROCESSING trades (review #6).
        self._processing_queue = False

        # Automatic persistence is only active within a session (start→stop), so
        # a coordinator built in a unit test does not write to the shared DB. The
        # explicit _persist_state/_restore_state helpers ignore this flag.
        self._persistence_active = False

        # F3 (audit 2026-07-13): a BUY that didn't (fully) fill at placement
        # time previously vanished from tracking — the coordinator only
        # registered a position on the filled portion, so any broker-side
        # post-fill went unwatched by every defense engine. Tracks the
        # remainder and reconciles it against ka10076 on the scheduler tick.
        self.fill_tracker = PendingOrderTracker()

        # F3 t6: counts scheduler ticks so the broker-local reconciler runs
        # every 2nd tick (60s at the default 30s interval) instead of every
        # tick — it does a full get_account_balance() call plus per-ticker
        # PositionManager lookups, heavier than the fill-tracker poll.
        self._reconcile_tick_count = 0

    # -------------------------------------------
    # Activity Logging
    # -------------------------------------------

    def _log_activity(
        self,
        activity_type: ActivityType,
        message: str,
        agent: str = "system",
        ticker: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Log an activity to the state's activity log."""
        activity = ActivityLog(
            activity_type=activity_type,
            agent=agent,
            ticker=ticker,
            message=message,
            details=details,
        )
        # Keep only last 100 activities
        self._state.activity_log.append(activity)
        if len(self._state.activity_log) > 100:
            self._state.activity_log = self._state.activity_log[-100:]

        logger.info(f"[{agent.upper()}] {message}")

    def get_activity_log(self, limit: int = 50) -> List[ActivityLog]:
        """Get recent activity log entries."""
        return self._state.activity_log[-limit:]

    # -------------------------------------------
    # Lifecycle
    # -------------------------------------------

    async def start(self):
        """Start the auto-trading system."""
        logger.info("[Coordinator] Starting auto-trading system")

        # Fetch initial account info
        await self._refresh_account_info()

        # Restore restart-critical state (positions+stops, queue, daily count)
        # BEFORE the monitor starts so recovered stops are watched immediately.
        await self._restore_state()

        # Activate persistence BEFORE the startup queue drain below, so trades
        # executed at open are persisted — otherwise a crash before the next
        # persist re-executes them and loses their stop defense (review #3).
        self._persistence_active = True

        # Start risk monitor
        await self.risk_monitor.start()

        # Update state
        self._state.mode = TradingMode.ACTIVE
        self._state.started_at = datetime.now()

        self._log_activity(
            ActivityType.SYSTEM_START,
            f"Auto-trading system started. Account: ₩{self._state.account.total_equity:,.0f}",
            details={"account": self._state.account.model_dump()},
        )

        await self._notify_state_change()

        # Process any pending trades in queue (if market is open)
        market_session = self._market_hours.get_market_session(MarketType.KRX)
        if market_session.is_open and self.get_trade_queue():
            logger.info("[Coordinator] Processing pending trade queue after start")
            await self.process_trade_queue()

        # Seed the scheduler's edge state and start watching for the KRX
        # closed→open transition so a queue built overnight processes at open.
        self._market_was_open = market_session.is_open
        if self._queue_scheduler_task is None or self._queue_scheduler_task.done():
            self._queue_scheduler_task = asyncio.create_task(
                self._queue_scheduler_loop()
            )

    async def stop(self):
        """Stop the auto-trading system."""
        logger.info("[Coordinator] Stopping auto-trading system")

        await self.risk_monitor.stop()
        self._state.mode = TradingMode.STOPPED

        # Stop the open-queue scheduler.
        if self._queue_scheduler_task is not None:
            self._queue_scheduler_task.cancel()
            self._queue_scheduler_task = None

        # Persist restart-critical state on graceful shutdown, then deactivate.
        if self._persistence_active:
            await self._persist_state()
        self._persistence_active = False

        self._log_activity(
            ActivityType.SYSTEM_STOP,
            "Auto-trading system stopped",
        )

        await self._notify_state_change()

    async def pause(self, reason: str = "Manual pause"):
        """Pause auto-trading."""
        await self.risk_monitor.pause(reason)
        self._state.mode = TradingMode.PAUSED

        self._log_activity(
            ActivityType.SYSTEM_PAUSE,
            f"Trading paused: {reason}",
            details={"reason": reason},
        )

        await self._notify_state_change()

    async def resume(self):
        """Resume auto-trading."""
        await self.risk_monitor.resume()
        self._state.mode = TradingMode.ACTIVE

        self._log_activity(
            ActivityType.SYSTEM_RESUME,
            "Trading resumed",
        )

        await self._notify_state_change()

        # Process any pending trades in queue (if market is open)
        market_session = self._market_hours.get_market_session(MarketType.KRX)
        if market_session.is_open and self.get_trade_queue():
            logger.info("[Coordinator] Processing pending trade queue after resume")
            await self.process_trade_queue()

    # -------------------------------------------
    # Trade Execution Flow
    # -------------------------------------------

    async def on_trade_approved(
        self,
        session_id: str,
        ticker: str,
        stock_name: Optional[str],
        action: str,  # "BUY" or "SELL"
        entry_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        risk_score: int,
        quantity_override: Optional[int] = None,
        autonomous: bool = False,
        queue_id: Optional[str] = None,
    ) -> AllocationPlan:
        """
        Handle an approved trade from the analysis system.

        autonomous=True marks trades originated by an autonomy engine (R3):
        if such a trade gets QUEUED, the queue processor re-checks the shared
        autonomy gate before executing it — a mode flip to HITL or a tripped
        limit between queueing and execution must win.

        Args:
            session_id: Analysis session ID
            ticker: Stock ticker
            stock_name: Stock name
            action: BUY or SELL
            entry_price: Proposed entry price
            stop_loss: Stop-loss price
            take_profit: Take-profit price
            risk_score: Risk score from analysis (1-10)
            quantity_override: Optional manual quantity override
            queue_id: The originating QueuedTrade.id, when this call comes
                from `_process_trade_queue_inner` (F3) — threaded onto any
                fill-tracker registration below so a later post-fill can
                annotate the queue entry it came from.

        Returns:
            AllocationPlan with execution details
        """
        self._log_activity(
            ActivityType.TRADE_APPROVED,
            f"Trade approved: {action} {stock_name or ticker} @ ₩{entry_price:,.0f} (risk: {risk_score})",
            agent="system",
            ticker=ticker,
            details={
                "session_id": session_id,
                "action": action,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_score": risk_score,
            },
        )

        # Update portfolio agent status with trade details
        self._update_agent_status(
            "portfolio",
            AgentStatus.WORKING,
            task=f"Calculating allocation for {action} {stock_name or ticker}",
            processing_stock=ticker,
            processing_stock_name=stock_name,
            trade_details={
                "action": action,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_score": risk_score,
            },
        )

        # Check market hours (KRX for Korean stocks)
        market_session = self._market_hours.get_market_session(MarketType.KRX)

        # Determine if we should queue the trade
        should_queue = False
        queue_reason = ""

        if not market_session.is_open:
            should_queue = True
            queue_reason = f"Market closed: {market_session.message}"
        elif self._state.mode == TradingMode.STOPPED:
            should_queue = True
            queue_reason = "Trading system not started - trade will execute when started"
        elif self._state.mode == TradingMode.PAUSED:
            should_queue = True
            queue_reason = "Trading paused - trade will execute when resumed"

        # Queue trade if needed
        if should_queue:
            queued_trade = self.add_to_queue(
                session_id=session_id,
                ticker=ticker,
                stock_name=stock_name,
                action=action,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_score=risk_score,
                reason=queue_reason,
                autonomous=autonomous,
                quantity=quantity_override,
            )

            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=_order_side_for_action(action),
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=f"Trade queued: {queue_reason} (Queue ID: {queued_trade.id})",
            )

        # Check daily trade limit
        if self._state.daily_trades_count >= self.risk_params.max_daily_trades:
            rationale = f"Daily trade limit reached ({self._state.daily_trades_count}/{self.risk_params.max_daily_trades})"
            self._log_activity(
                ActivityType.TRADE_REJECTED,
                rationale,
                agent="system",
                ticker=ticker,
            )
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=_order_side_for_action(action),
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=rationale,
            )

        # Refresh account info
        await self._refresh_account_info()

        # Calculate allocation
        side = _order_side_for_action(action)
        allocation = self.portfolio_agent.calculate_allocation(
            account=self._state.account,
            ticker=ticker,
            stock_name=stock_name,
            side=side,
            entry_price=entry_price,
            risk_score=risk_score,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_positions=self._state.positions,
        )

        # Override quantity if provided
        if quantity_override and quantity_override > 0:
            allocation.quantity = quantity_override
            allocation.estimated_amount = quantity_override * entry_price
            allocation.rationale += f" (quantity override: {quantity_override})"

        # Log allocation decision
        self._log_activity(
            ActivityType.ALLOCATION_CALCULATED,
            f"Allocation: {allocation.quantity} shares @ ₩{entry_price:,.0f} = ₩{allocation.estimated_amount:,.0f} ({allocation.position_pct:.1f}%)",
            agent="portfolio",
            ticker=ticker,
            details={
                "quantity": allocation.quantity,
                "entry_price": entry_price,
                "estimated_amount": allocation.estimated_amount,
                "position_pct": allocation.position_pct,
                "rationale": allocation.rationale,
            },
        )

        # Update portfolio agent with allocation result
        self._update_agent_status(
            "portfolio",
            AgentStatus.IDLE,
            action=f"Allocated {allocation.quantity} shares",
            processing_stock=ticker,
            processing_stock_name=stock_name,
            trade_details={
                "action": action,
                "quantity": allocation.quantity,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_score": risk_score,
                "estimated_amount": allocation.estimated_amount,
                "position_pct": allocation.position_pct,
            },
            last_result={
                "success": allocation.quantity > 0,
                "message": allocation.rationale,
                "quantity": allocation.quantity,
                "estimated_amount": allocation.estimated_amount,
            },
        )
        self._complete_agent_task("portfolio", success=allocation.quantity > 0)

        if allocation.quantity <= 0:
            self._log_activity(
                ActivityType.TRADE_REJECTED,
                f"Allocation rejected: {allocation.rationale}",
                agent="portfolio",
                ticker=ticker,
            )
            return allocation

        # Execute rebalancing orders first
        for rebalance_order in allocation.rebalance_orders:
            self._log_activity(
                ActivityType.ORDER_PLACED,
                f"Rebalance order: {rebalance_order.side.value} {rebalance_order.quantity} shares",
                agent="order",
                ticker=rebalance_order.ticker,
            )
            await self._execute_order(rebalance_order)

        # Execute main order
        order = OrderRequest(
            ticker=ticker,
            stock_name=stock_name,
            side=side,
            quantity=allocation.quantity,
            price=entry_price,
            session_id=session_id,
            reason=f"Trade approval (risk: {risk_score})",
        )

        self._log_activity(
            ActivityType.ORDER_PLACED,
            f"Order placed: {action} {allocation.quantity} {stock_name or ticker} @ ₩{entry_price:,.0f}",
            agent="order",
            ticker=ticker,
            details={
                "side": action,
                "quantity": allocation.quantity,
                "price": entry_price,
            },
        )

        # Update order agent status
        self._update_agent_status(
            "order",
            AgentStatus.WORKING,
            task=f"Executing {action} {allocation.quantity} {stock_name or ticker}",
            processing_stock=ticker,
            processing_stock_name=stock_name,
            trade_details={
                "action": action,
                "quantity": allocation.quantity,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "estimated_amount": allocation.estimated_amount,
            },
        )

        result = await self._execute_order(order)

        # Log execution result
        if result.filled_quantity > 0:
            self._log_activity(
                ActivityType.ORDER_EXECUTED,
                f"Order filled: {result.filled_quantity} shares @ ₩{result.avg_price:,.0f}",
                agent="order",
                ticker=ticker,
                details={
                    "filled_quantity": result.filled_quantity,
                    "avg_price": result.avg_price,
                    "order_id": result.order_id,
                },
            )
            # Update order agent with success result
            self._update_agent_status(
                "order",
                AgentStatus.IDLE,
                action=f"Filled {result.filled_quantity} shares @ ₩{result.avg_price:,.0f}",
                processing_stock=ticker,
                processing_stock_name=stock_name,
                trade_details={
                    "action": action,
                    "quantity": result.filled_quantity,
                    "entry_price": result.avg_price,
                    "total_amount": result.filled_quantity * result.avg_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                },
                last_result={
                    "success": True,
                    "message": f"Order filled: {result.filled_quantity} shares",
                    "order_id": result.order_id,
                    "filled_quantity": result.filled_quantity,
                    "avg_price": result.avg_price,
                },
            )
            self._complete_agent_task("order", success=True)

            # P1-1 gap (PART 2, 2026-07-13): `_execute_order` only records BUY
            # fills — its SELL branch defers to `_apply_sell_fill`, the choke
            # point every OTHER SELL caller (RiskMonitor triggers,
            # _execute_order_from_monitor) invokes right after. This
            # on_trade_approved path (agent-chat direct decisions + queue
            # replays) never calls `_apply_sell_fill`, so its SELL/REDUCE
            # fills recorded nothing. Record them here with the same
            # fire-and-forget helper, gated by `_persistence_active` like
            # every other call site — and only for SELL, so a BUY approval
            # (already recorded inside `_execute_order` above) is never
            # double-counted.
            if self._persistence_active and side == OrderSide.SELL:
                record_trade_fill(
                    stk_cd=ticker,
                    stk_nm=stock_name,
                    side="sell",
                    order_type=getattr(order.order_type, "value", order.order_type),
                    price=result.avg_price or entry_price or 0,
                    quantity=result.requested_quantity,
                    executed_quantity=result.filled_quantity,
                    status=(
                        "completed"
                        if result.filled_quantity >= result.requested_quantity
                        else "partial"
                    ),
                    order_id=result.order_id,
                    session_id=session_id,
                )
        else:
            self._log_activity(
                ActivityType.ORDER_FAILED,
                f"Order failed: {result.message or 'Unknown error'}",
                agent="order",
                ticker=ticker,
            )
            # Update order agent with failure result
            self._update_agent_status(
                "order",
                AgentStatus.IDLE,
                action=f"Order failed: {result.message or 'Unknown error'}",
                error=result.message,
                processing_stock=ticker,
                processing_stock_name=stock_name,
                last_result={
                    "success": False,
                    "message": result.message or "Unknown error",
                },
            )
            self._complete_agent_task("order", success=False)

        # If successful, add to monitoring
        if result.filled_quantity > 0 and side == OrderSide.BUY:
            position = ManagedPosition(
                ticker=ticker,
                stock_name=stock_name or ticker,
                quantity=result.filled_quantity,
                avg_price=result.avg_price,
                current_price=result.avg_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                stop_loss_mode=self.risk_params.stop_loss_mode,
                status=PositionStatus.FILLED,
                analysis_session_id=session_id,
                risk_score=risk_score,
            )
            self._add_position(position)

            self._log_activity(
                ActivityType.POSITION_OPENED,
                f"Position opened: {result.filled_quantity} {stock_name or ticker} @ ₩{result.avg_price:,.0f}",
                agent="portfolio",
                ticker=ticker,
                details={
                    "quantity": result.filled_quantity,
                    "avg_price": result.avg_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                },
            )

        # F3: an unfilled/partial BUY still has (or may soon have) broker-side
        # exposure that nothing is watching yet — track the remainder so the
        # scheduler's ka10076 poll can pick up the post-fill later. SELL
        # unfilled remainders are out of scope (R5-P4).
        #
        # Split orders (F3 review CRITICAL): the aggregate carries per-part
        # results in `result.parts`, each with its OWN broker ord_no. ka10076
        # matches by ord_no, so every unfilled/partial part is tracked as its
        # own TrackedOrder — one aggregate entry would poison the diff
        # arithmetic (several broker orders summed against one total).
        if side == OrderSide.BUY and result.status in ("pending", "partial"):
            registered: List[str] = []
            for part in (result.parts or [result]):
                if part.status not in ("pending", "partial"):
                    continue
                remaining = part.requested_quantity - part.filled_quantity
                if remaining <= 0:
                    continue
                self.fill_tracker.register(
                    TrackedOrder(
                        ord_no=part.order_id,
                        ticker=ticker,
                        stock_name=stock_name or ticker,
                        side="buy",
                        total_quantity=part.requested_quantity,
                        filled_quantity=part.filled_quantity,
                        filled_amount=part.filled_quantity * part.avg_price,
                        limit_price=entry_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        source_queue_id=queue_id,
                        source_session_id=session_id,
                        risk_score=risk_score,
                        trade_date=date.today().strftime("%Y%m%d"),
                    )
                )
                registered.append(f"{part.order_id}:{remaining}주")
            if registered:
                self._schedule_persist()
                self._log_activity(
                    ActivityType.ORDER_PLACED,
                    f"미체결 잔량 추적 등록: {stock_name or ticker} "
                    f"({', '.join(registered)})",
                    agent="order",
                    ticker=ticker,
                    details={"tracked": registered},
                )

        return allocation

    async def _execute_order(self, order: OrderRequest) -> OrderResult:
        """Execute an order and update state."""
        # Add to pending
        self._state.pending_orders.append(order)
        await self._notify_state_change()

        # Execute
        result = await self.order_agent.execute_order(order)

        # Remove from pending
        self._state.pending_orders = [
            o for o in self._state.pending_orders
            if o.ticker != order.ticker
        ]

        # Update trade count
        if result.filled_quantity > 0:
            self._state.daily_trades_count += 1
            self._schedule_persist()

            # P1-1: record the fill for /trades — BUY only here. Every SELL
            # caller of _execute_order also calls _apply_sell_fill right
            # after, which is the single choke point for SELL fills; a
            # side-agnostic record here would double-count those. Gated by
            # _persistence_active (same rule as _schedule_persist) so a
            # coordinator built in a unit test never writes to real storage.
            if self._persistence_active and order.side in (OrderSide.BUY, "buy"):
                record_trade_fill(
                    stk_cd=order.ticker,
                    stk_nm=order.stock_name,
                    side="buy",
                    order_type=getattr(order.order_type, "value", order.order_type),
                    price=result.avg_price or order.price or 0,
                    quantity=result.requested_quantity,
                    executed_quantity=result.filled_quantity,
                    status=(
                        "completed"
                        if result.filled_quantity >= result.requested_quantity
                        else "partial"
                    ),
                    order_id=result.order_id,
                    session_id=order.session_id,
                )

        await self._notify_state_change()

        return result

    async def _execute_order_from_monitor(self, order: OrderRequest):
        """Execute order from risk monitor (stop-loss/take-profit).

        This is the choke point for every AGENT_AUTO defensive sell — it MUST
        pass the shared autonomy gate, the same one PositionManager's
        `_execute_close_position` (A2) and the queue re-gate (R5-P0) already
        enforce. Before this fix a stop-loss/take-profit fired straight to the
        broker with no gate check at all (audit I1, 2026-07-13). A denied sell
        places nothing and leaves the position tracked/watched — the
        USER_APPROVAL alert path (RiskMonitor's non-AGENT_AUTO branch) is
        untouched by this change.
        """
        from services.autonomy import check_autonomy

        position = next(
            (p for p in self._state.positions if p.ticker == order.ticker), None
        )

        gate = await check_autonomy(
            "kiwoom",
            action="SELL",
            quantity=order.quantity,
            entry_price=order.price,
        )
        if not gate.allowed:
            logger.warning(
                f"[Coordinator] AGENT_AUTO defensive sell blocked by gate: "
                f"{order.ticker} check={gate.check} reason={gate.reason}"
            )
            # Notify once per denied episode, not on every RiskMonitor tick —
            # mirrors the PositionManager A2 latch (close_gate_denied_notified).
            if position is not None and not position.monitor_gate_denied_notified:
                position.monitor_gate_denied_notified = True
                await self._notify_monitor_gate_denied(order, gate.reason)
            return

        if position is not None and position.monitor_gate_denied_notified:
            # Gate allowed again: clear the latch so a future denial notifies.
            position.monitor_gate_denied_notified = False

        result = await self._execute_order(order)
        # Track the ACTUAL fill: full → remove, partial → reduce, none → retain.
        self._apply_sell_fill(order.ticker, result.filled_quantity, order=order, result=result)

    async def _notify_monitor_gate_denied(self, order: OrderRequest, gate_reason: str) -> None:
        """Best-effort Telegram notice when the autonomy gate blocks an
        AGENT_AUTO defensive sell — the human must know a stop-loss/take-profit
        did NOT execute and the position is still open."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"🚫 자율 방어매도 게이트 거부 ({order.ticker}, "
                    f"{order.reason or 'stop-loss/take-profit'}): {gate_reason}. "
                    f"포지션은 유지되며 수동 조치가 필요합니다."
                )
        except Exception as e:
            logger.warning(f"[Coordinator] Failed to notify gate denial: {e}")

    # -------------------------------------------
    # Position Management
    # -------------------------------------------

    def _add_position(self, position: ManagedPosition):
        """Add a position to tracking."""
        # Check if already exists
        existing_idx = next(
            (i for i, p in enumerate(self._state.positions) if p.ticker == position.ticker),
            None
        )

        if existing_idx is not None:
            # Update existing position (average in)
            existing = self._state.positions[existing_idx]
            total_qty = existing.quantity + position.quantity
            total_cost = (existing.avg_price * existing.quantity) + (position.avg_price * position.quantity)
            existing.quantity = total_qty
            existing.avg_price = total_cost / total_qty
            existing.last_updated = datetime.now()
            # I1 (final-review): coalesce stops onto the merged position —
            # keep existing's non-None stops, only fill gaps from the
            # incoming tranche.
            if existing.stop_loss is None and position.stop_loss is not None:
                existing.stop_loss = position.stop_loss
            if existing.take_profit is None and position.take_profit is not None:
                existing.take_profit = position.take_profit
            watched = existing
        else:
            self._state.positions.append(position)
            watched = position

        # Add to risk monitor — MUST watch the merged position (`watched`),
        # not the incoming delta `position`: add_position replaces
        # WatchConfig wholesale, so after a merge the monitor would otherwise
        # watch only the last tranche's quantity while the real position is
        # the merged total — a stop trigger would then sell only that
        # tranche (I1, final-review).
        self.risk_monitor.add_position(watched)

        # Update risk agent status
        self._update_agent_status(
            "risk",
            AgentStatus.WORKING,
            task=f"Monitoring {position.stock_name or position.ticker}",
            processing_stock=position.ticker,
            processing_stock_name=position.stock_name,
            trade_details={
                "action": "MONITOR",
                "quantity": position.quantity,
                "entry_price": position.avg_price,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
            },
        )

        logger.info(f"[Coordinator] Position added/updated: {position.ticker}")
        self._schedule_persist()

    def _remove_position(self, ticker: str):
        """Remove a position from tracking."""
        # Find position before removing for status update
        position = next((p for p in self._state.positions if p.ticker == ticker), None)

        self._state.positions = [
            p for p in self._state.positions if p.ticker != ticker
        ]
        self.risk_monitor.remove_position(ticker)

        # Update risk agent status
        remaining_count = len(self._state.positions)
        if remaining_count > 0:
            self._update_agent_status(
                "risk",
                AgentStatus.WORKING,
                task=f"Monitoring {remaining_count} positions",
                last_result={
                    "success": True,
                    "message": f"Position closed: {position.stock_name if position else ticker}",
                },
            )
        else:
            self._update_agent_status(
                "risk",
                AgentStatus.IDLE,
                action="No positions to monitor",
                last_result={
                    "success": True,
                    "message": f"Position closed: {position.stock_name if position else ticker}",
                },
            )

        logger.info(f"[Coordinator] Position removed: {ticker}")
        self._schedule_persist()

    def _apply_sell_fill(
        self,
        ticker: str,
        filled_quantity: int,
        *,
        order: Optional[OrderRequest] = None,
        result: Optional[OrderResult] = None,
    ) -> None:
        """Reconcile position tracking with the ACTUAL fill of a SELL/close (A3).

        Full fill → remove; partial → reduce and keep monitoring the remainder;
        none → keep the position. A sell that did not fill must NOT orphan the
        exposure — previously the close removed the position unconditionally, so a
        rejected/unfilled sell dropped a still-open position from all defense.

        `order`/`result` are optional so existing bare callers keep working,
        but every current call site passes both — this is the single choke
        point for recording a SELL fill (/trades, P1-1), independent of
        whether we still have a locally tracked position for `ticker`.
        """
        if filled_quantity <= 0:
            logger.warning(
                f"[Coordinator] SELL for {ticker} did not fill — position retained"
            )
            return

        if self._persistence_active and order is not None and result is not None:
            record_trade_fill(
                stk_cd=ticker,
                stk_nm=order.stock_name,
                side="sell",
                order_type=getattr(order.order_type, "value", order.order_type),
                price=result.avg_price or order.price or 0,
                quantity=result.requested_quantity,
                executed_quantity=filled_quantity,
                status=(
                    "completed"
                    if filled_quantity >= result.requested_quantity
                    else "partial"
                ),
                order_id=result.order_id,
                session_id=order.session_id,
            )

        position = next(
            (p for p in self._state.positions if p.ticker == ticker), None
        )
        if position is None:
            return
        if filled_quantity >= position.quantity:
            self._remove_position(ticker)
        else:
            position.quantity -= filled_quantity
            position.last_updated = datetime.now()
            # Re-register so the monitor watches the reduced size (keeps stops).
            self.risk_monitor.remove_position(ticker)
            self.risk_monitor.add_position(position)
            self._schedule_persist()
            logger.info(
                f"[Coordinator] Position {ticker} reduced by {filled_quantity}; "
                f"{position.quantity} remaining"
            )

    # -------------------------------------------
    # State Persistence (R5-P1 A4)
    # -------------------------------------------
    #
    # Positions (with stop levels), the trade queue, and the daily trade count
    # lived only in memory, so a restart left the risk monitor watching nothing —
    # stop-losses became a silent no-op. Persist them to SQLite (app_settings
    # blob) and reload on start so defense and queued autonomous trades survive a
    # restart. Stops are the coordinator's own data — the broker does not know
    # them — so the local state IS the source of truth to persist.

    _STATE_KEY = "trading:coordinator_state"

    async def _persist_state(self) -> None:
        """Best-effort persist of restart-critical state. Never raises — a storage
        failure must not break trading."""
        try:
            from services.storage_service import get_storage_service

            blob = json.dumps(
                {
                    "positions": [
                        p.model_dump(mode="json") for p in self._state.positions
                    ],
                    "trade_queue": [
                        t.model_dump(mode="json") for t in self._state.trade_queue
                    ],
                    # P2 SSOT prep (2026-07-14): the watch list lived only in
                    # memory alongside positions/queue, so a restart silently
                    # dropped every watched stock — the funnel's single source
                    # of truth must survive a restart the same way positions
                    # and the trade queue already do.
                    "watch_list": [
                        w.model_dump(mode="json") for w in self._state.watch_list
                    ],
                    "daily_trades_count": self._state.daily_trades_count,
                    "daily_count_date": date.today().isoformat(),
                    "tracked_orders": self.fill_tracker.to_payload(),
                }
            )
            storage = await get_storage_service()
            await storage.set_app_setting(self._STATE_KEY, blob)
        except Exception as e:
            logger.error(f"[Coordinator] Failed to persist state: {e}")

    async def _restore_state(self) -> None:
        """Reload restart-critical state. Positions (with stops) are re-registered
        with the risk monitor so defense resumes; the daily count resets on a new
        calendar day. Best-effort — a corrupt/missing blob starts clean."""
        try:
            from services.storage_service import get_storage_service

            storage = await get_storage_service()
            blob = await storage.get_app_setting(self._STATE_KEY)
            if not blob:
                return
            data = json.loads(blob)

            # Positions + stops → re-register with the risk monitor.
            self._state.positions = [
                ManagedPosition.model_validate(p) for p in data.get("positions", [])
            ]
            for position in self._state.positions:
                self.risk_monitor.add_position(position)

            # Queued trades.
            self._state.trade_queue = [
                QueuedTrade.model_validate(t) for t in data.get("trade_queue", [])
            ]

            # Watch list (P2 SSOT prep) — restored in whatever status it was
            # persisted in (ACTIVE/CONVERTED/REMOVED), so a CONVERTED entry
            # stays CONVERTED across a restart instead of reverting to
            # ACTIVE and becoming re-discussable.
            self._state.watch_list = [
                WatchedStock.model_validate(w) for w in data.get("watch_list", [])
            ]

            # Daily count — reset on a new calendar day.
            if data.get("daily_count_date") == date.today().isoformat():
                self._state.daily_trades_count = int(data.get("daily_trades_count", 0))
            else:
                self._state.daily_trades_count = 0

            # Tracked orders (F3): TRACKING orders resume so the scheduler poll
            # can pick up their post-fill. A TRACKING order whose trade_date
            # has rolled over (restarted on a later day) is expired instead —
            # nothing placed on a prior session can still fill. Log-only, no
            # notification, to avoid a restart notification storm.
            self.fill_tracker = PendingOrderTracker.from_payload(
                data.get("tracked_orders", [])
            )
            stale = self.fill_tracker.expire_stale(today=date.today().strftime("%Y%m%d"))
            if stale:
                logger.info(
                    f"[Coordinator] Expired {len(stale)} stale tracked orders on restore"
                )

            # F3 review M1c: restoring while the KRX session is CLOSED — the
            # post-close ka10076 snapshot is final, so run ONE last poll (a
            # fill that landed while the backend was down still becomes a
            # defended position) and expire whatever remains. Kills overnight
            # 30s polling and next-day tracking against reused ord_nos.
            # Expiry here is log-only (no alerts — restart storm prevention).
            if self.fill_tracker.tracking():
                market_open = self._market_hours.get_market_session(
                    MarketType.KRX
                ).is_open
                if not market_open:
                    await self._poll_tracked_fills()
                    closed_out = self.fill_tracker.expire_stale(today=None)
                    if closed_out:
                        logger.info(
                            f"[Coordinator] Expired {len(closed_out)} tracked "
                            f"orders on restore (market closed)"
                        )

            logger.info(
                f"[Coordinator] Restored {len(self._state.positions)} positions, "
                f"{len(self._state.trade_queue)} queued trades, "
                f"{len(self._state.watch_list)} watched stocks, "
                f"{len(self.fill_tracker.tracking())} tracked orders, "
                f"daily_count={self._state.daily_trades_count}"
            )
        except Exception as e:
            logger.error(f"[Coordinator] Failed to restore state: {e}")

    def _schedule_persist(self) -> None:
        """Fire-and-forget persist from a (possibly sync) mutator. No-op outside a
        session, or without a running loop (a coordinator built in a unit test)."""
        if not self._persistence_active:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._persist_state())

    # -------------------------------------------
    # Account & Price Data
    # -------------------------------------------

    async def _refresh_account_info(self):
        """Refresh account information from Kiwoom."""
        if self._kiwoom:
            try:
                # Fetch balance from Kiwoom
                # AccountBalance is a Pydantic model with:
                # - evlu_amt: 평가금액 (may include cash, so don't use directly)
                # - d2_ord_psbl_amt: D+2 주문가능금액 (available cash)
                # - holdings: list of Holding with individual evlu_amt
                # - total_value: property (evlu_amt + d2_ord_psbl_amt)
                balance = await self._kiwoom.get_account_balance()

                # Calculate stock value from holdings (not evlu_amt which may include cash)
                # See kr_stocks.py line 968-970 for reference
                stock_value = sum(h.evlu_amt for h in balance.holdings)
                available_cash = balance.d2_ord_psbl_amt
                total_equity = available_cash + stock_value

                self._state.account = AccountInfo(
                    total_equity=total_equity,
                    available_cash=available_cash,
                    total_stock_value=stock_value,
                )
                logger.info(f"[Coordinator] Account refreshed: equity={total_equity:,}, cash={available_cash:,}, stocks={stock_value:,}")
            except Exception as e:
                logger.error(f"[Coordinator] Failed to refresh account: {e}")
        else:
            # Simulation mode - use mock data
            self._state.account = AccountInfo(
                total_equity=10_000_000,  # 1000만원
                available_cash=5_000_000,
                total_stock_value=5_000_000,
            )

        # DI2: reprice every open position from the live quote feed.
        # `ManagedPosition.current_price` was only ever set once, at open
        # (avg_price), so `unrealized_pnl = (current_price - avg_price) * qty`
        # was permanently 0 and portfolio_agent's exposure math (which also
        # reads current_price) drifted from the live total_equity refreshed
        # just above. Do this every time account info is refreshed so both
        # stay consistent.
        await self._reprice_positions()

        self._state.last_updated = datetime.now()

    async def _reprice_positions(self) -> None:
        """Update each open position's `current_price` from the live quote feed.

        `_get_current_price` fails safe to 0/None on any broker error (see
        test_current_price_feed.py) — that is a "no fresh quote" signal, not
        a real price. Writing a fabricated 0 into a live position would zero
        out unrealized_pnl and exposure math, which is worse than a stale
        (but real) last-known price, so a falsy result SKIPS that position
        and leaves current_price untouched (T2 stale-price contract).

        Watch-list entries (P2 SSOT prep, 2026-07-14) get the same treatment:
        `WatchedStock.current_price` was only ever set at registration time,
        so the 5-min opportunity check (`ChatCoordinator._detect_opportunity`'s
        target-price proximity test) judged against a price that could be
        hours or days stale. Only ACTIVE entries are repriced — a
        CONVERTED/REMOVED entry's price is historical, not live.
        """
        for position in self._state.positions:
            price = await self._get_current_price(position.ticker)
            if not price:
                continue
            position.current_price = price
            position.last_updated = datetime.now()

        for watched in self._state.watch_list:
            if watched.status != WatchStatus.ACTIVE:
                continue
            price = await self._get_current_price(watched.ticker)
            if not price:
                continue
            watched.current_price = price
            watched.last_checked = datetime.now()

    async def _get_current_price(self, ticker: str) -> float:
        """Get current price for a ticker."""
        if self._kiwoom:
            try:
                # KiwoomClient has no `get_quote` method (that was a
                # never-implemented ghost API — live logs spammed "no
                # attribute 'get_quote'" every RiskMonitor cycle, always
                # returning 0 and silently disabling stop-loss/take-profit
                # checks via the `current_price <= 0` guard). The real quote
                # API is `get_stock_info` (ka10001), same one
                # agents/tools/kr_market_data.py uses.
                info = await self._kiwoom.get_stock_info(ticker)
                return float(info.cur_prc)
            except Exception as e:
                logger.error(f"[Coordinator] Failed to get price for {ticker}: {e}")
                return 0

        # Simulation mode - return mock price
        return 50000  # 5만원

    def _on_price_update(self, ticker: str, price: float) -> None:
        """Price-sink for RiskMonitor's 1s poll (T1, MEDIUM finding A, review
        2026-07-13).

        RiskMonitor already fetches a fresh price for every watched ticker
        once a second, via the very same `_get_current_price` injected above
        as `price_fetcher` — but until this fix that fresh price was written
        only to the monitor's own `WatchConfig.last_price` and discarded, so
        `ManagedPosition.current_price` (and unrealized_pnl/exposure derived
        from it) was only ever refreshed by `_reprice_positions`, itself only
        called from `_refresh_account_info` at trade-decision time. Displayed
        P&L/exposure went stale between decisions even though live price data
        was already flowing. This callback closes that loop at the same 1s
        cadence, independent of trade decisions.

        Same T2 stale-price contract as `_reprice_positions`: a falsy price
        (0/None — `_get_current_price`'s fail-safe signal for "no fresh
        quote") must never overwrite a live position's last-known price.
        """
        if not price:
            return
        position = next(
            (p for p in self._state.positions if p.ticker == ticker), None
        )
        if position is None:
            return
        position.current_price = price
        position.last_updated = datetime.now()

    # -------------------------------------------
    # Alerts & Callbacks
    # -------------------------------------------

    def set_alert_callback(self, callback: Callable[[TradingAlert], Awaitable[None]]):
        """Set callback for alerts."""
        self._alert_callback = callback

    def set_state_callback(self, callback: Callable[[TradingState], Awaitable[None]]):
        """Set callback for state changes."""
        self._state_callback = callback

    async def _on_alert(self, alert: TradingAlert):
        """Handle alert from risk monitor."""
        self._state.pending_alerts.append(alert)

        if self._alert_callback:
            await self._alert_callback(alert)

        await self._notify_state_change()

    async def _notify_state_change(self):
        """Notify state change."""
        if self._state_callback:
            await self._state_callback(self._state)

    # -------------------------------------------
    # Alert Actions
    # -------------------------------------------

    async def handle_alert_action(self, alert_id: str, action: str, data: Optional[dict] = None):
        """
        Handle user action on an alert.

        Args:
            alert_id: Alert ID
            action: Action to take
            data: Optional additional data
        """
        alert = next(
            (a for a in self._state.pending_alerts if a.id == alert_id),
            None
        )

        if not alert:
            logger.warning(f"[Coordinator] Alert {alert_id} not found")
            return

        logger.info(f"[Coordinator] Handling alert action: {alert_id} -> {action}")

        if action == "RESUME":
            await self.resume()

        elif action == "CLOSE_POSITION" and alert.ticker:
            await self._close_position(alert.ticker)

        elif action == "ADJUST_STOP_LOSS" and alert.ticker and data:
            new_sl = data.get("stop_loss")
            if new_sl:
                self.risk_monitor.update_stop_loss(alert.ticker, new_sl)
                # Also update the ManagedPosition so the adjusted stop is what
                # gets persisted — otherwise a restart reverts it to the old
                # value stored on the position (review #4).
                position = next(
                    (p for p in self._state.positions if p.ticker == alert.ticker),
                    None,
                )
                if position is not None:
                    position.stop_loss = new_sl
                    position.last_updated = datetime.now()
                self._schedule_persist()

        elif action == "EXECUTE_STOP_LOSS" and alert.ticker:
            config = self.risk_monitor._watching.get(alert.ticker)
            if config:
                # Update risk agent status - executing stop-loss
                self._update_agent_status(
                    "risk",
                    AgentStatus.WORKING,
                    task=f"Executing stop-loss for {config.stock_name or alert.ticker}",
                    processing_stock=alert.ticker,
                    processing_stock_name=config.stock_name,
                    trade_details={
                        "action": "STOP_LOSS",
                        "quantity": config.quantity,
                        "entry_price": config.entry_price,
                        "stop_loss": config.stop_loss,
                        "current_price": config.last_price,
                    },
                )

                price = config.last_price or config.entry_price
                order = OrderRequest(
                    ticker=alert.ticker,
                    stock_name=config.stock_name,
                    side=OrderSide.SELL,
                    quantity=config.quantity,
                    price=price,
                    reason="User-confirmed stop-loss",
                )
                result = await self._execute_order(order)
                # Track the ACTUAL fill — a rejected/unfilled sell keeps the
                # position under defense instead of orphaning it (review #8).
                self._apply_sell_fill(alert.ticker, result.filled_quantity, order=order, result=result)

        elif action == "EXECUTE_TAKE_PROFIT" and alert.ticker:
            config = self.risk_monitor._watching.get(alert.ticker)
            if config:
                # Update risk agent status - executing take-profit
                self._update_agent_status(
                    "risk",
                    AgentStatus.WORKING,
                    task=f"Executing take-profit for {config.stock_name or alert.ticker}",
                    processing_stock=alert.ticker,
                    processing_stock_name=config.stock_name,
                    trade_details={
                        "action": "TAKE_PROFIT",
                        "quantity": config.quantity,
                        "entry_price": config.entry_price,
                        "take_profit": config.take_profit,
                        "current_price": config.last_price,
                    },
                )

                price = config.last_price or config.take_profit
                order = OrderRequest(
                    ticker=alert.ticker,
                    stock_name=config.stock_name,
                    side=OrderSide.SELL,
                    quantity=config.quantity,
                    price=price,
                    reason="User-confirmed take-profit",
                )
                result = await self._execute_order(order)
                self._apply_sell_fill(alert.ticker, result.filled_quantity, order=order, result=result)

        elif action == "HOLD":
            # Do nothing, just acknowledge
            pass

        # Mark alert as resolved
        self.risk_monitor.resolve_alert(alert_id)
        self._state.pending_alerts = [a for a in self._state.pending_alerts if a.id != alert_id]

        await self._notify_state_change()

    async def _close_position(self, ticker: str) -> Optional[OrderResult]:
        """Close a position at market price.

        Returns the OrderResult of the placed SELL (or None if there was no
        position to close) — P1 (2026-07-15) added this return value so
        `_reduce_position` can delegate here when its own oversell clamp
        collapses a partial request into a full close, and still learn the
        ACTUAL filled quantity. Existing callers that ignore the return value
        (`handle_alert_action`'s CLOSE_POSITION, PositionManager's
        `_execute_close_position`) are unaffected.
        """
        position = next(
            (p for p in self._state.positions if p.ticker == ticker),
            None
        )

        if not position:
            logger.warning(f"[Coordinator] Position {ticker} not found")
            return None

        order = OrderRequest(
            ticker=ticker,
            stock_name=position.stock_name,
            side=OrderSide.SELL,
            quantity=position.quantity,
            price=position.current_price,
            reason="User-initiated close",
        )

        result = await self._execute_order(order)
        # Only drop/reduce tracking by the ACTUAL fill — a rejected or unfilled
        # sell must keep the position under defense (A3).
        self._apply_sell_fill(ticker, result.filled_quantity, order=order, result=result)
        return result

    async def _reduce_position(self, ticker: str, quantity: int) -> Optional[OrderResult]:
        """Place a SELL order for a SPECIFIC quantity — a partial reduce, not
        a full close (P1, 2026-07-15,
        docs/superpowers/plans/2026-07-15-position-mgmt-execution.md).

        `PositionManager._execute_reduce_position` is the (only) autonomous
        caller today: it already passes the request through
        `check_autonomy(SELL)` before reaching here, mirroring the existing
        full-close pattern (`PositionManager._execute_close_position` gates,
        then calls `_close_position`).

        Oversell-proof against THIS coordinator's OWN tracked quantity. The
        caller may be working off a separate ledger (PositionManager's
        `MonitoredPosition`, distinct from this coordinator's
        `ManagedPosition`) that can diverge from this one, so the clamp is
        re-applied here rather than trusted from the caller: `sell_qty =
        min(quantity, position.quantity)`. If that clamp collapses the
        request into a full close (requested >= held), delegates to the
        existing `_close_position` instead of duplicating its
        position-removal/risk-monitor-stop cleanup.

        Returns the OrderResult of whichever order was actually placed (the
        partial sell, or the delegated full close) so the caller can react to
        the ACTUAL filled quantity — never the requested one — the same
        choke-point discipline `_apply_sell_fill` already applies to every
        other SELL path.
        """
        position = next(
            (p for p in self._state.positions if p.ticker == ticker), None
        )
        if not position:
            logger.warning(f"[Coordinator] Position {ticker} not found for reduce")
            return None

        sell_qty = min(quantity, position.quantity)
        if sell_qty <= 0:
            logger.warning(
                f"[Coordinator] Reduce for {ticker} requested non-positive "
                f"sell quantity ({quantity} vs held {position.quantity})"
            )
            return None

        if sell_qty >= position.quantity:
            # Clamp collapses this into a full close — delegate rather than
            # duplicate _close_position's removal/stop-cleanup logic.
            return await self._close_position(ticker)

        order = OrderRequest(
            ticker=ticker,
            stock_name=position.stock_name,
            side=OrderSide.SELL,
            quantity=sell_qty,
            price=position.current_price,
            reason="Autonomous partial reduce",
        )

        result = await self._execute_order(order)
        # Reconcile by the ACTUAL fill, not the requested quantity — same
        # choke point every other SELL path uses (full → remove, partial →
        # decrement, none → retain).
        self._apply_sell_fill(ticker, result.filled_quantity, order=order, result=result)
        return result

    # -------------------------------------------
    # State Access
    # -------------------------------------------

    @property
    def state(self) -> TradingState:
        """Get current trading state."""
        return self._state

    @property
    def is_active(self) -> bool:
        """Check if trading is active."""
        return self._state.mode == TradingMode.ACTIVE

    def get_portfolio_summary(self) -> dict:
        """Get portfolio summary."""
        return self.portfolio_agent.get_portfolio_summary(self._state)

    def get_pending_alerts(self) -> List[TradingAlert]:
        """Get pending alerts."""
        return self.risk_monitor.get_pending_alerts()

    # -------------------------------------------
    # Agent Status Management
    # -------------------------------------------

    def _update_agent_status(
        self,
        agent: str,
        status: AgentStatus,
        task: Optional[str] = None,
        action: Optional[str] = None,
        error: Optional[str] = None,
        # 세부 정보 (Sub Agent Status 개선)
        processing_stock: Optional[str] = None,
        processing_stock_name: Optional[str] = None,
        trade_details: Optional[dict] = None,
        analysis_summary: Optional[dict] = None,
        last_result: Optional[dict] = None,
    ):
        """Update status of a specific agent with detailed information."""
        if agent in self._state.agent_states:
            agent_state = self._state.agent_states[agent]
            agent_state.status = status
            agent_state.current_task = task
            if action:
                agent_state.last_action = action
                agent_state.last_action_time = datetime.now()
            if error:
                agent_state.error_message = error
            else:
                agent_state.error_message = None

            # 세부 정보 업데이트
            if processing_stock is not None:
                agent_state.processing_stock = processing_stock
            if processing_stock_name is not None:
                agent_state.processing_stock_name = processing_stock_name
            if trade_details is not None:
                agent_state.trade_details = trade_details
            if analysis_summary is not None:
                agent_state.analysis_summary = analysis_summary
            if last_result is not None:
                agent_state.last_result = last_result

    def _complete_agent_task(self, agent: str, success: bool = True):
        """Mark agent task as completed."""
        if agent in self._state.agent_states:
            agent_state = self._state.agent_states[agent]
            agent_state.status = AgentStatus.IDLE
            agent_state.current_task = None
            if success:
                agent_state.tasks_completed += 1
            else:
                agent_state.tasks_failed += 1

    def get_agent_states(self) -> dict:
        """Get all agent states as dict."""
        return {
            name: state.model_dump()
            for name, state in self._state.agent_states.items()
        }

    # -------------------------------------------
    # Trade Queue Management
    # -------------------------------------------

    def add_to_queue(
        self,
        session_id: str,
        ticker: str,
        stock_name: Optional[str],
        action: str,
        entry_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        risk_score: int,
        reason: str,
        autonomous: bool = False,
        quantity: Optional[int] = None,
    ) -> QueuedTrade:
        """Add a trade to the queue for later execution.

        quantity carries the size decided at queueing time. It MUST be preserved
        for autonomous trades: the execution-time re-gate's notional cap denies
        a BUY/ADD of unknown size (fail-closed), so dropping it would cancel
        every queued autonomous buy — audit finding A5 (2026-07-12).
        """
        queued_trade = QueuedTrade(
            session_id=session_id,
            ticker=ticker,
            stock_name=stock_name,
            action=action,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_score=risk_score,
            reason=reason,
            autonomous=autonomous,
        )

        self._state.trade_queue.append(queued_trade)

        self._log_activity(
            ActivityType.TRADE_QUEUED,
            f"Trade queued: {action} {stock_name or ticker} (reason: {reason})",
            agent="system",
            ticker=ticker,
            details={
                "queue_id": queued_trade.id,
                "action": action,
                "entry_price": entry_price,
                "reason": reason,
            },
        )

        logger.info(f"[Coordinator] Trade queued: {queued_trade.id}")
        self._schedule_persist()
        return queued_trade

    def get_trade_queue(self, include_all: bool = False) -> List[QueuedTrade]:
        """
        Get trades in queue.

        Args:
            include_all: If True, return all trades including FAILED/COMPLETED.
                        If False, return only PENDING and PROCESSING trades.
        """
        if include_all:
            return list(self._state.trade_queue)

        # Default: return active trades (PENDING or PROCESSING)
        return [
            t for t in self._state.trade_queue
            if t.status in (QueueStatus.PENDING, QueueStatus.PROCESSING)
        ]

    def dismiss_trade(self, queue_id: str) -> bool:
        """
        Dismiss a completed/failed/cancelled trade from the queue.

        Only removes trades that are not PENDING or PROCESSING.
        """
        for i, trade in enumerate(self._state.trade_queue):
            if trade.id == queue_id:
                if trade.status in (QueueStatus.PENDING, QueueStatus.PROCESSING):
                    logger.warning(
                        f"[Coordinator] Cannot dismiss active trade: {queue_id} (status={trade.status})"
                    )
                    return False

                self._state.trade_queue.pop(i)
                logger.info(f"[Coordinator] Trade dismissed from queue: {queue_id}")
                self._schedule_persist()
                return True
        return False

    def cancel_queued_trade(self, queue_id: str) -> bool:
        """Cancel a queued trade."""
        for trade in self._state.trade_queue:
            if trade.id == queue_id and trade.status == QueueStatus.PENDING:
                trade.status = QueueStatus.CANCELLED

                self._log_activity(
                    ActivityType.TRADE_DEQUEUED,
                    f"Queued trade cancelled: {trade.ticker}",
                    agent="system",
                    ticker=trade.ticker,
                    details={"queue_id": queue_id},
                )

                logger.info(f"[Coordinator] Queued trade cancelled: {queue_id}")
                self._schedule_persist()
                return True
        return False

    async def process_trade_queue(self):
        """Process pending trades in queue (call when market opens).

        Re-entrancy-guarded: a second concurrent call returns immediately so a
        trade already being processed is not executed twice.
        """
        if self._processing_queue:
            logger.info("[Coordinator] process_trade_queue already running — skipping")
            return
        self._processing_queue = True
        try:
            await self._process_trade_queue_inner()
        finally:
            self._processing_queue = False

    async def _process_trade_queue_inner(self):
        pending_trades = self.get_trade_queue()
        if not pending_trades:
            return

        logger.info(f"[Coordinator] Processing {len(pending_trades)} queued trades")

        self._update_agent_status("order", AgentStatus.WORKING, f"Processing {len(pending_trades)} queued trades")

        for trade in pending_trades:
            try:
                trade.status = QueueStatus.PROCESSING

                self._log_activity(
                    ActivityType.TRADE_DEQUEUED,
                    f"Processing queued trade: {trade.action} {trade.ticker}",
                    agent="order",
                    ticker=trade.ticker,
                    details={"queue_id": trade.id},
                )

                # R3: autonomy-originated trades must pass the gate AGAIN at
                # execution time — the verdict from queueing time is stale
                # (mode may have been flipped to HITL, a limit may have tripped).
                if trade.autonomous:
                    from services.autonomy import check_autonomy

                    gate = await check_autonomy(
                        "kiwoom",
                        action=trade.action,
                        quantity=trade.quantity,
                        entry_price=trade.entry_price,
                    )
                    if not gate.allowed:
                        trade.status = QueueStatus.CANCELLED
                        self._log_activity(
                            ActivityType.TRADE_DEQUEUED,
                            f"Queued autonomous trade cancelled by gate: {trade.action} "
                            f"{trade.ticker} ({gate.check}: {gate.reason})",
                            agent="order",
                            ticker=trade.ticker,
                            details={"queue_id": trade.id, "gate_check": gate.check},
                        )
                        continue

                # Execute the trade
                allocation = await self.on_trade_approved(
                    session_id=trade.session_id,
                    ticker=trade.ticker,
                    stock_name=trade.stock_name,
                    action=trade.action,
                    entry_price=trade.entry_price,
                    stop_loss=trade.stop_loss,
                    take_profit=trade.take_profit,
                    risk_score=trade.risk_score,
                    quantity_override=trade.quantity,
                    autonomous=trade.autonomous,
                    queue_id=trade.id,
                )

                trade.allocation = allocation
                trade.executed_at = datetime.now()

                if allocation.quantity > 0:
                    trade.status = QueueStatus.COMPLETED
                else:
                    trade.status = QueueStatus.FAILED
                    trade.error_message = allocation.rationale

            except Exception as e:
                logger.error(f"[Coordinator] Failed to process queued trade {trade.id}: {e}")
                trade.status = QueueStatus.FAILED
                trade.error_message = str(e)

        self._complete_agent_task("order", True)
        if self._persistence_active:
            await self._persist_state()
        await self._notify_state_change()

    async def _check_queue_on_market_open(self) -> None:
        """One scheduler tick: process the queue on a KRX closed→open transition,
        and expire tracked orders on the inverse open→closed transition (F3).

        start() already drains the queue if the market is open at start time; this
        covers the case where the system is started (or a trade is queued) while
        the market is closed and the market opens later. Only the EDGE triggers —
        an already-open market is not re-processed every tick. The execution-time
        re-gate (R5-P0) re-checks autonomy safety when each queued trade runs.

        The open→closed edge is the local signal for "nothing placed today can
        fill any further" — KRX limit orders are day-valid and there is no
        broker push telling us the session ended, so every still-TRACKING order
        is expired and notified once, on the edge only (mirrors the open-edge
        guard so a closed market doesn't re-notify every tick).
        """
        is_open = self._market_hours.get_market_session(MarketType.KRX).is_open
        if is_open and not self._market_was_open and self.get_trade_queue():
            logger.info("[Coordinator] Market opened — processing queued trades")
            await self.process_trade_queue()
        elif not is_open and self._market_was_open:
            # F3 review HIGH: poll BEFORE expiring — the post-close ka10076
            # snapshot is final and includes closing-auction fills; expiring
            # first would drop a fill that landed on this very edge.
            await self._poll_tracked_fills()
            await self._expire_tracked_orders_on_market_close()
        self._market_was_open = is_open

    async def _expire_tracked_orders_on_market_close(self) -> None:
        """F3: expire every still-TRACKING order on the open→closed edge and
        notify once per order via the coordinator's normal alert path."""
        expired = self.fill_tracker.expire_stale(today=None)
        if not expired:
            return

        logger.info(f"[Coordinator] Market closed — expired {len(expired)} tracked orders")
        self._log_activity(
            ActivityType.MARKET_CLOSED,
            f"장 마감 — 미체결 추적 주문 {len(expired)}건 만료 처리",
            agent="system",
        )
        for order in expired:
            remaining = order.total_quantity - order.filled_quantity
            await self._on_alert(
                TradingAlert(
                    id=str(uuid.uuid4())[:8],
                    alert_type=AlertType.ORDER_FAILED,
                    ticker=order.ticker,
                    title="미체결 주문 만료",
                    message=(
                        f"{order.stock_name or order.ticker} 잔량 {remaining}주 — "
                        f"장 마감으로 추적 종료 (ord_no={order.ord_no})"
                    ),
                    data={"ord_no": order.ord_no, "remaining": remaining},
                )
            )
        self._schedule_persist()

    async def _poll_tracked_fills(self) -> None:
        """One scheduler tick: reconcile TRACKING orders against ka10076 fills.

        Skips the broker call entirely when nothing is TRACKING (flow-control —
        this runs every 30s alongside the queue-open check). ka10076 returns a
        cumulative daily snapshot per order, so `apply_fills` diffs it against
        each order's own accumulated fill and returns only the NEW portion —
        re-polling an unchanged snapshot is a no-op (idempotent). A query
        failure is logged and left for the next tick; tracked state does not
        change on failure.
        """
        if not self.fill_tracker.tracking():
            return
        if self._kiwoom is None:
            return

        try:
            fills = await self._kiwoom.get_filled_orders(use_cache=False)
        except Exception as e:
            logger.error(f"[Coordinator] Fill tracker poll failed: {e}")
            return

        deltas = self.fill_tracker.apply_fills(fills)
        if not deltas:
            return

        for delta in deltas:
            order = delta.order

            # P1-1: record this post-fill discovery for /trades. `quantity`
            # is the tracked order's full requested size; `executed_quantity`
            # is just the NEW portion this poll tick uncovered (delta), since
            # a single order can surface several of these rows across ticks.
            if self._persistence_active:
                order_status = getattr(order.status, "value", order.status)
                record_trade_fill(
                    stk_cd=order.ticker,
                    stk_nm=order.stock_name or order.ticker,
                    side=order.side,
                    order_type="limit",
                    price=delta.avg_fill_price,
                    quantity=order.total_quantity,
                    executed_quantity=delta.new_fill_qty,
                    status="completed" if order_status == "filled" else "partial",
                    order_id=order.ord_no,
                    session_id=order.source_session_id,
                )

            await register_fill_as_position(
                self,
                ticker=order.ticker,
                stock_name=order.stock_name or order.ticker,
                quantity=delta.new_fill_qty,
                avg_price=delta.avg_fill_price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                session_id=order.source_session_id,
                source="fill_tracker",
                # Match the placement-fill path's position semantics
                # (stop_loss_mode from risk params, risk from the proposal).
                stop_loss_mode=self.risk_params.stop_loss_mode,
                risk_score=order.risk_score,
            )

            self._log_activity(
                ActivityType.POSITION_OPENED,
                f"사후 체결: {order.stock_name or order.ticker} {delta.new_fill_qty}주 "
                f"@ ₩{delta.avg_fill_price:,.0f}",
                agent="order",
                ticker=order.ticker,
                details={
                    "ord_no": order.ord_no,
                    "new_fill_qty": delta.new_fill_qty,
                    "avg_fill_price": delta.avg_fill_price,
                    "stop_loss": order.stop_loss,
                },
            )

            stop_note = (
                f" — 손절 ₩{order.stop_loss:,.0f} 감시 시작" if order.stop_loss else ""
            )
            await self._on_alert(
                TradingAlert(
                    id=str(uuid.uuid4())[:8],
                    alert_type=AlertType.ORDER_FILLED,
                    ticker=order.ticker,
                    title="사후 체결 감지",
                    message=(
                        f"{order.stock_name or order.ticker} {delta.new_fill_qty}주 "
                        f"@ ₩{delta.avg_fill_price:,.0f} 체결 확인{stop_note}"
                    ),
                    data={
                        "ord_no": order.ord_no,
                        "new_fill_qty": delta.new_fill_qty,
                        "avg_fill_price": delta.avg_fill_price,
                    },
                )
            )

            # Post-fill queue annotation: the queue item that originated this
            # order (if any) gets a note appended — its status vocabulary is
            # unchanged (design spec §4.1/§7).
            if order.source_queue_id:
                queued = next(
                    (
                        t
                        for t in self._state.trade_queue
                        if t.id == order.source_queue_id
                    ),
                    None,
                )
                if queued is not None:
                    queued.reason = (
                        f"{queued.reason} | 사후체결 {delta.new_fill_qty}주 "
                        f"@{delta.avg_fill_price:,.0f}"
                    )

        self._schedule_persist()

    async def _queue_scheduler_loop(self) -> None:
        """Periodically check for the market-open transition until stopped."""
        try:
            while True:
                await asyncio.sleep(self._queue_scheduler_interval)
                try:
                    await self._check_queue_on_market_open()
                    await self._poll_tracked_fills()
                    self._reconcile_tick_count += 1
                    if self._reconcile_tick_count % 2 == 0:
                        await reconcile(self)
                except Exception as e:
                    logger.error(f"[Coordinator] Queue scheduler error: {e}")
        except asyncio.CancelledError:
            pass

    # -------------------------------------------
    # Watch List Management
    # -------------------------------------------

    def add_to_watch_list(
        self,
        session_id: str,
        ticker: str,
        stock_name: Optional[str],
        signal: str,
        confidence: float,
        current_price: float,
        target_entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        analysis_summary: str = "",
        key_factors: Optional[List[str]] = None,
        risk_score: int = 5,
    ) -> WatchedStock:
        """
        Add a stock to the watch list for monitoring.

        Args:
            session_id: Analysis session ID
            ticker: Stock ticker
            stock_name: Stock name
            signal: Analysis signal (e.g., "hold", "sell")
            confidence: Analysis confidence (0-1)
            current_price: Current stock price
            target_entry_price: Suggested entry price for buying
            stop_loss: Suggested stop-loss price
            take_profit: Suggested take-profit price
            analysis_summary: Brief summary of analysis
            key_factors: Key factors from analysis
            risk_score: Risk score (1-10)

        Returns:
            WatchedStock object
        """
        # Check if already in watch list
        existing = next(
            (w for w in self._state.watch_list
             if w.ticker == ticker and w.status == WatchStatus.ACTIVE),
            None
        )

        if existing:
            # Update existing entry
            existing.signal = signal
            existing.confidence = confidence
            existing.current_price = current_price
            existing.target_entry_price = target_entry_price
            existing.stop_loss = stop_loss
            existing.take_profit = take_profit
            existing.analysis_summary = analysis_summary
            existing.key_factors = key_factors or []
            existing.risk_score = risk_score
            existing.last_checked = datetime.now()

            logger.info(f"[Coordinator] Watch list updated: {ticker}")
            self._schedule_persist()
            return existing

        # Create new watch list entry
        watched = WatchedStock(
            session_id=session_id,
            ticker=ticker,
            stock_name=stock_name,
            signal=signal,
            confidence=confidence,
            current_price=current_price,
            target_entry_price=target_entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            analysis_summary=analysis_summary,
            key_factors=key_factors or [],
            risk_score=risk_score,
        )

        self._state.watch_list.append(watched)

        self._log_activity(
            ActivityType.WATCH_ADDED,
            f"Added to watch list: {stock_name or ticker} (signal: {signal}, confidence: {confidence:.0%})",
            agent="system",
            ticker=ticker,
            details={
                "watch_id": watched.id,
                "signal": signal,
                "confidence": confidence,
                "current_price": current_price,
                "analysis_summary": analysis_summary[:100] if analysis_summary else "",
            },
        )

        logger.info(f"[Coordinator] Added to watch list: {watched.id}")
        self._schedule_persist()
        return watched

    def get_watch_list(self) -> List[WatchedStock]:
        """Get all active items in watch list."""
        return [w for w in self._state.watch_list if w.status == WatchStatus.ACTIVE]

    def remove_from_watch_list(self, watch_id: str) -> bool:
        """Remove an item from watch list."""
        for watched in self._state.watch_list:
            if watched.id == watch_id and watched.status == WatchStatus.ACTIVE:
                watched.status = WatchStatus.REMOVED

                self._log_activity(
                    ActivityType.WATCH_REMOVED,
                    f"Removed from watch list: {watched.ticker}",
                    agent="system",
                    ticker=watched.ticker,
                    details={"watch_id": watch_id},
                )

                logger.info(f"[Coordinator] Removed from watch list: {watch_id}")
                self._schedule_persist()
                return True
        return False

    def convert_watch_to_queue(
        self,
        watch_id: str,
        action: str = "BUY",
        reason: str = "User converted from watch list",
    ) -> Optional[QueuedTrade]:
        """
        Convert a watched stock to the trade queue for execution.

        Args:
            watch_id: Watch list item ID
            action: Trade action (BUY or SELL)
            reason: Reason for conversion

        Returns:
            QueuedTrade if successful, None otherwise
        """
        watched = next(
            (w for w in self._state.watch_list
             if w.id == watch_id and w.status == WatchStatus.ACTIVE),
            None
        )

        if not watched:
            return None

        # Add to trade queue
        queued_trade = self.add_to_queue(
            session_id=watched.session_id,
            ticker=watched.ticker,
            stock_name=watched.stock_name,
            action=action,
            entry_price=watched.target_entry_price or watched.current_price,
            stop_loss=watched.stop_loss,
            take_profit=watched.take_profit,
            risk_score=watched.risk_score,
            reason=reason,
        )

        # Update watch status
        watched.status = WatchStatus.CONVERTED
        watched.triggered_at = datetime.now()

        self._log_activity(
            ActivityType.WATCH_CONVERTED,
            f"Watch list converted to trade: {watched.ticker} -> {action}",
            agent="system",
            ticker=watched.ticker,
            details={
                "watch_id": watch_id,
                "queue_id": queued_trade.id,
                "action": action,
            },
        )

        logger.info(f"[Coordinator] Watch list converted: {watch_id} -> {queued_trade.id}")
        return queued_trade

    def get_watched_stock(self, ticker: str) -> Optional[WatchedStock]:
        """Get a watched stock by ticker if it's active."""
        return next(
            (w for w in self._state.watch_list
             if w.ticker == ticker and w.status == WatchStatus.ACTIVE),
            None
        )

    def mark_watch_converted(self, ticker: str) -> bool:
        """Mark the active watch-list entry for `ticker` as CONVERTED.

        Used by the autonomous agent-chat path (`ChatCoordinator._execute_trade`)
        WITHOUT going through `convert_watch_to_queue` — that path calls
        `on_trade_approved` directly, so without this call the watch entry
        stayed ACTIVE forever. The 5-min watch-list check
        (`ChatCoordinator._check_watch_list`) could then re-detect the same
        "opportunity" and start a duplicate discussion/execution on the same
        ticker (P2 funnel-consolidation audit finding, 2026-07-14).

        Callers MUST gate this on `on_trade_approved`'s actual outcome, not
        merely on having attempted a decision: `on_trade_approved` has non-
        exception outcomes where no trade actually results (daily trade
        limit reached, portfolio sizing to <=0 shares, or an order placed
        but the broker filled 0 shares) — call this only when a trade
        genuinely executed or was queued (a real position/queue entry
        resulted), otherwise the watch entry must stay ACTIVE so the
        opportunity can be re-evaluated later (T2 review gap, 2026-07-14;
        see `services.agent_chat.coordinator._trade_actually_resulted`).

        Returns False (no-op) when there is no active watch entry for the
        ticker — a decision can legitimately originate outside the watch list.
        """
        watched = self.get_watched_stock(ticker)
        if watched is None:
            return False

        watched.status = WatchStatus.CONVERTED
        watched.triggered_at = datetime.now()

        self._log_activity(
            ActivityType.WATCH_CONVERTED,
            f"Watch list auto-converted by autonomous execution: {watched.ticker}",
            agent="system",
            ticker=ticker,
            details={"watch_id": watched.id},
        )

        logger.info(f"[Coordinator] Watch list auto-converted: {watched.id}")
        self._schedule_persist()
        return True

    # -------------------------------------------
    # Strategy Management
    # -------------------------------------------

    def get_strategy(self) -> Optional[TradingStrategy]:
        """Get the current trading strategy."""
        return self._strategy

    def set_strategy(self, strategy: Optional[TradingStrategy]):
        """
        Set the trading strategy.

        Args:
            strategy: TradingStrategy to apply, or None to clear
        """
        self._strategy = strategy

        if strategy:
            # Create strategy engine with LLM provider (if available)
            self._strategy_engine = StrategyEngine(strategy, llm_provider=None)

            self._log_activity(
                ActivityType.STRATEGY_CHANGED,
                f"Strategy set: {strategy.name} ({strategy.risk_tolerance.value})",
                agent="system",
                details={
                    "strategy_name": strategy.name,
                    "preset": strategy.preset.value,
                    "risk_tolerance": strategy.risk_tolerance.value,
                    "trading_style": strategy.trading_style.value,
                },
            )

            logger.info(f"[Coordinator] Strategy set: {strategy.name}")
        else:
            self._strategy_engine = None

            self._log_activity(
                ActivityType.STRATEGY_CHANGED,
                "Strategy cleared",
                agent="system",
            )

            logger.info("[Coordinator] Strategy cleared")

    def get_strategy_engine(self) -> Optional[StrategyEngine]:
        """Get the strategy engine instance."""
        return self._strategy_engine

    async def evaluate_with_strategy(
        self,
        ticker: str,
        stock_name: str,
        analysis_results: dict,
        current_price: float,
    ) -> dict:
        """
        Evaluate a trade using the current strategy.

        Args:
            ticker: Stock ticker
            stock_name: Stock name
            analysis_results: Analysis results from agents
            current_price: Current stock price

        Returns:
            Entry decision dict with action, confidence, etc.
        """
        if not self._strategy_engine:
            return {
                "action": "SKIP",
                "confidence": 0,
                "rationale": "No strategy configured",
            }

        # Prepare account info
        account_info = {
            "total_equity": self._state.account.total_equity,
            "available_cash": self._state.account.available_cash,
            "total_stock_value": self._state.account.total_stock_value,
            "positions": [p.model_dump() for p in self._state.positions],
        }

        # Update strategy agent status - working
        self._update_agent_status(
            "strategy",
            AgentStatus.WORKING,
            task=f"Evaluating entry for {stock_name or ticker}",
            processing_stock=ticker,
            processing_stock_name=stock_name,
            analysis_summary={
                "technical": analysis_results.get("technical", {}).get("signal", "N/A"),
                "fundamental": analysis_results.get("fundamental", {}).get("signal", "N/A"),
                "sentiment": analysis_results.get("sentiment", {}).get("signal", "N/A"),
                "risk": analysis_results.get("risk", {}).get("level", "N/A"),
            } if analysis_results else None,
        )

        try:
            decision = await self._strategy_engine.evaluate_entry(
                ticker=ticker,
                stock_name=stock_name,
                analysis_results=analysis_results,
                current_price=current_price,
                account_info=account_info,
            )

            self._log_activity(
                ActivityType.STRATEGY_EVALUATED,
                f"Strategy evaluation: {decision.action} (confidence: {decision.confidence}%)",
                agent="strategy",
                ticker=ticker,
                details={
                    "action": decision.action,
                    "confidence": decision.confidence,
                    "rationale": decision.rationale,
                    "key_factors": decision.key_factors,
                },
            )

            # Update strategy agent status - completed
            self._update_agent_status(
                "strategy",
                AgentStatus.IDLE,
                action=f"Decided: {decision.action} ({decision.confidence}%)",
                processing_stock=ticker,
                processing_stock_name=stock_name,
                trade_details={
                    "action": decision.action,
                    "confidence": decision.confidence,
                    "entry_price": decision.entry_price,
                    "stop_loss": decision.stop_loss,
                    "take_profit": decision.take_profit,
                },
                last_result={
                    "success": True,
                    "message": decision.rationale,
                },
            )
            self._complete_agent_task("strategy", success=True)

            return decision.model_dump()

        except Exception as e:
            logger.error(f"[Coordinator] Strategy evaluation failed: {e}")
            # Update strategy agent status - error
            self._update_agent_status(
                "strategy",
                AgentStatus.ERROR,
                error=str(e),
                processing_stock=ticker,
                processing_stock_name=stock_name,
                last_result={
                    "success": False,
                    "message": f"Strategy evaluation error: {e}",
                },
            )
            self._complete_agent_task("strategy", success=False)
            return {
                "action": "SKIP",
                "confidence": 0,
                "rationale": f"Strategy evaluation error: {e}",
            }
