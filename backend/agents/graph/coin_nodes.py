"""
LangGraph Node Functions for Coin Trading Workflow

Each node function receives the current state and returns state updates.
Nodes are executed in sequence as defined in the coin trading graph.
"""

import time
import uuid
from datetime import datetime
from typing import Literal

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.graph.coin_state import (
    CoinAnalysisResult,
    CoinAnalysisStage,
    CoinPosition,
    CoinTradeProposal,
    SignalType,
    TradeAction,
    add_coin_reasoning_log,
    calculate_coin_consensus_signal,
    coin_analysis_dict_to_context_string,
    get_all_coin_analyses,
)
from agents.llm_provider import get_llm_provider
from agents.prompts import (
    COIN_MARKET_ANALYST_PROMPT,
    COIN_RISK_ASSESSOR_PROMPT,
    COIN_SENTIMENT_ANALYST_PROMPT,
    COIN_STRATEGIC_DECISION_PROMPT,
    COIN_TECHNICAL_ANALYST_PROMPT,
)
from app.config import settings
from services.upbit import UpbitClient

logger = structlog.get_logger()


def _get_market_safely(state: dict, node_name: str) -> str:
    """Safely get market from state with detailed error logging."""
    market = state.get("market")
    if not market:
        logger.error(
            "state_missing_market",
            node=node_name,
            state_keys=list(state.keys()),
        )
        raise ValueError(f"State missing 'market' in {node_name}")
    return market


# -------------------------------------------
# Stage 1: Data Collection
# -------------------------------------------


async def coin_data_collection_node(state: dict) -> dict:
    """
    Fetch market data from Upbit API.
    This is the first node that gathers all necessary data.
    """
    start_time = time.perf_counter()
    market = _get_market_safely(state, "data_collection")

    logger.info(
        "node_started",
        node="coin_data_collection",
        market=market,
    )

    try:
        async with UpbitClient() as client:
            # Fetch comprehensive market data
            analysis_data = await client.get_analysis_data(
                market=market,
                candle_count=100,
                trade_count=50,
            )

            # Get orderbook
            orderbooks = await client.get_orderbook([market])
            orderbook = orderbooks[0] if orderbooks else None

            # Get recent trades
            trades = await client.get_trades(market, count=50)

        market_data = {
            "market": market,
            "current_price": analysis_data.current_price,
            "change_rate_24h": analysis_data.change_rate_24h,
            "volume_24h": analysis_data.volume_24h,
            "high_24h": analysis_data.high_24h,
            "low_24h": analysis_data.low_24h,
            "bid_ask_ratio": analysis_data.bid_ask_ratio,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # analysis_data.candles is already a list of dicts from get_analysis_data()
        candles = analysis_data.candles if analysis_data.candles else []
        orderbook_dict = orderbook.model_dump() if orderbook else None
        trades_list = [t.model_dump() for t in trades] if trades else []

        reasoning = (
            f"[Data Collection] {market}: "
            f"Price={analysis_data.current_price:,.0f} KRW, "
            f"24h={analysis_data.change_rate_24h:+.2f}%, "
            f"Volume={analysis_data.volume_24h:,.0f}"
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "node_completed",
            node="coin_data_collection",
            market=market,
            price=analysis_data.current_price,
            duration_ms=round(duration_ms, 2),
        )

        return {
            "market_data": market_data,
            "candles": candles,
            "orderbook": orderbook_dict,
            "trades": trades_list,
            "reasoning_log": add_coin_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
            "current_stage": CoinAnalysisStage.DATA_COLLECTION,
        }

    except Exception as e:
        error_msg = f"Data collection failed for {market}: {str(e)}"
        logger.error("coin_data_collection_failed", market=market, error=str(e))
        return {
            "error": error_msg,
            "reasoning_log": add_coin_reasoning_log(state, f"[Error] {error_msg}"),
            "current_stage": CoinAnalysisStage.COMPLETE,
        }


# -------------------------------------------
# Stage 2: Technical Analysis
# -------------------------------------------


async def coin_technical_analysis_node(state: dict) -> dict:
    """
    Cryptocurrency technical analysis.
    Analyzes price patterns, indicators, and orderbook.
    """
    start_time = time.perf_counter()
    market = _get_market_safely(state, "technical_analysis")
    llm = get_llm_provider()

    logger.info("node_started", node="coin_technical_analysis", market=market)

    # Get market data from state
    market_data = state.get("market_data", {})
    candles = state.get("candles", [])
    orderbook = state.get("orderbook", {})

    # Format market context for LLM
    market_context = _format_coin_market_context(market_data, candles, orderbook)

    # Calculate technical indicators
    indicators = _calculate_crypto_indicators(candles)

    messages = [
        SystemMessage(content=COIN_TECHNICAL_ANALYST_PROMPT),
        HumanMessage(content=f"Analyze {market}:\n\n{market_context}"),
    ]

    logger.debug("llm_request", node="coin_technical_analysis")
    llm_start = time.perf_counter()
    response = await llm.generate(messages)
    llm_duration = (time.perf_counter() - llm_start) * 1000
    logger.debug("llm_response", node="coin_technical_analysis", duration_ms=round(llm_duration, 2))

    # Determine signal from indicators
    signal = _determine_crypto_technical_signal(indicators, market_data)

    result = CoinAnalysisResult(
        agent_type="technical",
        market=market,
        signal=signal,
        confidence=0.75,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "trend": indicators.get("trend", "neutral"),
            "rsi": indicators.get("rsi"),
            "bid_ask_ratio": market_data.get("bid_ask_ratio"),
            "volume_24h": market_data.get("volume_24h"),
        },
    )

    reasoning = f"[Technical Analysis] {market}: {signal.value} (Confidence: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="coin_technical_analysis",
        market=market,
        signal=signal.value,
        duration_ms=round(duration_ms, 2),
    )

    return {
        "technical_analysis": result.model_dump(),
        "reasoning_log": add_coin_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": CoinAnalysisStage.TECHNICAL,
    }


