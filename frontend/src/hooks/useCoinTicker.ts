/**
 * useCoinTicker Hook
 *
 * Real-time price updates via WebSocket.
 * Falls back to polling if WebSocket is unavailable.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { getCoinTicker } from '@/api/client';
import { getTickerWebSocket, TickerData, TickerWebSocket } from '@/api/websocket';

export interface TickerDataState {
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
  /** Use polling instead of WebSocket (default: false) */
  usePolling?: boolean;
  /** Polling interval in milliseconds (default: 3000) */
  pollInterval?: number;
  /** Enable/disable the hook (default: true) */
  enabled?: boolean;
}

/**
 * Hook for real-time coin ticker data.
 *
 * Uses WebSocket for real-time updates by default,
 * can fall back to polling if needed.
 */
export function useCoinTicker(
  market: string | null,
  options: UseCoinTickerOptions = {}
) {
  const { usePolling = false, pollInterval = 3000, enabled = true } = options;

  const [data, setData] = useState<TickerDataState | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  const wsRef = useRef<TickerWebSocket | null>(null);
  const intervalRef = useRef<number | null>(null);
  const subscribedMarketRef = useRef<string | null>(null);

  // Convert WebSocket ticker data to our state format
  const convertTickerData = useCallback((ticker: TickerData): TickerDataState => {
    return {
      market: ticker.market,
      tradePrice: ticker.trade_price,
      change: ticker.change,
      changeRate: ticker.change_rate,
      changePrice: ticker.change_price,
      highPrice: ticker.high_price,
      lowPrice: ticker.low_price,
      tradeVolume: ticker.acc_trade_volume_24h,
      accTradePrice24h: ticker.acc_trade_price_24h,
      timestamp: new Date(ticker.trade_timestamp),
    };
  }, []);

  // Polling fetch function
  const fetchTicker = useCallback(async () => {
    if (!market) return;

    try {
      const response = await getCoinTicker(market);
      setData({
        market: response.market,
        tradePrice: response.trade_price,
        change: response.change as 'RISE' | 'EVEN' | 'FALL',
        changeRate: response.change_rate,
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

  // WebSocket mode
  useEffect(() => {
    if (!market || !enabled || usePolling) {
      return;
    }

    // Get or create the shared WebSocket instance
    const ws = getTickerWebSocket();
    wsRef.current = ws;

    // Handler for ticker updates
    const handleTicker = (ticker: TickerData) => {
      if (ticker.market === market.toUpperCase()) {
        setData(convertTickerData(ticker));
        setError(null);
        setIsLoading(false);
      }
    };

    // Setup handlers
    ws.setHandlers({
      onTicker: handleTicker,
      onConnect: () => {
        setIsConnected(true);
        // Subscribe when connected
        if (market) {
          ws.subscribe([market]);
          subscribedMarketRef.current = market;
        }
      },
      onDisconnect: () => {
        setIsConnected(false);
      },
      onError: (err) => {
        setError(typeof err === 'string' ? err : 'WebSocket error');
      },
    });

    // Connect if not already connected
    if (!ws.isConnected()) {
      setIsLoading(true);
      ws.connect();
    } else {
      // Already connected, just subscribe
      ws.subscribe([market]);
      subscribedMarketRef.current = market;
      setIsConnected(true);
    }

    return () => {
      // Unsubscribe when unmounting or market changes
      if (subscribedMarketRef.current && wsRef.current) {
        wsRef.current.unsubscribe([subscribedMarketRef.current]);
        subscribedMarketRef.current = null;
      }
    };
  }, [market, enabled, usePolling, convertTickerData]);

  // Polling mode (fallback)
  useEffect(() => {
    if (!market || !enabled || !usePolling) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
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
        intervalRef.current = null;
      }
    };
  }, [market, enabled, usePolling, pollInterval, fetchTicker]);

  // Clear data when market changes or disabled
  useEffect(() => {
    if (!market || !enabled) {
      setData(null);
    }
  }, [market, enabled]);

  return {
    data,
    isLoading,
    error,
    isConnected,
    refetch: fetchTicker,
  };
}

/**
 * Hook for multiple coin tickers via WebSocket.
 *
 * Efficiently subscribes to multiple markets at once.
 */
export function useCoinTickers(
  markets: string[],
  options: Omit<UseCoinTickerOptions, 'usePolling'> = {}
) {
  const { enabled = true } = options;

  const [data, setData] = useState<Map<string, TickerDataState>>(new Map());
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<TickerWebSocket | null>(null);
  const subscribedMarketsRef = useRef<Set<string>>(new Set());

  // Convert WebSocket ticker data to our state format
  const convertTickerData = useCallback((ticker: TickerData): TickerDataState => {
    return {
      market: ticker.market,
      tradePrice: ticker.trade_price,
      change: ticker.change,
      changeRate: ticker.change_rate,
      changePrice: ticker.change_price,
      highPrice: ticker.high_price,
      lowPrice: ticker.low_price,
      tradeVolume: ticker.acc_trade_volume_24h,
      accTradePrice24h: ticker.acc_trade_price_24h,
      timestamp: new Date(ticker.trade_timestamp),
    };
  }, []);

  useEffect(() => {
    if (!enabled || markets.length === 0) {
      return;
    }

    const ws = getTickerWebSocket();
    wsRef.current = ws;

    const handleTicker = (ticker: TickerData) => {
      setData(prev => {
        const newMap = new Map(prev);
        newMap.set(ticker.market, convertTickerData(ticker));
        return newMap;
      });
      setError(null);
    };

    ws.setHandlers({
      onTicker: handleTicker,
      onConnect: () => {
        setIsConnected(true);
        // Subscribe to all markets
        const marketsToSubscribe = markets.map(m => m.toUpperCase());
        ws.subscribe(marketsToSubscribe);
        subscribedMarketsRef.current = new Set(marketsToSubscribe);
      },
      onDisconnect: () => {
        setIsConnected(false);
      },
      onError: (err) => {
        setError(typeof err === 'string' ? err : 'WebSocket error');
      },
    });

    if (!ws.isConnected()) {
      ws.connect();
    } else {
      const marketsToSubscribe = markets.map(m => m.toUpperCase());
      ws.subscribe(marketsToSubscribe);
      subscribedMarketsRef.current = new Set(marketsToSubscribe);
      setIsConnected(true);
    }

    return () => {
      // Unsubscribe from all markets
      if (wsRef.current && subscribedMarketsRef.current.size > 0) {
        wsRef.current.unsubscribe(Array.from(subscribedMarketsRef.current));
        subscribedMarketsRef.current.clear();
      }
    };
  }, [markets.join(','), enabled, convertTickerData]);

  return {
    data,
    isConnected,
    error,
    getTicker: (market: string) => data.get(market.toUpperCase()),
  };
}
