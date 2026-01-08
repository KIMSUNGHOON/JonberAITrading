"""
Risk Monitor

Real-time monitoring of positions for stop-loss, take-profit, and sudden moves.
Sends alerts and can auto-execute based on configuration.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, List, Callable, Awaitable

from .models import (
    ManagedPosition,
    StopLossMode,
    AlertType,
    TradingAlert,
    TradingMode,
    RiskParameters,
    OrderRequest,
    OrderSide,
)

logger = logging.getLogger(__name__)


class RiskMonitor:
    """
    Risk monitoring agent.

    Responsibilities:
    - Monitor positions in real-time
    - Detect stop-loss / take-profit triggers
    - Detect sudden price movements
    - Pause trading and alert users
    - Auto-execute based on mode settings
    """

    def __init__(
        self,
        risk_params: Optional[RiskParameters] = None,
        price_fetcher: Optional[Callable[[str], Awaitable[float]]] = None,
        alert_sender: Optional[Callable[[TradingAlert], Awaitable[None]]] = None,
        order_executor: Optional[Callable[[OrderRequest], Awaitable[None]]] = None,
    ):
        """
        Initialize Risk Monitor.

        Args:
            risk_params: Risk parameters
            price_fetcher: Async function to get current price
            alert_sender: Async function to send alerts
            order_executor: Async function to execute orders
        """
        self.risk_params = risk_params or RiskParameters()
        self._get_price = price_fetcher
        self._send_alert = alert_sender
        self._execute_order = order_executor

        # Monitoring state
        self._watching: Dict[str, WatchConfig] = {}
        self._trading_mode = TradingMode.STOPPED
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Alert history
        self._alerts: List[TradingAlert] = []
        self._pending_alerts: List[TradingAlert] = []

    async def start(self):
        """Start the risk monitoring loop."""
        if self._running:
            return

        self._running = True
        self._trading_mode = TradingMode.ACTIVE
        self._task = asyncio.create_task(self._monitor_loop())

        logger.info("[RiskMonitor] Started monitoring")

    async def stop(self):
        """Stop the risk monitoring loop."""
        self._running = False
        self._trading_mode = TradingMode.STOPPED

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("[RiskMonitor] Stopped monitoring")

    async def pause(self, reason: str = "Manual pause"):
        """Pause trading (keeps monitoring but won't auto-execute)."""
        self._trading_mode = TradingMode.PAUSED

        alert = TradingAlert(
            id=str(uuid.uuid4())[:8],
            alert_type=AlertType.TRADING_PAUSED,
            title="Trading Paused",
            message=reason,
            action_required=False,
        )
        await self._add_alert(alert)

        logger.info(f"[RiskMonitor] Trading paused: {reason}")

    async def resume(self):
        """Resume trading after pause."""
        self._trading_mode = TradingMode.ACTIVE

        alert = TradingAlert(
            id=str(uuid.uuid4())[:8],
            alert_type=AlertType.TRADING_RESUMED,
            title="Trading Resumed",
            message="Auto-trading has been resumed",
            action_required=False,
        )
        await self._add_alert(alert)

        logger.info("[RiskMonitor] Trading resumed")

    def add_position(
        self,
        position: ManagedPosition,
        stop_loss_mode: Optional[StopLossMode] = None,
    ):
        """
        Add a position to watch.

        Args:
            position: Position to monitor
            stop_loss_mode: Override stop-loss mode for this position
        """
        config = WatchConfig(
            ticker=position.ticker,
            stock_name=position.stock_name,
            entry_price=position.avg_price,
            quantity=position.quantity,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            stop_loss_mode=stop_loss_mode or position.stop_loss_mode,
            last_price=position.current_price,
        )
        self._watching[position.ticker] = config

        logger.info(
            f"[RiskMonitor] Watching {position.ticker}: "
            f"SL={position.stop_loss}, TP={position.take_profit}, "
            f"mode={config.stop_loss_mode}"
        )

    def remove_position(self, ticker: str):
        """Remove a position from watching."""
        if ticker in self._watching:
            del self._watching[ticker]
            logger.info(f"[RiskMonitor] Stopped watching {ticker}")

    def update_stop_loss(self, ticker: str, new_stop_loss: float):
        """Update stop-loss for a position."""
        if ticker in self._watching:
            self._watching[ticker].stop_loss = new_stop_loss
            logger.info(f"[RiskMonitor] Updated {ticker} stop-loss to {new_stop_loss}")

    def update_take_profit(self, ticker: str, new_take_profit: float):
        """Update take-profit for a position."""
        if ticker in self._watching:
            self._watching[ticker].take_profit = new_take_profit
            logger.info(f"[RiskMonitor] Updated {ticker} take-profit to {new_take_profit}")

    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_all_positions()
                await asyncio.sleep(1)  # Check every second
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[RiskMonitor] Error in monitor loop: {e}")
                await asyncio.sleep(5)

    async def _check_all_positions(self):
        """Check all watched positions."""
        if not self._watching:
            return

        for ticker, config in list(self._watching.items()):
            try:
                await self._check_position(ticker, config)
            except Exception as e:
                logger.error(f"[RiskMonitor] Error checking {ticker}: {e}")

    async def _check_position(self, ticker: str, config: "WatchConfig"):
        """Check a single position for triggers."""
        # Get current price
        if self._get_price:
            try:
                current_price = await self._get_price(ticker)
            except Exception as e:
                logger.warning(f"[RiskMonitor] Failed to get price for {ticker}: {e}")
                return
        else:
            # Simulation: use last known price
            current_price = config.last_price

        if current_price <= 0:
            return

        # Calculate price change
        change_pct = ((current_price - config.entry_price) / config.entry_price) * 100

        # Check for sudden moves
        if config.last_price > 0:
            sudden_change = abs(
                (current_price - config.last_price) / config.last_price * 100
            )
            if sudden_change >= self.risk_params.sudden_move_threshold_pct:
                await self._handle_sudden_move(ticker, config, current_price, change_pct)
                config.last_price = current_price
                return

        config.last_price = current_price

        # Skip trigger checks if paused
        if self._trading_mode == TradingMode.PAUSED:
            return

        # Check stop-loss
        if config.stop_loss and current_price <= config.stop_loss:
            await self._handle_stop_loss(ticker, config, current_price)

        # Check take-profit
        elif config.take_profit and current_price >= config.take_profit:
            await self._handle_take_profit(ticker, config, current_price)

    async def _handle_sudden_move(
        self,
        ticker: str,
        config: "WatchConfig",
        current_price: float,
        change_pct: float,
    ):
        """Handle sudden price movement."""
        direction = "up" if change_pct > 0 else "down"
        alert_type = AlertType.SUDDEN_MOVE_UP if change_pct > 0 else AlertType.SUDDEN_MOVE_DOWN

        logger.warning(
            f"[RiskMonitor] Sudden move detected for {ticker}: "
            f"{change_pct:+.1f}% ({current_price})"
        )

        # Pause trading
        await self.pause(f"Sudden {direction} move in {ticker}: {change_pct:+.1f}%")

        # Create alert
        alert = TradingAlert(
            id=str(uuid.uuid4())[:8],
            alert_type=alert_type,
            ticker=ticker,
            title=f"Sudden Price Movement: {ticker}",
            message=f"{config.stock_name or ticker} moved {change_pct:+.1f}% to ₩{current_price:,.0f}",
            data={
                "ticker": ticker,
                "current_price": current_price,
                "entry_price": config.entry_price,
                "change_pct": change_pct,
                "direction": direction,
            },
            action_required=True,
            options=["RESUME", "CLOSE_POSITION", "ADJUST_STOP_LOSS"],
        )

        await self._add_alert(alert)

    async def _handle_stop_loss(
        self,
        ticker: str,
        config: "WatchConfig",
        current_price: float,
    ):
        """Handle stop-loss trigger."""
        loss_pct = ((current_price - config.entry_price) / config.entry_price) * 100

        logger.warning(
            f"[RiskMonitor] Stop-loss triggered for {ticker}: "
            f"{loss_pct:.1f}% loss ({current_price} <= {config.stop_loss})"
        )

        if config.stop_loss_mode == StopLossMode.AGENT_AUTO:
            # Auto-execute
            await self._execute_stop_loss(ticker, config, current_price)
        else:
            # User approval required
            alert = TradingAlert(
                id=str(uuid.uuid4())[:8],
                alert_type=AlertType.STOP_LOSS_TRIGGERED,
                ticker=ticker,
                title=f"Stop-Loss Triggered: {ticker}",
                message=f"{config.stock_name or ticker} hit stop-loss at ₩{current_price:,.0f} ({loss_pct:.1f}% loss)",
                data={
                    "ticker": ticker,
                    "current_price": current_price,
                    "stop_loss": config.stop_loss,
                    "entry_price": config.entry_price,
                    "quantity": config.quantity,
                    "loss_pct": loss_pct,
                    "estimated_loss": (config.entry_price - current_price) * config.quantity,
                },
                action_required=True,
                options=["EXECUTE_STOP_LOSS", "ADJUST_STOP_LOSS", "HOLD"],
            )

            await self._add_alert(alert)

    async def _handle_take_profit(
        self,
        ticker: str,
        config: "WatchConfig",
        current_price: float,
    ):
        """Handle take-profit trigger."""
        profit_pct = ((current_price - config.entry_price) / config.entry_price) * 100

        logger.info(
            f"[RiskMonitor] Take-profit triggered for {ticker}: "
            f"{profit_pct:.1f}% profit ({current_price} >= {config.take_profit})"
        )

        # Check take-profit mode (using same setting as stop-loss for simplicity)
        take_profit_mode = self.risk_params.take_profit_mode

        if take_profit_mode == StopLossMode.AGENT_AUTO:
            # Auto-execute
            await self._execute_take_profit(ticker, config, current_price)
        else:
            # User approval required
            alert = TradingAlert(
                id=str(uuid.uuid4())[:8],
                alert_type=AlertType.TAKE_PROFIT_TRIGGERED,
                ticker=ticker,
                title=f"Take-Profit Triggered: {ticker}",
                message=f"{config.stock_name or ticker} reached target at ₩{current_price:,.0f} ({profit_pct:.1f}% profit)",
                data={
                    "ticker": ticker,
                    "current_price": current_price,
                    "take_profit": config.take_profit,
                    "entry_price": config.entry_price,
                    "quantity": config.quantity,
                    "profit_pct": profit_pct,
                    "estimated_profit": (current_price - config.entry_price) * config.quantity,
                },
                action_required=True,
                options=["EXECUTE_TAKE_PROFIT", "ADJUST_TARGET", "HOLD"],
            )

            await self._add_alert(alert)

    async def _execute_stop_loss(
        self,
        ticker: str,
        config: "WatchConfig",
        current_price: float,
    ):
        """Execute stop-loss order."""
        if not self._execute_order:
            logger.warning("[RiskMonitor] No order executor configured")
            return

        order = OrderRequest(
            ticker=ticker,
            stock_name=config.stock_name,
            side=OrderSide.SELL,
            quantity=config.quantity,
            price=current_price,
            reason="Stop-loss auto-execution",
        )

        try:
            await self._execute_order(order)
            self.remove_position(ticker)

            alert = TradingAlert(
                id=str(uuid.uuid4())[:8],
                alert_type=AlertType.ORDER_FILLED,
                ticker=ticker,
                title=f"Stop-Loss Executed: {ticker}",
                message=f"Sold {config.quantity} shares at ₩{current_price:,.0f}",
                action_required=False,
            )
            await self._add_alert(alert)

        except Exception as e:
            logger.error(f"[RiskMonitor] Stop-loss execution failed: {e}")

            alert = TradingAlert(
                id=str(uuid.uuid4())[:8],
                alert_type=AlertType.ORDER_FAILED,
                ticker=ticker,
                title=f"Stop-Loss Failed: {ticker}",
                message=str(e),
                action_required=True,
                options=["RETRY", "MANUAL_SELL"],
            )
            await self._add_alert(alert)

    async def _execute_take_profit(
        self,
        ticker: str,
        config: "WatchConfig",
        current_price: float,
    ):
        """Execute take-profit order."""
        if not self._execute_order:
            logger.warning("[RiskMonitor] No order executor configured")
            return

        order = OrderRequest(
            ticker=ticker,
            stock_name=config.stock_name,
            side=OrderSide.SELL,
            quantity=config.quantity,
            price=current_price,
            reason="Take-profit auto-execution",
        )

        try:
            await self._execute_order(order)
            self.remove_position(ticker)

            alert = TradingAlert(
                id=str(uuid.uuid4())[:8],
                alert_type=AlertType.ORDER_FILLED,
                ticker=ticker,
                title=f"Take-Profit Executed: {ticker}",
                message=f"Sold {config.quantity} shares at ₩{current_price:,.0f}",
                action_required=False,
            )
            await self._add_alert(alert)

        except Exception as e:
            logger.error(f"[RiskMonitor] Take-profit execution failed: {e}")

    async def _add_alert(self, alert: TradingAlert):
        """Add and send alert."""
        self._alerts.append(alert)

        if alert.action_required:
            self._pending_alerts.append(alert)

        if self._send_alert:
            try:
                await self._send_alert(alert)
            except Exception as e:
                logger.error(f"[RiskMonitor] Failed to send alert: {e}")

    def get_pending_alerts(self) -> List[TradingAlert]:
        """Get all pending alerts requiring action."""
        return [a for a in self._pending_alerts if not a.resolved]

    def acknowledge_alert(self, alert_id: str):
        """Mark an alert as acknowledged."""
        for alert in self._pending_alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                alert.acknowledged_at = datetime.now()
                break

    def resolve_alert(self, alert_id: str):
        """Mark an alert as resolved."""
        for alert in self._pending_alerts:
            if alert.id == alert_id:
                alert.resolved = True
                break

    @property
    def is_active(self) -> bool:
        return self._trading_mode == TradingMode.ACTIVE

    @property
    def is_paused(self) -> bool:
        return self._trading_mode == TradingMode.PAUSED

    @property
    def trading_mode(self) -> TradingMode:
        return self._trading_mode


class WatchConfig:
    """Configuration for watching a position."""

    def __init__(
        self,
        ticker: str,
        stock_name: Optional[str] = None,
        entry_price: float = 0,
        quantity: int = 0,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        stop_loss_mode: StopLossMode = StopLossMode.USER_APPROVAL,
        last_price: float = 0,
    ):
        self.ticker = ticker
        self.stock_name = stock_name
        self.entry_price = entry_price
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.stop_loss_mode = stop_loss_mode
        self.last_price = last_price
