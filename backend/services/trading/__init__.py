"""
Auto-Trading Service Module

Provides AI-agent based automated trading with:
- Portfolio management and position sizing
- Order execution with rate limiting
- Risk monitoring and alerts
- Human-in-the-loop approval workflows
"""

from .models import (
    TradingMode,
    StopLossMode,
    PositionStatus,
    OrderType,
    OrderSide,
    ManagedPosition,
    OrderRequest,
    OrderResult,
    AllocationPlan,
    TradingState,
    TradingAlert,
    RiskParameters,
)
from .portfolio_agent import PortfolioAgent
from .order_agent import OrderAgent
from .risk_monitor import RiskMonitor
from .coordinator import ExecutionCoordinator

__all__ = [
    # Models
    "TradingMode",
    "StopLossMode",
    "PositionStatus",
    "OrderType",
    "OrderSide",
    "ManagedPosition",
    "OrderRequest",
    "OrderResult",
    "AllocationPlan",
    "TradingState",
    "TradingAlert",
    "RiskParameters",
    # Agents
    "PortfolioAgent",
    "OrderAgent",
    "RiskMonitor",
    "ExecutionCoordinator",
]
