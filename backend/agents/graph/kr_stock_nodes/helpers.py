"""
Helper Functions for Korean Stock Trading Nodes

Contains signal determination, confidence calculation, utility functions,
and core analysis logic shared between sequential and parallel execution.
"""

from typing import TYPE_CHECKING

import pandas as pd
import structlog

from agents.graph.kr_stock_state import KRStockAnalysisResult, SignalType, TradeAction

if TYPE_CHECKING:
    from agents.llm_provider import LLMProvider

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


def _determine_kr_fundamental_signal(market_data: dict) -> tuple[SignalType, float]:
    """
    Determine signal and confidence from Korean stock fundamental data.

    Returns:
        Tuple of (signal, confidence)
    """
    score = 0
    data_points = 0  # Track available data for confidence calculation

    # PER (Korean market average ~12-15)
    per = market_data.get("per")
    if per is not None and per > 0:
        data_points += 1
        if per < 8:
            score += 2.5  # Very undervalued
        elif per < 10:
            score += 2
        elif per < 15:
            score += 1
        elif per > 50:
            score -= 2
        elif per > 30:
            score -= 1

    # PBR (Korean market average ~1.0)
    pbr = market_data.get("pbr")
    if pbr is not None and pbr > 0:
        data_points += 1
        if pbr < 0.5:
            score += 2  # Very undervalued
        elif pbr < 0.7:
            score += 1.5
        elif pbr < 1.0:
            score += 0.5
        elif pbr > 5:
            score -= 2
        elif pbr > 3:
            score -= 1

    # EPS (earnings per share) - positive is good
    eps = market_data.get("eps")
    if eps is not None:
        data_points += 1
        if eps > 0:
            score += 0.5  # Profitable
        elif eps < 0:
            score -= 1  # Loss-making

    # Calculate confidence based on data availability
    base_confidence = 0.50
    data_bonus = min(data_points * 0.10, 0.30)  # Up to 0.30 for 3 data points
    signal_strength_bonus = min(abs(score) * 0.05, 0.15)  # Up to 0.15 for strong signals
    confidence = min(base_confidence + data_bonus + signal_strength_bonus, 0.90)

    # Map score to signal (improved thresholds)
    if score >= 4:
        return SignalType.STRONG_BUY, confidence
    elif score >= 2:
        return SignalType.BUY, confidence
    elif score <= -3:
        return SignalType.STRONG_SELL, confidence
    elif score <= -1.5:
        return SignalType.SELL, confidence
    return SignalType.HOLD, confidence


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
    """Convert signal to trade action (without position context)."""
    if signal in (SignalType.STRONG_BUY, SignalType.BUY):
        return TradeAction.BUY
    elif signal in (SignalType.STRONG_SELL, SignalType.SELL):
        return TradeAction.SELL
    return TradeAction.HOLD


def _signal_to_action_with_position(
    signal: SignalType,
    has_position: bool,
    position_pnl_pct: float = 0.0,
) -> TradeAction:
    """
    Convert signal to trade action considering existing position.

    Args:
        signal: Analysis consensus signal
        has_position: True if user already holds this stock
        position_pnl_pct: Current position profit/loss percentage

    Returns:
        Appropriate TradeAction based on signal and position context
    """
    if has_position:
        # User already holds this stock
        if signal in (SignalType.STRONG_BUY, SignalType.BUY):
            # Positive signal + holding -> ADD more or HOLD
            if position_pnl_pct < 0:
                # Currently at loss - good opportunity to average down
                return TradeAction.ADD
            elif position_pnl_pct > 20:
                # Big profit - hold and watch
                return TradeAction.HOLD
            else:
                # Small profit - can add more
                return TradeAction.ADD
        elif signal in (SignalType.STRONG_SELL, SignalType.SELL):
            # Negative signal + holding -> SELL or REDUCE
            if signal == SignalType.STRONG_SELL:
                return TradeAction.SELL  # Full sell
            else:
                return TradeAction.REDUCE  # Partial sell
        else:
            # HOLD signal + holding -> maintain position
            return TradeAction.HOLD
    else:
        # User doesn't hold this stock
        if signal in (SignalType.STRONG_BUY, SignalType.BUY):
            return TradeAction.BUY  # New buy
        elif signal == SignalType.STRONG_SELL:
            return TradeAction.AVOID  # Strong negative - avoid buying
        elif signal == SignalType.SELL:
            return TradeAction.WATCH  # Negative but not critical - watch
        else:
            # HOLD signal + no position -> watch (user can buy if interested)
            return TradeAction.WATCH


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


