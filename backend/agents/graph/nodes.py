"""
LangGraph Node Functions for Trading Workflow

Each node function receives the current state and returns state updates.
Nodes are executed in sequence or parallel as defined in the graph.
"""

import time
import uuid
from datetime import datetime
from typing import Literal

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.graph.state import (
    AnalysisResult,
    AnalysisStage,
    Position,
    SignalType,
    SubTask,
    TradeAction,
    TradeProposal,
    add_reasoning_log,
    calculate_consensus_signal,
    get_all_analyses,
)
from agents.llm_provider import get_llm_provider
from agents.tools.market_data import (
    calculate_technical_indicators,
    format_market_data_for_llm,
    get_current_price,
    get_market_data,
    get_ticker_info,
)
from agents.tools.write_todos import decompose_task, format_tasks_for_log

logger = structlog.get_logger()


def _get_ticker_safely(state: dict, node_name: str) -> str:
    """Safely get ticker from state with detailed error logging."""
    ticker = state.get("ticker")
    if not ticker:
        logger.error(
            "state_missing_ticker",
            node=node_name,
            state_keys=list(state.keys()),
            state_preview={k: str(v)[:100] for k, v in list(state.items())[:5]},
        )
        raise ValueError(f"State missing 'ticker' in {node_name}. State keys: {list(state.keys())}")
    return ticker


# -------------------------------------------
# Stage 1A: Task Decomposition
# -------------------------------------------


async def task_decomposition_node(state: dict) -> dict:
    """
    Decompose the analysis task into subtasks for subagents.
    Uses the write_todos pattern from DeepAgents.
    """
    start_time = time.perf_counter()

    # Safe ticker access with detailed error logging
    ticker = _get_ticker_safely(state, "task_decomposition")
    query = state.get("user_query", f"Analyze {ticker} for trading opportunity")

    logger.info(
        "node_started",
        node="task_decomposition",
        ticker=ticker,
        query_preview=query[:100] if query else None,
    )

    # Decompose task into subtasks
    todos = await decompose_task(ticker, query, use_llm=True)

    logger.debug(
        "task_decomposition_result",
        ticker=ticker,
        task_count=len(todos),
        tasks=[t.task[:50] for t in todos],
    )

    # Format for log
    tasks_log = format_tasks_for_log(todos)
    reasoning = f"[Task Decomposition] Breaking down analysis for {ticker}:\n{tasks_log}"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="task_decomposition",
        ticker=ticker,
        duration_ms=round(duration_ms, 2),
    )

    return {
        "todos": [t.model_dump() for t in todos],
        "reasoning_log": add_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": AnalysisStage.TECHNICAL,
    }


# -------------------------------------------
# Stage 1B: Technical Analysis
# -------------------------------------------

TECHNICAL_ANALYST_PROMPT = """You are an expert technical analyst. Analyze the provided market data and identify:

1. **Trend Analysis**: Current trend direction and strength
2. **Key Levels**: Support and resistance levels
3. **Indicators**: RSI, MACD, Moving Averages interpretation
4. **Chart Patterns**: Any identifiable patterns (if discernible)
5. **Volume Analysis**: Volume trends and significance
6. **Entry/Exit Points**: Suggested levels based on technicals

Based on your analysis, provide:
- A trading signal: STRONG_BUY, BUY, HOLD, SELL, or STRONG_SELL
- A confidence score from 0.0 to 1.0
- Key factors supporting your view (3-5 bullet points)

Be specific with numbers and levels. Focus on actionable insights."""


