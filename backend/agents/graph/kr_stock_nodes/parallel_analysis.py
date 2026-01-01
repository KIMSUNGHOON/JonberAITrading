"""
Parallel Analysis Node for Korean Stock Trading

Executes Technical, Fundamental, and Sentiment analyses in parallel
using shared core analysis functions.
"""

import asyncio
import time

import structlog
from langchain_core.messages import AIMessage

from agents.graph.kr_stock_state import (
    KRStockAnalysisStage,
    add_kr_stock_reasoning_log,
)
from .helpers import (
    _get_stk_cd_safely,
    analyze_technical_core,
    analyze_fundamental_core,
    analyze_sentiment_core,
)

logger = structlog.get_logger()


async def kr_stock_parallel_analysis_node(state: dict) -> dict:
    """
    Execute Technical, Fundamental, and Sentiment analyses in parallel.

    This node combines three independent analysis stages into a single
    parallel execution, reducing total analysis time by ~50%.

    Uses shared core analysis functions from helpers.py to avoid
    code duplication with sequential analysis nodes.

    Flow:
    1. Run Technical, Fundamental, Sentiment analyses concurrently
    2. Merge all results into state
    3. Continue to Risk Assessment

    Performance:
    - Sequential: ~6-9 seconds (2-3s each)
    - Parallel: ~3 seconds (max of individual times)
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "parallel_analysis")
    stk_nm = state.get("stk_nm", stk_cd)

    logger.info(
        "node_started",
        node="kr_stock_parallel_analysis",
        stk_cd=stk_cd,
    )

    try:
        # Execute all three analyses in parallel using core functions
        results = await asyncio.gather(
            _run_technical_analysis(state),
            _run_fundamental_analysis(state),
            _run_sentiment_analysis(state),
            return_exceptions=True,
        )

        # Process results
        merged_state = {}
        reasoning_parts = []
        success_count = 0

        # Technical Analysis
        if isinstance(results[0], Exception):
            logger.error("parallel_technical_failed", error=str(results[0]))
        elif results[0]:
            merged_state.update(results[0])
            if "technical_analysis" in results[0]:
                tech = results[0]["technical_analysis"]
                reasoning_parts.append(
                    f"[기술적] {tech.get('signal', 'N/A')} ({tech.get('confidence', 0):.0%})"
                )
            success_count += 1

        # Fundamental Analysis
        if isinstance(results[1], Exception):
            logger.error("parallel_fundamental_failed", error=str(results[1]))
        elif results[1]:
            merged_state.update(results[1])
            if "fundamental_analysis" in results[1]:
                fund = results[1]["fundamental_analysis"]
                reasoning_parts.append(
                    f"[펀더멘탈] {fund.get('signal', 'N/A')} ({fund.get('confidence', 0):.0%})"
                )
            success_count += 1

        # Sentiment Analysis
        if isinstance(results[2], Exception):
            logger.error("parallel_sentiment_failed", error=str(results[2]))
        elif results[2]:
            merged_state.update(results[2])
            if "sentiment_analysis" in results[2]:
                sent = results[2]["sentiment_analysis"]
                reasoning_parts.append(
                    f"[심리] {sent.get('signal', 'N/A')} ({sent.get('confidence', 0):.0%})"
                )
            success_count += 1

        duration_ms = (time.perf_counter() - start_time) * 1000
        reasoning = f"[병렬 분석] {stk_nm}: {', '.join(reasoning_parts)} ({duration_ms:.0f}ms)"

        logger.info(
            "node_completed",
            node="kr_stock_parallel_analysis",
            stk_cd=stk_cd,
            success_count=success_count,
            duration_ms=round(duration_ms, 2),
        )

        # Combine reasoning logs
        all_reasoning = state.get("reasoning_log", [])
        all_reasoning.append(reasoning)

        merged_state["reasoning_log"] = all_reasoning
        merged_state["messages"] = [AIMessage(content=reasoning)]
        merged_state["current_stage"] = KRStockAnalysisStage.SENTIMENT  # Ready for Risk

        return merged_state

    except Exception as e:
        error_msg = f"병렬 분석 실패 ({stk_cd}): {str(e)}"
        logger.error("kr_stock_parallel_analysis_failed", stk_cd=stk_cd, error=str(e))
        return {
            "error": error_msg,
            "reasoning_log": add_kr_stock_reasoning_log(state, f"[오류] {error_msg}"),
            "current_stage": KRStockAnalysisStage.COMPLETE,
        }


async def _run_technical_analysis(state: dict) -> dict:
    """
    Run technical analysis for parallel execution.

    Wraps analyze_technical_core and returns result dict.
    """
    result = await analyze_technical_core(state)
    return {"technical_analysis": result.model_dump()}


async def _run_fundamental_analysis(state: dict) -> dict:
    """
    Run fundamental analysis for parallel execution.

    Wraps analyze_fundamental_core and returns result dict.
    """
    result = await analyze_fundamental_core(state)
    return {"fundamental_analysis": result.model_dump()}


async def _run_sentiment_analysis(state: dict) -> dict:
    """
    Run sentiment analysis for parallel execution.

    Wraps analyze_sentiment_core and returns result dict.
    """
    result = await analyze_sentiment_core(state)
    return {"sentiment_analysis": result.model_dump()}
