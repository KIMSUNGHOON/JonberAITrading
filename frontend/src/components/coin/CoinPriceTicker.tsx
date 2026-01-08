/**
 * CoinPriceTicker Component
 *
 * Displays real-time coin price with change indicators.
 * Updates automatically via polling.
 */

import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { useCoinTicker } from '@/hooks/useCoinTicker';

interface CoinPriceTickerProps {
  market: string;
  koreanName?: string;
  showDetails?: boolean;
  className?: string;
}

export function CoinPriceTicker({
  market,
  koreanName,
  showDetails = false,
  className = '',
}: CoinPriceTickerProps) {
  const { data, isLoading, error } = useCoinTicker(market);

  if (error) {
    return <div className="text-sm text-red-400">Failed to load price</div>;
  }

  if (isLoading || !data) {
    return (
      <div className="animate-pulse">
        <div className="h-6 bg-surface rounded w-24" />
      </div>
    );
  }

  const formatPrice = (price: number) => {
    if (price >= 1000) {
      return price.toLocaleString('ko-KR');
    }
    return price.toFixed(price < 1 ? 4 : 2);
  };

  const formatPercent = (rate: number) => {
    const sign = rate > 0 ? '+' : '';
    return `${sign}${rate.toFixed(2)}%`;
  };

  const getChangeColor = (change: string) => {
    switch (change) {
      case 'RISE':
        return 'text-green-400';
      case 'FALL':
        return 'text-red-400';
      default:
        return 'text-gray-400';
    }
  };

  const ChangeIcon =
    data.change === 'RISE'
      ? TrendingUp
      : data.change === 'FALL'
        ? TrendingDown
        : Minus;

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <div className="flex items-center gap-2">
        {koreanName && <span className="text-sm text-gray-400">{koreanName}</span>}
        <span className="text-xs text-gray-500">{market}</span>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-xl font-semibold">
          {formatPrice(data.tradePrice)} KRW
        </span>

        <div className={`flex items-center gap-1 ${getChangeColor(data.change)}`}>
          <ChangeIcon className="w-4 h-4" />
          <span className="text-sm font-medium">{formatPercent(data.changeRate)}</span>
        </div>
      </div>

      {showDetails && (
        <div className="flex gap-4 text-xs text-gray-500 mt-1">
          <span>High: {formatPrice(data.highPrice)}</span>
          <span>Low: {formatPrice(data.lowPrice)}</span>
          <span>Vol: {(data.accTradePrice24h / 1e9).toFixed(1)}B</span>
        </div>
      )}
    </div>
  );
}
