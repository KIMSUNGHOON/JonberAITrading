"""
LangGraph Node Functions for Korean Stock Trading Workflow

Each node function receives the current state and returns state updates.
Nodes are executed in sequence as defined in the Korean stock trading graph.
Uses Kiwoom Securities REST API for market data and order execution.
"""

import time
import uuid
from datetime import datetime
from typing import Literal

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.graph.kr_stock_state import (
    KRStockAnalysisResult,
    KRStockAnalysisStage,
    KRStockPosition,
    KRStockTradeProposal,
    SignalType,
    TradeAction,
    add_kr_stock_reasoning_log,
    calculate_kr_stock_consensus_signal,
    get_all_kr_stock_analyses,
    kr_stock_analysis_dict_to_context_string,
)
from agents.llm_provider import get_llm_provider
from agents.prompts import (
    KR_STOCK_FUNDAMENTAL_ANALYST_PROMPT,
    KR_STOCK_RISK_ASSESSOR_PROMPT,
    KR_STOCK_SENTIMENT_ANALYST_PROMPT,
    KR_STOCK_STRATEGIC_DECISION_PROMPT,
    KR_STOCK_TECHNICAL_ANALYST_PROMPT,
)
from agents.tools.kr_market_data import (
    calculate_kr_technical_indicators,
    format_kr_market_data_for_llm,
    get_kr_current_price,
    get_kr_daily_chart,
    get_kr_orderbook,
    get_kr_stock_info,
)
from services.technical_indicators import TechnicalIndicators, get_indicator_summary
from app.config import settings
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from services.kiwoom import OrderType

logger = structlog.get_logger()


def _get_stk_cd_safely(state: dict, node_name: str) -> str:
    """Safely get stock code from state with detailed error logging."""
    stk_cd = state.get("stk_cd")
    if not stk_cd:
        logger.error(
            "state_missing_stk_cd",
            node=node_name,
            state_keys=list(state.keys()),
        )
        raise ValueError(f"State missing 'stk_cd' in {node_name}")
    return stk_cd


# -------------------------------------------
# Stage 1: Data Collection
# -------------------------------------------


