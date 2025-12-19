/**
 * useCoinTicker Hook
 *
 * Polls Upbit ticker API for real-time price updates.
 * Uses polling instead of WebSocket for simplicity.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { getCoinTicker } from '@/api/client';

export interface TickerData {
  market: string;
  tradePrice: number;
  change: 'RISE' | 'EVEN' | 'FALL';
  changeRate: number;
  changePrice: number;
  highPrice: number;
  lowPrice: number;
  tradeVolume: number;
  accTradePrice24h: number;
  timestamp: Date;
}

interface UseCoinTickerOptions {
  pollInterval?: number; // milliseconds, default 3000 (3 seconds)
  enabled?: boolean;
}

export function useCoinTicker(
  market: string | null,
  options: UseCoinTickerOptions = {}
) {
  const { pollInterval = 3000, enabled = true } = options;

  const [data, setData] = useState<TickerData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);

  const fetchTicker = useCallback(async () => {
    if (!market) return;

    try {
      const response = await getCoinTicker(market);
      setData({
        market: response.market,
        tradePrice: response.trade_price,
        change: response.change as 'RISE' | 'EVEN' | 'FALL',
        changeRate: response.change_rate * 100, // Convert to percentage
        changePrice: response.change_price,
        highPrice: response.high_price,
        lowPrice: response.low_price,
        tradeVolume: response.trade_volume,
        accTradePrice24h: response.acc_trade_price_24h,
        timestamp: new Date(response.timestamp),
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch ticker');
    }
  }, [market]);

  useEffect(() => {
    if (!market || !enabled) {
      setData(null);
      return;
    }

    // Initial fetch
    setIsLoading(true);
    fetchTicker().finally(() => setIsLoading(false));

    // Start polling
    intervalRef.current = window.setInterval(fetchTicker, pollInterval);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [market, enabled, pollInterval, fetchTicker]);

  return { data, isLoading, error, refetch: fetchTicker };
}