# -------------------------------------------
# Stage 3: Market Analysis (replaces Fundamental for crypto)
# -------------------------------------------


async def coin_market_analysis_node(state: dict) -> dict:
    """
    Cryptocurrency market analysis.
    Analyzes volume, market structure, and BTC correlation.
    """
    start_time = time.perf_counter()
    market = _get_market_safely(state, "market_analysis")
    llm = get_llm_provider()

    logger.info("node_started", node="coin_market_analysis", market=market)

    market_data = state.get("market_data", {})
    korean_name = state.get("korean_name", market)

    # Format market analysis context
    market_context = f"""
=== Cryptocurrency Market Analysis ===
Market: {market}
Name: {korean_name}
Current Price: {market_data.get('current_price', 0):,.0f} KRW
24h Change: {market_data.get('change_rate_24h', 0):+.2f}%
24h Volume: {market_data.get('volume_24h', 0):,.0f} KRW
24h High: {market_data.get('high_24h', 0):,.0f} KRW
24h Low: {market_data.get('low_24h', 0):,.0f} KRW
Bid/Ask Ratio: {market_data.get('bid_ask_ratio', 1.0):.2f}
"""

    messages = [
        SystemMessage(content=COIN_MARKET_ANALYST_PROMPT),
        HumanMessage(content=f"Analyze market dynamics for {market}:\n\n{market_context}"),
    ]

    logger.debug("llm_request", node="coin_market_analysis")
    response = await llm.generate(messages)

    # Determine signal from market data
    signal = _determine_market_signal(market_data)

    result = CoinAnalysisResult(
        agent_type="market",
        market=market,
        signal=signal,
        confidence=0.70,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "volume_24h": market_data.get("volume_24h"),
            "change_rate_24h": market_data.get("change_rate_24h"),
            "bid_ask_ratio": market_data.get("bid_ask_ratio"),
        },
    )

    reasoning = f"[Market Analysis] {market}: {signal.value} (Confidence: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="coin_market_analysis", market=market, duration_ms=round(duration_ms, 2))

    return {
        "market_analysis": result.model_dump(),
        "reasoning_log": add_coin_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": CoinAnalysisStage.MARKET_ANALYSIS,
    }


