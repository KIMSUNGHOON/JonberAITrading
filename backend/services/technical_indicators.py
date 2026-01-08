"""
Technical Indicators Service

Provides comprehensive technical analysis calculations including:
- Trend indicators (SMA, EMA, MACD)
- Momentum indicators (RSI, Stochastic)
- Volatility indicators (Bollinger Bands, ATR)
- Volume indicators
- Signal detection (Golden/Dead Cross, Divergence)

Usage:
    from services.technical_indicators import TechnicalIndicators

    indicators = TechnicalIndicators(price_data)
    result = indicators.calculate_all()
    signals = indicators.detect_signals()
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd


class Signal(str, Enum):
    """Trading signal types."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    NEUTRAL = "neutral"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class TrendDirection(str, Enum):
    """Market trend direction."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class IndicatorResult:
    """Result container for indicator calculations."""
    value: Optional[float]
    signal: Signal = Signal.NEUTRAL
    description: str = ""


def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert value to float, handling NaN and None."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if np.isnan(value) or np.isinf(value):
            return default
        return float(value)
    if pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class TechnicalIndicators:
    """
    Technical indicators calculator with signal detection.

    Accepts a pandas DataFrame with OHLCV data and calculates
    various technical indicators and trading signals.
    """

    def __init__(self, df: pd.DataFrame):
        """
        Initialize with price data.

        Args:
            df: DataFrame with columns: open, high, low, close, volume
                Index should be DatetimeIndex (optional but recommended)
        """
        self.df = df.copy()
        self._validate_data()

        # Cache for calculated values
        self._cache: dict = {}

    def _validate_data(self) -> None:
        """Validate input data has required columns."""
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

    @property
    def close(self) -> pd.Series:
        return self.df["close"]

    @property
    def high(self) -> pd.Series:
        return self.df["high"]

    @property
    def low(self) -> pd.Series:
        return self.df["low"]

    @property
    def volume(self) -> pd.Series:
        return self.df["volume"]

    # =========================================
    # Moving Averages
    # =========================================

    def sma(self, period: int) -> pd.Series:
        """Simple Moving Average."""
        cache_key = f"sma_{period}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self.close.rolling(window=period).mean()
        return self._cache[cache_key]

    def ema(self, period: int) -> pd.Series:
        """Exponential Moving Average."""
        cache_key = f"ema_{period}"
        if cache_key not in self._cache:
            self._cache[cache_key] = self.close.ewm(span=period, adjust=False).mean()
        return self._cache[cache_key]

    def wma(self, period: int) -> pd.Series:
        """Weighted Moving Average."""
        cache_key = f"wma_{period}"
        if cache_key not in self._cache:
            weights = np.arange(1, period + 1)
            self._cache[cache_key] = self.close.rolling(period).apply(
                lambda x: np.dot(x, weights) / weights.sum(), raw=True
            )
        return self._cache[cache_key]

    # =========================================
    # Momentum Indicators
    # =========================================

    def rsi(self, period: int = 14) -> pd.Series:
        """
        Relative Strength Index.

        - RSI > 70: Overbought (potential sell signal)
        - RSI < 30: Oversold (potential buy signal)
        """
        cache_key = f"rsi_{period}"
        if cache_key not in self._cache:
            delta = self.close.diff()
            gain = delta.where(delta > 0, 0).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            self._cache[cache_key] = 100 - (100 / (1 + rs))
        return self._cache[cache_key]

    def stochastic(self, k_period: int = 14, d_period: int = 3) -> tuple[pd.Series, pd.Series]:
        """
        Stochastic Oscillator (%K and %D).

        - %K > 80: Overbought
        - %K < 20: Oversold
        """
        cache_key = f"stoch_{k_period}_{d_period}"
        if cache_key not in self._cache:
            lowest_low = self.low.rolling(window=k_period).min()
            highest_high = self.high.rolling(window=k_period).max()
            k = 100 * (self.close - lowest_low) / (highest_high - lowest_low)
            d = k.rolling(window=d_period).mean()
            self._cache[cache_key] = (k, d)
        return self._cache[cache_key]

    def macd(
        self, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        Moving Average Convergence Divergence.

        Returns:
            (macd_line, signal_line, histogram)
        """
        cache_key = f"macd_{fast}_{slow}_{signal}"
        if cache_key not in self._cache:
            ema_fast = self.ema(fast)
            ema_slow = self.ema(slow)
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            histogram = macd_line - signal_line
            self._cache[cache_key] = (macd_line, signal_line, histogram)
        return self._cache[cache_key]

    def cci(self, period: int = 20) -> pd.Series:
        """Commodity Channel Index."""
        cache_key = f"cci_{period}"
        if cache_key not in self._cache:
            tp = (self.high + self.low + self.close) / 3
            sma_tp = tp.rolling(window=period).mean()
            mean_dev = tp.rolling(window=period).apply(
                lambda x: np.abs(x - x.mean()).mean(), raw=True
            )
            self._cache[cache_key] = (tp - sma_tp) / (0.015 * mean_dev)
        return self._cache[cache_key]

    # =========================================
    # Volatility Indicators
    # =========================================

    def bollinger_bands(
        self, period: int = 20, std_dev: float = 2.0
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        Bollinger Bands.

        Returns:
            (upper_band, middle_band, lower_band)
        """
        cache_key = f"bb_{period}_{std_dev}"
        if cache_key not in self._cache:
            middle = self.sma(period)
            std = self.close.rolling(window=period).std()
            upper = middle + (std * std_dev)
            lower = middle - (std * std_dev)
            self._cache[cache_key] = (upper, middle, lower)
        return self._cache[cache_key]

    def atr(self, period: int = 14) -> pd.Series:
        """Average True Range - volatility measure."""
        cache_key = f"atr_{period}"
        if cache_key not in self._cache:
            tr1 = self.high - self.low
            tr2 = abs(self.high - self.close.shift())
            tr3 = abs(self.low - self.close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            self._cache[cache_key] = tr.rolling(window=period).mean()
        return self._cache[cache_key]

    def volatility_percent(self, period: int = 20) -> pd.Series:
        """Historical volatility as percentage."""
        cache_key = f"vol_pct_{period}"
        if cache_key not in self._cache:
            returns = self.close.pct_change()
            self._cache[cache_key] = returns.rolling(window=period).std() * 100
        return self._cache[cache_key]

    # =========================================
    # Volume Indicators
    # =========================================

    def volume_sma(self, period: int = 20) -> pd.Series:
        """Volume Simple Moving Average."""
        return self.volume.rolling(window=period).mean()

    def volume_ratio(self, period: int = 20) -> float:
        """Current volume vs average volume ratio."""
        avg_vol = self.volume_sma(period).iloc[-1]
        if avg_vol > 0:
            return _safe_float(self.volume.iloc[-1] / avg_vol)
        return 1.0

    def obv(self) -> pd.Series:
        """On-Balance Volume."""
        cache_key = "obv"
        if cache_key not in self._cache:
            direction = np.sign(self.close.diff())
            self._cache[cache_key] = (direction * self.volume).cumsum()
        return self._cache[cache_key]

    # =========================================
    # Trend Detection
    # =========================================

    def trend_direction(self) -> TrendDirection:
        """Determine overall market trend based on multiple factors."""
        if len(self.df) < 60:
            return TrendDirection.NEUTRAL

        current = self.close.iloc[-1]
        sma_20 = self.sma(20).iloc[-1]
        sma_60 = self.sma(60).iloc[-1]

        # Check trend alignment
        bullish_signals = 0
        bearish_signals = 0

        if current > sma_20:
            bullish_signals += 1
        else:
            bearish_signals += 1

        if current > sma_60:
            bullish_signals += 1
        else:
            bearish_signals += 1

        if sma_20 > sma_60:
            bullish_signals += 1
        else:
            bearish_signals += 1

        if bullish_signals >= 2:
            return TrendDirection.BULLISH
        elif bearish_signals >= 2:
            return TrendDirection.BEARISH
        return TrendDirection.NEUTRAL

    # =========================================
    # Signal Detection
    # =========================================

    def detect_signals(self) -> list[dict]:
        """
        Detect trading signals from multiple indicators.

        Returns:
            List of signal dictionaries with type, source, and description
        """
        signals = []

        if len(self.df) < 20:
            return signals

        # RSI signals
        rsi_val = _safe_float(self.rsi().iloc[-1])
        if rsi_val > 70:
            signals.append({
                "type": "warning",
                "source": "RSI",
                "signal": Signal.SELL,
                "value": rsi_val,
                "description": f"RSI 과매수 구간 ({rsi_val:.1f})",
            })
        elif rsi_val < 30:
            signals.append({
                "type": "opportunity",
                "source": "RSI",
                "signal": Signal.BUY,
                "value": rsi_val,
                "description": f"RSI 과매도 구간 ({rsi_val:.1f})",
            })

        # MACD signals
        macd_line, signal_line, histogram = self.macd()
        hist_now = _safe_float(histogram.iloc[-1])
        hist_prev = _safe_float(histogram.iloc[-2]) if len(histogram) > 1 else 0

        if hist_now > 0 and hist_prev <= 0:
            signals.append({
                "type": "opportunity",
                "source": "MACD",
                "signal": Signal.BUY,
                "value": hist_now,
                "description": "MACD 매수 시그널 (히스토그램 상향돌파)",
            })
        elif hist_now < 0 and hist_prev >= 0:
            signals.append({
                "type": "warning",
                "source": "MACD",
                "signal": Signal.SELL,
                "value": hist_now,
                "description": "MACD 매도 시그널 (히스토그램 하향돌파)",
            })

        # Golden/Dead Cross
        if len(self.df) >= 60:
            sma_20_now = _safe_float(self.sma(20).iloc[-1])
            sma_20_prev = _safe_float(self.sma(20).iloc[-2])
            sma_60_now = _safe_float(self.sma(60).iloc[-1])
            sma_60_prev = _safe_float(self.sma(60).iloc[-2])

            if sma_20_now > sma_60_now and sma_20_prev <= sma_60_prev:
                signals.append({
                    "type": "opportunity",
                    "source": "MA Cross",
                    "signal": Signal.STRONG_BUY,
                    "value": None,
                    "description": "골든크로스 발생 (20일선이 60일선 상향돌파)",
                })
            elif sma_20_now < sma_60_now and sma_20_prev >= sma_60_prev:
                signals.append({
                    "type": "warning",
                    "source": "MA Cross",
                    "signal": Signal.STRONG_SELL,
                    "value": None,
                    "description": "데드크로스 발생 (20일선이 60일선 하향돌파)",
                })

        # Bollinger Band signals
        bb_upper, bb_middle, bb_lower = self.bollinger_bands()
        current_price = self.close.iloc[-1]

        if current_price > bb_upper.iloc[-1]:
            signals.append({
                "type": "warning",
                "source": "Bollinger",
                "signal": Signal.SELL,
                "value": current_price,
                "description": "볼린저 밴드 상단 돌파 (과매수 가능)",
            })
        elif current_price < bb_lower.iloc[-1]:
            signals.append({
                "type": "opportunity",
                "source": "Bollinger",
                "signal": Signal.BUY,
                "value": current_price,
                "description": "볼린저 밴드 하단 돌파 (과매도 가능)",
            })

        # Volume surge
        vol_ratio = self.volume_ratio()
        if vol_ratio > 2.0:
            signals.append({
                "type": "info",
                "source": "Volume",
                "signal": Signal.NEUTRAL,
                "value": vol_ratio,
                "description": f"거래량 급증 (평균 대비 {vol_ratio:.1f}배)",
            })

        return signals

    # =========================================
    # Comprehensive Output
    # =========================================

    def calculate_all(self) -> dict:
        """
        Calculate all indicators and return comprehensive result.

        Returns:
            Dictionary with all calculated indicators
        """
        if len(self.df) < 20:
            return {"error": "Insufficient data (need at least 20 periods)"}

        current_price = _safe_float(self.close.iloc[-1])

        # Moving averages
        sma_5 = _safe_float(self.sma(5).iloc[-1]) if len(self.df) >= 5 else None
        sma_20 = _safe_float(self.sma(20).iloc[-1])
        sma_60 = _safe_float(self.sma(60).iloc[-1]) if len(self.df) >= 60 else None
        sma_120 = _safe_float(self.sma(120).iloc[-1]) if len(self.df) >= 120 else None

        # RSI
        rsi_val = _safe_float(self.rsi().iloc[-1])

        # MACD
        macd_line, signal_line, histogram = self.macd()

        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = self.bollinger_bands()

        # Stochastic
        stoch_k, stoch_d = self.stochastic()

        # ATR
        atr_val = _safe_float(self.atr().iloc[-1]) if len(self.df) >= 14 else None

        # Price position
        price_vs_sma20_pct = ((current_price - sma_20) / sma_20 * 100) if sma_20 else 0

        # Support/Resistance (20-day range)
        support = _safe_float(self.low.tail(20).min())
        resistance = _safe_float(self.high.tail(20).max())

        # Volatility
        volatility = _safe_float(self.volatility_percent().iloc[-1]) if len(self.df) >= 20 else None

        return {
            "current_price": current_price,
            "moving_averages": {
                "sma_5": sma_5,
                "sma_20": sma_20,
                "sma_60": sma_60,
                "sma_120": sma_120,
            },
            "momentum": {
                "rsi": rsi_val,
                "rsi_signal": "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral",
                "stochastic_k": _safe_float(stoch_k.iloc[-1]),
                "stochastic_d": _safe_float(stoch_d.iloc[-1]),
            },
            "macd": {
                "line": _safe_float(macd_line.iloc[-1]),
                "signal": _safe_float(signal_line.iloc[-1]),
                "histogram": _safe_float(histogram.iloc[-1]),
            },
            "bollinger_bands": {
                "upper": _safe_float(bb_upper.iloc[-1]),
                "middle": _safe_float(bb_middle.iloc[-1]),
                "lower": _safe_float(bb_lower.iloc[-1]),
                "width_pct": _safe_float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_middle.iloc[-1] * 100),
            },
            "volatility": {
                "atr": atr_val,
                "daily_pct": volatility,
            },
            "volume": {
                "current": _safe_float(self.volume.iloc[-1]),
                "avg_20": _safe_float(self.volume_sma(20).iloc[-1]),
                "ratio": self.volume_ratio(),
            },
            "levels": {
                "support_20d": support,
                "resistance_20d": resistance,
            },
            "trend": {
                "direction": self.trend_direction().value,
                "price_vs_sma20_pct": price_vs_sma20_pct,
            },
            "signals": self.detect_signals(),
        }


# =========================================
# Utility Functions
# =========================================

def calculate_indicators_for_ticker(df: pd.DataFrame) -> dict:
    """
    Convenience function to calculate all indicators for given data.

    Args:
        df: DataFrame with OHLCV data

    Returns:
        Dictionary with all indicator values and signals
    """
    try:
        indicators = TechnicalIndicators(df)
        return indicators.calculate_all()
    except Exception as e:
        return {"error": str(e)}


def get_indicator_summary(df: pd.DataFrame) -> str:
    """
    Get human-readable summary of technical indicators.

    Args:
        df: DataFrame with OHLCV data

    Returns:
        Formatted string summary
    """
    try:
        indicators = TechnicalIndicators(df)
        result = indicators.calculate_all()

        if "error" in result:
            return f"지표 계산 오류: {result['error']}"

        lines = [
            f"=== 기술적 지표 요약 ===",
            f"현재가: {result['current_price']:,.0f}원",
            f"",
            f"[이동평균선]",
            f"  5일선: {result['moving_averages']['sma_5']:,.0f}원" if result['moving_averages']['sma_5'] else "",
            f"  20일선: {result['moving_averages']['sma_20']:,.0f}원",
            f"  60일선: {result['moving_averages']['sma_60']:,.0f}원" if result['moving_averages']['sma_60'] else "",
            f"",
            f"[모멘텀]",
            f"  RSI(14): {result['momentum']['rsi']:.1f} ({result['momentum']['rsi_signal']})",
            f"  스토캐스틱 %K: {result['momentum']['stochastic_k']:.1f}",
            f"",
            f"[MACD]",
            f"  라인: {result['macd']['line']:.0f}",
            f"  시그널: {result['macd']['signal']:.0f}",
            f"  히스토그램: {result['macd']['histogram']:.0f}",
            f"",
            f"[볼린저 밴드]",
            f"  상단: {result['bollinger_bands']['upper']:,.0f}원",
            f"  중간: {result['bollinger_bands']['middle']:,.0f}원",
            f"  하단: {result['bollinger_bands']['lower']:,.0f}원",
            f"",
            f"[추세]",
            f"  방향: {result['trend']['direction']}",
            f"  가격 vs 20일선: {result['trend']['price_vs_sma20_pct']:+.1f}%",
            f"",
            f"[거래량]",
            f"  vs 20일 평균: {result['volume']['ratio']:.2f}x",
        ]

        # Add signals
        if result['signals']:
            lines.append(f"")
            lines.append(f"[매매 시그널]")
            for sig in result['signals']:
                lines.append(f"  • {sig['description']}")

        return "\n".join(filter(None, lines))

    except Exception as e:
        return f"요약 생성 오류: {str(e)}"
