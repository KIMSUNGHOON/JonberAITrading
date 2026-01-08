/**
 * KRStockTradeHistory Component
 *
 * Displays executed Korean stock trade history with pagination.
 */

import { useState, useEffect } from 'react';
import { History, RefreshCw, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react';
import { getKRStockTrades } from '@/api/client';
import type { KRStockTradeRecord } from '@/types';

interface KRStockTradeHistoryProps {
  stk_cd?: string;
  pageSize?: number;
}

export function KRStockTradeHistory({ stk_cd, pageSize = 10 }: KRStockTradeHistoryProps) {
  const [trades, setTrades] = useState<KRStockTradeRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getKRStockTrades({
        stk_cd,
        page,
        limit: pageSize,
      });
      setTrades(response.trades);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '거래 내역 로드 실패');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTrades();
  }, [stk_cd, page]);

  const formatKRW = (value: number) => {
    const absValue = Math.abs(value);
    if (absValue >= 1e8) return `${(value / 1e8).toFixed(2)}억`;
    if (absValue >= 1e4) return `${(value / 1e4).toFixed(0)}만`;
    return value.toLocaleString('ko-KR');
  };

  const formatQuantity = (value: number) => {
    return value.toLocaleString('ko-KR');
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
          <History size={18} className="text-blue-500" />
          <h3 className="font-semibold">거래 내역</h3>
          {total > 0 && (
            <span className="text-xs text-gray-500">
              ({total}건)
            </span>
          )}
        </div>
        <button
          onClick={fetchTrades}
          className="p-1 hover:bg-surface rounded transition-colors"
          title="새로고침"
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
                    trade.side === 'buy'
                      ? 'bg-red-500/20 text-red-400'
                      : 'bg-blue-500/20 text-blue-400'
                  }`}>
                    {trade.side === 'buy' ? '매수' : '매도'}
                  </span>
                  <span className="font-medium">{trade.stk_nm || trade.stk_cd}</span>
                  {trade.stk_nm && (
                    <span className="text-xs text-gray-500">{trade.stk_cd}</span>
                  )}
                </div>
                <span className={`px-2 py-0.5 rounded text-xs ${
                  trade.status === 'filled'
                    ? 'bg-green-500/10 text-green-400'
                    : trade.status === 'partial'
                      ? 'bg-yellow-500/10 text-yellow-400'
                      : 'bg-gray-500/10 text-gray-400'
                }`}>
                  {trade.status === 'filled' ? '체결' : trade.status === 'partial' ? '부분체결' : trade.status}
                </span>
              </div>

              {/* Trade Details */}
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div>
                  <span className="text-gray-400 text-xs">체결가</span>
                  <div className="font-mono">{formatKRW(trade.price)}원</div>
                </div>
                <div>
                  <span className="text-gray-400 text-xs">수량</span>
                  <div className="font-mono">{formatQuantity(trade.executed_quantity)}주</div>
                </div>
                <div>
                  <span className="text-gray-400 text-xs">총액</span>
                  <div className="font-mono">{formatKRW(trade.total_krw)}원</div>
                </div>
              </div>

              {/* Fee & Time */}
              <div className="flex items-center justify-between mt-2 text-xs text-gray-500">
                {trade.fee > 0 && (
                  <span>수수료: {formatKRW(trade.fee)}원</span>
                )}
                <span>{formatDate(trade.created_at)}</span>
              </div>

              {/* Paper Trade Indicator */}
              {trade.id.startsWith('paper-') && (
                <div className="mt-2 text-xs text-yellow-400">
                  모의거래
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-6 text-gray-500">
          <History size={24} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">거래 내역 없음</p>
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