# =============================================================================
# Core Analysis Functions (Shared between sequential and parallel execution)
# =============================================================================


def _prepare_chart_dataframe(chart_data: list) -> pd.DataFrame:
    """
    Convert chart data list to DataFrame with proper date index.

    Args:
        chart_data: List of chart data dictionaries

    Returns:
        DataFrame with date index, or empty DataFrame if no data
    """
    if not chart_data:
        return pd.DataFrame()

    df = pd.DataFrame(chart_data)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    if not df.empty:
        df.set_index("date", inplace=True)

    return df


def _calculate_enhanced_indicators(df: pd.DataFrame) -> tuple[dict, list]:
    """
    Calculate enhanced technical indicators using TechnicalIndicators service.

    Args:
        df: DataFrame with OHLCV data

    Returns:
        Tuple of (enhanced_indicators dict, detected_signals list)
    """
    if df.empty or len(df) < 20:
        return {}, []

    try:
        from services.technical_indicators import TechnicalIndicators

        tech_service = TechnicalIndicators(df)
        enhanced_indicators = tech_service.calculate_all()
        detected_signals = enhanced_indicators.get("signals", [])
        return enhanced_indicators, detected_signals
    except Exception as e:
        logger.warning("enhanced_indicators_failed", error=str(e))
        return {}, []


def _format_detected_signals_text(detected_signals: list) -> str:
    """Format detected signals as text for LLM prompt."""
    if not detected_signals:
        return ""

    text = "\n\n=== 감지된 시그널 ===\n"
    for sig in detected_signals:
        text += f"• {sig.get('description', '')}\n"
    return text


async def _send_telegram_notification(
    stk_cd: str,
    stk_nm: str,
    agent_type: str,
    signal: str,
    confidence: float,
    key_factors: list[str],
) -> None:
    """
    Send Telegram notification for sub-agent decision.

    Silently handles errors to not disrupt analysis flow.
    """
    try:
        from services.telegram import get_telegram_notifier

        telegram = await get_telegram_notifier()
        if telegram.is_ready:
            await telegram.send_subagent_decision(
                ticker=stk_cd,
                stock_name=stk_nm,
                agent_type=agent_type,
                signal=signal,
                confidence=confidence,
                key_factors=key_factors[:5],
            )
    except Exception as e:
        logger.debug("telegram_notification_skipped", agent=agent_type, error=str(e))


