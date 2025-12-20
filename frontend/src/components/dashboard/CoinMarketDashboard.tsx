/**
 * Coin Market Dashboard Component
 *
 * Displays real-time coin market overview with:
 * - Top coins by volume
 * - Top gainers/losers
 * - Market trends
 */

import { useState, useEffect, useMemo, useRef } from 'react';
import { TrendingUp, TrendingDown, BarChart3, RefreshCw, Loader2 } from 'lucide-react';
import { getCoinTickers, getCoinMarkets } from '@/api/client';

interface TickerData {
  market: string;
  trade_price: number;
  change: 'RISE' | 'EVEN' | 'FALL';
  change_rate: number;
  change_price: number;
  acc_trade_price_24h: number;
}

interface CoinMarketDashboardProps {
  compact?: boolean;
}

export function CoinMarketDashboard({ compact = false }: CoinMarketDashboardProps) {
  const [tickers, setTickers] = useState<TickerData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Cache valid KRW markets from Upbit
  const validMarketsRef = useRef<string[]>([]);

  // Fetch valid markets first, then tickers
  const fetchTickers = async () => {
    try {
      setIsLoading(true);

      // If we don't have valid markets cached, fetch them first
      if (validMarketsRef.current.length === 0) {
        const marketsResponse = await getCoinMarkets();
        // Filter to only KRW markets and take top 20 by name
        validMarketsRef.current = marketsResponse.markets
          .filter((m) => m.market.startsWith('KRW-'))
          .slice(0, 20)
          .map((m) => m.market);
      }

      if (validMarketsRef.current.length === 0) {
        throw new Error('No valid markets found');
      }

      const response = await getCoinTickers(validMarketsRef.current);
      setTickers(response.tickers);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch market data');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTickers();
    // Refresh every 30 seconds
    const interval = setInterval(fetchTickers, 30000);
    return () => clearInterval(interval);
  }, []);

  // Sort by volume (top 10)
  const topByVolume = useMemo(() => {
    return [...tickers]
      .sort((a, b) => b.acc_trade_price_24h - a.acc_trade_price_24h)
      .slice(0, compact ? 5 : 10);
  }, [tickers, compact]);

  // Top gainers (positive change rate)
  const topGainers = useMemo(() => {
    return [...tickers]
      .filter((t) => t.change === 'RISE')
      .sort((a, b) => b.change_rate - a.change_rate)
      .slice(0, compact ? 3 : 5);
  }, [tickers, compact]);

  // Top losers (negative change rate)
  const topLosers = useMemo(() => {
    return [...tickers]
      .filter((t) => t.change === 'FALL')
      .sort((a, b) => a.change_rate - b.change_rate)
      .slice(0, compact ? 3 : 5);
  }, [tickers, compact]);

  const formatKRW = (value: number) => {
    if (value >= 1e12) return `${(value / 1e12).toFixed(1)}T`;
    if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
    if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
    return value.toLocaleString('ko-KR');
  };

  const formatPrice = (price: number) => {
    if (price >= 1000) {
      return price.toLocaleString('ko-KR');
    }
    return price.toLocaleString('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  };

  const getSymbol = (market: string) => market.replace('KRW-', '');

  if (isLoading && tickers.length === 0) {
    return (
      <div className="card flex items-center justify-center h-48">
        <Loader2 className="w-6 h-6 animate-spin text-blue-400" />
        <span className="ml-2 text-gray-400">Loading market data...</span>
      </div>
    );
  }

  if (error && tickers.length === 0) {
    return (
      <div className="card flex flex-col items-center justify-center h-48 text-gray-400">
        <p>{error}</p>
        <button
          onClick={fetchTickers}
          className="mt-2 px-3 py-1 text-sm bg-surface rounded hover:bg-surface-light"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className={`space-y-4 ${compact ? '' : 'p-4'}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-400" />
          Coin Market Overview
        </h2>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          {lastUpdated && (
            <span>Updated {lastUpdated.toLocaleTimeString('ko-KR')}</span>
          )}
          <button
            onClick={fetchTickers}
            disabled={isLoading}
            className="p-1 hover:bg-surface rounded"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Grid Layout */}
      <div className={`grid gap-4 ${compact ? 'grid-cols-1' : 'grid-cols-1 lg:grid-cols-3'}`}>
        {/* Top by Volume */}
        <div className="card">
          <h3 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            Top by Volume
          </h3>
          <div className="space-y-2">
            {topByVolume.map((ticker, idx) => (
              <div
                key={ticker.market}
                className="flex items-center justify-between py-1.5 px-2 bg-surface rounded hover:bg-surface-light transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500 w-4">{idx + 1}</span>
                  <span className="font-medium">{getSymbol(ticker.market)}</span>
                </div>
                <div className="text-right">
                  <div className="text-sm">{formatPrice(ticker.trade_price)}</div>
                  <div className="text-xs text-gray-500">
                    {formatKRW(ticker.acc_trade_price_24h)} KRW
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Top Gainers */}
        <div className="card">
          <h3 className="text-sm font-medium text-green-400 mb-3 flex items-center gap-2">
            <TrendingUp className="w-4 h-4" />
            Top Gainers
          </h3>
          <div className="space-y-2">
            {topGainers.length > 0 ? (
              topGainers.map((ticker) => (
                <div
                  key={ticker.market}
                  className="flex items-center justify-between py-1.5 px-2 bg-surface rounded hover:bg-surface-light transition-colors"
                >
                  <span className="font-medium">{getSymbol(ticker.market)}</span>
                  <div className="text-right">
                    <div className="text-sm">{formatPrice(ticker.trade_price)}</div>
                    <div className="text-xs text-green-400">
                      +{(ticker.change_rate * 100).toFixed(2)}%
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-sm text-gray-500 text-center py-4">
                No gainers at the moment
              </div>
            )}
          </div>
        </div>

        {/* Top Losers */}
        <div className="card">
          <h3 className="text-sm font-medium text-red-400 mb-3 flex items-center gap-2">
            <TrendingDown className="w-4 h-4" />
            Top Losers
          </h3>
          <div className="space-y-2">
            {topLosers.length > 0 ? (
              topLosers.map((ticker) => (
                <div
                  key={ticker.market}
                  className="flex items-center justify-between py-1.5 px-2 bg-surface rounded hover:bg-surface-light transition-colors"
                >
                  <span className="font-medium">{getSymbol(ticker.market)}</span>
                  <div className="text-right">
                    <div className="text-sm">{formatPrice(ticker.trade_price)}</div>
                    <div className="text-xs text-red-400">
                      {(ticker.change_rate * 100).toFixed(2)}%
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-sm text-gray-500 text-center py-4">
                No losers at the moment
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