async def technical_analysis_node(state: dict) -> dict:
    """
    Technical analysis subagent.
    Analyzes price patterns, indicators, and trends.
    """
    start_time = time.perf_counter()
    ticker = _get_ticker_safely(state, "technical_analysis")
    llm = get_llm_provider()

    logger.info("node_started", node="technical_analysis", ticker=ticker)

    # Fetch market data
    logger.debug("fetching_market_data", ticker=ticker, period="3mo")
    df = await get_market_data(ticker, period="3mo")
    market_context = format_market_data_for_llm(df, ticker)
    indicators = calculate_technical_indicators(df)

    logger.debug(
        "market_data_fetched",
        ticker=ticker,
        data_points=len(df) if df is not None else 0,
        indicators_keys=list(indicators.keys()) if indicators else [],
    )

    messages = [
        SystemMessage(content=TECHNICAL_ANALYST_PROMPT),
        HumanMessage(content=f"Analyze {ticker}:\n\n{market_context}"),
    ]

    logger.debug("llm_request", node="technical_analysis", message_count=len(messages))
    llm_start = time.perf_counter()
    response = await llm.generate(messages)
    llm_duration = (time.perf_counter() - llm_start) * 1000
    logger.debug(
        "llm_response",
        node="technical_analysis",
        response_length=len(response),
        duration_ms=round(llm_duration, 2),
    )

    # Determine signal from indicators
    signal = _determine_technical_signal(indicators)

    result = AnalysisResult(
        agent_type="technical",
        ticker=ticker,
        signal=signal,
        confidence=0.75,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "trend": indicators.get("trend", "neutral"),
            "rsi": indicators.get("rsi"),
            "macd": indicators.get("macd", {}).get("histogram"),
            "support": indicators.get("support"),
            "resistance": indicators.get("resistance"),
        },
    )

    reasoning = f"[Technical Analysis] {ticker}: {signal.value} (Confidence: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="technical_analysis",
        ticker=ticker,
        signal=signal.value,
        confidence=result.confidence,
        duration_ms=round(duration_ms, 2),
    )

    return {
        "technical_analysis": result,
        "reasoning_log": add_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": AnalysisStage.FUNDAMENTAL,
    }


# -------------------------------------------
# Stage 1C: Fundamental Analysis
# -------------------------------------------

FUNDAMENTAL_ANALYST_PROMPT = """You are an expert fundamental analyst. Evaluate the company based on:

1. **Valuation Metrics**: P/E, P/B, EV/EBITDA relative to peers and history
2. **Financial Health**: Balance sheet strength, debt levels, cash position
3. **Growth Metrics**: Revenue growth, earnings growth, margin trends
4. **Competitive Position**: Market share, moat, industry dynamics
5. **Catalysts & Risks**: Upcoming events, regulatory issues, macro factors

Based on your analysis, provide:
- A trading signal: STRONG_BUY, BUY, HOLD, SELL, or STRONG_SELL
- A confidence score from 0.0 to 1.0
- Key factors supporting your view (3-5 bullet points)

Focus on intrinsic value and business quality."""


async def fundamental_analysis_node(state: dict) -> dict:
    """
    Fundamental analysis subagent.
    Analyzes company financials, valuation, and business metrics.
    """
    start_time = time.perf_counter()
    ticker = _get_ticker_safely(state, "fundamental_analysis")
    llm = get_llm_provider()

    logger.info("node_started", node="fundamental_analysis", ticker=ticker)

    # Fetch company info
    info = await get_ticker_info(ticker)
    logger.debug("ticker_info_fetched", ticker=ticker, info_keys=list(info.keys())[:10] if info else [])

    # Format fundamental data
    fundamental_context = _format_fundamental_data(info)

    messages = [
        SystemMessage(content=FUNDAMENTAL_ANALYST_PROMPT),
        HumanMessage(content=f"Analyze fundamentals for {ticker}:\n\n{fundamental_context}"),
    ]

    logger.debug("llm_request", node="fundamental_analysis", message_count=len(messages))
    llm_start = time.perf_counter()
    response = await llm.generate(messages)
    llm_duration = (time.perf_counter() - llm_start) * 1000
    logger.debug("llm_response", node="fundamental_analysis", response_length=len(response), duration_ms=round(llm_duration, 2))

    # Determine signal from fundamentals
    signal = _determine_fundamental_signal(info)

    result = AnalysisResult(
        agent_type="fundamental",
        ticker=ticker,
        signal=signal,
        confidence=0.70,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "pe_ratio": info.get("trailingPE"),
            "pb_ratio": info.get("priceToBook"),
            "market_cap": info.get("marketCap"),
            "beta": info.get("beta"),
        },
    )

    reasoning = f"[Fundamental Analysis] {ticker}: {signal.value} (Confidence: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="fundamental_analysis", ticker=ticker, signal=signal.value, duration_ms=round(duration_ms, 2))

    return {
        "fundamental_analysis": result,
        "reasoning_log": add_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": AnalysisStage.SENTIMENT,
    }


# -------------------------------------------
# Stage 1D: Sentiment Analysis
# -------------------------------------------