async def analyze_technical_core(state: dict) -> KRStockAnalysisResult:
    """
    Core technical analysis logic.

    Shared between kr_stock_technical_analysis_node and parallel analysis.

    Args:
        state: Analysis state with market_data, chart_df, orderbook

    Returns:
        KRStockAnalysisResult with technical analysis
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.llm_provider import get_llm_provider
    from agents.prompts import KR_STOCK_TECHNICAL_ANALYST_PROMPT
    from agents.tools.kr_market_data import (
        calculate_kr_technical_indicators,
        format_kr_market_data_for_llm,
    )

    stk_cd = state.get("stk_cd", "")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    market_data = state.get("market_data", {})
    chart_data = state.get("chart_df", [])
    orderbook = state.get("orderbook", {})

    # Prepare DataFrame
    df = _prepare_chart_dataframe(chart_data)

    # Calculate indicators
    market_context = format_kr_market_data_for_llm(market_data, df, orderbook)
    indicators = calculate_kr_technical_indicators(df)
    enhanced_indicators, detected_signals = _calculate_enhanced_indicators(df)

    # Format signals for LLM
    signals_text = _format_detected_signals_text(detected_signals)

    # LLM analysis
    messages = [
        SystemMessage(content=KR_STOCK_TECHNICAL_ANALYST_PROMPT),
        HumanMessage(
            content=f"{stk_nm} ({stk_cd}) 기술적 분석:\n\n{market_context}{signals_text}"
        ),
    ]
    response = await llm.generate(messages)

    # Determine signal and confidence
    signal = _determine_kr_stock_technical_signal_enhanced(
        indicators, orderbook, detected_signals
    )
    confidence = _calculate_technical_confidence(detected_signals, indicators)

    # Build result
    result = KRStockAnalysisResult(
        agent_type="technical",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        signal=signal,
        confidence=confidence,
        summary=response[:500] if len(response) > 500 else response,
        reasoning=response,
        key_factors=_extract_key_factors(response)
        + [s.get("description", "") for s in detected_signals[:3]],
        signals={
            "trend": enhanced_indicators.get("trend", {}).get(
                "direction", indicators.get("trend", "neutral")
            ),
            "rsi": enhanced_indicators.get("momentum", {}).get(
                "rsi", indicators.get("rsi")
            ),
            "macd_histogram": enhanced_indicators.get("macd", {}).get(
                "histogram", indicators.get("macd", {}).get("histogram")
            ),
            "bid_ask_ratio": orderbook.get("bid_ask_ratio"),
            "volume_ratio": enhanced_indicators.get("volume", {}).get(
                "ratio", indicators.get("volume_ratio")
            ),
            "cross": indicators.get("cross"),
        },
    )

    # Send Telegram notification
    await _send_telegram_notification(
        stk_cd, stk_nm, "technical", signal.value, confidence, result.key_factors
    )

    return result


async def analyze_fundamental_core(state: dict) -> KRStockAnalysisResult:
    """
    Core fundamental analysis logic.

    Shared between kr_stock_fundamental_analysis_node and parallel analysis.

    Args:
        state: Analysis state with market_data

    Returns:
        KRStockAnalysisResult with fundamental analysis
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.llm_provider import get_llm_provider
    from agents.prompts import KR_STOCK_FUNDAMENTAL_ANALYST_PROMPT

    stk_cd = state.get("stk_cd", "")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    market_data = state.get("market_data", {})
    fundamental_context = _format_kr_fundamental_data(market_data)

    # LLM analysis
    messages = [
        SystemMessage(content=KR_STOCK_FUNDAMENTAL_ANALYST_PROMPT),
        HumanMessage(content=f"{stk_nm} ({stk_cd}) 기본적 분석:\n\n{fundamental_context}"),
    ]
    response = await llm.generate(messages)

    # Determine signal and confidence
    signal, confidence = _determine_kr_fundamental_signal(market_data)

    # Build result
    result = KRStockAnalysisResult(
        agent_type="fundamental",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        signal=signal,
        confidence=confidence,
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

    # Send Telegram notification
    await _send_telegram_notification(
        stk_cd, stk_nm, "fundamental", signal.value, confidence, result.key_factors
    )

    return result


async def analyze_sentiment_core(state: dict) -> KRStockAnalysisResult:
    """
    Core sentiment analysis logic.

    Shared between kr_stock_sentiment_analysis_node and parallel analysis.

    Args:
        state: Analysis state with market_data

    Returns:
        KRStockAnalysisResult with sentiment analysis
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.llm_provider import get_llm_provider
    from agents.prompts import KR_STOCK_SENTIMENT_ANALYST_PROMPT

    stk_cd = state.get("stk_cd", "")
    stk_nm = state.get("stk_nm", stk_cd)
    llm = get_llm_provider()

    market_data = state.get("market_data", {})
    news_sentiment = None
    news_articles = []

    # Try to fetch and analyze real news
    try:
        from app.dependencies import get_news_service
        from services.news import NewsSentimentAnalyzer

        news_service = await get_news_service()
        if news_service.providers:
            search_result = await news_service.search_stock_news(
                stock_code=stk_cd,
                stock_name=stk_nm,
                count=100,
            )
            news_articles = search_result.articles

            if news_articles:
                analyzer = NewsSentimentAnalyzer(llm)
                news_sentiment = await analyzer.analyze(
                    articles=news_articles,
                    stock_name=stk_nm,
                    stock_code=stk_cd,
                )
    except Exception as e:
        logger.warning("news_fetch_failed", stk_cd=stk_cd, error=str(e))

    # Determine signal based on news or fallback to momentum
    if news_sentiment:
        if news_sentiment.recommendation == "BUY":
            signal = SignalType.BUY
        elif news_sentiment.recommendation == "SELL":
            signal = SignalType.SELL
        else:
            signal = SignalType.HOLD

        confidence = news_sentiment.confidence
        summary = news_sentiment.summary
        key_factors = (
            news_sentiment.positive_factors[:3]
            + news_sentiment.risk_factors[:2]
            + news_sentiment.key_topics[:2]
        )
        sentiment_value = news_sentiment.sentiment
        sentiment_score = news_sentiment.score
    else:
        # Fallback: Use price momentum as proxy
        change_rate = market_data.get("prdy_ctrt", 0)
        if change_rate >= 5:
            signal = SignalType.BUY
            sentiment_value = "positive"
            sentiment_score = min(change_rate * 10, 80)
        elif change_rate >= 2:
            signal = SignalType.BUY
            sentiment_value = "slightly_positive"
            sentiment_score = 40
        elif change_rate <= -5:
            signal = SignalType.SELL
            sentiment_value = "negative"
            sentiment_score = max(change_rate * 10, -80)
        elif change_rate <= -2:
            signal = SignalType.SELL
            sentiment_value = "slightly_negative"
            sentiment_score = -40
        else:
            signal = SignalType.HOLD
            sentiment_value = "neutral"
            sentiment_score = 0

        confidence = 0.40
        summary = f"{stk_nm} 뉴스 데이터 없음. 가격 모멘텀 기반 심리 추정."
        key_factors = ["뉴스 미확보", f"전일대비 {change_rate:+.2f}%"]

    # LLM additional analysis
    messages = [
        SystemMessage(content=KR_STOCK_SENTIMENT_ANALYST_PROMPT),
        HumanMessage(
            content=f"{stk_nm} ({stk_cd}) 시장심리 분석.\n"
            f"현재가: {market_data.get('cur_prc', 0):,}원\n"
            f"전일대비: {market_data.get('prdy_ctrt', 0):+.2f}%\n"
            f"뉴스 감성: {sentiment_value} (점수: {sentiment_score})\n"
        ),
    ]
    llm_response = await llm.generate(messages)

    # Combine summaries
    combined_summary = summary
    if llm_response and len(llm_response) > 50:
        combined_summary = f"{summary}\n\n추가 분석: {llm_response[:400]}"

    # Build result
    result = KRStockAnalysisResult(
        agent_type="sentiment",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        signal=signal,
        confidence=confidence,
        summary=combined_summary[:800] if len(combined_summary) > 800 else combined_summary,
        reasoning=llm_response if llm_response else summary,
        key_factors=key_factors[:5] + _extract_key_factors(llm_response)[:3],
        signals={
            "news_sentiment": sentiment_value,
            "news_score": sentiment_score,
            "news_count": len(news_articles),
        },
    )

    # Send Telegram notification
    await _send_telegram_notification(
        stk_cd, stk_nm, "sentiment", signal.value, confidence, result.key_factors
    )

    return result
