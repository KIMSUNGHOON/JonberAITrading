"""
Market Data Tool

Provides market data fetching with yfinance and fallback to mock data.
Supports both live and mock modes for development/testing.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

# Data directory for mock data
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "mock"


def get_market_data_mode() -> str:
    """Get market data mode from settings."""
    try:
        from app.config import settings
        return settings.MARKET_DATA_MODE
    except ImportError:
        return "mock"


async def get_market_data(
    ticker: str,
    period: str = "3mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Fetch market data for a ticker.

    Args:
        ticker: Stock symbol (e.g., "AAPL")
        period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd, max)
        interval: Data interval (1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo)

    Returns:
        DataFrame with OHLCV data (Open, High, Low, Close, Volume)
    """
    mode = get_market_data_mode()

    if mode == "mock":
        return _generate_mock_data(ticker, period)

    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)

        if df.empty:
            logger.warning(
                "yfinance_empty_response",
                ticker=ticker,
                period=period,
            )
            return _generate_mock_data(ticker, period)

        logger.info(
            "market_data_fetched",
            ticker=ticker,
            rows=len(df),
            period=period,
        )
        return df

    except Exception as e:
        logger.error(
            "yfinance_error",
            ticker=ticker,
            error=str(e),
        )
        return _generate_mock_data(ticker, period)


async def get_ticker_info(ticker: str) -> dict:
    """
    Get basic ticker information.

    Args:
        ticker: Stock symbol

    Returns:
        Dictionary with company info
    """
    mode = get_market_data_mode()

    if mode == "mock":
        return _get_mock_ticker_info(ticker)

    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        info = stock.info

        logger.info("ticker_info_fetched", ticker=ticker)
        return info

    except Exception as e:
        logger.error(
            "ticker_info_error",
            ticker=ticker,
            error=str(e),
        )
        return _get_mock_ticker_info(ticker)


async def get_current_price(ticker: str) -> float:
    """Get current price for a ticker."""
    mode = get_market_data_mode()

    if mode == "mock":
        # Generate consistent mock price based on ticker
        np.random.seed(hash(ticker) % 2**32)
        return round(np.random.uniform(50, 500), 2)

    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        # Try to get real-time price, fall back to last close
        info = stock.info
        price = info.get("regularMarketPrice") or info.get("previousClose", 100.0)
        return float(price)

    except Exception as e:
        logger.error("current_price_error", ticker=ticker, error=str(e))
        np.random.seed(hash(ticker) % 2**32)
        return round(np.random.uniform(50, 500), 2)


def calculate_technical_indicators(df: pd.DataFrame) -> dict:
    """
    Calculate common technical indicators from price data.

    Args:
        df: DataFrame with OHLCV data

    Returns:
        Dictionary with calculated indicators
    """
    if df.empty or len(df) < 20:
        return {}

    close = df["Close"]

    # Simple Moving Averages
    sma_20 = close.rolling(window=20).mean().iloc[-1]
    sma_50 = close.rolling(window=50).mean().iloc[-1] if len(df) >= 50 else None

    # RSI (14-period)
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs)).iloc[-1]

    # MACD
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_histogram = macd_line - signal_line

    # Bollinger Bands
    bb_middle = close.rolling(window=20).mean()
    bb_std = close.rolling(window=20).std()
    bb_upper = bb_middle + (bb_std * 2)
    bb_lower = bb_middle - (bb_std * 2)

    # Volume analysis
    volume = df["Volume"]
    avg_volume = volume.rolling(window=20).mean().iloc[-1]
    volume_ratio = volume.iloc[-1] / avg_volume if avg_volume > 0 else 1.0

    # Trend detection
    current_price = close.iloc[-1]
    price_vs_sma20 = (current_price - sma_20) / sma_20 * 100 if sma_20 else 0

    # Support/Resistance (simplified)
    recent_low = close.tail(20).min()
    recent_high = close.tail(20).max()

    return {
        "current_price": round(current_price, 2),
        "sma_20": round(sma_20, 2) if pd.notna(sma_20) else None,
        "sma_50": round(sma_50, 2) if sma_50 and pd.notna(sma_50) else None,
        "rsi": round(rsi, 2) if pd.notna(rsi) else None,
        "macd": {
            "line": round(macd_line.iloc[-1], 4) if pd.notna(macd_line.iloc[-1]) else None,
            "signal": round(signal_line.iloc[-1], 4) if pd.notna(signal_line.iloc[-1]) else None,
            "histogram": round(macd_histogram.iloc[-1], 4) if pd.notna(macd_histogram.iloc[-1]) else None,
        },
        "bollinger": {
            "upper": round(bb_upper.iloc[-1], 2) if pd.notna(bb_upper.iloc[-1]) else None,
            "middle": round(bb_middle.iloc[-1], 2) if pd.notna(bb_middle.iloc[-1]) else None,
            "lower": round(bb_lower.iloc[-1], 2) if pd.notna(bb_lower.iloc[-1]) else None,
        },
        "volume_ratio": round(volume_ratio, 2),
        "price_vs_sma20_pct": round(price_vs_sma20, 2),
        "support": round(recent_low, 2),
        "resistance": round(recent_high, 2),
        "trend": "bullish" if price_vs_sma20 > 2 else "bearish" if price_vs_sma20 < -2 else "neutral",
    }