SENTIMENT_ANALYST_PROMPT = """You are a sentiment analysis expert. Evaluate market sentiment based on:

1. **News Sentiment**: Recent news tone and impact
2. **Social Media**: Retail investor sentiment, trending discussions
3. **Analyst Views**: Recent rating changes, price target adjustments
4. **Institutional Activity**: Large holder changes, 13F filings
5. **Options Flow**: Unusual options activity, put/call ratios
6. **Insider Trading**: Recent insider buys/sells

Based on your analysis, provide:
- A trading signal: STRONG_BUY, BUY, HOLD, SELL, or STRONG_SELL
- A confidence score from 0.0 to 1.0
- Key factors supporting your view (3-5 bullet points)

Note: In this simulation, provide your best assessment based on general market knowledge."""


async def sentiment_analysis_node(state: dict) -> dict:
    """
    Sentiment analysis subagent.
    Analyzes market sentiment from various sources.
    """
    start_time = time.perf_counter()
    ticker = _get_ticker_safely(state, "sentiment_analysis")
    llm = get_llm_provider()

    logger.info("node_started", node="sentiment_analysis", ticker=ticker)

    # Get company info for context
    info = await get_ticker_info(ticker)

    messages = [
        SystemMessage(content=SENTIMENT_ANALYST_PROMPT),
        HumanMessage(
            content=f"Analyze sentiment for {ticker} ({info.get('shortName', ticker)}) "
            f"in the {info.get('sector', 'unknown')} sector."
        ),
    ]

    logger.debug("llm_request", node="sentiment_analysis", message_count=len(messages))
    llm_start = time.perf_counter()
    response = await llm.generate(messages)
    llm_duration = (time.perf_counter() - llm_start) * 1000
    logger.debug("llm_response", node="sentiment_analysis", response_length=len(response), duration_ms=round(llm_duration, 2))

    # Default to neutral sentiment (would be parsed from real data)
    signal = SignalType.HOLD

    result = AnalysisResult(
        agent_type="sentiment",
        ticker=ticker,
        signal=signal,
        confidence=0.60,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "news_sentiment": "neutral",
            "social_sentiment": "neutral",
            "analyst_rating": "hold",
        },
    )

    reasoning = f"[Sentiment Analysis] {ticker}: {signal.value} (Confidence: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="sentiment_analysis", ticker=ticker, signal=signal.value, duration_ms=round(duration_ms, 2))

    return {
        "sentiment_analysis": result,
        "reasoning_log": add_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": AnalysisStage.RISK,
    }


# -------------------------------------------
# Stage 1E: Risk Assessment
# -------------------------------------------

RISK_ASSESSOR_PROMPT = """You are a risk management expert. Based on the analyses provided, evaluate:

1. **Volatility Risk**: Historical and implied volatility assessment
2. **Downside Risk**: Maximum drawdown scenarios, stop-loss levels
3. **Position Sizing**: Recommended position size (% of portfolio)
4. **Correlation Risk**: Portfolio concentration, sector exposure
5. **Event Risk**: Upcoming events that could impact position
6. **Exit Strategy**: Take-profit levels, trailing stop recommendations

Provide:
- An overall risk score from 0.0 (low risk) to 1.0 (high risk)
- Recommended stop-loss level
- Recommended position size (1-10% of portfolio)
- Key risk factors (3-5 bullet points)

Be conservative and prioritize capital preservation."""


async def risk_assessment_node(state: dict) -> dict:
    """
    Risk assessment subagent.
    Evaluates portfolio risk and position sizing.
    """
    start_time = time.perf_counter()
    ticker = _get_ticker_safely(state, "risk_assessment")
    llm = get_llm_provider()

    logger.info("node_started", node="risk_assessment", ticker=ticker)

    # Gather all previous analyses
    analyses = get_all_analyses(state)
    logger.debug("analyses_gathered", ticker=ticker, analysis_count=len(analyses))
    analyses_context = "\n\n".join(a.to_context_string() for a in analyses)

    # Get current price for stop-loss calculation
    current_price = await get_current_price(ticker)
    logger.debug("current_price_fetched", ticker=ticker, price=current_price)

    messages = [
        SystemMessage(content=RISK_ASSESSOR_PROMPT),
        HumanMessage(
            content=f"Assess risk for {ticker} (Current Price: ${current_price:.2f}):\n\n{analyses_context}"
        ),
    ]

    logger.debug("llm_request", node="risk_assessment", message_count=len(messages))
    llm_start = time.perf_counter()
    response = await llm.generate(messages)
    llm_duration = (time.perf_counter() - llm_start) * 1000
    logger.debug("llm_response", node="risk_assessment", response_length=len(response), duration_ms=round(llm_duration, 2))

    # Calculate risk score based on analysis disagreement
    risk_score = _calculate_risk_score(analyses)

    result = AnalysisResult(
        agent_type="risk",
        ticker=ticker,
        signal=SignalType.HOLD,
        confidence=0.80,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "risk_score": risk_score,
            "max_position_pct": 5.0 if risk_score < 0.5 else 3.0,
            "suggested_stop_loss": round(current_price * 0.95, 2),
            "suggested_take_profit": round(current_price * 1.10, 2),
        },
    )

    reasoning = f"[Risk Assessment] {ticker}: Risk Score {risk_score:.0%}, Max Position {result.signals['max_position_pct']}%"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="risk_assessment", ticker=ticker, risk_score=risk_score, duration_ms=round(duration_ms, 2))

    return {
        "risk_assessment": result,
        "reasoning_log": add_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": AnalysisStage.SYNTHESIS,
    }


