/**
 * KRStockPriceTicker Component
 *
 * Displays real-time Korean stock price with change indicators.
 * Fetches data from Kiwoom API.
 */

import { useState, useEffect, useCallback } from 'react';
import { TrendingUp, TrendingDown, Minus, Loader2 } from 'lucide-react';
import { getKRStockTicker } from '@/api/client';

interface KRStockPriceTickerProps {
  stk_cd: string;
  stk_nm?: string;
  showDetails?: boolean;
  className?: string;
}

interface TickerData {
  price: number;
  change: number;
  changeRate: number;
  high: number;
  low: number;
  volume: number;
}

export function KRStockPriceTicker({
  stk_cd,
  stk_nm,
  showDetails = false,
  className = '',
}: KRStockPriceTickerProps) {
  const [data, setData] = useState<TickerData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTicker = useCallback(async () => {
    try {
      const response = await getKRStockTicker(stk_cd);
      setData({
        price: response.cur_prc,
        change: response.prdy_vrss,
        changeRate: response.prdy_ctrt,
        high: response.high_prc,
        low: response.low_prc,
        volume: response.trde_prica,
      });
      setError(null);
    } catch (err) {
      console.error('Failed to fetch KR stock ticker:', err);
      setError('Failed to load price');
    } finally {
      setIsLoading(false);
    }
  }, [stk_cd]);

  useEffect(() => {
    fetchTicker();
    // Refresh every 30 seconds (avoid rate limits)
    const interval = setInterval(fetchTicker, 30000);
    return () => clearInterval(interval);
  }, [fetchTicker]);

  if (error) {
    return <div className="text-sm text-red-400">{error}</div>;
  }

  if (isLoading || !data) {
    return (
      <div className="flex items-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
        <span className="text-sm text-gray-400">Loading...</span>
      </div>
    );
  }

  const formatPrice = (price: number) => {
    return price.toLocaleString('ko-KR');
  };

  const formatPercent = (rate: number) => {
    const sign = rate > 0 ? '+' : '';
    return `${sign}${rate.toFixed(2)}%`;
  };

  const getChangeColor = () => {
    if (data.change > 0) return 'text-red-400'; // Korean market: red = up
    if (data.change < 0) return 'text-blue-400'; // Korean market: blue = down
    return 'text-gray-400';
  };

  const ChangeIcon =
    data.change > 0
      ? TrendingUp
      : data.change < 0
        ? TrendingDown
        : Minus;

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <div className="flex items-center gap-2">
        {stk_nm && <span className="text-sm text-gray-400">{stk_nm}</span>}
        <span className="text-xs text-gray-500">{stk_cd}</span>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-xl font-semibold">
          {formatPrice(data.price)}원
        </span>

        <div className={`flex items-center gap-1 ${getChangeColor()}`}>
          <ChangeIcon className="w-4 h-4" />
          <span className="text-sm font-medium">{formatPercent(data.changeRate)}</span>
        </div>
      </div>

      {showDetails && (
        <div className="flex gap-4 text-xs text-gray-500 mt-1">
          <span>고가: {formatPrice(data.high)}</span>
          <span>저가: {formatPrice(data.low)}</span>
          <span>거래대금: {(data.volume / 1e8).toFixed(1)}억</span>
        </div>
      )}
    </div>
  );
}
