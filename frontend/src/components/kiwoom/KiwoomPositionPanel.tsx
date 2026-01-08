/**
 * KiwoomPositionPanel Component
 *
 * Displays open Korean stock positions with real-time P&L.
 * Supports closing positions with confirmation.
 */

import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, X, RefreshCw, AlertCircle, Target, Shield, Building2 } from 'lucide-react';
import { getKRStockPositions, closeKRStockPosition } from '@/api/client';
import type { KRStockPosition } from '@/types';

interface KiwoomPositionPanelProps {
  onPositionClose?: () => void;
}

export function KiwoomPositionPanel({ onPositionClose }: KiwoomPositionPanelProps) {
  const [positions, setPositions] = useState<KRStockPosition[]>([]);
  const [totalValue, setTotalValue] = useState(0);
  const [totalPnl, setTotalPnl] = useState(0);
  const [totalPnlPct, setTotalPnlPct] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [closingStock, setClosingStock] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState<string | null>(null);

  const fetchPositions = async (showLoading = false) => {
    // Only show loading spinner on manual refresh or initial load
    if (showLoading) {
      setIsLoading(true);
    }
    setError(null);
    try {
      const response = await getKRStockPositions();
      setPositions(response.positions);
      setTotalValue(response.total_value_krw);
      setTotalPnl(response.total_pnl);
      setTotalPnlPct(response.total_pnl_pct);
    } catch (err) {
      setError(err instanceof Error ? err.message : '포지션 로드 실패');
    } finally {
      if (showLoading) {
        setIsLoading(false);
      }
    }
  };

  useEffect(() => {
    // Initial load with loading indicator
    fetchPositions(true);
    // Silent refresh for interval (no loading spinner)
    const interval = setInterval(() => fetchPositions(false), 10000);
    return () => clearInterval(interval);
  }, []);

  const handleClosePosition = async (stk_cd: string) => {
    if (confirmClose !== stk_cd) {
      setConfirmClose(stk_cd);
      return;
    }

    setClosingStock(stk_cd);
    setConfirmClose(null);
    try {
      await closeKRStockPosition(stk_cd);
      await fetchPositions(true);
      onPositionClose?.();
    } catch (err) {
      console.error('Failed to close position:', err);
      setError(err instanceof Error ? err.message : '포지션 청산 실패');
    } finally {
      setClosingStock(null);
    }
  };

  const formatKRW = (value: number) => {
    const absValue = Math.abs(value);
    if (absValue >= 1e8) return `${(value / 1e8).toFixed(2)}억`;
    if (absValue >= 1e4) return `${(value / 1e4).toFixed(0)}만`;
    return value.toLocaleString('ko-KR');
  };

  const formatQuantity = (value: number) => {
    return value.toLocaleString('ko-KR');
  };

  if (isLoading && positions.length === 0) {
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
          <Building2 size={18} className="text-blue-500" />
          <h3 className="font-semibold">보유 종목</h3>
          {positions.length > 0 && (
            <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded-full">
              {positions.length}
            </span>
          )}
        </div>
        <button
          onClick={() => fetchPositions(true)}
          className="p-1 hover:bg-surface rounded transition-colors"
          title="새로고침"
          aria-label="Refresh positions"
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

      {/* Portfolio Summary */}
      {positions.length > 0 && (
        <div className="p-3 bg-surface rounded-lg">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">총 평가금액</span>
            <span className="font-semibold">{formatKRW(totalValue)}원</span>
          </div>
          <div className="flex items-center justify-between mt-1">
            <span className="text-gray-400">총 손익</span>
            <div className={`flex items-center gap-1 font-semibold ${
              totalPnl >= 0 ? 'text-red-400' : 'text-blue-400'
            }`}>
              {totalPnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              <span>{totalPnl >= 0 ? '+' : ''}{formatKRW(totalPnl)}원</span>
              <span className="text-xs">({totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%)</span>
            </div>
          </div>
        </div>
      )}

      {/* Position List */}
      {positions.length > 0 ? (
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {positions.map((position) => (
            <div
              key={position.stk_cd}
              className="p-3 bg-surface rounded-lg"
            >
              {/* Stock Info */}
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="font-medium">{position.stk_nm}</div>
                  <div className="text-xs text-gray-500">{position.stk_cd}</div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm">{formatQuantity(position.quantity)}주</div>
                  <div className="text-xs text-gray-500">
                    @ {position.avg_entry_price.toLocaleString('ko-KR')}원
                  </div>
                </div>
              </div>

              {/* Price & P&L */}
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">현재가</span>
                <span>{position.current_price.toLocaleString('ko-KR')}원</span>
              </div>
              <div className="flex items-center justify-between text-sm mt-1">
                <span className="text-gray-400">평가손익</span>
                <span className={position.unrealized_pnl >= 0 ? 'text-red-400' : 'text-blue-400'}>
                  {position.unrealized_pnl >= 0 ? '+' : ''}{formatKRW(position.unrealized_pnl)}원
                  ({position.unrealized_pnl_pct >= 0 ? '+' : ''}{position.unrealized_pnl_pct.toFixed(2)}%)
                </span>
              </div>

              {/* Stop Loss / Take Profit */}
              {(position.stop_loss || position.take_profit) && (
                <div className="flex items-center gap-4 mt-2 text-xs">
                  {position.stop_loss && (
                    <div className="flex items-center gap-1 text-blue-400">
                      <Shield size={12} />
                      <span>손절: {position.stop_loss.toLocaleString('ko-KR')}원</span>
                    </div>
                  )}
                  {position.take_profit && (
                    <div className="flex items-center gap-1 text-red-400">
                      <Target size={12} />
                      <span>익절: {position.take_profit.toLocaleString('ko-KR')}원</span>
                    </div>
                  )}
                </div>
              )}

              {/* Close Button */}
              <div className="mt-3 pt-2 border-t border-border">
                {confirmClose === position.stk_cd ? (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-yellow-400">청산하시겠습니까?</span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setConfirmClose(null)}
                        className="px-2 py-1 text-xs bg-surface hover:bg-border rounded"
                      >
                        취소
                      </button>
                      <button
                        onClick={() => handleClosePosition(position.stk_cd)}
                        className="px-2 py-1 text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded"
                        disabled={closingStock === position.stk_cd}
                      >
                        {closingStock === position.stk_cd ? '청산 중...' : '확인'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => handleClosePosition(position.stk_cd)}
                    className="w-full flex items-center justify-center gap-1 py-1 text-xs text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                    disabled={closingStock === position.stk_cd}
                  >
                    <X size={12} />
                    <span>포지션 청산</span>
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">
          <Building2 size={32} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">보유 종목 없음</p>
          <p className="text-xs mt-1">분석을 시작하여 거래를 생성하세요</p>
        </div>
      )}
    </div>
  );
}