# -------------------------------------------
# Stage 1F: Strategic Decision (Synthesis)
# -------------------------------------------

STRATEGIC_DECISION_PROMPT = """You are a senior portfolio manager. Based on all analyses provided, make a final trading decision.

Synthesize the findings from:
- Technical Analysis: Price patterns and indicators
- Fundamental Analysis: Company valuation and financials
- Sentiment Analysis: Market mood and news
- Risk Assessment: Risk factors and position sizing

Your decision should:
1. Clearly state BUY, SELL, or HOLD
2. If BUY/SELL, specify quantity and price levels
3. Provide clear rationale weighing all factors
4. Present both bull and bear cases
5. Include specific entry, stop-loss, and take-profit levels

Be decisive but prudent. If signals conflict significantly, HOLD may be appropriate."""


async def strategic_decision_node(state: dict) -> dict:
    """
    Synthesize all analyses into a trade proposal.
    This is where the final decision is made before human approval.
    """
    start_time = time.perf_counter()
    ticker = _get_ticker_safely(state, "strategic_decision")
    llm = get_llm_provider()

    logger.info("node_started", node="strategic_decision", ticker=ticker)

    # Collect all analyses
    analyses = get_all_analyses(state)
    logger.debug("synthesizing_analyses", ticker=ticker, analysis_count=len(analyses))
    analyses_context = "\n\n".join(a.to_context_string() for a in analyses)

    # Calculate consensus
    consensus_signal, avg_confidence = calculate_consensus_signal(analyses)
    logger.debug("consensus_calculated", ticker=ticker, signal=consensus_signal.value, confidence=avg_confidence)

    messages = [
        SystemMessage(content=STRATEGIC_DECISION_PROMPT),
        HumanMessage(
            content=f"Make trading decision for {ticker}:\n\n"
            f"Consensus Signal: {consensus_signal.value} (Avg Confidence: {avg_confidence:.0%})\n\n"
            f"{analyses_context}"
        ),
    ]

    logger.debug("llm_request", node="strategic_decision", message_count=len(messages))
    llm_start = time.perf_counter()
    response = await llm.generate(messages)
    llm_duration = (time.perf_counter() - llm_start) * 1000
    logger.debug("llm_response", node="strategic_decision", response_length=len(response), duration_ms=round(llm_duration, 2))

    # Determine action from consensus
    action = _signal_to_action(consensus_signal)

    # Get risk parameters
    risk = state.get("risk_assessment")
    risk_signals = risk.signals if risk else {}

    current_price = await get_current_price(ticker)

    # Create trade proposal
    proposal = TradeProposal(
        id=str(uuid.uuid4()),
        ticker=ticker,
        action=action,
        quantity=100,
        entry_price=current_price,
        stop_loss=risk_signals.get("suggested_stop_loss"),
        take_profit=risk_signals.get("suggested_take_profit"),
        risk_score=risk_signals.get("risk_score", 0.5),
        position_size_pct=risk_signals.get("max_position_pct", 5.0),
        rationale=response,
        bull_case=_extract_bull_case(response),
        bear_case=_extract_bear_case(response),
        analyses=analyses,
    )

    reasoning = f"[Strategic Decision] Proposal: {action.value} {proposal.quantity} {ticker} @ ${current_price:.2f}"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="strategic_decision",
        ticker=ticker,
        action=action.value,
        proposal_id=proposal.id[:8],
        duration_ms=round(duration_ms, 2),
    )

    return {
        "trade_proposal": proposal,
        "synthesis": {
            "consensus_signal": consensus_signal.value,
            "average_confidence": avg_confidence,
            "decision_rationale": response[:500],
        },
        "awaiting_approval": True,
        "reasoning_log": add_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": AnalysisStage.APPROVAL,
    }


