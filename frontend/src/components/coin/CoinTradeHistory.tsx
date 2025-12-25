/**
 * CoinTradeHistory Component
 *
 * Displays executed trade history with pagination.
 */

import { useState, useEffect } from 'react';
import { History, RefreshCw, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react';
import { getCoinTrades } from '@/api/client';
import type { CoinTradeRecord } from '@/types';

interface CoinTradeHistoryProps {
  market?: string;
  pageSize?: number;
}

export function CoinTradeHistory({ market, pageSize = 10 }: CoinTradeHistoryProps) {
  const [trades, setTrades] = useState<CoinTradeRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getCoinTrades({
        market,
        page,
        limit: pageSize,
      });
      setTrades(response.trades);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load trade history');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTrades();
  }, [market, page]);

  const formatKRW = (value: number) => {
    if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
    if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
    return value.toLocaleString('ko-KR', { maximumFractionDigits: 0 });
  };

  const formatVolume = (value: number) => {
    if (value >= 1) return value.toLocaleString('ko-KR', { maximumFractionDigits: 4 });
    if (value >= 0.0001) return value.toFixed(6);
    return value.toFixed(8);
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString('ko-KR', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const totalPages = Math.ceil(total / pageSize);

  if (isLoading && trades.length === 0) {
    return (
      <div className="card animate-pulse">
        <div className="h-32 bg-surface rounded" />
      </div>
    );
  }

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <History size={18} className="text-primary" />
          <h3 className="font-semibold">Trade History</h3>
          {total > 0 && (
            <span className="text-xs text-gray-500">
              ({total} total)
            </span>
          )}
        </div>
        <button
          onClick={fetchTrades}
          className="p-1 hover:bg-surface rounded transition-colors"
          title="Refresh"
        >
          <RefreshCw size={16} className={`text-gray-400 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 p-2 bg-red-500/10 rounded text-red-400 text-sm">
          <AlertCircle size={14} />
          <span>{error}</span>
        </div>
      )}

      {/* Trade List */}
      {trades.length > 0 ? (
        <div className="space-y-2">
          {trades.map((trade) => (
            <div
              key={trade.id}
              className="p-3 bg-surface rounded-lg"
            >
              {/* Trade Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    trade.side === 'bid'
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-red-500/20 text-red-400'
                  }`}>
                    {trade.side === 'bid' ? 'BUY' : 'SELL'}
                  </span>
                  <span className="font-medium">{trade.market}</span>
                </div>
                <span className={`px-2 py-0.5 rounded text-xs ${
                  trade.state === 'done'
                    ? 'bg-green-500/10 text-green-400'
                    : 'bg-gray-500/10 text-gray-400'
                }`}>
                  {trade.state}
                </span>
              </div>

              {/* Trade Details */}
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div>
                  <span className="text-gray-400 text-xs">Price</span>
                  <div className="font-mono">{formatKRW(trade.price)}</div>
                </div>
                <div>
                  <span className="text-gray-400 text-xs">Volume</span>
                  <div className="font-mono">{formatVolume(trade.executed_volume)}</div>
                </div>
                <div>
                  <span className="text-gray-400 text-xs">Total</span>
                  <div className="font-mono">{formatKRW(trade.total_krw)}</div>
                </div>
              </div>

              {/* Fee & Time */}
              <div className="flex items-center justify-between mt-2 text-xs text-gray-500">
                {trade.fee > 0 && (
                  <span>Fee: {trade.fee.toFixed(4)}</span>
                )}
                <span>{formatDate(trade.created_at)}</span>
              </div>

              {/* Paper Trade Indicator */}
              {trade.id.startsWith('paper-') && (
                <div className="mt-2 text-xs text-yellow-400">
                  Paper Trade
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-6 text-gray-500">
          <History size={24} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No trade history</p>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2 border-t border-border">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="p-1 hover:bg-surface rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="text-sm text-gray-400">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="p-1 hover:bg-surface rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