async def kr_stock_data_collection_node(state: dict) -> dict:
    """
    Fetch market data from Kiwoom API.
    This is the first node that gathers all necessary data.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "data_collection")

    logger.info(
        "node_started",
        node="kr_stock_data_collection",
        stk_cd=stk_cd,
    )

    try:
        # Fetch stock info
        stock_info = await get_kr_stock_info(stk_cd)

        # Fetch daily chart
        chart_df = await get_kr_daily_chart(stk_cd)

        # Fetch orderbook
        orderbook = await get_kr_orderbook(stk_cd)

        # Convert chart DataFrame to list of dicts for serialization
        chart_data = []
        if not chart_df.empty:
            for idx, row in chart_df.iterrows():
                chart_data.append({
                    "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                    "open": int(row["open"]),
                    "high": int(row["high"]),
                    "low": int(row["low"]),
                    "close": int(row["close"]),
                    "volume": int(row["volume"]),
                })

        stk_nm = stock_info.get("stk_nm", "")
        cur_prc = stock_info.get("cur_prc", 0)
        prdy_ctrt = stock_info.get("prdy_ctrt", 0)

        reasoning = (
            f"[데이터 수집] {stk_nm} ({stk_cd}): "
            f"현재가={cur_prc:,}원, "
            f"전일대비={prdy_ctrt:+.2f}%, "
            f"차트 {len(chart_data)}일치"
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "node_completed",
            node="kr_stock_data_collection",
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            duration_ms=round(duration_ms, 2),
        )

        return {
            "stk_nm": stk_nm,
            "market_data": stock_info,
            "chart_df": chart_data,
            "orderbook": orderbook,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
            "current_stage": KRStockAnalysisStage.DATA_COLLECTION,
        }

    except Exception as e:
        error_msg = f"데이터 수집 실패 ({stk_cd}): {str(e)}"
        logger.error("kr_stock_data_collection_failed", stk_cd=stk_cd, error=str(e))
        return {
            "error": error_msg,
            "reasoning_log": add_kr_stock_reasoning_log(state, f"[오류] {error_msg}"),
            "current_stage": KRStockAnalysisStage.COMPLETE,
        }


# -------------------------------------------
# Stage 2: Technical Analysis
# -------------------------------------------


async def kr_stock_technical_analysis_node(state: dict) -> dict:
    """
    Korean stock technical analysis.
    Analyzes price patterns, indicators, and orderbook using TechnicalIndicators service.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "technical_analysis")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    logger.info("node_started", node="kr_stock_technical_analysis", stk_cd=stk_cd)

    # Get market data from state
    market_data = state.get("market_data", {})
    chart_data = state.get("chart_df", [])
    orderbook = state.get("orderbook", {})

    # Convert chart_data back to DataFrame for indicator calculation
    import pandas as pd
    if chart_data:
        df = pd.DataFrame(chart_data)
        # Handle various date formats safely
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])  # Remove rows with unparseable dates
        if not df.empty:
            df.set_index("date", inplace=True)
    else:
        df = pd.DataFrame()

    # Format market context for LLM
    market_context = format_kr_market_data_for_llm(market_data, df, orderbook)

    # Calculate technical indicators using the new service
    indicators = calculate_kr_technical_indicators(df)

    # Also use the new TechnicalIndicators service for enhanced analysis
    enhanced_indicators = {}
    detected_signals = []
    indicator_summary = ""
    if not df.empty and len(df) >= 20:
        try:
            tech_service = TechnicalIndicators(df)
            enhanced_indicators = tech_service.calculate_all()
            detected_signals = enhanced_indicators.get("signals", [])
            indicator_summary = get_indicator_summary(df)
        except Exception as e:
            logger.warning("enhanced_indicators_failed", error=str(e))

    # Include detected signals in context
    signals_text = ""
    if detected_signals:
        signals_text = "\n\n=== 감지된 시그널 ===\n"
        for sig in detected_signals:
            signals_text += f"• {sig.get('description', '')}\n"

    messages = [
        SystemMessage(content=KR_STOCK_TECHNICAL_ANALYST_PROMPT),
        HumanMessage(content=f"{stk_nm} ({stk_cd}) 기술적 분석:\n\n{market_context}{signals_text}"),
    ]

    logger.debug("llm_request", node="kr_stock_technical_analysis")
    llm_start = time.perf_counter()
    response = await llm.generate(messages)
    llm_duration = (time.perf_counter() - llm_start) * 1000
    logger.debug("llm_response", node="kr_stock_technical_analysis", duration_ms=round(llm_duration, 2))

    # Determine signal from indicators (using detected signals for better accuracy)
    signal = _determine_kr_stock_technical_signal_enhanced(indicators, orderbook, detected_signals)

    # Calculate confidence based on signal strength
    confidence = _calculate_technical_confidence(detected_signals, indicators)

    result = KRStockAnalysisResult(
        agent_type="technical",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        signal=signal,
        confidence=confidence,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response) + [s.get("description", "") for s in detected_signals[:3]],
        signals={
            "trend": enhanced_indicators.get("trend", {}).get("direction", indicators.get("trend", "neutral")),
            "rsi": enhanced_indicators.get("momentum", {}).get("rsi", indicators.get("rsi")),
            "macd_histogram": enhanced_indicators.get("macd", {}).get("histogram", indicators.get("macd", {}).get("histogram")),
            "bid_ask_ratio": orderbook.get("bid_ask_ratio"),
            "volume_ratio": enhanced_indicators.get("volume", {}).get("ratio", indicators.get("volume_ratio")),
            "cross": indicators.get("cross"),
            "sma_20": enhanced_indicators.get("moving_averages", {}).get("sma_20"),
            "sma_60": enhanced_indicators.get("moving_averages", {}).get("sma_60"),
            "bollinger_upper": enhanced_indicators.get("bollinger_bands", {}).get("upper"),
            "bollinger_lower": enhanced_indicators.get("bollinger_bands", {}).get("lower"),
            "stochastic_k": enhanced_indicators.get("momentum", {}).get("stochastic_k"),
            "atr": enhanced_indicators.get("volatility", {}).get("atr"),
        },
    )

    # Create detailed reasoning
    signal_descriptions = [s.get("description", "") for s in detected_signals[:3]]
    signals_summary = ", ".join(signal_descriptions) if signal_descriptions else "특이 시그널 없음"
    reasoning = f"[기술적 분석] {stk_nm}: {signal.value} (신뢰도: {confidence:.0%}) - {signals_summary}"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="kr_stock_technical_analysis",
        stk_cd=stk_cd,
        signal=signal.value,
        confidence=round(confidence, 2),
        detected_signals=len(detected_signals),
        duration_ms=round(duration_ms, 2),
    )

    return {
        "technical_analysis": result.model_dump(),
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.TECHNICAL,
    }


