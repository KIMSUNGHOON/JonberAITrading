"""
Main LangGraph Assembly for Korean Stock Trading Agent

Assembles all nodes into a complete Korean stock trading workflow with:
- Market data collection from Kiwoom Securities API
- Sequential analysis (technical, fundamental, sentiment, risk)
- Human-in-the-loop approval
- Trade execution via Kiwoom REST API
"""

from typing import Optional

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agents.graph.kr_stock_nodes import (
    kr_stock_data_collection_node,
    kr_stock_execution_node,
    kr_stock_fundamental_analysis_node,
    kr_stock_human_approval_node,
    kr_stock_re_analyze_node,
    kr_stock_risk_assessment_node,
    kr_stock_sentiment_analysis_node,
    kr_stock_strategic_decision_node,
    kr_stock_technical_analysis_node,
    should_continue_kr_stock_execution,
)
from agents.graph.kr_stock_state import KRStockTradingState, create_kr_stock_initial_state

logger = structlog.get_logger()


def create_kr_stock_trading_graph() -> StateGraph:
    """
    Create the main Korean stock trading workflow graph.

    Workflow Stages:
    1. Data Collection - Fetch market data from Kiwoom API
    2. Analysis Phase (Sequential):
       - Technical Analysis (charts, indicators, orderbook)
       - Fundamental Analysis (PER, PBR, EPS, etc.)
       - Sentiment Analysis (news, disclosures)
       - Risk Assessment (volatility, position sizing)
    3. Strategic Decision - Synthesize and propose trade
    4. Human Approval - HITL interrupt point
    5. Execution - Execute approved trades via Kiwoom API

    Flow:
    ```
    [Start]
        |
    [Data Collection] -> [Technical] -> [Fundamental] -> [Sentiment]
                                                              |
                                                          [Risk] -> [Decision]
                                                                         |
                                                                   [Approval] <- INTERRUPT
                                                                         |
                                                                 +-------+-------+
                                                                 |               |
                                                            [Execute]     [Re-analyze]
                                                                 |               |
                                                              [End]    [Data Collection]
    ```
    """
    # Initialize graph with KRStockTradingState TypedDict
    workflow = StateGraph(KRStockTradingState)

    # -------------------------------------------
    # Add Nodes
    # -------------------------------------------

    # Stage 1: Data Collection from Kiwoom
    workflow.add_node("data_collection", kr_stock_data_collection_node)

    # Stage 2: Analysis (Sequential)
    workflow.add_node("technical", kr_stock_technical_analysis_node)
    workflow.add_node("fundamental", kr_stock_fundamental_analysis_node)
    workflow.add_node("sentiment", kr_stock_sentiment_analysis_node)
    workflow.add_node("risk", kr_stock_risk_assessment_node)

    # Stage 3: Strategic Decision
    workflow.add_node("decision", kr_stock_strategic_decision_node)

    # Stage 4: Human Approval
    workflow.add_node("approval", kr_stock_human_approval_node)

    # Stage 4.5: Re-analysis (when user rejects)
    workflow.add_node("re_analyze", kr_stock_re_analyze_node)

    # Stage 5: Execution
    workflow.add_node("execute", kr_stock_execution_node)

    # -------------------------------------------
    # Define Edges
    # -------------------------------------------

    # Set entry point
    workflow.set_entry_point("data_collection")

    # Sequential analysis flow
    workflow.add_edge("data_collection", "technical")
    workflow.add_edge("technical", "fundamental")
    workflow.add_edge("fundamental", "sentiment")
    workflow.add_edge("sentiment", "risk")
    workflow.add_edge("risk", "decision")
    workflow.add_edge("decision", "approval")

    # Conditional edge after approval
    workflow.add_conditional_edges(
        "approval",
        should_continue_kr_stock_execution,
        {
            "execute": "execute",
            "re_analyze": "re_analyze",
            "end": END,
        },
    )

    # Re-analysis loops back to data collection
    workflow.add_edge("re_analyze", "data_collection")

    # Execution leads to end
    workflow.add_edge("execute", END)

    return workflow


def compile_kr_stock_trading_graph(
    checkpointer: Optional[MemorySaver] = None,
    interrupt_before_approval: bool = True,
) -> StateGraph:
    """
    Compile the Korean stock trading graph with checkpointing support.

    Args:
        checkpointer: LangGraph checkpointer for state persistence.
        interrupt_before_approval: If True, pause before human approval node.

    Returns:
        Compiled StateGraph ready for execution.
    """
    workflow = create_kr_stock_trading_graph()

    if checkpointer is None:
        checkpointer = MemorySaver()

    # Configure interrupts for HITL
    interrupt_before = ["approval"] if interrupt_before_approval else []

    compiled = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
    )

    logger.info(
        "kr_stock_trading_graph_compiled",
        interrupt_before=interrupt_before,
        checkpointer_type=type(checkpointer).__name__,
    )

    return compiled


