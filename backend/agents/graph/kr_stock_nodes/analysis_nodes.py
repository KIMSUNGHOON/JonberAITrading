"""
Analysis Nodes for Korean Stock Trading

Contains Technical, Fundamental, and Sentiment analysis nodes.
These nodes wrap the core analysis functions with node-specific
logging, timing, and state management.
"""

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


async def kr_stock_technical_analysis_node(state: dict) -> dict:
    """
    Korean stock technical analysis node.

    Wraps analyze_technical_core with node-specific logging and state management.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "technical_analysis")
    stk_nm = state.get("stk_nm", stk_cd)

    logger.info("node_started", node="kr_stock_technical_analysis", stk_cd=stk_cd)

    # Call core analysis function
    result = await analyze_technical_core(state)

    # Build reasoning message
    signal_descriptions = result.key_factors[:3]
    signals_summary = ", ".join(signal_descriptions) if signal_descriptions else "특이 시그널 없음"
    reasoning = f"[기술적 분석] {stk_nm}: {result.signal.value} (신뢰도: {result.confidence:.0%}) - {signals_summary}"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="kr_stock_technical_analysis",
        stk_cd=stk_cd,
        signal=result.signal.value,
        confidence=round(result.confidence, 2),
        duration_ms=round(duration_ms, 2),
    )

    return {
        "technical_analysis": result.model_dump(),
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.TECHNICAL,
    }


async def kr_stock_fundamental_analysis_node(state: dict) -> dict:
    """
    Korean stock fundamental analysis node.

    Wraps analyze_fundamental_core with node-specific logging and state management.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "fundamental_analysis")
    stk_nm = state.get("stk_nm", stk_cd)

    logger.info("node_started", node="kr_stock_fundamental_analysis", stk_cd=stk_cd)

    # Call core analysis function
    result = await analyze_fundamental_core(state)

    # Build reasoning message
    reasoning = f"[기본적 분석] {stk_nm}: {result.signal.value} (신뢰도: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="kr_stock_fundamental_analysis",
        stk_cd=stk_cd,
        signal=result.signal.value,
        confidence=round(result.confidence, 2),
        duration_ms=round(duration_ms, 2),
    )

    return {
        "fundamental_analysis": result.model_dump(),
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.FUNDAMENTAL,
    }


async def kr_stock_sentiment_analysis_node(state: dict) -> dict:
    """
    Korean stock sentiment analysis node.

    Wraps analyze_sentiment_core with node-specific logging and state management.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "sentiment_analysis")
    stk_nm = state.get("stk_nm", stk_cd)

    logger.info("node_started", node="kr_stock_sentiment_analysis", stk_cd=stk_cd)

    # Call core analysis function
    result = await analyze_sentiment_core(state)

    # Build reasoning message
    news_count = result.signals.get("news_count", 0)
    reasoning = f"[시장심리 분석] {stk_nm}: {result.signal.value} (신뢰도: {result.confidence:.0%}, 뉴스 {news_count}건)"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="kr_stock_sentiment_analysis",
        stk_cd=stk_cd,
        signal=result.signal.value,
        confidence=round(result.confidence, 2),
        news_count=news_count,
        duration_ms=round(duration_ms, 2),
    )

    return {
        "sentiment_analysis": result.model_dump(),
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.SENTIMENT,
    }
