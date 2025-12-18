"""
Market Data Tool

Provides market data fetching with yfinance and fallback to mock data.
Supports:
- Live data from yfinance (free, no API key needed)
- Cached historical data for offline development
- Mock data generation for testing
- Local SQLite storage for downloaded data
"""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

# Data directories
DATA_DIR = Path(__file__).parent.parent.parent / "data"
MOCK_DIR = DATA_DIR / "mock"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DB = CACHE_DIR / "market_data.db"


def _to_python_float(value, default: float = 0.0) -> float:
    """Convert numpy/pandas float to Python float for serialization."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    if pd.isna(value):
        return default
    return float(value)

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
MOCK_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


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
        return float(round(np.random.uniform(50, 500), 2))

    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        # Try to get real-time price, fall back to last close
        info = stock.info
        price = info.get("regularMarketPrice") or info.get("previousClose", 100.0)
        return _to_python_float(price, 100.0)

    except Exception as e:
        logger.error("current_price_error", ticker=ticker, error=str(e))
        np.random.seed(hash(ticker) % 2**32)
        return float(round(np.random.uniform(50, 500), 2))


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

    # Convert all values to Python native types for serialization
    return {
        "current_price": round(_to_python_float(current_price), 2),
        "sma_20": round(_to_python_float(sma_20), 2) if pd.notna(sma_20) else None,
        "sma_50": round(_to_python_float(sma_50), 2) if sma_50 and pd.notna(sma_50) else None,
        "rsi": round(_to_python_float(rsi), 2) if pd.notna(rsi) else None,
        "macd": {
            "line": round(_to_python_float(macd_line.iloc[-1]), 4) if pd.notna(macd_line.iloc[-1]) else None,
            "signal": round(_to_python_float(signal_line.iloc[-1]), 4) if pd.notna(signal_line.iloc[-1]) else None,
            "histogram": round(_to_python_float(macd_histogram.iloc[-1]), 4) if pd.notna(macd_histogram.iloc[-1]) else None,
        },
        "bollinger": {
            "upper": round(_to_python_float(bb_upper.iloc[-1]), 2) if pd.notna(bb_upper.iloc[-1]) else None,
            "middle": round(_to_python_float(bb_middle.iloc[-1]), 2) if pd.notna(bb_middle.iloc[-1]) else None,
            "lower": round(_to_python_float(bb_lower.iloc[-1]), 2) if pd.notna(bb_lower.iloc[-1]) else None,
        },
        "volume_ratio": round(_to_python_float(volume_ratio), 2),
        "price_vs_sma20_pct": round(_to_python_float(price_vs_sma20), 2),
        "support": round(_to_python_float(recent_low), 2),
        "resistance": round(_to_python_float(recent_high), 2),
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

    # Convert all numpy types to Python native types
    return {
        "symbol": ticker,
        "shortName": f"Mock Company ({ticker})",
        "longName": f"Mock {ticker} Corporation",
        "sector": sector,
        "industry": f"{sector} Services",
        "marketCap": int(np.random.uniform(1e9, 1e12)),
        "trailingPE": float(round(np.random.uniform(10, 50), 2)),
        "forwardPE": float(round(np.random.uniform(8, 40), 2)),
        "priceToBook": float(round(np.random.uniform(1, 10), 2)),
        "dividendYield": float(round(np.random.uniform(0, 0.05), 4)),
        "beta": float(round(np.random.uniform(0.5, 2.0), 2)),
        "52WeekHigh": float(round(np.random.uniform(100, 600), 2)),
        "52WeekLow": float(round(np.random.uniform(50, 300), 2)),
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


# -------------------------------------------
# Data Caching System
# -------------------------------------------

def _init_cache_db() -> None:
    """Initialize SQLite cache database."""
    conn = sqlite3.connect(CACHE_DB)
    cursor = conn.cursor()

    # Create tables for cached data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            ticker TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticker_info (
            ticker TEXT PRIMARY KEY,
            info_json TEXT,
            updated_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_metadata (
            ticker TEXT PRIMARY KEY,
            last_updated TEXT,
            period TEXT
        )
    """)

    conn.commit()
    conn.close()
    logger.debug("cache_db_initialized", db_path=str(CACHE_DB))


