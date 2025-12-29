"""
Korean Stock Market Data Tool

Provides market data fetching for Korean stocks via Kiwoom Securities REST API.
Supports:
- Live data from Kiwoom API (requires API keys)
- Technical indicator calculation (RSI, MACD, Bollinger Bands, etc.)
- Formatted output for LLM context
"""

from typing import Optional

import numpy as np
import pandas as pd
import structlog

from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

logger = structlog.get_logger()


def _to_python_float(value, default: float = 0.0) -> float:
    """Convert numpy/pandas float to Python float for serialization."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    if pd.isna(value):
        return default
    return float(value)


async def get_kr_stock_info(stk_cd: str) -> dict:
    """
    Get Korean stock basic information via Kiwoom API.

    Args:
        stk_cd: Stock code (e.g., "005930" for Samsung Electronics)

    Returns:
        Dictionary with stock info
    """
    try:
        client = await get_shared_kiwoom_client_async()
        info = await client.get_stock_info(stk_cd)

        logger.info("kr_stock_info_fetched", stk_cd=stk_cd)

        return {
            "stk_cd": info.stk_cd,
            "stk_nm": info.stk_nm,
            "cur_prc": info.cur_prc,
            "prdy_vrss": info.prdy_vrss,
            "prdy_ctrt": info.prdy_ctrt,
            "acml_vol": info.acml_vol,
            "acml_tr_pbmn": info.acml_tr_pbmn,
            "strt_prc": info.strt_prc,
            "high_prc": info.high_prc,
            "low_prc": info.low_prc,
            "stk_hgpr": info.stk_hgpr,
            "stk_lwpr": info.stk_lwpr,
            "per": info.per,
            "pbr": info.pbr,
            "eps": info.eps,
            "bps": info.bps,
            "lstg_stqt": info.lstg_stqt,
            "mrkt_tot_amt": info.mrkt_tot_amt,
        }

    except Exception as e:
        logger.error("kr_stock_info_error", stk_cd=stk_cd, error=str(e))
        return _get_mock_kr_stock_info(stk_cd)


async def get_kr_current_price(stk_cd: str) -> int:
    """
    Get current price for a Korean stock.

    Args:
        stk_cd: Stock code

    Returns:
        Current price in KRW
    """
    try:
        client = await get_shared_kiwoom_client_async()
        return await client.get_current_price(stk_cd)
    except Exception as e:
        logger.error("kr_current_price_error", stk_cd=stk_cd, error=str(e))
        # Return mock price based on stock code
        np.random.seed(hash(stk_cd) % 2**32)
        return int(np.random.uniform(10000, 500000))


async def get_kr_orderbook(stk_cd: str) -> dict:
    """
    Get orderbook data for a Korean stock.

    Args:
        stk_cd: Stock code

    Returns:
        Orderbook dictionary
    """
    try:
        client = await get_shared_kiwoom_client_async()
        orderbook = await client.get_orderbook(stk_cd)

        logger.info("kr_orderbook_fetched", stk_cd=stk_cd)

        return {
            "stk_cd": orderbook.stk_cd,
            "sell_hogas": [
                {"price": h.price, "quantity": h.quantity}
                for h in orderbook.sell_hogas
            ],
            "buy_hogas": [
                {"price": h.price, "quantity": h.quantity}
                for h in orderbook.buy_hogas
            ],
            "tot_sell_qty": orderbook.tot_sell_qty,
            "tot_buy_qty": orderbook.tot_buy_qty,
            "bid_ask_ratio": (
                orderbook.tot_buy_qty / orderbook.tot_sell_qty
                if orderbook.tot_sell_qty > 0
                else 1.0
            ),
        }

    except Exception as e:
        logger.error("kr_orderbook_error", stk_cd=stk_cd, error=str(e))
        return _get_mock_kr_orderbook(stk_cd)


async def get_kr_daily_chart(
    stk_cd: str,
    base_dt: Optional[str] = None,
) -> pd.DataFrame:
    """
    Get daily chart data for a Korean stock.

    Args:
        stk_cd: Stock code
        base_dt: Base date (YYYYMMDD), None for today

    Returns:
        DataFrame with OHLCV data
    """
    try:
        client = await get_shared_kiwoom_client_async()
        df = await client.get_daily_chart_df(stk_cd, base_dt)

        logger.info(
            "kr_daily_chart_fetched",
            stk_cd=stk_cd,
            rows=len(df),
        )

        return df

    except Exception as e:
        logger.error("kr_daily_chart_error", stk_cd=stk_cd, error=str(e))
        return _generate_mock_kr_chart(stk_cd)


async def get_kr_account_balance() -> dict:
    """
    Get account balance from Kiwoom.

    Returns:
        Account balance dictionary
    """
    try:
        client = await get_shared_kiwoom_client_async()
        balance = await client.get_account_balance()

        return {
            "pchs_amt": balance.pchs_amt,
            "evlu_amt": balance.evlu_amt,
            "evlu_pfls_amt": balance.evlu_pfls_amt,
            "evlu_pfls_rt": balance.evlu_pfls_rt,
            "d2_ord_psbl_amt": balance.d2_ord_psbl_amt,
            "holdings": [
                {
                    "stk_cd": h.stk_cd,
                    "stk_nm": h.stk_nm,
                    "hldg_qty": h.hldg_qty,
                    "avg_buy_prc": h.avg_buy_prc,
                    "cur_prc": h.cur_prc,
                    "evlu_amt": h.evlu_amt,
                    "evlu_pfls_amt": h.evlu_pfls_amt,
                    "evlu_pfls_rt": h.evlu_pfls_rt,
                }
                for h in balance.holdings
            ],
        }

    except Exception as e:
        logger.error("kr_account_balance_error", error=str(e))
        return {
            "pchs_amt": 0,
            "evlu_amt": 0,
            "evlu_pfls_amt": 0,
            "evlu_pfls_rt": 0.0,
            "d2_ord_psbl_amt": 10_000_000,  # Mock 1000만원
            "holdings": [],
        }


def calculate_kr_technical_indicators(df: pd.DataFrame) -> dict:
    """
    Calculate technical indicators from Korean stock price data.

    Args:
        df: DataFrame with OHLCV data (columns: open, high, low, close, volume)

    Returns:
        Dictionary with calculated indicators
    """
    if df.empty or len(df) < 20:
        return {}

    close = df["close"]

    # Simple Moving Averages
    sma_5 = close.rolling(window=5).mean().iloc[-1]
    sma_20 = close.rolling(window=20).mean().iloc[-1]
    sma_60 = close.rolling(window=60).mean().iloc[-1] if len(df) >= 60 else None

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
    volume = df["volume"]
    avg_volume = volume.rolling(window=20).mean().iloc[-1]
    volume_ratio = volume.iloc[-1] / avg_volume if avg_volume > 0 else 1.0

    # Trend detection
    current_price = close.iloc[-1]
    price_vs_sma20 = (current_price - sma_20) / sma_20 * 100 if sma_20 else 0
    price_vs_sma5 = (current_price - sma_5) / sma_5 * 100 if sma_5 else 0

    # Support/Resistance (simplified)
    recent_low = close.tail(20).min()
    recent_high = close.tail(20).max()

    # Golden/Dead Cross detection
    if sma_60 is not None:
        if sma_20 > sma_60 and df["close"].rolling(window=20).mean().iloc[-2] <= df["close"].rolling(window=60).mean().iloc[-2]:
            cross = "golden_cross"
        elif sma_20 < sma_60 and df["close"].rolling(window=20).mean().iloc[-2] >= df["close"].rolling(window=60).mean().iloc[-2]:
            cross = "dead_cross"
        else:
            cross = "none"
    else:
        cross = "unknown"

    return {
        "current_price": int(current_price),
        "sma_5": int(sma_5) if pd.notna(sma_5) else None,
        "sma_20": int(sma_20) if pd.notna(sma_20) else None,
        "sma_60": int(sma_60) if sma_60 and pd.notna(sma_60) else None,
        "rsi": round(_to_python_float(rsi), 2) if pd.notna(rsi) else None,
        "macd": {
            "line": round(_to_python_float(macd_line.iloc[-1]), 0) if pd.notna(macd_line.iloc[-1]) else None,
            "signal": round(_to_python_float(signal_line.iloc[-1]), 0) if pd.notna(signal_line.iloc[-1]) else None,
            "histogram": round(_to_python_float(macd_histogram.iloc[-1]), 0) if pd.notna(macd_histogram.iloc[-1]) else None,
        },
        "bollinger": {
            "upper": int(bb_upper.iloc[-1]) if pd.notna(bb_upper.iloc[-1]) else None,
            "middle": int(bb_middle.iloc[-1]) if pd.notna(bb_middle.iloc[-1]) else None,
            "lower": int(bb_lower.iloc[-1]) if pd.notna(bb_lower.iloc[-1]) else None,
        },
        "volume_ratio": round(_to_python_float(volume_ratio), 2),
        "price_vs_sma5_pct": round(_to_python_float(price_vs_sma5), 2),
        "price_vs_sma20_pct": round(_to_python_float(price_vs_sma20), 2),
        "support": int(recent_low),
        "resistance": int(recent_high),
        "cross": cross,
        "trend": "bullish" if price_vs_sma20 > 2 else "bearish" if price_vs_sma20 < -2 else "neutral",
    }


def format_kr_market_data_for_llm(
    stock_info: dict,
    df: pd.DataFrame,
    orderbook: Optional[dict] = None,
) -> str:
    """
    Format Korean stock market data into a string suitable for LLM context.

    Args:
        stock_info: Stock basic info dictionary
        df: DataFrame with OHLCV data
        orderbook: Optional orderbook data

    Returns:
        Formatted string for LLM consumption
    """
    stk_cd = stock_info.get("stk_cd", "")
    stk_nm = stock_info.get("stk_nm", "")

    # Calculate indicators
    indicators = calculate_kr_technical_indicators(df) if not df.empty else {}

    lines = [
        f"=== 한국 주식 시장 데이터: {stk_nm} ({stk_cd}) ===",
        f"현재가: {stock_info.get('cur_prc', 0):,}원",
        f"전일대비: {stock_info.get('prdy_vrss', 0):+,}원 ({stock_info.get('prdy_ctrt', 0):+.2f}%)",
        f"",
        f"오늘 시가: {stock_info.get('strt_prc', 0):,}원",
        f"오늘 고가: {stock_info.get('high_prc', 0):,}원",
        f"오늘 저가: {stock_info.get('low_prc', 0):,}원",
        f"상한가: {stock_info.get('stk_hgpr', 0):,}원",
        f"하한가: {stock_info.get('stk_lwpr', 0):,}원",
        f"",
        f"거래량: {stock_info.get('acml_vol', 0):,}주",
        f"거래대금: {stock_info.get('acml_tr_pbmn', 0):,}원",
        f"",
    ]

    # Fundamental data
    if stock_info.get("per") or stock_info.get("pbr"):
        lines.extend([
            f"=== 밸류에이션 지표 ===",
            f"PER: {stock_info.get('per', 'N/A')}배",
            f"PBR: {stock_info.get('pbr', 'N/A')}배",
            f"EPS: {stock_info.get('eps', 'N/A'):,}원" if stock_info.get('eps') else "EPS: N/A",
            f"BPS: {stock_info.get('bps', 'N/A'):,}원" if stock_info.get('bps') else "BPS: N/A",
            f"시가총액: {stock_info.get('mrkt_tot_amt', 0) // 100_000_000:,}억원" if stock_info.get('mrkt_tot_amt') else "",
            f"",
        ])

    # Technical indicators
    if indicators:
        lines.extend([
            f"=== 기술적 지표 ===",
            f"RSI (14): {indicators.get('rsi', 'N/A')}",
            f"5일 이평: {indicators.get('sma_5', 'N/A'):,}원" if indicators.get('sma_5') else "5일 이평: N/A",
            f"20일 이평: {indicators.get('sma_20', 'N/A'):,}원" if indicators.get('sma_20') else "20일 이평: N/A",
            f"60일 이평: {indicators.get('sma_60', 'N/A'):,}원" if indicators.get('sma_60') else "60일 이평: N/A",
            f"MACD 히스토그램: {indicators.get('macd', {}).get('histogram', 'N/A')}",
            f"추세: {indicators.get('trend', 'N/A')}",
            f"골든/데드 크로스: {indicators.get('cross', 'N/A')}",
            f"거래량 비율 (vs 20일 평균): {indicators.get('volume_ratio', 'N/A')}x",
            f"",
            f"=== 지지/저항 ===",
            f"최근 20일 지지선: {indicators.get('support', 'N/A'):,}원" if indicators.get('support') else "",
            f"최근 20일 저항선: {indicators.get('resistance', 'N/A'):,}원" if indicators.get('resistance') else "",
            f"볼린저 상단: {indicators.get('bollinger', {}).get('upper', 'N/A'):,}원" if indicators.get('bollinger', {}).get('upper') else "",
            f"볼린저 하단: {indicators.get('bollinger', {}).get('lower', 'N/A'):,}원" if indicators.get('bollinger', {}).get('lower') else "",
            f"",
        ])

    # Orderbook data
    if orderbook:
        bid_ask_ratio = orderbook.get("bid_ask_ratio", 1.0)
        lines.extend([
            f"=== 호가 분석 ===",
            f"총 매도호가 잔량: {orderbook.get('tot_sell_qty', 0):,}주",
            f"총 매수호가 잔량: {orderbook.get('tot_buy_qty', 0):,}주",
            f"매수/매도 비율: {bid_ask_ratio:.2f}",
            f"수급 판단: {'매수 우위' if bid_ask_ratio > 1.2 else '매도 우위' if bid_ask_ratio < 0.8 else '균형'}",
            f"",
        ])

    # Recent price action
    if not df.empty:
        recent = df.tail(5)
        lines.append(f"=== 최근 5일 가격 ===")
        for idx, row in recent.iterrows():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            lines.append(
                f"  {date_str}: 시가={int(row['open']):,} 고가={int(row['high']):,} "
                f"저가={int(row['low']):,} 종가={int(row['close']):,} 거래량={int(row['volume']):,}"
            )

    return "\n".join(lines)


# -------------------------------------------
# Mock Data Generation (for testing/offline)
# -------------------------------------------


def _get_mock_kr_stock_info(stk_cd: str) -> dict:
    """Generate mock Korean stock info."""
    np.random.seed(hash(stk_cd) % 2**32)

    base_price = int(np.random.uniform(10000, 500000))
    change = int(np.random.uniform(-base_price * 0.1, base_price * 0.1))
    change_rate = (change / (base_price - change)) * 100

    # Common Korean stock names
    mock_names = {
        "005930": "삼성전자",
        "000660": "SK하이닉스",
        "035420": "NAVER",
        "035720": "카카오",
        "005380": "현대차",
        "051910": "LG화학",
        "006400": "삼성SDI",
        "068270": "셀트리온",
        "207940": "삼성바이오로직스",
        "005490": "POSCO홀딩스",
    }

    return {
        "stk_cd": stk_cd,
        "stk_nm": mock_names.get(stk_cd, f"Mock Stock {stk_cd}"),
        "cur_prc": base_price,
        "prdy_vrss": change,
        "prdy_ctrt": round(change_rate, 2),
        "acml_vol": int(np.random.uniform(100000, 10000000)),
        "acml_tr_pbmn": int(np.random.uniform(1e9, 1e12)),
        "strt_prc": base_price - int(np.random.uniform(-1000, 1000)),
        "high_prc": base_price + int(np.random.uniform(0, 5000)),
        "low_prc": base_price - int(np.random.uniform(0, 5000)),
        "stk_hgpr": int(base_price * 1.30),
        "stk_lwpr": int(base_price * 0.70),
        "per": round(np.random.uniform(5, 50), 2),
        "pbr": round(np.random.uniform(0.5, 5), 2),
        "eps": int(np.random.uniform(1000, 50000)),
        "bps": int(np.random.uniform(10000, 200000)),
        "lstg_stqt": int(np.random.uniform(1e8, 1e10)),
        "mrkt_tot_amt": int(np.random.uniform(1e12, 1e15)),
    }


def _get_mock_kr_orderbook(stk_cd: str) -> dict:
    """Generate mock orderbook."""
    np.random.seed(hash(stk_cd) % 2**32)
    base_price = int(np.random.uniform(10000, 500000))

    sell_hogas = []
    buy_hogas = []

    # Generate 10 levels of orderbook
    for i in range(10):
        sell_hogas.append({
            "price": base_price + (i + 1) * 100,
            "quantity": int(np.random.uniform(100, 10000)),
        })
        buy_hogas.append({
            "price": base_price - (i + 1) * 100,
            "quantity": int(np.random.uniform(100, 10000)),
        })

    tot_sell = sum(h["quantity"] for h in sell_hogas)
    tot_buy = sum(h["quantity"] for h in buy_hogas)

    return {
        "stk_cd": stk_cd,
        "sell_hogas": sell_hogas,
        "buy_hogas": buy_hogas,
        "tot_sell_qty": tot_sell,
        "tot_buy_qty": tot_buy,
        "bid_ask_ratio": tot_buy / tot_sell if tot_sell > 0 else 1.0,
    }


def _generate_mock_kr_chart(stk_cd: str, days: int = 100) -> pd.DataFrame:
    """Generate mock OHLCV data for Korean stock."""
    from datetime import datetime, timedelta

    np.random.seed(hash(stk_cd) % 2**32)

    # Generate dates (business days only, Korean market)
    end_date = datetime.now()
    dates = pd.date_range(end=end_date, periods=days, freq="B")

    # Base price varies by stock code
    base_price = int(np.random.uniform(10000, 500000))

    # Generate returns with slight positive drift and volatility
    daily_returns = np.random.normal(0.0005, 0.02, days)

    # Add some momentum/trend
    trend = np.linspace(0, np.random.uniform(-0.1, 0.1), days)
    daily_returns += trend / days

    # Calculate prices
    prices = base_price * np.cumprod(1 + daily_returns)
    prices = prices.astype(int)

    # Generate OHLCV data
    df = pd.DataFrame(
        {
            "open": (prices * np.random.uniform(0.995, 1.005, days)).astype(int),
            "high": (prices * np.random.uniform(1.005, 1.025, days)).astype(int),
            "low": (prices * np.random.uniform(0.975, 0.995, days)).astype(int),
            "close": prices,
            "volume": np.random.randint(100_000, 10_000_000, days),
        },
        index=dates,
    )

    # Ensure High >= all others, Low <= all others
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)

    logger.info(
        "mock_kr_chart_generated",
        stk_cd=stk_cd,
        rows=len(df),
    )

    return df


# Popular Korean stocks for testing
POPULAR_KR_STOCKS = [
    # 대형주
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("035720", "카카오"),
    ("005380", "현대차"),
    # 2차전지
    ("051910", "LG화학"),
    ("006400", "삼성SDI"),
    ("373220", "LG에너지솔루션"),
    # 바이오
    ("068270", "셀트리온"),
    ("207940", "삼성바이오로직스"),
    # 금융
    ("105560", "KB금융"),
    ("055550", "신한지주"),
    # 철강/화학
    ("005490", "POSCO홀딩스"),
    ("051900", "LG생활건강"),
]
