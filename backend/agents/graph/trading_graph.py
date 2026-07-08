"""
Main LangGraph Assembly for Trading Agent

Assembles all nodes into a complete trading workflow with:
- Task decomposition
- Parallel/sequential analysis
- Human-in-the-loop approval
- Trade execution
"""

from typing import Optional

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from agents.graph.nodes import (
    execution_node,
    fundamental_analysis_node,
    human_approval_node,
    re_analyze_node,
    risk_assessment_node,
    sentiment_analysis_node,
    should_continue_to_execution,
    strategic_decision_node,
    task_decomposition_node,
    technical_analysis_node,
)
from agents.graph.state import TradingState, create_initial_state
from agents.graph.graph_factory import build_analysis_graph, compile_analysis_graph

logger = structlog.get_logger()


def create_trading_graph() -> StateGraph:
    """
    Create the main trading workflow graph.

    Workflow Stages:
    1. Task Decomposition - Break down analysis into subtasks
    2. Analysis Phase (Sequential for now, can be parallelized):
       - Technical Analysis
       - Fundamental Analysis
       - Sentiment Analysis
       - Risk Assessment
    3. Strategic Decision - Synthesize and propose trade
    4. Human Approval - HITL interrupt point
    5. Execution - Execute approved trades

    Flow:
    ```
    [Start]
        ↓
    [Decompose] → [Technical] → [Fundamental] → [Sentiment]
                                                     ↓
                                               [Risk] → [Decision]
                                                            ↓
                                                      [Approval] ← INTERRUPT
                                                            ↓
                                                    ┌──────┴──────┐
                                                    ↓             ↓
                                               [Execute]       [End]
                                                    ↓
                                                 [End]
    ```
    """
    # Topology is shared across all 3 market stacks; see graph_factory.
    return build_analysis_graph(
        TradingState,
        entry_node=("decompose", task_decomposition_node),
        analysis_nodes=[
            ("technical", technical_analysis_node),
            ("fundamental", fundamental_analysis_node),
            ("sentiment", sentiment_analysis_node),
            ("risk", risk_assessment_node),
        ],
        decision_node=strategic_decision_node,
        approval_node=human_approval_node,
        re_analyze_node=re_analyze_node,
        execute_node=execution_node,
        cond_fn=should_continue_to_execution,
    )


def compile_trading_graph(
    checkpointer: Optional[MemorySaver] = None,
    interrupt_before_approval: bool = True,
) -> StateGraph:
    """
    Compile the trading graph with checkpointing support.

    Args:
        checkpointer: LangGraph checkpointer for state persistence.
                     Uses MemorySaver by default for development.
        interrupt_before_approval: If True, pause before human approval node.

    Returns:
        Compiled StateGraph ready for execution.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    compiled = compile_analysis_graph(
        create_trading_graph(),
        checkpointer,
        interrupt_before_approval=interrupt_before_approval,
    )

    logger.info(
        "trading_graph_compiled",
        interrupt_before=["approval"] if interrupt_before_approval else [],
        checkpointer_type=type(checkpointer).__name__,
    )

    return compiled


# -------------------------------------------
# Singleton Pattern
# -------------------------------------------

_trading_graph: Optional[StateGraph] = None


def get_trading_graph() -> StateGraph:
    """
    Get or create the singleton trading graph.

    Returns:
        Compiled trading graph ready for execution.
    """
    global _trading_graph
    if _trading_graph is None:
        _trading_graph = compile_trading_graph()
    return _trading_graph


def reset_trading_graph() -> None:
    """Reset the trading graph (useful for testing)."""
    global _trading_graph
    _trading_graph = None


# -------------------------------------------
# Execution Helpers
# -------------------------------------------


async def run_analysis(
    ticker: str,
    user_query: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> dict:
    """
    Run a complete trading analysis for a ticker.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        user_query: Optional analysis query
        thread_id: Optional thread ID for state persistence

    Returns:
        Final state after analysis (paused at approval)
    """
    import uuid

    graph = get_trading_graph()
    initial_state = create_initial_state(ticker, user_query)

    config = {
        "configurable": {
            "thread_id": thread_id or str(uuid.uuid4()),
        }
    }

    logger.info(
        "analysis_started",
        ticker=ticker,
        thread_id=config["configurable"]["thread_id"],
    )

    # Run until interrupt (approval node)
    final_state = None
    async for event in graph.astream(initial_state, config):
        # Each event is a dict with node_name: node_output
        for node_name, node_output in event.items():
            if node_name != "__end__":
                logger.debug(
                    "graph_node_completed",
                    node=node_name,
                    ticker=ticker,
                )
                final_state = node_output

    return final_state


async def resume_after_approval(
    thread_id: str,
    approval_status: str,
    user_feedback: Optional[str] = None,
) -> dict:
    """
    Resume workflow after human approval decision.

    Args:
        thread_id: Thread ID of the paused workflow
        approval_status: "approved", "rejected", or "modified"
        user_feedback: Optional feedback from human reviewer

    Returns:
        Final state after execution
    """
    graph = get_trading_graph()

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
        "approval_received",
        thread_id=thread_id,
        status=approval_status,
    )

    # Resume from interrupt with updated state
    final_state = None
    async for event in graph.astream(update, config):
        for node_name, node_output in event.items():
            if node_name != "__end__":
                final_state = node_output

    return final_state


# -------------------------------------------
# Graph Visualization (for debugging)
# -------------------------------------------


def get_graph_diagram() -> str:
    """
    Get a text representation of the graph structure.

    Returns:
        ASCII diagram of the workflow.
    """
    return """
    Trading Analysis Workflow
    =========================

    [START]
        │
        ▼
    ┌─────────────────┐
    │ Task Decompose  │ ─── Break down analysis tasks
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │   Technical     │ ─── Price patterns, indicators
    │    Analysis     │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Fundamental    │ ─── Financials, valuation
    │    Analysis     │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │   Sentiment     │ ─── News, social media
    │    Analysis     │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │      Risk       │ ─── Risk assessment, sizing
    │   Assessment    │
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
        ┌────┴────┐
        │         │
        ▼         ▼
    [Approved] [Rejected]
        │         │
        ▼         ▼
    ┌────────┐   [END]
    │Execute │
    │ Trade  │
    └────┬───┘
         │
         ▼
      [END]
    """