def save_to_cache(ticker: str, df: pd.DataFrame) -> None:
    """Save market data to local cache."""
    _init_cache_db()
    conn = sqlite3.connect(CACHE_DB)

    try:
        for idx, row in df.iterrows():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            # Convert all numpy types to Python native types for SQLite
            conn.execute(
                """
                INSERT OR REPLACE INTO price_history
                (ticker, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    date_str,
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    int(row["Volume"]),
                ),
            )

        # Update metadata
        conn.execute(
            """
            INSERT OR REPLACE INTO cache_metadata (ticker, last_updated, period)
            VALUES (?, ?, ?)
            """,
            (ticker, datetime.now().isoformat(), f"{len(df)} days"),
        )

        conn.commit()
        logger.info("cache_saved", ticker=ticker, rows=len(df))

    except Exception as e:
        logger.error("cache_save_error", ticker=ticker, error=str(e))
    finally:
        conn.close()


def load_from_cache(ticker: str, days: int = 90) -> Optional[pd.DataFrame]:
    """Load market data from local cache."""
    if not CACHE_DB.exists():
        return None

    conn = sqlite3.connect(CACHE_DB)
    try:
        query = """
            SELECT date, open, high, low, close, volume
            FROM price_history
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(ticker, days))

        if df.empty:
            return None

        # Convert to standard OHLCV format
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        df.sort_index(inplace=True)

        logger.info("cache_loaded", ticker=ticker, rows=len(df))
        return df

    except Exception as e:
        logger.error("cache_load_error", ticker=ticker, error=str(e))
        return None
    finally:
        conn.close()


def get_cached_tickers() -> list[str]:
    """Get list of tickers in cache."""
    if not CACHE_DB.exists():
        return []

    conn = sqlite3.connect(CACHE_DB)
    try:
        cursor = conn.execute("SELECT DISTINCT ticker FROM price_history")
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


# -------------------------------------------
# Data Download Utilities
# -------------------------------------------

async def download_historical_data(
    tickers: list[str],
    period: str = "2y",
    save_to_db: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Download historical data for multiple tickers.

    This is useful for:
    - Pre-loading data for offline development
    - Building a local database for testing
    - Reducing API calls during development

    Args:
        tickers: List of stock symbols
        period: Time period to download (1y, 2y, 5y, max)
        save_to_db: Whether to save to SQLite cache

    Returns:
        Dictionary mapping ticker to DataFrame
    """
    import yfinance as yf

    results = {}

    logger.info("download_started", tickers=tickers, period=period)

    for ticker in tickers:
        try:
            logger.info("downloading_ticker", ticker=ticker)
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval="1d")

            if not df.empty:
                results[ticker] = df

                if save_to_db:
                    save_to_cache(ticker, df)

                logger.info(
                    "ticker_downloaded",
                    ticker=ticker,
                    rows=len(df),
                    start=df.index.min().strftime("%Y-%m-%d"),
                    end=df.index.max().strftime("%Y-%m-%d"),
                )
            else:
                logger.warning("ticker_empty", ticker=ticker)

            # Rate limiting to avoid API throttling
            time.sleep(0.5)

        except Exception as e:
            logger.error("download_error", ticker=ticker, error=str(e))

    logger.info("download_completed", total=len(results))
    return results


# Popular tickers for testing and development
POPULAR_TICKERS = [
    # Tech Giants
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # Finance
    "JPM", "BAC", "GS", "V", "MA",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV",
    # Consumer
    "WMT", "KO", "PEP", "MCD",
    # Energy
    "XOM", "CVX",
    # ETFs
    "SPY", "QQQ", "IWM",
]


async def download_popular_tickers(period: str = "2y") -> dict[str, pd.DataFrame]:
    """Download historical data for popular tickers."""
    return await download_historical_data(POPULAR_TICKERS, period=period)


def export_cache_to_csv(output_dir: Optional[Path] = None) -> None:
    """Export cached data to CSV files for analysis."""
    output_dir = output_dir or DATA_DIR / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    tickers = get_cached_tickers()

    for ticker in tickers:
        df = load_from_cache(ticker, days=10000)  # Load all data
        if df is not None:
            filepath = output_dir / f"{ticker}.csv"
            df.to_csv(filepath)
            logger.info("exported_to_csv", ticker=ticker, path=str(filepath))


def get_cache_stats() -> dict:
    """Get statistics about cached data."""
    if not CACHE_DB.exists():
        return {"status": "no_cache", "tickers": 0}

    conn = sqlite3.connect(CACHE_DB)
    try:
        cursor = conn.execute("""
            SELECT ticker, COUNT(*) as days, MIN(date) as start, MAX(date) as end
            FROM price_history
            GROUP BY ticker
        """)

        stats = {
            "status": "ok",
            "tickers": {},
        }

        for row in cursor.fetchall():
            stats["tickers"][row[0]] = {
                "days": row[1],
                "start": row[2],
                "end": row[3],
            }

        stats["total_tickers"] = len(stats["tickers"])
        return stats

    finally:
        conn.close()