# -------------------------------------------
# Stage 2: Human Approval (HITL Interrupt)
# -------------------------------------------


async def human_approval_node(state: dict) -> dict:
    """
    Human-in-the-loop approval checkpoint.
    This node is an interrupt point - execution pauses here.
    """
    ticker = _get_ticker_safely(state, "human_approval")
    proposal = state.get("trade_proposal")

    logger.info(
        "node_started",
        node="human_approval",
        ticker=ticker,
        proposal_id=proposal.id[:8] if proposal else None,
        action=proposal.action.value if proposal else None,
    )

    reasoning = f"[HITL] Awaiting human approval for {proposal.action.value} {proposal.ticker}..." if proposal else "[HITL] No proposal to approve"

    logger.info(
        "awaiting_human_approval",
        ticker=ticker,
        proposal_id=proposal.id[:8] if proposal else None,
        action=proposal.action.value if proposal else None,
        entry_price=proposal.entry_price if proposal else None,
    )

    return {
        "awaiting_approval": True,
        "current_stage": AnalysisStage.APPROVAL,
        "reasoning_log": add_reasoning_log(state, reasoning),
    }


# -------------------------------------------
# Stage 3: Trade Execution
# -------------------------------------------


async def execution_node(state: dict) -> dict:
    """
    Execute the approved trade.
    In production, this would connect to a broker API.
    """
    proposal = state.get("trade_proposal")
    approval_status = state.get("approval_status")

    if approval_status != "approved" or not proposal:
        reasoning = f"[Execution] Trade not approved (status: {approval_status}). Skipping execution."
        return {
            "execution_status": "cancelled",
            "current_stage": AnalysisStage.COMPLETE,
            "reasoning_log": add_reasoning_log(state, reasoning),
        }

    logger.info(
        "trade_execution_start",
        ticker=proposal.ticker,
        action=proposal.action.value,
        quantity=proposal.quantity,
    )

    # Simulate trade execution
    # In production: broker_api.execute_order(proposal)
    current_price = await get_current_price(proposal.ticker)

    if proposal.action == TradeAction.HOLD:
        reasoning = f"[Execution] HOLD decision - no trade executed for {proposal.ticker}"
        return {
            "execution_status": "completed",
            "current_stage": AnalysisStage.COMPLETE,
            "reasoning_log": add_reasoning_log(state, reasoning),
        }

    # Create position record
    position = Position(
        ticker=proposal.ticker,
        quantity=proposal.quantity if proposal.action == TradeAction.BUY else -proposal.quantity,
        entry_price=current_price,
        current_price=current_price,
        stop_loss=proposal.stop_loss,
        take_profit=proposal.take_profit,
    )

    reasoning = (
        f"[Execution] Trade executed: {proposal.action.value} {proposal.quantity} "
        f"{proposal.ticker} @ ${current_price:.2f}"
    )

    return {
        "execution_status": "completed",
        "active_position": position,
        "current_stage": AnalysisStage.COMPLETE,
        "reasoning_log": add_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
    }


# -------------------------------------------
# Conditional Edges
# -------------------------------------------


def should_continue_to_execution(state: dict) -> Literal["execute", "end"]:
    """Conditional edge: Check if trade was approved."""
    if state.get("approval_status") == "approved":
        return "execute"
    return "end"


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def _determine_technical_signal(indicators: dict) -> SignalType:
    """Determine signal from technical indicators."""
    if not indicators:
        return SignalType.HOLD

    score = 0

    # RSI
    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi < 30:
            score += 2  # Oversold
        elif rsi < 40:
            score += 1
        elif rsi > 70:
            score -= 2  # Overbought
        elif rsi > 60:
            score -= 1

    # Trend
    trend = indicators.get("trend", "neutral")
    if trend == "bullish":
        score += 1
    elif trend == "bearish":
        score -= 1

    # MACD
    macd = indicators.get("macd", {}).get("histogram")
    if macd is not None:
        if macd > 0:
            score += 1
        else:
            score -= 1

    # Map score to signal
    if score >= 3:
        return SignalType.STRONG_BUY
    elif score >= 1:
        return SignalType.BUY
    elif score <= -3:
        return SignalType.STRONG_SELL
    elif score <= -1:
        return SignalType.SELL
    return SignalType.HOLD


