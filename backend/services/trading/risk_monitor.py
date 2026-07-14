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
    OrderType,
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

    # T3 (MEDIUM finding B, review 2026-07-13): absolute cap on consecutive
    # sudden-move re-arms, expressed as a multiple of
    # `risk_params.sudden_move_cooldown_ticks`. A ticker whose tick-to-tick
    # move keeps qualifying as "sudden" would otherwise re-arm the cooldown
    # forever and never reach the ordinary N-tick recovery path — this is
    # the circuit breaker for that circuit breaker, guaranteeing recovery
    # even if the move never stabilizes.
    ABSOLUTE_COOLDOWN_CAP_MULTIPLIER = 3

    def __init__(
        self,
        risk_params: Optional[RiskParameters] = None,
        price_fetcher: Optional[Callable[[str], Awaitable[float]]] = None,
        alert_sender: Optional[Callable[[TradingAlert], Awaitable[None]]] = None,
        order_executor: Optional[Callable[[OrderRequest], Awaitable[None]]] = None,
        price_sink: Optional[Callable[[str, float], None]] = None,
    ):
        """
        Initialize Risk Monitor.

        Args:
            risk_params: Risk parameters
            price_fetcher: Async function to get current price
            alert_sender: Async function to send alerts
            order_executor: Async function to execute orders
            price_sink: Optional callback(ticker, price) invoked every tick
                right after a fresh price is fetched (T1, MEDIUM finding A).
                Decoupled from the monitor's own stop-loss/take-profit logic
                so a live 1s price feed can be mirrored back into an
                external tracker (ExecutionCoordinator's ManagedPosition)
                without this monitor knowing anything about it. The sink
                owns its own "stale price" contract — this monitor calls it
                unconditionally with whatever `price_fetcher` returned,
                including a fail-safe 0.
        """
        self.risk_params = risk_params or RiskParameters()
        self._get_price = price_fetcher
        self._send_alert = alert_sender
        self._execute_order = order_executor
        self._price_sink = price_sink

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

    def update_stop_loss(self, ticker: str, new_stop_loss: float) -> bool:
        """
        Update stop-loss for a position.

        Returns:
            True if `ticker` is being watched and the update was applied,
            False otherwise (T7 review C1 — callers, e.g. the SL/TP API
            route, must be able to tell a real update apart from a no-op
            instead of assuming success unconditionally).
        """
        if ticker in self._watching:
            self._watching[ticker].stop_loss = new_stop_loss
            logger.info(f"[RiskMonitor] Updated {ticker} stop-loss to {new_stop_loss}")
            return True
        return False

    def update_take_profit(self, ticker: str, new_take_profit: float) -> bool:
        """
        Update take-profit for a position.

        Returns:
            True if `ticker` is being watched and the update was applied,
            False otherwise (see `update_stop_loss`).
        """
        if ticker in self._watching:
            self._watching[ticker].take_profit = new_take_profit
            logger.info(f"[RiskMonitor] Updated {ticker} take-profit to {new_take_profit}")
            return True
        return False

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

        # T1 (MEDIUM finding A, review 2026-07-13): this 1s poll already
        # fetches a fresh price for every watched ticker — previously that
        # price was written only to `config.last_price` below and
        # discarded, so an external tracker (ExecutionCoordinator's
        # ManagedPosition.current_price, and unrealized P&L/exposure
        # derived from it) went stale between trade decisions. Feed it back
        # unconditionally via the decoupled price_sink so both stay fresh
        # at the same cadence; the sink owns the "no 0/None overwrite"
        # contract, not this monitor.
        if self._price_sink:
            try:
                self._price_sink(ticker, current_price)
            except Exception as e:
                logger.warning(f"[RiskMonitor] price_sink failed for {ticker}: {e}")

        if current_price <= 0:
            return

        # Calculate price change
        change_pct = ((current_price - config.entry_price) / config.entry_price) * 100

        # Tick-to-tick move, used both to DETECT a new sudden move and to
        # judge whether an in-progress per-ticker cooldown has stabilized.
        tick_change_pct = 0.0
        if config.last_price > 0:
            tick_change_pct = abs(
                (current_price - config.last_price) / config.last_price * 100
            )
            if tick_change_pct >= self.risk_params.sudden_move_threshold_pct:
                # M1 (C2 audit 2026-07-13): pause THIS ticker only — does
                # NOT touch _trading_mode or any other watched ticker. The
                # old code called the GLOBAL pause() here, which froze
                # stop-loss/take-profit checks for the entire book over one
                # ticker's dead-candle.
                #
                # T3 (MEDIUM finding B, review 2026-07-13): a ticker whose
                # tick-to-tick move keeps qualifying as "sudden" on EVERY
                # tick re-enters this branch every time and re-arms the
                # cooldown below before it can ever count down — its
                # stop-loss/take-profit defense would never resume under a
                # perpetual move. `sudden_move_ticks_in_cooldown` counts
                # consecutive ticks spent here (across re-arms — NOT reset
                # by them) and is a circuit breaker for the circuit
                # breaker: once it exceeds the absolute cap, defense is
                # force-resumed regardless of the ongoing move.
                config.sudden_move_ticks_in_cooldown += 1
                absolute_cap = (
                    self.risk_params.sudden_move_cooldown_ticks
                    * self.ABSOLUTE_COOLDOWN_CAP_MULTIPLIER
                )
                if config.sudden_move_ticks_in_cooldown > absolute_cap:
                    logger.warning(
                        f"[RiskMonitor] {ticker} force-recovered from "
                        f"sudden-move cooldown after "
                        f"{config.sudden_move_ticks_in_cooldown} consecutive "
                        f"ticks (absolute cap {absolute_cap}) — "
                        "stop-loss/take-profit resumed despite continued "
                        "volatility"
                    )
                    config.sudden_move_cooldown_ticks = 0
                    config.sudden_move_ticks_in_cooldown = 0
                    config.last_price = current_price
                    # Fall through to stop-loss/take-profit evaluation
                    # below instead of returning — guaranteed recovery,
                    # not another skip.
                else:
                    await self._handle_sudden_move(ticker, config, current_price, change_pct)
                    config.last_price = current_price
                    return

        # This ticker is cooling down from its OWN prior sudden move.
        # Auto-recovers after N monitor ticks OR once price stabilizes
        # (volatility at/under sudden_move_stabilization_pct) — no human
        # RESUME required.
        if config.sudden_move_cooldown_ticks > 0:
            config.sudden_move_cooldown_ticks -= 1
            stabilized = tick_change_pct <= self.risk_params.sudden_move_stabilization_pct
            if config.sudden_move_cooldown_ticks > 0 and not stabilized:
                config.last_price = current_price
                return
            config.sudden_move_cooldown_ticks = 0
            config.sudden_move_ticks_in_cooldown = 0
            logger.info(
                f"[RiskMonitor] {ticker} sudden-move cooldown cleared "
                f"({'price stabilized' if stabilized else 'tick-count elapsed'}); "
                "stop-loss/take-profit resumed automatically"
            )
            # Fall through: re-evaluate stop-loss/take-profit with the
            # current price in this same tick.

        config.last_price = current_price

        # Manual/global kill-switch (ExecutionCoordinator.pause()/resume(),
        # the alert "RESUME" action) — unrelated to the per-ticker
        # sudden-move cooldown above. Still intentionally gates ALL tickers
        # when an operator explicitly pauses the whole book.
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
        """Handle sudden price movement.

        Pauses stop-loss/take-profit checks for THIS ticker only, via
        `config.sudden_move_cooldown_ticks` (M1, C2 audit 2026-07-13). This
        deliberately does NOT call the global `pause()` — that API is kept
        as a separate manual/operator kill-switch (ExecutionCoordinator.
        pause()/resume(), the alert "RESUME" action), which still legitimately
        gates every ticker when invoked explicitly. The per-ticker cooldown
        set here auto-clears in `_check_position` after N monitor ticks or
        once price stabilizes — no human action required.
        """
        direction = "up" if change_pct > 0 else "down"
        alert_type = AlertType.SUDDEN_MOVE_UP if change_pct > 0 else AlertType.SUDDEN_MOVE_DOWN

        logger.warning(
            f"[RiskMonitor] Sudden move detected for {ticker}: "
            f"{change_pct:+.1f}% ({current_price})"
        )

        # Per-ticker pause + auto-recovery — NOT the global pause().
        config.sudden_move_cooldown_ticks = self.risk_params.sudden_move_cooldown_ticks

        # Create alert. "RESUME" is intentionally omitted: recovery is now
        # automatic and per-ticker, and the global resume() would not clear
        # this ticker's cooldown anyway.
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
            options=["CLOSE_POSITION", "ADJUST_STOP_LOSS"],
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
            # P2-4 Task P2: defensive exits must submit as MARKET, not the
            # OrderRequest default of LIMIT (models.py). A LIMIT order sent
            # at the trigger price records a fill at that (favorable) price
            # if the mock/live broker fills it there — understating real
            # gap/crash risk. MARKET makes the broker report the true
            # adverse fill via ka10076, so the KR ledger stays broker-truth
            # (no app-side synthetic slippage added here — this is an
            # order-construction fix, correct in live too, not a sim).
            order_type=OrderType.MARKET,
            reason="Stop-loss auto-execution",
        )

        try:
            # The order executor (coordinator) reconciles position tracking with
            # the ACTUAL fill (remove on full, reduce on partial, keep on none) —
            # do NOT unconditionally remove here or it clobbers a re-registered
            # partial remainder / a retained unfilled position (review #5b).
            await self._execute_order(order)

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
            # P2-4 Task P2: see _execute_stop_loss — MARKET so the broker
            # reports the true fill instead of the (favorable) trigger price.
            order_type=OrderType.MARKET,
            reason="Take-profit auto-execution",
        )

        try:
            # See _execute_stop_loss: the executor reconciles by actual fill; do
            # not unconditionally remove here (review #5b).
            await self._execute_order(order)

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

        # M1 (C2 audit 2026-07-13): remaining monitor ticks this ticker's
        # OWN stop-loss/take-profit checks stay paused after a sudden move.
        # 0 = not paused. Set by RiskMonitor._handle_sudden_move, decremented
        # and auto-cleared by RiskMonitor._check_position — per-ticker only,
        # independent of the global _trading_mode.
        self.sudden_move_cooldown_ticks: int = 0

        # T3 (MEDIUM finding B, review 2026-07-13): consecutive ticks spent
        # in the sudden-move branch since the cooldown FIRST armed, counting
        # across re-arms (a perpetual mover never resets this by re-arming
        # `sudden_move_cooldown_ticks` above). Reset to 0 whenever the
        # ticker actually recovers — via the ordinary tick-count/
        # stabilization path in `_check_position`, or via the absolute-cap
        # force-recovery itself. Guarantees this ticker's defense resumes
        # even under a move that never qualifies as "stabilized".
        self.sudden_move_ticks_in_cooldown: int = 0

    @property
    def is_sudden_move_paused(self) -> bool:
        return self.sudden_move_cooldown_ticks > 0
