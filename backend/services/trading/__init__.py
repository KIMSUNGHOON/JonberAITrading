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
    ActivityType,
    ActivityLog,
    ManagedPosition,
    OrderRequest,
    OrderResult,
    AllocationPlan,
    TradingState,
    TradingAlert,
    RiskParameters,
    QueueStatus,
    QueuedTrade,
    AgentStatus,
    AgentState,
)
from .market_hours import MarketType, MarketSession, MarketHoursService, get_market_hours_service
from .portfolio_agent import PortfolioAgent
from .order_agent import OrderAgent
from .risk_monitor import RiskMonitor
from .coordinator import ExecutionCoordinator
from .strategy import (
    RiskTolerance,
    TradingStyle,
    StrategyPreset,
    EntryConditions,
    ExitConditions,
    PositionSizingRules,
    TradingStrategy,
    EntryDecision,
    ExitDecision,
    STRATEGY_PRESETS,
    get_strategy_preset,
    get_all_presets,
)
from .strategy_engine import StrategyEngine

__all__ = [
    # Models
    "TradingMode",
    "StopLossMode",
    "PositionStatus",
    "OrderType",
    "OrderSide",
    "ActivityType",
    "ActivityLog",
    "ManagedPosition",
    "OrderRequest",
    "OrderResult",
    "AllocationPlan",
    "TradingState",
    "TradingAlert",
    "RiskParameters",
    "QueueStatus",
    "QueuedTrade",
    "AgentStatus",
    "AgentState",
    # Market Hours
    "MarketType",
    "MarketSession",
    "MarketHoursService",
    "get_market_hours_service",
    # Agents
    "PortfolioAgent",
    "OrderAgent",
    "RiskMonitor",
    "ExecutionCoordinator",
    # Strategy
    "RiskTolerance",
    "TradingStyle",
    "StrategyPreset",
    "EntryConditions",
    "ExitConditions",
    "PositionSizingRules",
    "TradingStrategy",
    "EntryDecision",
    "ExitDecision",
    "STRATEGY_PRESETS",
    "get_strategy_preset",
    "get_all_presets",
    "StrategyEngine",
]
