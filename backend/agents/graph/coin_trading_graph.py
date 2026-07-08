"""
Main LangGraph Assembly for Coin Trading Agent

Assembles all nodes into a complete cryptocurrency trading workflow with:
- Market data collection from Upbit
- Sequential analysis (technical, market, sentiment, risk)
- Human-in-the-loop approval
- Trade execution
"""

from typing import Optional

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from agents.graph.coin_nodes import (
    coin_data_collection_node,
    coin_execution_node,
    coin_human_approval_node,
    coin_market_analysis_node,
    coin_re_analyze_node,
    coin_risk_assessment_node,
    coin_sentiment_analysis_node,
    coin_strategic_decision_node,
    coin_technical_analysis_node,
    should_continue_coin_execution,
)
from agents.graph.coin_state import CoinTradingState, create_coin_initial_state
from agents.graph.graph_factory import build_analysis_graph, compile_analysis_graph

logger = structlog.get_logger()


def create_coin_trading_graph() -> StateGraph:
    """
    Create the main coin trading workflow graph.

    Workflow Stages:
    1. Data Collection - Fetch market data from Upbit
    2. Analysis Phase (Sequential):
       - Technical Analysis (charts, indicators)
       - Market Analysis (volume, trends)
       - Sentiment Analysis (social, news)
       - Risk Assessment (volatility, position sizing)
    3. Strategic Decision - Synthesize and propose trade
    4. Human Approval - HITL interrupt point
    5. Execution - Execute approved trades via Upbit API

    Flow:
    ```
    [Start]
        ↓
    [Data Collection] → [Technical] → [Market] → [Sentiment]
                                                       ↓
                                                   [Risk] → [Decision]
                                                                 ↓
                                                           [Approval] ← INTERRUPT
                                                                 ↓
                                                         ┌──────┴──────┐
                                                         ↓             ↓
                                                    [Execute]   [Re-analyze]
                                                         ↓             ↓
                                                      [End]    [Data Collection]
    ```
    """
    # Topology is shared across all 3 market stacks; see graph_factory.
    return build_analysis_graph(
        CoinTradingState,
        entry_node=("data_collection", coin_data_collection_node),
        analysis_nodes=[
            ("technical", coin_technical_analysis_node),
            ("market", coin_market_analysis_node),
            ("sentiment", coin_sentiment_analysis_node),
            ("risk", coin_risk_assessment_node),
        ],
        decision_node=coin_strategic_decision_node,
        approval_node=coin_human_approval_node,
        re_analyze_node=coin_re_analyze_node,
        execute_node=coin_execution_node,
        cond_fn=should_continue_coin_execution,
    )