# -------------------------------------------
# Stage 4: Sentiment Analysis
# -------------------------------------------


async def coin_sentiment_analysis_node(state: dict) -> dict:
    """
    Cryptocurrency sentiment analysis.
    Analyzes social media, news, and market psychology.
    """
    start_time = time.perf_counter()
    market = _get_market_safely(state, "sentiment_analysis")
    llm = get_llm_provider()

    logger.info("node_started", node="coin_sentiment_analysis", market=market)

    market_data = state.get("market_data", {})
    korean_name = state.get("korean_name", market)

    messages = [
        SystemMessage(content=COIN_SENTIMENT_ANALYST_PROMPT),
        HumanMessage(
            content=f"Analyze sentiment for {market} ({korean_name}). "
            f"Current price: {market_data.get('current_price', 0):,.0f} KRW, "
            f"24h change: {market_data.get('change_rate_24h', 0):+.2f}%"
        ),
    ]

    logger.debug("llm_request", node="coin_sentiment_analysis")
    response = await llm.generate(messages)

    # Default to neutral sentiment
    signal = SignalType.HOLD

    result = CoinAnalysisResult(
        agent_type="sentiment",
        market=market,
        signal=signal,
        confidence=0.60,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "news_sentiment": "neutral",
            "social_sentiment": "neutral",
            "fear_greed": "neutral",
        },
    )

    reasoning = f"[Sentiment Analysis] {market}: {signal.value} (Confidence: {result.confidence:.0%})"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="coin_sentiment_analysis", market=market, duration_ms=round(duration_ms, 2))

    return {
        "sentiment_analysis": result.model_dump(),
        "reasoning_log": add_coin_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": CoinAnalysisStage.SENTIMENT,
    }


# -------------------------------------------
# Stage 5: Risk Assessment
# -------------------------------------------


async def coin_risk_assessment_node(state: dict) -> dict:
    """
    Cryptocurrency risk assessment.
    Evaluates volatility, liquidity, and position sizing.
    """
    start_time = time.perf_counter()
    market = _get_market_safely(state, "risk_assessment")
    llm = get_llm_provider()

    logger.info("node_started", node="coin_risk_assessment", market=market)

    # Gather all previous analyses
    analyses = get_all_coin_analyses(state)
    analyses_context = "\n\n".join(coin_analysis_dict_to_context_string(a) for a in analyses)

    market_data = state.get("market_data", {})
    current_price = market_data.get("current_price", 0)

    messages = [
        SystemMessage(content=COIN_RISK_ASSESSOR_PROMPT),
        HumanMessage(
            content=f"Assess risk for {market} (Current: {current_price:,.0f} KRW):\n\n{analyses_context}"
        ),
    ]

    logger.debug("llm_request", node="coin_risk_assessment")
    response = await llm.generate(messages)

    # Calculate risk score
    risk_score = _calculate_crypto_risk_score(analyses, market_data)

    # Crypto-specific stop loss (wider due to volatility)
    stop_loss_pct = 0.08 if risk_score < 0.5 else 0.12  # 8% or 12%
    take_profit_pct = 0.15 if risk_score < 0.5 else 0.10  # 15% or 10%

    result = CoinAnalysisResult(
        agent_type="risk",
        market=market,
        signal=SignalType.HOLD,
        confidence=0.80,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response),
        signals={
            "risk_score": risk_score,
            "max_position_pct": 3.0 if risk_score < 0.5 else 2.0,  # Conservative for crypto
            "suggested_stop_loss": round(current_price * (1 - stop_loss_pct), 0),
            "suggested_take_profit": round(current_price * (1 + take_profit_pct), 0),
        },
    )

    reasoning = f"[Risk Assessment] {market}: Risk Score {risk_score:.0%}, Max Position {result.signals['max_position_pct']}%"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info("node_completed", node="coin_risk_assessment", market=market, risk_score=risk_score, duration_ms=round(duration_ms, 2))

    return {
        "risk_assessment": result.model_dump(),
        "reasoning_log": add_coin_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": CoinAnalysisStage.RISK,
    }


