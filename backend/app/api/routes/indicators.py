"""
Technical Indicators API Routes

Provides REST API endpoints for technical indicator calculations.

Endpoints:
    GET /api/indicators/kr/{stk_cd} - Korean stock indicators
    GET /api/indicators/coin/{market} - Cryptocurrency indicators
"""

from typing import Any, Optional

import pandas as pd
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agents.tools.kr_market_data import get_kr_daily_chart
from services.technical_indicators import (
    Signal,
    TechnicalIndicators,
    calculate_indicators_for_ticker,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/indicators", tags=["indicators"])


# =========================================
# Response Models
# =========================================


class MovingAveragesResponse(BaseModel):
    """Moving averages data."""
    sma_5: Optional[float] = None
    sma_20: Optional[float] = None
    sma_60: Optional[float] = None
    sma_120: Optional[float] = None


class MomentumResponse(BaseModel):
    """Momentum indicators."""
    rsi: Optional[float] = None
    rsi_signal: str = "neutral"
    stochastic_k: Optional[float] = None
    stochastic_d: Optional[float] = None


class MACDResponse(BaseModel):
    """MACD indicator values."""
    line: Optional[float] = None
    signal: Optional[float] = None
    histogram: Optional[float] = None


class BollingerBandsResponse(BaseModel):
    """Bollinger Bands values."""
    upper: Optional[float] = None
    middle: Optional[float] = None
    lower: Optional[float] = None
    width_pct: Optional[float] = None


class VolatilityResponse(BaseModel):
    """Volatility metrics."""
    atr: Optional[float] = None
    daily_pct: Optional[float] = None


class VolumeResponse(BaseModel):
    """Volume metrics."""
    current: Optional[float] = None
    avg_20: Optional[float] = None
    ratio: Optional[float] = None


class LevelsResponse(BaseModel):
    """Support/Resistance levels."""
    support_20d: Optional[float] = None
    resistance_20d: Optional[float] = None


class TrendResponse(BaseModel):
    """Trend information."""
    direction: str = "neutral"
    price_vs_sma20_pct: Optional[float] = None


class SignalResponse(BaseModel):
    """Trading signal."""
    type: str  # "opportunity", "warning", "info"
    source: str  # "RSI", "MACD", "MA Cross", etc.
    signal: str  # "strong_buy", "buy", "neutral", "sell", "strong_sell"
    value: Optional[float] = None
    description: str


class IndicatorsResponse(BaseModel):
    """Complete technical indicators response."""
    ticker: str
    current_price: float
    moving_averages: MovingAveragesResponse
    momentum: MomentumResponse
    macd: MACDResponse
    bollinger_bands: BollingerBandsResponse
    volatility: VolatilityResponse
    volume: VolumeResponse
    levels: LevelsResponse
    trend: TrendResponse
    signals: list[SignalResponse] = Field(default_factory=list)


class IndicatorsSummaryResponse(BaseModel):
    """Simple summary response."""
    ticker: str
    recommendation: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0-100
    key_signals: list[str]
    summary: str


# =========================================
# Helper Functions
# =========================================


def _normalize_signal(signal_value: Any) -> str:
    """Convert Signal enum or string to string value."""
    if signal_value is None:
        return "neutral"
    if isinstance(signal_value, Signal):
        return signal_value.value
    if hasattr(signal_value, "value"):
        return signal_value.value
    return str(signal_value) if signal_value else "neutral"


# =========================================
# Endpoints
# =========================================


@router.get("/kr/{stk_cd}", response_model=IndicatorsResponse)
async def get_kr_stock_indicators(
    stk_cd: str,
    period: int = Query(default=100, ge=20, le=365, description="Number of days for calculation"),
):
    """
    Get technical indicators for a Korean stock.

    Args:
        stk_cd: Stock code (e.g., "005930" for Samsung Electronics)
        period: Number of days to fetch (default: 100, min: 20, max: 365)

    Returns:
        Complete technical indicators including RSI, MACD, Bollinger Bands, etc.
    """
    try:
        logger.info("fetching_kr_indicators", stk_cd=stk_cd, period=period)

        # Fetch price data
        df = await get_kr_daily_chart(stk_cd)

        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for stock: {stk_cd}")

        # Limit to requested period
        if len(df) > period:
            df = df.tail(period)

        # Calculate indicators
        result = calculate_indicators_for_ticker(df)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        # Convert signals to response format
        signals = [
            SignalResponse(
                type=s.get("type", "info"),
                source=s.get("source", ""),
                signal=_normalize_signal(s.get("signal")),
                value=s.get("value"),
                description=s.get("description", ""),
            )
            for s in result.get("signals", [])
        ]

        return IndicatorsResponse(
            ticker=stk_cd,
            current_price=result["current_price"],
            moving_averages=MovingAveragesResponse(**result["moving_averages"]),
            momentum=MomentumResponse(**result["momentum"]),
            macd=MACDResponse(**result["macd"]),
            bollinger_bands=BollingerBandsResponse(**result["bollinger_bands"]),
            volatility=VolatilityResponse(**result["volatility"]),
            volume=VolumeResponse(**result["volume"]),
            levels=LevelsResponse(**result["levels"]),
            trend=TrendResponse(**result["trend"]),
            signals=signals,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("kr_indicators_error", stk_cd=stk_cd, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to calculate indicators: {str(e)}")


@router.get("/kr/{stk_cd}/summary", response_model=IndicatorsSummaryResponse)
async def get_kr_stock_indicators_summary(stk_cd: str):
    """
    Get simplified technical analysis summary for a Korean stock.

    Returns a recommendation (BUY/SELL/HOLD) with confidence score.
    """
    try:
        logger.info("fetching_kr_indicators_summary", stk_cd=stk_cd)

        # Fetch price data
        df = await get_kr_daily_chart(stk_cd)

        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for stock: {stk_cd}")

        # Calculate indicators
        indicators = TechnicalIndicators(df)
        result = indicators.calculate_all()

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        # Calculate recommendation based on signals
        signals = result.get("signals", [])
        buy_score = 0
        sell_score = 0

        for sig in signals:
            signal_value = _normalize_signal(sig.get("signal"))

            if signal_value in ("strong_buy", "buy"):
                buy_score += 2 if signal_value == "strong_buy" else 1
            elif signal_value in ("strong_sell", "sell"):
                sell_score += 2 if signal_value == "strong_sell" else 1

        # Determine recommendation
        if buy_score > sell_score + 1:
            recommendation = "BUY"
            confidence = min(70 + buy_score * 5, 95)
        elif sell_score > buy_score + 1:
            recommendation = "SELL"
            confidence = min(70 + sell_score * 5, 95)
        else:
            recommendation = "HOLD"
            confidence = 50 + abs(buy_score - sell_score) * 10

        # Extract key signals
        key_signals = [s.get("description", "") for s in signals[:5]]

        # Create summary
        trend = result.get("trend", {}).get("direction", "neutral")
        rsi = result.get("momentum", {}).get("rsi", 0)
        rsi_status = "과매수" if rsi > 70 else "과매도" if rsi < 30 else "중립"

        summary = f"추세: {trend}, RSI({rsi:.1f}): {rsi_status}"

        return IndicatorsSummaryResponse(
            ticker=stk_cd,
            recommendation=recommendation,
            confidence=confidence,
            key_signals=key_signals,
            summary=summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("kr_indicators_summary_error", stk_cd=stk_cd, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")


@router.get("/coin/{market}")
async def get_coin_indicators(
    market: str,
    period: int = Query(default=100, ge=20, le=365, description="Number of days for calculation"),
):
    """
    Get technical indicators for a cryptocurrency.

    Args:
        market: Market code (e.g., "KRW-BTC" for Bitcoin in KRW)
        period: Number of days to fetch (default: 100)

    Returns:
        Complete technical indicators
    """
    # Import here to avoid circular dependency
    from services.upbit import UpbitClient

    try:
        logger.info("fetching_coin_indicators", market=market, period=period)

        # Fetch price data from Upbit
        client = UpbitClient()
        candles = await client.get_candles_days(market, count=min(period, 200))

        if not candles:
            raise HTTPException(status_code=404, detail=f"No data found for market: {market}")

        # Convert to DataFrame
        df = pd.DataFrame([
            {
                "open": c.opening_price,
                "high": c.high_price,
                "low": c.low_price,
                "close": c.trade_price,
                "volume": c.candle_acc_trade_volume,
            }
            for c in candles
        ])

        # Reverse to chronological order (Upbit returns newest first)
        df = df.iloc[::-1].reset_index(drop=True)

        # Calculate indicators
        result = calculate_indicators_for_ticker(df)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        # Normalize signal values in response
        if "signals" in result:
            result["signals"] = [
                {
                    **s,
                    "signal": _normalize_signal(s.get("signal")),
                }
                for s in result["signals"]
            ]

        return {
            "market": market,
            **result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("coin_indicators_error", market=market, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to calculate indicators: {str(e)}")
