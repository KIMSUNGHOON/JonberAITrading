/**
 * CoinInfo Component
 *
 * Detailed information display for a selected coin.
 * Shows price, 24h stats, and orderbook summary.
 */

import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, BarChart3, ArrowUpDown } from 'lucide-react';
import { getCoinOrderbook } from '@/api/client';
import { useCoinTicker } from '@/hooks/useCoinTicker';

interface CoinInfoProps {
  market: string;
  koreanName?: string;
}

interface OrderbookData {
  totalAskSize: number;
  totalBidSize: number;
  bidAskRatio: number;
  topAsks: Array<{ price: number; size: number }>;
  topBids: Array<{ price: number; size: number }>;
}

export function CoinInfo({ market, koreanName }: CoinInfoProps) {
  const { data: ticker, isLoading: tickerLoading } = useCoinTicker(market);
  const [orderbook, setOrderbook] = useState<OrderbookData | null>(null);

  // Fetch orderbook (less frequently)
  useEffect(() => {
    async function fetchOrderbook() {
      try {
        const response = await getCoinOrderbook(market);
        setOrderbook({
          totalAskSize: response.total_ask_size,
          totalBidSize: response.total_bid_size,
          bidAskRatio: response.bid_ask_ratio,
          topAsks: response.asks.slice(0, 5),
          topBids: response.bids.slice(0, 5),
        });
      } catch (err) {
        console.error('Failed to fetch orderbook:', err);
      }
    }

    fetchOrderbook();
    const interval = setInterval(fetchOrderbook, 30000); // Every 30 seconds
    return () => clearInterval(interval);
  }, [market]);

  const formatKRW = (value: number) => {
    if (value >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
    if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
    if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
    return value.toLocaleString('ko-KR');
  };

  if (tickerLoading) {
    return (
      <div className="card animate-pulse">
        <div className="h-32 bg-surface rounded" />
      </div>
    );
  }

  if (!ticker) {
    return null;
  }

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{koreanName || market}</h2>
          <div className="text-xs text-gray-500">{market}</div>
        </div>
        <div
          className={`px-2 py-1 rounded text-xs font-medium ${
            ticker.change === 'RISE'
              ? 'bg-green-500/20 text-green-400'
              : ticker.change === 'FALL'
                ? 'bg-red-500/20 text-red-400'
                : 'bg-gray-500/20 text-gray-400'
          }`}
        >
          {ticker.change === 'RISE'
            ? 'Rising'
            : ticker.change === 'FALL'
              ? 'Falling'
              : 'Stable'}
        </div>
      </div>

      {/* Price */}
      <div>
        <div className="text-2xl font-bold">
          {ticker.tradePrice.toLocaleString('ko-KR')} KRW
        </div>
        <div
          className={`flex items-center gap-2 mt-1 ${
            ticker.change === 'RISE'
              ? 'text-green-400'
              : ticker.change === 'FALL'
                ? 'text-red-400'
                : 'text-gray-400'
          }`}
        >
          {ticker.change === 'RISE' ? (
            <TrendingUp className="w-4 h-4" />
          ) : ticker.change === 'FALL' ? (
            <TrendingDown className="w-4 h-4" />
          ) : null}
          <span>
            {ticker.changePrice > 0 ? '+' : ''}
            {ticker.changePrice.toLocaleString('ko-KR')} (
            {ticker.changeRate > 0 ? '+' : ''}
            {ticker.changeRate.toFixed(2)}%)
          </span>
        </div>
      </div>

      {/* 24h Stats Grid */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-surface p-3 rounded-lg">
          <div className="text-xs text-gray-500 mb-1">24h High</div>
          <div className="font-medium text-green-400">
            {ticker.highPrice.toLocaleString('ko-KR')}
          </div>
        </div>
        <div className="bg-surface p-3 rounded-lg">
          <div className="text-xs text-gray-500 mb-1">24h Low</div>
          <div className="font-medium text-red-400">
            {ticker.lowPrice.toLocaleString('ko-KR')}
          </div>
        </div>
        <div className="bg-surface p-3 rounded-lg">
          <div className="text-xs text-gray-500 mb-1 flex items-center gap-1">
            <BarChart3 className="w-3 h-3" /> 24h Volume
          </div>
          <div className="font-medium">{formatKRW(ticker.accTradePrice24h)}</div>
        </div>
        {orderbook && (
          <div className="bg-surface p-3 rounded-lg">
            <div className="text-xs text-gray-500 mb-1 flex items-center gap-1">
              <ArrowUpDown className="w-3 h-3" /> Bid/Ask Ratio
            </div>
            <div
              className={`font-medium ${
                orderbook.bidAskRatio > 1
                  ? 'text-green-400'
                  : orderbook.bidAskRatio < 1
                    ? 'text-red-400'
                    : 'text-gray-400'
              }`}
            >
              {orderbook.bidAskRatio.toFixed(2)}
            </div>
          </div>
        )}
      </div>

      {/* Mini Orderbook */}
      {orderbook && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <div className="text-gray-500 mb-1">Top Bids (Buy)</div>
            {orderbook.topBids.slice(0, 3).map((bid, i) => (
              <div key={i} className="flex justify-between text-green-400 opacity-80">
                <span>{bid.price.toLocaleString('ko-KR')}</span>
                <span>{bid.size.toFixed(4)}</span>
              </div>
            ))}
          </div>
          <div>
            <div className="text-gray-500 mb-1">Top Asks (Sell)</div>
            {orderbook.topAsks.slice(0, 3).map((ask, i) => (
              <div key={i} className="flex justify-between text-red-400 opacity-80">
                <span>{ask.price.toLocaleString('ko-KR')}</span>
                <span>{ask.size.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
