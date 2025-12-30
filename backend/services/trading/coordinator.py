"""
Execution Coordinator

Orchestrates the trading workflow:
Analysis → Approval → Portfolio → Order → Monitor
"""

import asyncio
import logging
from datetime import datetime
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

logger = logging.getLogger(__name__)


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

    async def stop(self):
        """Stop the auto-trading system."""
        logger.info("[Coordinator] Stopping auto-trading system")

        await self.risk_monitor.stop()
        self._state.mode = TradingMode.STOPPED

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
    ) -> AllocationPlan:
        """
        Handle an approved trade from the analysis system.

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
            )

            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.BUY if action == "BUY" else OrderSide.SELL,
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
                side=OrderSide.BUY if action == "BUY" else OrderSide.SELL,
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=rationale,
            )

        # Refresh account info
        await self._refresh_account_info()

        # Calculate allocation
        side = OrderSide.BUY if action == "BUY" else OrderSide.SELL
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
        else:
            self._log_activity(
                ActivityType.ORDER_FAILED,
                f"Order failed: {result.error or 'Unknown error'}",
                agent="order",
                ticker=ticker,
            )

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

        await self._notify_state_change()

        return result

    async def _execute_order_from_monitor(self, order: OrderRequest):
        """Execute order from risk monitor (stop-loss/take-profit)."""
        result = await self._execute_order(order)

        if result.filled_quantity > 0:
            # Remove position
            self._remove_position(order.ticker)

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
        else:
            self._state.positions.append(position)

        # Add to risk monitor
        self.risk_monitor.add_position(position)

        logger.info(f"[Coordinator] Position added/updated: {position.ticker}")

    def _remove_position(self, ticker: str):
        """Remove a position from tracking."""
        self._state.positions = [
            p for p in self._state.positions if p.ticker != ticker
        ]
        self.risk_monitor.remove_position(ticker)

        logger.info(f"[Coordinator] Position removed: {ticker}")

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

        self._state.last_updated = datetime.now()

    async def _get_current_price(self, ticker: str) -> float:
        """Get current price for a ticker."""
        if self._kiwoom:
            try:
                quote = await self._kiwoom.get_quote(ticker)
                return quote.get("current_price", 0)
            except Exception as e:
                logger.error(f"[Coordinator] Failed to get price for {ticker}: {e}")
                return 0

        # Simulation mode - return mock price
        return 50000  # 5만원

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

        elif action == "EXECUTE_STOP_LOSS" and alert.ticker:
            config = self.risk_monitor._watching.get(alert.ticker)
            if config:
                price = config.last_price or config.entry_price
                order = OrderRequest(
                    ticker=alert.ticker,
                    stock_name=config.stock_name,
                    side=OrderSide.SELL,
                    quantity=config.quantity,
                    price=price,
                    reason="User-confirmed stop-loss",
                )
                await self._execute_order(order)
                self._remove_position(alert.ticker)

        elif action == "EXECUTE_TAKE_PROFIT" and alert.ticker:
            config = self.risk_monitor._watching.get(alert.ticker)
            if config:
                price = config.last_price or config.take_profit
                order = OrderRequest(
                    ticker=alert.ticker,
                    stock_name=config.stock_name,
                    side=OrderSide.SELL,
                    quantity=config.quantity,
                    price=price,
                    reason="User-confirmed take-profit",
                )
                await self._execute_order(order)
                self._remove_position(alert.ticker)

        elif action == "HOLD":
            # Do nothing, just acknowledge
            pass

        # Mark alert as resolved
        self.risk_monitor.resolve_alert(alert_id)
        self._state.pending_alerts = [a for a in self._state.pending_alerts if a.id != alert_id]

        await self._notify_state_change()

    async def _close_position(self, ticker: str):
        """Close a position at market price."""
        position = next(
            (p for p in self._state.positions if p.ticker == ticker),
            None
        )

        if not position:
            logger.warning(f"[Coordinator] Position {ticker} not found")
            return

        order = OrderRequest(
            ticker=ticker,
            stock_name=position.stock_name,
            side=OrderSide.SELL,
            quantity=position.quantity,
            price=position.current_price,
            reason="User-initiated close",
        )

        await self._execute_order(order)
        self._remove_position(ticker)

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
    ):
        """Update status of a specific agent."""
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
    ) -> QueuedTrade:
        """Add a trade to the queue for later execution."""
        queued_trade = QueuedTrade(
            session_id=session_id,
            ticker=ticker,
            stock_name=stock_name,
            action=action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_score=risk_score,
            reason=reason,
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
        return queued_trade

    def get_trade_queue(self) -> List[QueuedTrade]:
        """Get all pending trades in queue."""
        return [t for t in self._state.trade_queue if t.status == QueueStatus.PENDING]

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
                return True
        return False

    async def process_trade_queue(self):
        """Process pending trades in queue (call when market opens)."""
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
        await self._notify_state_change()

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

            return decision.model_dump()

        except Exception as e:
            logger.error(f"[Coordinator] Strategy evaluation failed: {e}")
            return {
                "action": "SKIP",
                "confidence": 0,
                "rationale": f"Strategy evaluation error: {e}",
            }