# -------------------------------------------
# Stage 6: Strategic Decision
# -------------------------------------------


async def coin_strategic_decision_node(state: dict) -> dict:
    """
    Synthesize all analyses into a coin trade proposal.
    """
    start_time = time.perf_counter()
    market = _get_market_safely(state, "strategic_decision")
    llm = get_llm_provider()

    logger.info("node_started", node="coin_strategic_decision", market=market)

    # Collect all analyses
    analyses = get_all_coin_analyses(state)
    analyses_context = "\n\n".join(coin_analysis_dict_to_context_string(a) for a in analyses)

    # Calculate consensus
    consensus_signal, avg_confidence = calculate_coin_consensus_signal(analyses)

    messages = [
        SystemMessage(content=COIN_STRATEGIC_DECISION_PROMPT),
        HumanMessage(
            content=f"Make trading decision for {market}:\n\n"
            f"Consensus Signal: {consensus_signal.value} (Avg Confidence: {avg_confidence:.0%})\n\n"
            f"{analyses_context}"
        ),
    ]

    logger.debug("llm_request", node="coin_strategic_decision")
    response = await llm.generate(messages)

    # Determine action from consensus
    action = _signal_to_action(consensus_signal)

    # Get risk parameters
    risk = state.get("risk_assessment", {})
    risk_signals = risk.get("signals", {})

    market_data = state.get("market_data", {})
    current_price = market_data.get("current_price", 0)
    position_size_pct = float(risk_signals.get("max_position_pct", 3.0))

    # Calculate quantity based on available KRW balance
    quantity = 0.0
    if action in (TradeAction.BUY, "BUY") and current_price > 0:
        try:
            # Get Upbit API credentials
            access_key = getattr(settings, "UPBIT_ACCESS_KEY", None)
            secret_key = getattr(settings, "UPBIT_SECRET_KEY", None)

            if access_key and secret_key:
                client = UpbitClient(access_key=access_key, secret_key=secret_key)
                accounts = await client.get_accounts()

                # Find KRW balance
                krw_balance = 0.0
                for account in accounts:
                    if account.currency == "KRW":
                        krw_balance = float(account.balance)
                        break

                # Calculate quantity: (KRW balance * position_size%) / price
                investment_amount = krw_balance * position_size_pct / 100
                quantity = investment_amount / current_price

                logger.info(
                    "coin_quantity_calculated",
                    market=market,
                    krw_balance=krw_balance,
                    position_size_pct=position_size_pct,
                    investment_amount=investment_amount,
                    current_price=current_price,
                    quantity=quantity,
                )
            else:
                logger.warning("coin_api_keys_not_configured", market=market)
        except Exception as e:
            logger.warning(
                "coin_quantity_calculation_failed",
                market=market,
                error=str(e),
            )
            # quantity remains 0, user can modify in approval dialog

    # Create trade proposal
    proposal = CoinTradeProposal(
        id=str(uuid.uuid4()),
        market=market,
        korean_name=state.get("korean_name"),
        action=action,
        quantity=quantity,
        entry_price=float(current_price),
        stop_loss=float(risk_signals.get("suggested_stop_loss", current_price * 0.92)),
        take_profit=float(risk_signals.get("suggested_take_profit", current_price * 1.15)),
        risk_score=float(risk_signals.get("risk_score", 0.5)),
        position_size_pct=position_size_pct,
        rationale=response,
        bull_case=_extract_bull_case(response),
        bear_case=_extract_bear_case(response),
        analyses=analyses,
    )

    reasoning = f"[Strategic Decision] Proposal: {action.value} {market} {quantity:.4f} @ {current_price:,.0f} KRW"

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "node_completed",
        node="coin_strategic_decision",
        market=market,
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
        "reasoning_log": add_coin_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
        "current_stage": CoinAnalysisStage.SYNTHESIS,
    }


