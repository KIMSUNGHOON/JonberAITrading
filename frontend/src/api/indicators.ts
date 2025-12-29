/**
 * Technical Indicators API Client
 *
 * Provides functions to fetch technical indicators from the backend.
 */

import axios from 'axios';
import type {
  TechnicalIndicatorsResponse,
  IndicatorsSummaryResponse,
  IndicatorSignal,
} from '@/types';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

/**
 * Fetch full technical indicators for a Korean stock.
 *
 * @param stkCd - Stock code (e.g., "005930" for Samsung Electronics)
 * @param period - Number of days to analyze (default: 100)
 */
export async function getKRStockIndicators(
  stkCd: string,
  period = 100
): Promise<TechnicalIndicatorsResponse> {
  const response = await axios.get<TechnicalIndicatorsResponse>(
    `${API_BASE_URL}/indicators/kr/${stkCd}`,
    { params: { period } }
  );
  return response.data;
}

/**
 * Fetch simplified indicator summary for a Korean stock.
 *
 * @param stkCd - Stock code
 */
export async function getKRStockIndicatorsSummary(
  stkCd: string
): Promise<IndicatorsSummaryResponse> {
  const response = await axios.get<IndicatorsSummaryResponse>(
    `${API_BASE_URL}/indicators/kr/${stkCd}/summary`
  );
  return response.data;
}

/**
 * Fetch technical indicators for a cryptocurrency.
 *
 * @param market - Market code (e.g., "KRW-BTC")
 * @param period - Number of days to analyze (default: 100)
 */
export async function getCoinIndicators(
  market: string,
  period = 100
): Promise<TechnicalIndicatorsResponse> {
  const response = await axios.get<TechnicalIndicatorsResponse>(
    `${API_BASE_URL}/indicators/coin/${market}`,
    { params: { period } }
  );
  return response.data;
}

// -------------------------------------------
// Utility Functions
// -------------------------------------------

/**
 * Get formatted signal descriptions from indicators.
 */
export function getSignalDescriptions(signals: IndicatorSignal[]): string[] {
  return signals.map((s) => s.description);
}

/**
 * Get buy/sell recommendation from signals.
 */
export function getOverallRecommendation(
  signals: IndicatorSignal[]
): 'BUY' | 'SELL' | 'HOLD' {
  let buyScore = 0;
  let sellScore = 0;

  for (const sig of signals) {
    if (sig.signal === 'strong_buy') buyScore += 2;
    else if (sig.signal === 'buy') buyScore += 1;
    else if (sig.signal === 'strong_sell') sellScore += 2;
    else if (sig.signal === 'sell') sellScore += 1;
  }

  if (buyScore > sellScore + 1) return 'BUY';
  if (sellScore > buyScore + 1) return 'SELL';
  return 'HOLD';
}

/**
 * Format RSI value with signal description.
 */
export function formatRSI(rsi: number | null): {
  value: string;
  signal: 'overbought' | 'oversold' | 'neutral';
  color: string;
} {
  if (rsi === null) {
    return { value: 'N/A', signal: 'neutral', color: 'text-gray-400' };
  }

  const value = rsi.toFixed(1);

  if (rsi > 70) {
    return { value, signal: 'overbought', color: 'text-red-400' };
  }
  if (rsi < 30) {
    return { value, signal: 'oversold', color: 'text-green-400' };
  }
  return { value, signal: 'neutral', color: 'text-gray-300' };
}

/**
 * Format MACD histogram with color indication.
 */
export function formatMACD(histogram: number | null): {
  value: string;
  trend: 'bullish' | 'bearish';
  color: string;
} {
  if (histogram === null) {
    return { value: 'N/A', trend: 'bullish', color: 'text-gray-400' };
  }

  const value = histogram.toFixed(0);

  if (histogram > 0) {
    return { value: `+${value}`, trend: 'bullish', color: 'text-green-400' };
  }
  return { value, trend: 'bearish', color: 'text-red-400' };
}

/**
 * Format Korean Won price.
 */
export function formatKRW(value: number | null): string {
  if (value === null) return 'N/A';

  if (value >= 1e8) {
    return `₩${(value / 1e8).toFixed(2)}억`;
  }
  if (value >= 1e4) {
    return `₩${(value / 1e4).toFixed(0)}만`;
  }
  return `₩${value.toLocaleString('ko-KR')}`;
}

/**
 * Format percentage change with color.
 */
export function formatPercentChange(value: number | null): {
  text: string;
  color: string;
} {
  if (value === null) {
    return { text: 'N/A', color: 'text-gray-400' };
  }

  const sign = value > 0 ? '+' : '';
  const text = `${sign}${value.toFixed(2)}%`;

  if (value > 0) {
    return { text, color: 'text-green-400' };
  }
  if (value < 0) {
    return { text, color: 'text-red-400' };
  }
  return { text, color: 'text-gray-300' };
}

/**
 * Get trend description in Korean.
 */
export function getTrendLabel(trend: 'bullish' | 'bearish' | 'neutral'): string {
  switch (trend) {
    case 'bullish':
      return '상승세';
    case 'bearish':
      return '하락세';
    default:
      return '보합세';
  }
}