# -------------------------------------------
# Stage 3: Fundamental Analysis
# -------------------------------------------


async def kr_stock_fundamental_analysis_node(state: dict) -> dict:
    """
    Korean stock fundamental analysis.
    Analyzes valuation, financials, and business metrics.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "fundamental_analysis")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    logger.info("node_started", node="kr_stock_fundamental_analysis", stk_cd=stk_cd)

    market_data = state.get("market_data", {})

    # Format fundamental data context
    fundamental_context = _format_kr_fundamental_data(market_data)

    messages = [
        SystemMessage(content=KR_STOCK_FUNDAMENTAL_ANALYST_PROMPT),
        HumanMessage(content=f"{stk_nm} ({stk_cd}) 기본적 분석:\n\n{fundamental_context}"),
    ]

    logger.debug("llm_request", node="kr_stock_fundamental_analysis")
    response = await llm.generate(messages)

    # Determine signal from fundamental data
    signal = _determine_kr_fundamental_signal(market_data)

    result = KRStockAnalysisResult(
        agent_type="fundamental",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        signal=signal,
        confidence=0.70,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "per": market_data.get("per"),
            "pbr": market_data.get("pbr"),
            "eps": market_data.get("eps"),
            "bps": market_data.get("bps"),
            "market_cap": market_data.get("mrkt_tot_amt"),
        },
    )

    reasoning = f"[기본적 분석] {stk_nm}: {signal.value} (신뢰도: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="kr_stock_fundamental_analysis", stk_cd=stk_cd, duration_ms=round(duration_ms, 2))

    return {
        "fundamental_analysis": result.model_dump(),
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.FUNDAMENTAL,
    }


# -------------------------------------------
# Stage 4: Sentiment Analysis
# -------------------------------------------


async def kr_stock_sentiment_analysis_node(state: dict) -> dict:
    """
    Korean stock sentiment analysis.
    Analyzes news, disclosures, and market sentiment.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "sentiment_analysis")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    logger.info("node_started", node="kr_stock_sentiment_analysis", stk_cd=stk_cd)

    market_data = state.get("market_data", {})

    messages = [
        SystemMessage(content=KR_STOCK_SENTIMENT_ANALYST_PROMPT),
        HumanMessage(
            content=f"{stk_nm} ({stk_cd}) 시장심리 분석. "
            f"현재가: {market_data.get('cur_prc', 0):,}원, "
            f"전일대비: {market_data.get('prdy_ctrt', 0):+.2f}%"
        ),
    ]

    logger.debug("llm_request", node="kr_stock_sentiment_analysis")
    response = await llm.generate(messages)

    # Default to neutral sentiment
    signal = SignalType.HOLD

    result = KRStockAnalysisResult(
        agent_type="sentiment",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        signal=signal,
        confidence=0.60,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "news_sentiment": "neutral",
            "disclosure_impact": "neutral",
            "analyst_consensus": "hold",
        },
    )

    reasoning = f"[시장심리 분석] {stk_nm}: {signal.value} (신뢰도: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="kr_stock_sentiment_analysis", stk_cd=stk_cd, duration_ms=round(duration_ms, 2))

    return {
        "sentiment_analysis": result.model_dump(),
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.SENTIMENT,
    }


# -------------------------------------------
# Stage 5: Risk Assessment
# -------------------------------------------