# -------------------------------------------
# Stage 7: Human Approval
# -------------------------------------------


async def coin_human_approval_node(state: dict) -> dict:
    """
    Human-in-the-loop approval checkpoint for coin trades.
    """
    market = _get_market_safely(state, "human_approval")
    proposal = state.get("trade_proposal", {})

    proposal_id = proposal.get("id", "")[:8]
    proposal_action = proposal.get("action")

    logger.info(
        "node_started",
        node="coin_human_approval",
        market=market,
        proposal_id=proposal_id,
    )

    reasoning = f"[HITL] Awaiting human approval for {proposal_action} {market}..."

    return {
        "awaiting_approval": True,
        "current_stage": CoinAnalysisStage.APPROVAL,
        "reasoning_log": add_coin_reasoning_log(state, reasoning),
    }


async def coin_re_analyze_node(state: dict) -> dict:
    """
    Prepare for re-analysis after rejection.
    """
    market = _get_market_safely(state, "re_analyze")
    user_feedback = state.get("user_feedback", "")
    re_analyze_count = state.get("re_analyze_count", 0) + 1

    logger.info(
        "node_started",
        node="coin_re_analyze",
        market=market,
        re_analyze_count=re_analyze_count,
    )

    reasoning = f"[RE-ANALYSIS] User requested re-analysis (attempt #{re_analyze_count})"
    if user_feedback:
        reasoning += f"\nUser feedback: {user_feedback}"

    return {
        "current_stage": CoinAnalysisStage.DATA_COLLECTION,
        "technical_analysis": None,
        "market_analysis": None,
        "sentiment_analysis": None,
        "risk_assessment": None,
        "synthesis": None,
        "trade_proposal": None,
        "awaiting_approval": False,
        "approval_status": None,
        "re_analyze_count": re_analyze_count,
        "re_analyze_feedback": user_feedback,
        "reasoning_log": add_coin_reasoning_log(state, reasoning),
    }


# -------------------------------------------
# Stage 8: Execution
# -------------------------------------------


async def coin_execution_node(state: dict) -> dict:
    """
    Execute the approved coin trade.

    Supports two modes based on UPBIT_TRADING_MODE:
    - paper: Simulates trade execution (creates CoinPosition only)
    - live: Executes actual orders via Upbit API
    """
    proposal = state.get("trade_proposal", {})
    approval_status = state.get("approval_status")

    if approval_status != "approved" or not proposal:
        reasoning = f"[Execution] Trade not approved (status: {approval_status}). Skipping."
        return {
            "execution_status": "cancelled",
            "current_stage": CoinAnalysisStage.COMPLETE,
            "reasoning_log": add_coin_reasoning_log(state, reasoning),
        }

    market = proposal.get("market", "")
    action = proposal.get("action", "HOLD")
    entry_price = proposal.get("entry_price", 0)
    quantity = proposal.get("quantity", 0)

    logger.info(
        "coin_trade_execution_start",
        market=market,
        action=action,
        trading_mode=getattr(settings, "UPBIT_TRADING_MODE", "paper"),
    )

    if action == "HOLD" or action == TradeAction.HOLD:
        reasoning = f"[Execution] HOLD decision - no trade executed for {market}"
        return {
            "execution_status": "completed",
            "current_stage": CoinAnalysisStage.COMPLETE,
            "reasoning_log": add_coin_reasoning_log(state, reasoning),
        }

    # Check trading mode
    trading_mode = getattr(settings, "UPBIT_TRADING_MODE", "paper")

    if trading_mode == "live":
        # Live trading mode - execute actual order via Upbit API
        return await _execute_live_order(state, proposal, market, action, entry_price, quantity)
    else:
        # Paper trading mode - simulate trade execution
        return await _execute_paper_order(state, proposal, market, action, entry_price, quantity)