def compile_coin_trading_graph(
    checkpointer: Optional[MemorySaver] = None,
    interrupt_before_approval: bool = True,
) -> StateGraph:
    """
    Compile the coin trading graph with checkpointing support.

    Args:
        checkpointer: LangGraph checkpointer for state persistence.
        interrupt_before_approval: If True, pause before human approval node.

    Returns:
        Compiled StateGraph ready for execution.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    compiled = compile_analysis_graph(
        create_coin_trading_graph(),
        checkpointer,
        interrupt_before_approval=interrupt_before_approval,
    )

    logger.info(
        "coin_trading_graph_compiled",
        interrupt_before=["approval"] if interrupt_before_approval else [],
        checkpointer_type=type(checkpointer).__name__,
    )

    return compiled


# -------------------------------------------
# Singleton Pattern
# -------------------------------------------

_coin_trading_graph: Optional[StateGraph] = None


def get_coin_trading_graph() -> StateGraph:
    """
    Get or create the singleton coin trading graph.

    Returns:
        Compiled trading graph ready for execution.
    """
    global _coin_trading_graph
    if _coin_trading_graph is None:
        # Durable persistence (P6): SqliteCheckpointer partitions by thread_id so
        # HITL interrupt/resume survives a restart. Local import avoids a cycle.
        from agents.graph.sqlite_checkpointer import SqliteCheckpointer
        _coin_trading_graph = compile_coin_trading_graph(checkpointer=SqliteCheckpointer())
    return _coin_trading_graph


def reset_coin_trading_graph() -> None:
    """Reset the coin trading graph (useful for testing)."""
    global _coin_trading_graph
    _coin_trading_graph = None


# -------------------------------------------
# Execution Helpers
# -------------------------------------------


async def run_coin_analysis(
    market: str,
    korean_name: Optional[str] = None,
    user_query: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> dict:
    """
    Run a complete coin trading analysis for a market.

    Args:
        market: Market code (e.g., "KRW-BTC")
        korean_name: Korean name of the coin
        user_query: Optional analysis query
        thread_id: Optional thread ID for state persistence

    Returns:
        Final state after analysis (paused at approval)
    """
    import uuid

    graph = get_coin_trading_graph()
    initial_state = create_coin_initial_state(market, korean_name, user_query)

    config = {
        "configurable": {
            "thread_id": thread_id or str(uuid.uuid4()),
        }
    }

    logger.info(
        "coin_analysis_started",
        market=market,
        thread_id=config["configurable"]["thread_id"],
    )

    # Run until interrupt (approval node)
    final_state = None
    async for event in graph.astream(initial_state, config):
        for node_name, node_output in event.items():
            if node_name != "__end__":
                logger.debug(
                    "coin_graph_node_completed",
                    node=node_name,
                    market=market,
                )
                final_state = node_output

    return final_state


async def resume_coin_after_approval(
    thread_id: str,
    approval_status: str,
    user_feedback: Optional[str] = None,
) -> dict:
    """
    Resume coin workflow after human approval decision.

    Args:
        thread_id: Thread ID of the paused workflow
        approval_status: "approved", "rejected", or "modified"
        user_feedback: Optional feedback from human reviewer

    Returns:
        Final state after execution
    """
    graph = get_coin_trading_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    # Update state with approval decision
    update = {
        "approval_status": approval_status,
        "user_feedback": user_feedback,
        "awaiting_approval": False,
    }

    logger.info(
        "coin_approval_received",
        thread_id=thread_id,
        status=approval_status,
    )

    # Inject the decision into the checkpoint, then resume with astream(None).
    # (astream(update) would RESTART the graph from its entry, not resume.)
    await graph.aupdate_state(config, update)
    final_state = None
    async for event in graph.astream(None, config):
        for node_name, node_output in event.items():
            if node_name != "__end__":
                final_state = node_output

    return final_state


# -------------------------------------------
# Graph Visualization
# -------------------------------------------


def get_coin_graph_diagram() -> str:
    """
    Get a text representation of the coin graph structure.

    Returns:
        ASCII diagram of the workflow.
    """
    return """
    Coin Trading Analysis Workflow (Upbit)
    ======================================

    [START]
        │
        ▼
    ┌─────────────────┐
    │ Data Collection │ ─── Fetch from Upbit API
    │   (from Upbit)  │     (ticker, candles, orderbook)
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │   Technical     │ ─── Price patterns, RSI, MACD
    │    Analysis     │     Volume, orderbook depth
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │    Market       │ ─── 24h volume, BTC correlation
    │    Analysis     │     Exchange flows, market cap
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │   Sentiment     │ ─── Fear & Greed, social media
    │    Analysis     │     News, whale activity
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │      Risk       │ ─── Volatility, liquidity risk
    │   Assessment    │     Position sizing (conservative)
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │   Strategic     │ ─── Synthesize & propose
    │    Decision     │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │     Human       │ ◄── INTERRUPT POINT
    │    Approval     │     (HITL Review)
    └────────┬────────┘
             │
        ┌────┴────┬────────┐
        │         │        │
        ▼         ▼        ▼
    [Approved] [Rejected] [Cancel]
        │         │        │
        ▼         ▼        ▼
    ┌────────┐ ┌──────┐  [END]
    │Execute │ │Re-   │
    │ Trade  │ │Analyze│
    └────┬───┘ └───┬──┘
         │         │
         ▼         ▼
      [END]    [Data Collection]
    """