def _determine_fundamental_signal(info: dict) -> SignalType:
    """Determine signal from fundamental data."""
    if not info:
        return SignalType.HOLD

    score = 0

    # P/E Ratio
    pe = info.get("trailingPE")
    if pe is not None:
        if pe < 15:
            score += 1
        elif pe > 30:
            score -= 1

    # P/B Ratio
    pb = info.get("priceToBook")
    if pb is not None:
        if pb < 2:
            score += 1
        elif pb > 5:
            score -= 1

    # Map score to signal
    if score >= 2:
        return SignalType.BUY
    elif score <= -2:
        return SignalType.SELL
    return SignalType.HOLD


def _calculate_risk_score(analyses: list[AnalysisResult]) -> float:
    """Calculate risk score based on analysis disagreement."""
    if not analyses:
        return 0.5

    # Signal values
    signal_map = {
        SignalType.STRONG_BUY: 2,
        SignalType.BUY: 1,
        SignalType.HOLD: 0,
        SignalType.SELL: -1,
        SignalType.STRONG_SELL: -2,
    }

    signals = [signal_map[a.signal] for a in analyses if a.agent_type != "risk"]

    if len(signals) < 2:
        return 0.5

    # Calculate variance in signals (disagreement = risk)
    import numpy as np

    variance = np.var(signals)
    # Normalize to 0-1 range (max variance is 4 for signals from -2 to 2)
    risk_score = min(variance / 4.0, 1.0)

    # Also factor in average confidence (lower confidence = higher risk)
    avg_confidence = sum(a.confidence for a in analyses) / len(analyses)
    risk_score = (risk_score + (1 - avg_confidence)) / 2

    return round(risk_score, 2)


def _signal_to_action(signal: SignalType) -> TradeAction:
    """Convert signal to trade action."""
    if signal in (SignalType.STRONG_BUY, SignalType.BUY):
        return TradeAction.BUY
    elif signal in (SignalType.STRONG_SELL, SignalType.SELL):
        return TradeAction.SELL
    return TradeAction.HOLD


def _extract_key_factors(response: str) -> list[str]:
    """Extract key factors from LLM response."""
    # Simple extraction - look for bullet points or numbered items
    factors = []
    lines = response.split("\n")

    for line in lines:
        line = line.strip()
        if line.startswith(("-", "•", "*")) or (line and line[0].isdigit() and "." in line[:3]):
            # Clean up the line
            clean = line.lstrip("-•*0123456789. ").strip()
            if clean and len(clean) > 10:
                factors.append(clean[:200])  # Limit length

    return factors[:5]  # Return top 5


def _extract_bull_case(response: str) -> str:
    """Extract bull case from response."""
    lower = response.lower()
    if "bull" in lower:
        start = lower.find("bull")
        return response[start : start + 500]
    return ""


def _extract_bear_case(response: str) -> str:
    """Extract bear case from response."""
    lower = response.lower()
    if "bear" in lower:
        start = lower.find("bear")
        return response[start : start + 500]
    return ""


def _format_fundamental_data(info: dict) -> str:
    """Format fundamental data for LLM context."""
    lines = [
        f"=== Fundamental Data ===",
        f"Company: {info.get('shortName', 'Unknown')}",
        f"Sector: {info.get('sector', 'Unknown')}",
        f"Industry: {info.get('industry', 'Unknown')}",
        f"",
        f"Valuation Metrics:",
        f"- Market Cap: ${info.get('marketCap', 0):,.0f}",
        f"- P/E Ratio (Trailing): {info.get('trailingPE', 'N/A')}",
        f"- P/E Ratio (Forward): {info.get('forwardPE', 'N/A')}",
        f"- Price to Book: {info.get('priceToBook', 'N/A')}",
        f"- Dividend Yield: {info.get('dividendYield', 0) * 100:.2f}%" if info.get('dividendYield') else "- Dividend Yield: N/A",
        f"",
        f"Risk Metrics:",
        f"- Beta: {info.get('beta', 'N/A')}",
        f"- 52 Week High: ${info.get('52WeekHigh', 'N/A')}",
        f"- 52 Week Low: ${info.get('52WeekLow', 'N/A')}",
    ]
    return "\n".join(lines)
