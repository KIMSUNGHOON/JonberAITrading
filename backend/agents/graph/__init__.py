"""
LangGraph Trading Agents Package

Exports trading graphs for both stock and cryptocurrency analysis.
"""

# Stock trading graph
from agents.graph.trading_graph import (
    get_trading_graph,
    reset_trading_graph,
    run_analysis,
    resume_after_approval,
)
from agents.graph.state import (
    TradingState,
    create_initial_state,
    AnalysisStage,
)

# Coin trading graph
from agents.graph.coin_trading_graph import (
    get_coin_trading_graph,
    reset_coin_trading_graph,
    run_coin_analysis,
    resume_coin_after_approval,
)
from agents.graph.coin_state import (
    CoinTradingState,
    create_coin_initial_state,
    CoinAnalysisStage,
)

__all__ = [
    # Stock
    "get_trading_graph",
    "reset_trading_graph",
    "run_analysis",
    "resume_after_approval",
    "TradingState",
    "create_initial_state",
    "AnalysisStage",
    # Coin
    "get_coin_trading_graph",
    "reset_coin_trading_graph",
    "run_coin_analysis",
    "resume_coin_after_approval",
    "CoinTradingState",
    "create_coin_initial_state",
    "CoinAnalysisStage",
]
