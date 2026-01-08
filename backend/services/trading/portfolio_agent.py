"""
Portfolio Agent

Manages portfolio allocation, position sizing, and rebalancing.
All decisions are based on risk parameters and current account state.
"""

import logging
from typing import Optional, List
from datetime import datetime

from .models import (
    AccountInfo,
    AllocationPlan,
    ManagedPosition,
    OrderRequest,
    OrderSide,
    RiskParameters,
    TradingState,
)

logger = logging.getLogger(__name__)


class PortfolioAgent:
    """
    Portfolio management agent.

    Responsibilities:
    - Calculate optimal position sizes based on risk
    - Determine allocation for new trades
    - Suggest rebalancing when needed
    - Ensure risk limits are maintained
    """

    def __init__(self, risk_params: Optional[RiskParameters] = None):
        """
        Initialize Portfolio Agent.

        Args:
            risk_params: Risk parameters for allocation decisions
        """
        self.risk_params = risk_params or RiskParameters()

    def calculate_allocation(
        self,
        account: AccountInfo,
        ticker: str,
        stock_name: Optional[str],
        side: OrderSide,
        entry_price: float,
        risk_score: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        current_positions: Optional[List[ManagedPosition]] = None,
    ) -> AllocationPlan:
        """
        Calculate optimal allocation for a new trade.

        Args:
            account: Current account information
            ticker: Stock ticker
            stock_name: Stock name
            side: Buy or sell
            entry_price: Planned entry price
            risk_score: Risk score from analysis (1-10)
            stop_loss: Stop-loss price
            take_profit: Take-profit price
            current_positions: Existing positions

        Returns:
            AllocationPlan with quantity and any needed rebalancing
        """
        logger.info(
            f"[PortfolioAgent] Calculating allocation for {ticker} "
            f"(side={side}, price={entry_price}, risk={risk_score})"
        )

        current_positions = current_positions or []

        # Check if already holding this stock
        existing_position = next(
            (p for p in current_positions if p.ticker == ticker),
            None
        )

        if side == OrderSide.SELL:
            return self._calculate_sell_allocation(
                existing_position, ticker, stock_name, entry_price
            )

        # For BUY: calculate position size
        return self._calculate_buy_allocation(
            account=account,
            ticker=ticker,
            stock_name=stock_name,
            entry_price=entry_price,
            risk_score=risk_score,
            stop_loss=stop_loss,
            take_profit=take_profit,
            existing_position=existing_position,
            current_positions=current_positions,
        )

    def _calculate_buy_allocation(
        self,
        account: AccountInfo,
        ticker: str,
        stock_name: Optional[str],
        entry_price: float,
        risk_score: int,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        existing_position: Optional[ManagedPosition],
        current_positions: List[ManagedPosition],
    ) -> AllocationPlan:
        """Calculate allocation for a BUY order."""

        # 1. Calculate available capital for this trade
        available_for_trade = self._calculate_available_capital(
            account, current_positions
        )

        if available_for_trade <= 0:
            logger.warning(
                f"[PortfolioAgent] No capital available for {ticker}"
            )
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.BUY,
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale="Insufficient capital - minimum cash reserve required",
            )

        # 2. Calculate position size based on risk
        max_position_value = self._calculate_max_position_value(
            account.total_equity, risk_score
        )

        # 3. Consider existing position
        if existing_position:
            current_value = existing_position.quantity * existing_position.current_price
            current_position_pct = (current_value / account.total_equity) * 100 if account.total_equity > 0 else 0

            # Check if already at or above max position
            if current_value >= max_position_value:
                logger.warning(
                    f"[PortfolioAgent] {ticker} already at max position: "
                    f"{existing_position.quantity}주 ({current_position_pct:.1f}%)"
                )
                return AllocationPlan(
                    ticker=ticker,
                    stock_name=stock_name,
                    side=OrderSide.BUY,
                    quantity=0,
                    entry_price=entry_price,
                    estimated_amount=0,
                    position_pct=0,
                    rationale=f"이미 보유 중: {existing_position.quantity}주 ({current_position_pct:.1f}%) - 추가 매수 불가 (최대 포지션 도달)",
                )

            # Calculate remaining allowed position
            max_position_value = max_position_value - current_value

        # 4. Apply constraints
        position_value = min(available_for_trade, max_position_value)

        # 5. Calculate quantity
        quantity = int(position_value / entry_price)

        if quantity <= 0:
            rationale = "Position size too small after risk adjustment"
            if existing_position:
                existing_pct = (existing_position.quantity * existing_position.current_price / account.total_equity) * 100 if account.total_equity > 0 else 0
                rationale = f"추가 매수 불가: 이미 {existing_position.quantity}주 보유 ({existing_pct:.1f}%)"
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.BUY,
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=rationale,
            )

        # 6. Final calculations
        estimated_amount = quantity * entry_price
        position_pct = (estimated_amount / account.total_equity) * 100 if account.total_equity > 0 else 0

        # 7. Check if rebalancing is needed
        rebalance_orders = self._check_rebalancing_needed(
            account, current_positions, estimated_amount
        )

        rationale = self._build_rationale(
            risk_score, position_pct, existing_position is not None
        )

        logger.info(
            f"[PortfolioAgent] Allocation: {quantity} shares @ {entry_price} "
            f"= {estimated_amount:,.0f} ({position_pct:.1f}% of equity)"
        )

        return AllocationPlan(
            ticker=ticker,
            stock_name=stock_name,
            side=OrderSide.BUY,
            quantity=quantity,
            entry_price=entry_price,
            estimated_amount=estimated_amount,
            position_pct=position_pct,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_score=risk_score,
            rebalance_orders=rebalance_orders,
            rationale=rationale,
        )

    def _calculate_sell_allocation(
        self,
        existing_position: Optional[ManagedPosition],
        ticker: str,
        stock_name: Optional[str],
        price: float,
    ) -> AllocationPlan:
        """Calculate allocation for a SELL order."""

        if not existing_position:
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=OrderSide.SELL,
                quantity=0,
                entry_price=price,
                estimated_amount=0,
                position_pct=0,
                rationale="No position to sell",
            )

        return AllocationPlan(
            ticker=ticker,
            stock_name=stock_name,
            side=OrderSide.SELL,
            quantity=existing_position.quantity,
            entry_price=price,
            estimated_amount=existing_position.quantity * price,
            position_pct=0,  # Will be 0 after sell
            rationale="Full position liquidation",
        )

    def _calculate_available_capital(
        self,
        account: AccountInfo,
        current_positions: List[ManagedPosition],
    ) -> float:
        """Calculate capital available for new trades."""

        # Must maintain minimum cash reserve
        min_cash = account.total_equity * self.risk_params.min_cash_ratio
        available = account.available_cash - min_cash

        # Check total stock allocation limit
        current_stock_value = sum(
            p.quantity * p.current_price for p in current_positions
        )
        max_stock_value = account.total_equity * self.risk_params.max_total_stock_pct
        stock_headroom = max_stock_value - current_stock_value

        return max(0, min(available, stock_headroom))

    def _calculate_max_position_value(
        self,
        total_equity: float,
        risk_score: int,
    ) -> float:
        """
        Calculate maximum position value based on risk.

        Higher risk score = smaller position.
        """
        base_max = total_equity * self.risk_params.max_single_position_pct

        # Risk adjustment: reduce position for higher risk
        # Risk 1-3: 100% of max
        # Risk 4-6: 70% of max
        # Risk 7-10: 50% of max
        if risk_score <= 3:
            risk_factor = 1.0
        elif risk_score <= 6:
            risk_factor = 0.7
        else:
            risk_factor = 0.5

        return base_max * risk_factor

    def _check_rebalancing_needed(
        self,
        account: AccountInfo,
        positions: List[ManagedPosition],
        new_trade_amount: float,
    ) -> List[OrderRequest]:
        """Check if rebalancing is needed to accommodate new trade."""
        rebalance_orders = []

        # Check if new trade would exceed max stock allocation
        current_stock_value = sum(p.quantity * p.current_price for p in positions)
        projected_stock_value = current_stock_value + new_trade_amount
        max_stock_value = account.total_equity * self.risk_params.max_total_stock_pct

        if projected_stock_value > max_stock_value:
            excess = projected_stock_value - max_stock_value

            # Find positions to reduce (prioritize worst performers)
            sorted_positions = sorted(
                positions,
                key=lambda p: p.unrealized_pnl_pct
            )

            for pos in sorted_positions:
                if excess <= 0:
                    break

                # Calculate how much to sell
                pos_value = pos.quantity * pos.current_price
                sell_value = min(pos_value, excess)
                sell_qty = int(sell_value / pos.current_price)

                if sell_qty > 0:
                    rebalance_orders.append(OrderRequest(
                        ticker=pos.ticker,
                        stock_name=pos.stock_name,
                        side=OrderSide.SELL,
                        quantity=sell_qty,
                        reason=f"Rebalancing to accommodate new position",
                    ))
                    excess -= sell_qty * pos.current_price

        return rebalance_orders

    def _build_rationale(
        self,
        risk_score: int,
        position_pct: float,
        is_addition: bool,
    ) -> str:
        """Build human-readable rationale for allocation."""
        parts = []

        if risk_score <= 3:
            parts.append(f"Low risk (score: {risk_score}/10)")
        elif risk_score <= 6:
            parts.append(f"Medium risk (score: {risk_score}/10)")
        else:
            parts.append(f"High risk (score: {risk_score}/10) - reduced position")

        parts.append(f"Position size: {position_pct:.1f}% of portfolio")

        if is_addition:
            parts.append("Adding to existing position")

        return " | ".join(parts)

    def suggest_rebalancing(
        self,
        state: TradingState,
    ) -> Optional[List[OrderRequest]]:
        """
        Analyze portfolio and suggest rebalancing if needed.

        Returns:
            List of rebalancing orders, or None if not needed
        """
        if not state.positions:
            return None

        rebalance_orders = []
        total_equity = state.account.total_equity

        for position in state.positions:
            pos_value = position.quantity * position.current_price
            pos_pct = (pos_value / total_equity) * 100 if total_equity > 0 else 0

            # Check if position exceeds max single position
            max_pct = self.risk_params.max_single_position_pct * 100

            if pos_pct > max_pct * 1.1:  # 10% tolerance
                excess_pct = pos_pct - max_pct
                excess_value = (excess_pct / 100) * total_equity
                sell_qty = int(excess_value / position.current_price)

                if sell_qty > 0:
                    rebalance_orders.append(OrderRequest(
                        ticker=position.ticker,
                        stock_name=position.stock_name,
                        side=OrderSide.SELL,
                        quantity=sell_qty,
                        reason=f"Position exceeds max allocation ({pos_pct:.1f}% > {max_pct:.1f}%)",
                    ))

        return rebalance_orders if rebalance_orders else None

    def get_portfolio_summary(
        self,
        state: TradingState,
    ) -> dict:
        """Get portfolio summary for display."""
        positions_summary = []

        for pos in state.positions:
            pos_value = pos.quantity * pos.current_price
            pos_pct = (pos_value / state.account.total_equity) * 100 if state.account.total_equity > 0 else 0

            positions_summary.append({
                "ticker": pos.ticker,
                "stock_name": pos.stock_name,
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_price": pos.current_price,
                "value": pos_value,
                "weight_pct": pos_pct,
                "unrealized_pnl": pos.unrealized_pnl,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "risk_score": pos.risk_score,
            })

        return {
            "total_equity": state.account.total_equity,
            "cash": state.account.available_cash,
            "cash_ratio": state.account.cash_ratio * 100,
            "stock_value": state.account.total_stock_value,
            "stock_ratio": state.account.stock_ratio * 100,
            "positions": positions_summary,
            "total_unrealized_pnl": state.total_unrealized_pnl,
            "total_unrealized_pnl_pct": state.total_unrealized_pnl_pct,
            "daily_trades": state.daily_trades_count,
            "max_daily_trades": state.risk_params.max_daily_trades,
        }