# -------------------------------------------
# Singleton Pattern
# -------------------------------------------

_kr_stock_trading_graph: Optional[StateGraph] = None


def get_kr_stock_trading_graph() -> StateGraph:
    """
    Get or create the singleton Korean stock trading graph.

    Returns:
        Compiled trading graph ready for execution.
    """
    global _kr_stock_trading_graph
    if _kr_stock_trading_graph is None:
        _kr_stock_trading_graph = compile_kr_stock_trading_graph()
    return _kr_stock_trading_graph


def reset_kr_stock_trading_graph() -> None:
    """Reset the Korean stock trading graph (useful for testing)."""
    global _kr_stock_trading_graph
    _kr_stock_trading_graph = None


# -------------------------------------------
# Execution Helpers
# -------------------------------------------


async def run_kr_stock_analysis(
    stk_cd: str,
    stk_nm: Optional[str] = None,
    user_query: Optional[str] = None,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict:
    """
    Run a complete Korean stock trading analysis for a stock.

    Args:
        stk_cd: Stock code (e.g., "005930" for Samsung Electronics)
        stk_nm: Stock name (e.g., "삼성전자")
        user_query: Optional analysis query
        thread_id: Optional thread ID for state persistence
        session_id: Optional session ID for tracking

    Returns:
        Final state after analysis (paused at approval)
    """
    import uuid

    graph = get_kr_stock_trading_graph()
    initial_state = create_kr_stock_initial_state(stk_cd, stk_nm, user_query, session_id)

    config = {
        "configurable": {
            "thread_id": thread_id or str(uuid.uuid4()),
        }
    }

    logger.info(
        "kr_stock_analysis_started",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        thread_id=config["configurable"]["thread_id"],
    )

    # Run until interrupt (approval node)
    final_state = None
    async for event in graph.astream(initial_state, config):
        for node_name, node_output in event.items():
            if node_name != "__end__":
                logger.debug(
                    "kr_stock_graph_node_completed",
                    node=node_name,
                    stk_cd=stk_cd,
                )
                final_state = node_output

    return final_state


async def resume_kr_stock_after_approval(
    thread_id: str,
    approval_status: str,
    user_feedback: Optional[str] = None,
    quantity: Optional[int] = None,
) -> dict:
    """
    Resume Korean stock workflow after human approval decision.

    Args:
        thread_id: Thread ID of the paused workflow
        approval_status: "approved", "rejected", or "modified"
        user_feedback: Optional feedback from human reviewer
        quantity: Optional quantity override (number of shares)

    Returns:
        Final state after execution
    """
    graph = get_kr_stock_trading_graph()

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

    # Optionally update quantity in proposal
    # This would need to be handled in the execution node

    logger.info(
        "kr_stock_approval_received",
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
# Graph Visualization
# -------------------------------------------


def get_kr_stock_graph_diagram() -> str:
    """
    Get a text representation of the Korean stock graph structure.

    Returns:
        ASCII diagram of the workflow.
    """
    return """
    Korean Stock Trading Analysis Workflow (Kiwoom Securities)
    ===========================================================

    [START]
        |
        v
    +---------------------+
    |   Data Collection   | --- Kiwoom API 호출
    |   (Kiwoom API)      |     (종목정보, 일봉, 호가)
    +---------+-----------+
              |
              v
    +---------------------+
    |     Technical       | --- 기술적 분석
    |      Analysis       |     (RSI, MACD, 이동평균, 볼린저)
    +---------+-----------+
              |
              v
    +---------------------+
    |    Fundamental      | --- 기본적 분석
    |      Analysis       |     (PER, PBR, EPS, BPS)
    +---------+-----------+
              |
              v
    +---------------------+
    |     Sentiment       | --- 시장심리 분석
    |      Analysis       |     (뉴스, 공시, 수급)
    +---------+-----------+
              |
              v
    +---------------------+
    |        Risk         | --- 리스크 평가
    |     Assessment      |     (변동성, 포지션 사이징)
    +---------+-----------+
              |
              v
    +---------------------+
    |     Strategic       | --- 종합 분석 & 제안
    |      Decision       |
    +---------+-----------+
              |
              v
    +---------------------+
    |       Human         | <-- 인터럽트 포인트
    |      Approval       |     (HITL 검토)
    +---------+-----------+
              |
         +----+----+----------+
         |         |          |
         v         v          v
    [승인]     [거부]      [취소]
         |         |          |
         v         v          v
    +--------+ +------+    [END]
    |  주문  | | 재   |
    |  실행  | | 분석 |
    +---+----+ +---+--+
        |         |
        v         v
     [END]    [Data Collection]

    주요 기능:
    - 모의투자 / 실거래 지원 (KIWOOM_IS_MOCK 설정)
    - 이용약관 제11조 Rate Limit 준수 (초당 5건)
    - 메모리 캐시로 API 호출 최소화
    - 자동 주문번호 발급 및 체결 확인
    """
