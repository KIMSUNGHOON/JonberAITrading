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
)
from .portfolio_agent import PortfolioAgent
from .order_agent import OrderAgent, KiwoomRateLimiter
from .risk_monitor import RiskMonitor

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

        # Callbacks
        self._alert_callback: Optional[Callable[[TradingAlert], Awaitable[None]]] = None
        self._state_callback: Optional[Callable[[TradingState], Awaitable[None]]] = None

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

        await self._notify_state_change()

    async def stop(self):
        """Stop the auto-trading system."""
        logger.info("[Coordinator] Stopping auto-trading system")

        await self.risk_monitor.stop()
        self._state.mode = TradingMode.STOPPED

        await self._notify_state_change()

    async def pause(self, reason: str = "Manual pause"):
        """Pause auto-trading."""
        await self.risk_monitor.pause(reason)
        self._state.mode = TradingMode.PAUSED
        await self._notify_state_change()

    async def resume(self):
        """Resume auto-trading."""
        await self.risk_monitor.resume()
        self._state.mode = TradingMode.ACTIVE
        await self._notify_state_change()

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
        logger.info(
            f"[Coordinator] Trade approved: {action} {ticker} "
            f"@ {entry_price} (risk: {risk_score})"
        )

        # Check if trading is active
        if self._state.mode != TradingMode.ACTIVE:
            logger.warning("[Coordinator] Trading not active, skipping execution")
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.BUY if action == "BUY" else OrderSide.SELL,
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=f"Trading is {self._state.mode.value}",
            )

        # Check daily trade limit
        if self._state.daily_trades_count >= self.risk_params.max_daily_trades:
            logger.warning("[Coordinator] Daily trade limit reached")
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.BUY if action == "BUY" else OrderSide.SELL,
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale="Daily trade limit reached",
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

        if allocation.quantity <= 0:
            logger.warning(f"[Coordinator] Allocation returned 0 quantity: {allocation.rationale}")
            return allocation

        # Execute rebalancing orders first
        for rebalance_order in allocation.rebalance_orders:
            logger.info(f"[Coordinator] Executing rebalance: {rebalance_order}")
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

        result = await self._execute_order(order)

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
                balance = await self._kiwoom.get_account_balance()
                self._state.account = AccountInfo(
                    total_equity=balance.get("total_equity", 0),
                    available_cash=balance.get("available_cash", 0),
                    total_stock_value=balance.get("stock_value", 0),
                )
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