async def _execute_paper_order(
    state: dict,
    proposal: dict,
    market: str,
    action: str,
    entry_price: float,
    quantity: float,
) -> dict:
    """Execute simulated paper trade and save to storage."""
    from services.storage_service import get_storage_service

    # Extract currency from market (e.g., "KRW-BTC" -> "BTC")
    currency = market.split("-")[1] if "-" in market else market

    # Determine side based on action
    side = "bid" if action in ("BUY", TradeAction.BUY) else "ask"

    # Generate trade ID
    trade_id = f"paper-{uuid.uuid4()}"
    session_id = state.get("session_id")

    # Save trade to storage
    storage = await get_storage_service()
    await storage.save_coin_trade({
        "id": trade_id,
        "session_id": session_id,
        "market": market,
        "side": side,
        "order_type": "paper",
        "price": float(entry_price),
        "volume": float(quantity),
        "executed_volume": float(quantity),
        "fee": 0,
        "total_krw": float(entry_price * quantity),
        "state": "done",
        "order_uuid": trade_id,
    })

    # Save or update position for BUY orders
    if side == "bid":
        await storage.save_coin_position({
            "market": market,
            "currency": currency,
            "quantity": float(quantity),
            "avg_entry_price": float(entry_price),
            "stop_loss": proposal.get("stop_loss"),
            "take_profit": proposal.get("take_profit"),
            "session_id": session_id,
        })

    position = CoinPosition(
        market=market,
        quantity=quantity,
        entry_price=float(entry_price),
        current_price=float(entry_price),
        stop_loss=proposal.get("stop_loss"),
        take_profit=proposal.get("take_profit"),
    )

    reasoning = f"[Execution] (Paper) Trade simulated: {action} {market} @ {entry_price:,.0f} KRW, qty: {quantity}"

    logger.info(
        "paper_trade_executed",
        market=market,
        action=action,
        quantity=quantity,
        entry_price=entry_price,
        trade_id=trade_id,
    )

    return {
        "execution_status": "completed",
        "active_position": position.model_dump(),
        "trade_id": trade_id,
        "current_stage": CoinAnalysisStage.COMPLETE,
        "reasoning_log": add_coin_reasoning_log(state, reasoning),
        "messages": [AIMessage(content=reasoning)],
    }