async def kr_stock_risk_assessment_node(state: dict) -> dict:
    """
    Korean stock risk assessment.
    Evaluates volatility, liquidity, and position sizing.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "risk_assessment")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    logger.info("node_started", node="kr_stock_risk_assessment", stk_cd=stk_cd)

    # Gather all previous analyses
    analyses = get_all_kr_stock_analyses(state)
    analyses_context = "\n\n".join(kr_stock_analysis_dict_to_context_string(a) for a in analyses)

    market_data = state.get("market_data", {})
    current_price = market_data.get("cur_prc", 0)

    messages = [
        SystemMessage(content=KR_STOCK_RISK_ASSESSOR_PROMPT),
        HumanMessage(
            content=f"{stk_nm} ({stk_cd}) 리스크 평가 (현재가: {current_price:,}원):\n\n{analyses_context}"
        ),
    ]

    logger.debug("llm_request", node="kr_stock_risk_assessment")
    response = await llm.generate(messages)

    # Calculate risk score
    risk_score = _calculate_kr_stock_risk_score(analyses, market_data)

    # Korean stock stop-loss calculation (typically 5-8%)
    stop_loss_pct = 0.05 if risk_score < 0.5 else 0.08
    take_profit_pct = 0.10 if risk_score < 0.5 else 0.08

    result = KRStockAnalysisResult(
        agent_type="risk",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        signal=SignalType.HOLD,
        confidence=0.80,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "risk_score": risk_score,
            "max_position_pct": 5.0 if risk_score < 0.5 else 3.0,
            "suggested_stop_loss": int(current_price * (1 - stop_loss_pct)),
            "suggested_take_profit": int(current_price * (1 + take_profit_pct)),
        },
    )

    reasoning = f"[리스크 평가] {stk_nm}: 리스크 점수 {risk_score:.0%}, 최대 포지션 {result.signals['max_position_pct']}%"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="kr_stock_risk_assessment", stk_cd=stk_cd, risk_score=risk_score, duration_ms=round(duration_ms, 2))

    return {
        "risk_assessment": result.model_dump(),
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.RISK,
    }


# -------------------------------------------
# Stage 6: Strategic Decision
# -------------------------------------------


async def kr_stock_strategic_decision_node(state: dict) -> dict:
    """
    Synthesize all analyses into a Korean stock trade proposal.
    """
    start_time = time.perf_counter()
    stk_cd = _get_stk_cd_safely(state, "strategic_decision")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    logger.info("node_started", node="kr_stock_strategic_decision", stk_cd=stk_cd)

    # Collect all analyses
    analyses = get_all_kr_stock_analyses(state)
    analyses_context = "\n\n".join(kr_stock_analysis_dict_to_context_string(a) for a in analyses)

    # Calculate consensus
    consensus_signal, avg_confidence = calculate_kr_stock_consensus_signal(analyses)

    messages = [
        SystemMessage(content=KR_STOCK_STRATEGIC_DECISION_PROMPT),
        HumanMessage(
            content=f"{stk_nm} ({stk_cd}) 투자 결정:\n\n"
            f"컨센서스 시그널: {consensus_signal.value} (평균 신뢰도: {avg_confidence:.0%})\n\n"
            f"{analyses_context}"
        ),
    ]

    logger.debug("llm_request", node="kr_stock_strategic_decision")
    response = await llm.generate(messages)

    # Determine action from consensus
    action = _signal_to_action(consensus_signal)

    # Get risk parameters
    risk = state.get("risk_assessment", {})
    risk_signals = risk.get("signals", {})

    market_data = state.get("market_data", {})
    current_price = market_data.get("cur_prc", 0)
    position_size_pct = float(risk_signals.get("max_position_pct", 5.0))

    # Calculate quantity based on available balance
    quantity = 0
    if action in (TradeAction.BUY, "BUY") and current_price > 0:
        try:
            client = await get_shared_kiwoom_client_async()
            cash_balance = await client.get_cash_balance()
            orderable_amount = cash_balance.ord_psbl_amt

            # Calculate quantity: (orderable * position_size%) / price
            investment_amount = int(orderable_amount * position_size_pct / 100)
            quantity = investment_amount // current_price

            logger.info(
                "kr_stock_quantity_calculated",
                stk_cd=stk_cd,
                orderable_amount=orderable_amount,
                position_size_pct=position_size_pct,
                investment_amount=investment_amount,
                current_price=current_price,
                quantity=quantity,
            )
        except Exception as e:
            logger.warning(
                "kr_stock_quantity_calculation_failed",
                stk_cd=stk_cd,
                error=str(e),
            )
            # quantity remains 0, user can modify in approval dialog

    # Create trade proposal
    proposal = KRStockTradeProposal(
        id=str(uuid.uuid4()),
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        action=action,
        quantity=quantity,
        entry_price=current_price,
        stop_loss=risk_signals.get("suggested_stop_loss", int(current_price * 0.95)),
        take_profit=risk_signals.get("suggested_take_profit", int(current_price * 1.10)),
        risk_score=float(risk_signals.get("risk_score", 0.5)),
        position_size_pct=position_size_pct,
        rationale=response,
        bull_case=_extract_bull_case(response),
        bear_case=_extract_bear_case(response),
        analyses=analyses,
    )

    reasoning = f"[투자 결정] 제안: {action.value} {stk_nm} {quantity}주 @ {current_price:,}원"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="kr_stock_strategic_decision",
        stk_cd=stk_cd,
        action=action.value,
        duration_ms=round(duration_ms, 2),
    )

    return {
        "trade_proposal": proposal.model_dump(),
        "synthesis": {
            "consensus_signal": consensus_signal.value,
            "average_confidence": avg_confidence,
            "decision_rationale": response[:500],
        },
        "awaiting_approval": True,
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": KRStockAnalysisStage.SYNTHESIS,
    }


# -------------------------------------------
# Stage 7: Human Approval
# -------------------------------------------


async def kr_stock_human_approval_node(state: dict) -> dict:
    """
    Human-in-the-loop approval checkpoint for Korean stock trades.
    """
    stk_cd = _get_stk_cd_safely(state, "human_approval")
    stk_nm = state.get("stk_nm", stk_cd)
    proposal = state.get("trade_proposal", {})

    proposal_id = proposal.get("id", "")[:8]
    proposal_action = proposal.get("action")

    logger.info(
        "node_started",
        node="kr_stock_human_approval",
        stk_cd=stk_cd,
        proposal_id=proposal_id,
    )

    reasoning = f"[HITL] {stk_nm} {proposal_action} 거래 승인 대기 중..."

    return {
        "awaiting_approval": True,
        "current_stage": KRStockAnalysisStage.APPROVAL,
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
    }


async def kr_stock_re_analyze_node(state: dict) -> dict:
    """
    Prepare for re-analysis after rejection.
    """
    stk_cd = _get_stk_cd_safely(state, "re_analyze")
    stk_nm = state.get("stk_nm", stk_cd)
    user_feedback = state.get("user_feedback", "")
    re_analyze_count = state.get("re_analyze_count", 0) + 1

    logger.info(
        "node_started",
        node="kr_stock_re_analyze",
        stk_cd=stk_cd,
        re_analyze_count=re_analyze_count,
    )

    reasoning = f"[재분석] 사용자 요청에 따른 재분석 (시도 #{re_analyze_count})"
    if user_feedback:
        reasoning += f"\n사용자 피드백: {user_feedback}"

    return {
        "current_stage": KRStockAnalysisStage.DATA_COLLECTION,
        "technical_analysis": None,
        "fundamental_analysis": None,
        "sentiment_analysis": None,
        "risk_assessment": None,
        "synthesis": None,
        "trade_proposal": None,
        "awaiting_approval": False,
        "approval_status": None,
        "re_analyze_count": re_analyze_count,
        "re_analyze_feedback": user_feedback,
        "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
    }


# -------------------------------------------
# Stage 8: Execution
# -------------------------------------------


async def kr_stock_execution_node(state: dict) -> dict:
    """
    Execute the approved Korean stock trade via Kiwoom API.

    Supports two modes based on KIWOOM_IS_MOCK:
    - mock: Uses mock trading API (simulated)
    - live: Uses live trading API (real money)
    """
    proposal = state.get("trade_proposal", {})
    approval_status = state.get("approval_status")

    if approval_status != "approved" or not proposal:
        reasoning = f"[실행] 거래 미승인 (상태: {approval_status}). 실행 건너뜀."
        return {
            "execution_status": "cancelled",
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        }

    stk_cd = proposal.get("stk_cd", "")
    stk_nm = proposal.get("stk_nm", stk_cd)
    action = proposal.get("action", "HOLD")
    entry_price = proposal.get("entry_price", 0)
    quantity = proposal.get("quantity", 0)

    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)
    mode_str = "모의투자" if is_mock else "실거래"

    logger.info(
        "kr_stock_trade_execution_start",
        stk_cd=stk_cd,
        action=action,
        trading_mode=mode_str,
    )

    if action == "HOLD" or action == TradeAction.HOLD:
        reasoning = f"[실행] HOLD 결정 - {stk_nm} 거래 미실행"
        return {
            "execution_status": "completed",
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
        }

    # Execute order via Kiwoom API (using shared singleton)
    try:
        client = await get_shared_kiwoom_client_async()

        if action == "BUY" or action == TradeAction.BUY:
            order_response = await client.place_buy_order(
                stk_cd=stk_cd,
                qty=quantity,
                price=entry_price,
                order_type=OrderType.LIMIT,
            )
        elif action == "SELL" or action == TradeAction.SELL:
            order_response = await client.place_sell_order(
                stk_cd=stk_cd,
                qty=quantity,
                price=entry_price,
                order_type=OrderType.LIMIT,
            )
        else:
            reasoning = f"[실행] 알 수 없는 액션: {action}"
            return {
                "execution_status": "failed",
                "error": f"Unknown action: {action}",
                "current_stage": KRStockAnalysisStage.COMPLETE,
                "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            }

        logger.info(
            "kr_stock_order_placed",
            stk_cd=stk_cd,
            action=action,
            order_no=order_response.ord_no,
            return_code=order_response.return_code,
        )

        # Create position record
        position = KRStockPosition(
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            quantity=quantity if action == "BUY" else -quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=proposal.get("stop_loss"),
            take_profit=proposal.get("take_profit"),
        )

        reasoning = (
            f"[실행] ({mode_str}) 주문 접수: {action} {stk_nm} {quantity}주 @ {entry_price:,}원, "
            f"주문번호: {order_response.ord_no}"
        )

        return {
            "execution_status": "completed",
            "active_position": position.model_dump(),
            "order_response": {
                "ord_no": order_response.ord_no,
                "return_code": order_response.return_code,
                "return_msg": order_response.return_msg,
            },
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(
            "kr_stock_order_failed",
            stk_cd=stk_cd,
            action=action,
            error=error_msg,
        )

        reasoning = f"[실행] 주문 실패: {error_msg}"

        return {
            "execution_status": "failed",
            "error": error_msg,
            "current_stage": KRStockAnalysisStage.COMPLETE,
            "reasoning_log": add_kr_stock_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
        }


# -------------------------------------------
# Conditional Edges
# -------------------------------------------


def should_continue_kr_stock_execution(state: dict) -> Literal["execute", "re_analyze", "end"]:
    """Conditional edge: Check if trade was approved, rejected, or cancelled."""
    approval_status = state.get("approval_status")

    if approval_status == "approved":
        return "execute"
    elif approval_status == "rejected":
        return "re_analyze"
    else:
        return "end"


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def _determine_kr_stock_technical_signal(indicators: dict, orderbook: dict) -> SignalType:
    """Determine signal from Korean stock technical indicators."""
    score = 0

    # RSI
    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi < 30:
            score += 2
        elif rsi < 40:
            score += 1
        elif rsi > 70:
            score -= 2
        elif rsi > 60:
            score -= 1

    # Trend
    trend = indicators.get("trend", "neutral")
    if trend == "bullish":
        score += 1
    elif trend == "bearish":
        score -= 1

    # Golden/Dead Cross
    cross = indicators.get("cross", "none")
    if cross == "golden_cross":
        score += 2
    elif cross == "dead_cross":
        score -= 2

    # Bid/Ask ratio (orderbook)
    bid_ask = orderbook.get("bid_ask_ratio", 1.0)
    if bid_ask > 1.3:
        score += 1
    elif bid_ask < 0.7:
        score -= 1

    # Volume ratio
    volume_ratio = indicators.get("volume_ratio", 1.0)
    if volume_ratio > 2.0:
        score += 1  # High volume can confirm trend

    # Map score to signal
    if score >= 4:
        return SignalType.STRONG_BUY
    elif score >= 2:
        return SignalType.BUY
    elif score <= -4:
        return SignalType.STRONG_SELL
    elif score <= -2:
        return SignalType.SELL
    return SignalType.HOLD


def _determine_kr_stock_technical_signal_enhanced(
    indicators: dict, orderbook: dict, detected_signals: list
) -> SignalType:
    """
    Enhanced signal determination using TechnicalIndicators service signals.
    Combines traditional indicator analysis with detected signals.
    """
    # Start with base signal from traditional indicators
    base_signal = _determine_kr_stock_technical_signal(indicators, orderbook)

    # Count bullish/bearish signals from detected signals
    bullish_count = 0
    bearish_count = 0

    for sig in detected_signals:
        signal_type = sig.get("signal", "neutral")
        if signal_type in ("strong_buy", "buy"):
            bullish_count += 2 if signal_type == "strong_buy" else 1
        elif signal_type in ("strong_sell", "sell"):
            bearish_count += 2 if signal_type == "strong_sell" else 1

    # Adjust signal based on detected signals
    net_signal = bullish_count - bearish_count

    # If detected signals strongly agree with base signal, upgrade it
    if base_signal in (SignalType.BUY, SignalType.STRONG_BUY):
        if net_signal >= 3:
            return SignalType.STRONG_BUY
        elif net_signal >= 1:
            return SignalType.BUY
        elif net_signal <= -3:
            return SignalType.HOLD  # Mixed signals, downgrade to hold
    elif base_signal in (SignalType.SELL, SignalType.STRONG_SELL):
        if net_signal <= -3:
            return SignalType.STRONG_SELL
        elif net_signal <= -1:
            return SignalType.SELL
        elif net_signal >= 3:
            return SignalType.HOLD  # Mixed signals, downgrade to hold
    else:  # HOLD
        # Detected signals can upgrade HOLD
        if net_signal >= 4:
            return SignalType.BUY
        elif net_signal <= -4:
            return SignalType.SELL

    return base_signal


def _calculate_technical_confidence(detected_signals: list, indicators: dict) -> float:
    """
    Calculate confidence level based on signal strength and consistency.

    Returns:
        Confidence value between 0.0 and 1.0
    """
    base_confidence = 0.5

    # Factor 1: Number of detected signals (more signals = more data = higher confidence)
    signal_count = len(detected_signals)
    signal_bonus = min(signal_count * 0.05, 0.2)  # Up to 0.2 for 4+ signals

    # Factor 2: Signal agreement (all bullish or all bearish = high confidence)
    if detected_signals:
        bullish = sum(1 for s in detected_signals if s.get("signal") in ("buy", "strong_buy"))
        bearish = sum(1 for s in detected_signals if s.get("signal") in ("sell", "strong_sell"))
        total = bullish + bearish

        if total > 0:
            agreement = max(bullish, bearish) / total
            agreement_bonus = agreement * 0.15  # Up to 0.15 for full agreement
        else:
            agreement_bonus = 0
    else:
        agreement_bonus = 0

    # Factor 3: Indicator data availability
    data_bonus = 0
    if indicators.get("rsi") is not None:
        data_bonus += 0.03
    if indicators.get("macd") is not None:
        data_bonus += 0.03
    if indicators.get("trend") and indicators.get("trend") != "neutral":
        data_bonus += 0.02
    if indicators.get("cross") and indicators.get("cross") != "none":
        data_bonus += 0.05  # Cross signals are strong indicators

    # Factor 4: Strong signals in detected_signals
    strong_signal_bonus = 0
    for sig in detected_signals:
        signal_type = sig.get("signal", "")
        if signal_type in ("strong_buy", "strong_sell"):
            strong_signal_bonus += 0.03

    strong_signal_bonus = min(strong_signal_bonus, 0.1)  # Cap at 0.1

    total_confidence = base_confidence + signal_bonus + agreement_bonus + data_bonus + strong_signal_bonus

    return min(max(total_confidence, 0.3), 0.95)  # Clamp between 0.3 and 0.95


def _determine_kr_fundamental_signal(market_data: dict) -> SignalType:
    """Determine signal from Korean stock fundamental data."""
    score = 0

    # PER (Korean market average ~12-15)
    per = market_data.get("per")
    if per is not None:
        if per < 10:
            score += 2
        elif per < 15:
            score += 1
        elif per > 30:
            score -= 1
        elif per > 50:
            score -= 2

    # PBR (Korean market average ~1.0)
    pbr = market_data.get("pbr")
    if pbr is not None:
        if pbr < 0.7:
            score += 1
        elif pbr < 1.0:
            score += 0.5
        elif pbr > 3:
            score -= 1

    # Map score to signal
    if score >= 3:
        return SignalType.BUY
    elif score >= 1:
        return SignalType.BUY
    elif score <= -2:
        return SignalType.SELL
    return SignalType.HOLD


def _calculate_kr_stock_risk_score(analyses: list, market_data: dict) -> float:
    """Calculate risk score for Korean stock."""
    base_risk = 0.3  # Korean stocks have moderate base risk

    # Add risk for high volatility (based on price change)
    change_rate = abs(market_data.get("prdy_ctrt", 0))
    volatility_risk = min(change_rate / 15, 0.3)  # Up to 0.3 for 15%+ daily change

    # Add risk for signal disagreement
    if len(analyses) >= 2:
        signals = [a.get("signal", "hold") for a in analyses if a.get("agent_type") != "risk"]
        unique_signals = set(signals)
        disagreement_risk = (len(unique_signals) - 1) * 0.1
    else:
        disagreement_risk = 0

    return min(round(base_risk + volatility_risk + disagreement_risk, 2), 1.0)


def _format_kr_fundamental_data(market_data: dict) -> str:
    """Format Korean stock fundamental data for LLM context."""
    lines = [
        f"=== 기본적 분석 데이터 ===",
        f"종목명: {market_data.get('stk_nm', 'N/A')}",
        f"종목코드: {market_data.get('stk_cd', 'N/A')}",
        f"",
        f"=== 밸류에이션 ===",
        f"PER: {market_data.get('per', 'N/A')}배",
        f"PBR: {market_data.get('pbr', 'N/A')}배",
        f"EPS: {market_data.get('eps', 0):,}원" if market_data.get('eps') else "EPS: N/A",
        f"BPS: {market_data.get('bps', 0):,}원" if market_data.get('bps') else "BPS: N/A",
        f"",
        f"=== 시장 정보 ===",
        f"시가총액: {(market_data.get('mrkt_tot_amt', 0) // 100_000_000):,}억원" if market_data.get('mrkt_tot_amt') else "시가총액: N/A",
        f"상장주식수: {market_data.get('lstg_stqt', 0):,}주" if market_data.get('lstg_stqt') else "상장주식수: N/A",
    ]
    return "\n".join(lines)


def _signal_to_action(signal: SignalType) -> TradeAction:
    """Convert signal to trade action."""
    if signal in (SignalType.STRONG_BUY, SignalType.BUY):
        return TradeAction.BUY
    elif signal in (SignalType.STRONG_SELL, SignalType.SELL):
        return TradeAction.SELL
    return TradeAction.HOLD


def _extract_key_factors(response: str) -> list[str]:
    """Extract key factors from LLM response."""
    factors = []
    lines = response.split("\n")

    for line in lines:
        line = line.strip()
        if line.startswith(("-", "•", "*", "·")) or (line and line[0].isdigit() and "." in line[:3]):
            clean = line.lstrip("-•*·0123456789. ").strip()
            if clean and len(clean) > 10:
                factors.append(clean[:200])

    return factors[:5]


def _extract_bull_case(response: str) -> str:
    """Extract bull case from response."""
    lower = response.lower()
    keywords = ["bull", "상승", "긍정", "매수", "강점"]
    for keyword in keywords:
        if keyword in lower:
            start = lower.find(keyword)
            return response[start : start + 500]
    return ""


def _extract_bear_case(response: str) -> str:
    """Extract bear case from response."""
    lower = response.lower()
    keywords = ["bear", "하락", "부정", "매도", "약점", "리스크"]
    for keyword in keywords:
        if keyword in lower:
            start = lower.find(keyword)
            return response[start : start + 500]
    return ""