# -------------------------------------------
# Mock Data Generation
# -------------------------------------------


def _generate_mock_data(ticker: str, period: str) -> pd.DataFrame:
    """Generate realistic mock market data for testing."""

    # Determine number of days based on period
    period_days = {
        "1d": 1,
        "5d": 5,
        "1mo": 30,
        "3mo": 90,
        "6mo": 180,
        "1y": 365,
        "2y": 730,
        "ytd": 180,
        "max": 1000,
    }
    days = period_days.get(period, 90)

    # Generate dates (business days only)
    end_date = datetime.now()
    dates = pd.date_range(end=end_date, periods=days, freq="B")

    # Generate realistic price data with ticker-based seed
    np.random.seed(hash(ticker) % 2**32)

    # Base price varies by ticker
    base_price = np.random.uniform(50, 500)

    # Generate returns with slight positive drift and volatility
    daily_returns = np.random.normal(0.0005, 0.02, days)

    # Add some momentum/trend
    trend = np.linspace(0, np.random.uniform(-0.1, 0.1), days)
    daily_returns += trend / days

    # Calculate prices
    prices = base_price * np.cumprod(1 + daily_returns)

    # Generate OHLCV data
    df = pd.DataFrame(
        {
            "Open": prices * np.random.uniform(0.995, 1.005, days),
            "High": prices * np.random.uniform(1.005, 1.025, days),
            "Low": prices * np.random.uniform(0.975, 0.995, days),
            "Close": prices,
            "Volume": np.random.randint(1_000_000, 50_000_000, days),
        },
        index=dates,
    )

    # Ensure High >= all others, Low <= all others
    df["High"] = df[["Open", "High", "Close"]].max(axis=1)
    df["Low"] = df[["Open", "Low", "Close"]].min(axis=1)

    logger.info(
        "mock_data_generated",
        ticker=ticker,
        rows=len(df),
        period=period,
    )

    return df


def _get_mock_ticker_info(ticker: str) -> dict:
    """Generate mock ticker info."""
    np.random.seed(hash(ticker) % 2**32)

    sectors = ["Technology", "Healthcare", "Finance", "Consumer", "Energy", "Industrial"]
    sector = sectors[hash(ticker) % len(sectors)]

    return {
        "symbol": ticker,
        "shortName": f"Mock Company ({ticker})",
        "longName": f"Mock {ticker} Corporation",
        "sector": sector,
        "industry": f"{sector} Services",
        "marketCap": int(np.random.uniform(1e9, 1e12)),
        "trailingPE": round(np.random.uniform(10, 50), 2),
        "forwardPE": round(np.random.uniform(8, 40), 2),
        "priceToBook": round(np.random.uniform(1, 10), 2),
        "dividendYield": round(np.random.uniform(0, 0.05), 4),
        "beta": round(np.random.uniform(0.5, 2.0), 2),
        "52WeekHigh": round(np.random.uniform(100, 600), 2),
        "52WeekLow": round(np.random.uniform(50, 300), 2),
        "averageVolume": int(np.random.uniform(1e6, 50e6)),
    }


# -------------------------------------------
# Data Formatting for LLM
# -------------------------------------------


def format_market_data_for_llm(df: pd.DataFrame, ticker: str) -> str:
    """
    Format market data into a string suitable for LLM context.

    Args:
        df: DataFrame with OHLCV data
        ticker: Stock ticker symbol

    Returns:
        Formatted string for LLM consumption
    """
    if df.empty:
        return f"No market data available for {ticker}"

    # Calculate indicators
    indicators = calculate_technical_indicators(df)

    # Get recent price action
    recent = df.tail(10)

    # Format output
    lines = [
        f"=== Market Data for {ticker} ===",
        f"Current Price: ${indicators.get('current_price', 'N/A')}",
        f"",
        f"Technical Indicators:",
        f"- RSI (14): {indicators.get('rsi', 'N/A')}",
        f"- SMA 20: ${indicators.get('sma_20', 'N/A')}",
        f"- SMA 50: ${indicators.get('sma_50', 'N/A')}",
        f"- MACD: {indicators.get('macd', {}).get('histogram', 'N/A')}",
        f"- Trend: {indicators.get('trend', 'N/A')}",
        f"- Volume Ratio: {indicators.get('volume_ratio', 'N/A')}x avg",
        f"",
        f"Support/Resistance:",
        f"- Support: ${indicators.get('support', 'N/A')}",
        f"- Resistance: ${indicators.get('resistance', 'N/A')}",
        f"",
        f"Recent Price Action (Last 10 days):",
    ]

    for idx, row in recent.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
        lines.append(
            f"  {date_str}: O=${row['Open']:.2f} H=${row['High']:.2f} "
            f"L=${row['Low']:.2f} C=${row['Close']:.2f} V={row['Volume']:,.0f}"
        )

    return "\n".join(lines)