async def _execute_live_order(
    state: dict,
    proposal: dict,
    market: str,
    action: str,
    entry_price: float,
    quantity: float,
) -> dict:
    """Execute live trade via Upbit API and save to storage."""
    from services.storage_service import get_storage_service

    # Extract currency from market (e.g., "KRW-BTC" -> "BTC")
    currency = market.split("-")[1] if "-" in market else market
    session_id = state.get("session_id")

    try:
        # Determine order parameters based on action
        if action == "BUY" or action == TradeAction.BUY:
            side = "bid"
            ord_type = "limit"
            price = entry_price
            volume = quantity
        elif action == "SELL" or action == TradeAction.SELL:
            side = "ask"
            ord_type = "limit"
            price = entry_price
            volume = quantity
        else:
            reasoning = f"[Execution] Unknown action: {action}"
            return {
                "execution_status": "failed",
                "error": f"Unknown action: {action}",
                "current_stage": CoinAnalysisStage.COMPLETE,
                "reasoning_log": add_coin_reasoning_log(state, reasoning),
            }

        # Create Upbit client and execute order
        async with UpbitClient(
            access_key=settings.UPBIT_ACCESS_KEY,
            secret_key=settings.UPBIT_SECRET_KEY,
        ) as client:
            # Place the order
            order = await client.place_order(
                market=market,
                side=side,
                ord_type=ord_type,
                price=price,
                volume=volume,
            )

            logger.info(
                "live_order_placed",
                order_uuid=order.uuid,
                market=order.market,
                side=order.side,
                state=order.state,
            )

            # Save trade to storage
            storage = await get_storage_service()
            trade_id = f"live-{order.uuid}"
            executed_volume = float(order.executed_volume) if order.executed_volume else 0
            exec_price = float(order.price) if order.price else float(entry_price)

            await storage.save_coin_trade({
                "id": trade_id,
                "session_id": session_id,
                "market": market,
                "side": side,
                "order_type": ord_type,
                "price": exec_price,
                "volume": float(quantity),
                "executed_volume": executed_volume,
                "fee": float(order.paid_fee) if order.paid_fee else 0,
                "total_krw": exec_price * executed_volume if executed_volume else exec_price * quantity,
                "state": order.state,
                "order_uuid": order.uuid,
            })

            # Save or update position for BUY orders (if order executed)
            if side == "bid" and order.state in ("done", "wait"):
                await storage.save_coin_position({
                    "market": market,
                    "currency": currency,
                    "quantity": executed_volume if executed_volume else float(quantity),
                    "avg_entry_price": exec_price,
                    "stop_loss": proposal.get("stop_loss"),
                    "take_profit": proposal.get("take_profit"),
                    "session_id": session_id,
                })

            # Create position record for state
            position = CoinPosition(
                market=market,
                quantity=quantity,
                entry_price=float(entry_price),
                current_price=float(entry_price),
                stop_loss=proposal.get("stop_loss"),
                take_profit=proposal.get("take_profit"),
            )

            reasoning = (
                f"[Execution] (Live) Order placed: {action} {market} @ {entry_price:,.0f} KRW, "
                f"qty: {quantity}, order_id: {order.uuid}, state: {order.state}"
            )

            return {
                "execution_status": "completed",
                "active_position": position.model_dump(),
                "order_uuid": order.uuid,
                "trade_id": trade_id,
                "order_state": order.state,
                "current_stage": CoinAnalysisStage.COMPLETE,
                "reasoning_log": add_coin_reasoning_log(state, reasoning),
                "messages": [AIMessage(content=reasoning)],
            }

    except Exception as e:
        error_msg = str(e)
        logger.error(
            "live_order_failed",
            market=market,
            action=action,
            error=error_msg,
        )

        reasoning = f"[Execution] Order failed: {error_msg}"

        return {
            "execution_status": "failed",
            "error": error_msg,
            "current_stage": CoinAnalysisStage.COMPLETE,
            "reasoning_log": add_coin_reasoning_log(state, reasoning),
            "messages": [AIMessage(content=reasoning)],
        }


# -------------------------------------------
# Conditional Edges
# -------------------------------------------


def should_continue_coin_execution(state: dict) -> Literal["execute", "re_analyze", "end"]:
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


def _format_coin_market_context(market_data: dict, candles: list, orderbook: dict) -> str:
    """Format coin market data for LLM context."""
    lines = [
        "=== Market Data ===",
        f"Current Price: {market_data.get('current_price', 0):,.0f} KRW",
        f"24h Change: {market_data.get('change_rate_24h', 0):+.2f}%",
        f"24h High: {market_data.get('high_24h', 0):,.0f} KRW",
        f"24h Low: {market_data.get('low_24h', 0):,.0f} KRW",
        f"24h Volume: {market_data.get('volume_24h', 0):,.0f} KRW",
        f"Bid/Ask Ratio: {market_data.get('bid_ask_ratio', 1.0):.2f}",
        "",
    ]

    # Recent candles summary (keys from CoinAnalysisData: date, open, high, low, close, volume)
    if candles and len(candles) >= 5:
        lines.append("=== Recent Price Action (Last 5 candles) ===")
        for c in candles[:5]:
            lines.append(
                f"{c.get('date', 'N/A')}: "
                f"O={c.get('open', 0):,.0f} "
                f"H={c.get('high', 0):,.0f} "
                f"L={c.get('low', 0):,.0f} "
                f"C={c.get('close', 0):,.0f}"
            )
        lines.append("")

    # Orderbook summary
    if orderbook:
        lines.append("=== Orderbook ===")
        lines.append(f"Total Ask Size: {orderbook.get('total_ask_size', 0):.4f}")
        lines.append(f"Total Bid Size: {orderbook.get('total_bid_size', 0):.4f}")

    return "\n".join(lines)


def _calculate_crypto_indicators(candles: list) -> dict:
    """Calculate technical indicators from candle data."""
    if not candles or len(candles) < 14:
        return {"trend": "neutral"}

    try:
        # Extract close prices (key is 'close' from CoinAnalysisData)
        closes = [c.get("close", 0) for c in candles]

        # Simple trend detection
        recent_avg = sum(closes[:10]) / 10
        older_avg = sum(closes[10:20]) / 10 if len(closes) >= 20 else recent_avg

        if recent_avg > older_avg * 1.02:
            trend = "bullish"
        elif recent_avg < older_avg * 0.98:
            trend = "bearish"
        else:
            trend = "neutral"

        # Simple RSI approximation (14-period)
        gains = []
        losses = []
        for i in range(1, min(15, len(closes))):
            diff = closes[i-1] - closes[i]  # Note: candles are newest first
            if diff > 0:
                gains.append(diff)
            else:
                losses.append(abs(diff))

        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0.01
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))

        return {
            "trend": trend,
            "rsi": round(rsi, 2),
        }
    except Exception:
        return {"trend": "neutral"}


def _determine_crypto_technical_signal(indicators: dict, market_data: dict) -> SignalType:
    """Determine signal from crypto technical indicators."""
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

    # Bid/Ask ratio
    bid_ask = market_data.get("bid_ask_ratio", 1.0)
    if bid_ask > 1.2:
        score += 1
    elif bid_ask < 0.8:
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


def _determine_market_signal(market_data: dict) -> SignalType:
    """Determine signal from market data."""
    score = 0

    change_rate = market_data.get("change_rate_24h", 0)
    if change_rate > 5:
        score += 1
    elif change_rate < -5:
        score -= 1

    bid_ask = market_data.get("bid_ask_ratio", 1.0)
    if bid_ask > 1.2:
        score += 1
    elif bid_ask < 0.8:
        score -= 1

    if score >= 2:
        return SignalType.BUY
    elif score <= -2:
        return SignalType.SELL
    return SignalType.HOLD


def _calculate_crypto_risk_score(analyses: list, market_data: dict) -> float:
    """Calculate risk score for crypto (higher base risk than stocks)."""
    base_risk = 0.4  # Crypto has higher base risk

    # Add risk for high volatility
    change_rate = abs(market_data.get("change_rate_24h", 0))
    volatility_risk = min(change_rate / 20, 0.3)  # Up to 0.3 for 20%+ daily change

    # Add risk for signal disagreement
    if len(analyses) >= 2:
        signals = [a.get("signal", "hold") for a in analyses if a.get("agent_type") != "risk"]
        unique_signals = set(signals)
        disagreement_risk = (len(unique_signals) - 1) * 0.1
    else:
        disagreement_risk = 0

    return min(round(base_risk + volatility_risk + disagreement_risk, 2), 1.0)


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
        if line.startswith(("-", "•", "*")) or (line and line[0].isdigit() and "." in line[:3]):
            clean = line.lstrip("-•*0123456789. ").strip()
            if clean and len(clean) > 10:
                factors.append(clean[:200])

    return factors[:5]


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
