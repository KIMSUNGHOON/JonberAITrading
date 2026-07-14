/**
 * KiwoomPositionPanel Component
 *
 * Displays open Korean stock positions with real-time P&L.
 * Supports closing positions with confirmation.
 *
 * A2 (page-ux-improvements, 대안2): sourced from `/operations` (getOperations
 * 'kiwoom') — the SAME endpoint the dashboard funnel's PIPELINE `보유` column
 * reads (OperationsPanel.tsx `HoldingColumn`). Previously this panel called
 * `getKRStockPositions()` -> `GET /kr_stocks/positions`, which hardcodes
 * `stop_loss=None, take_profit=None`
 * (backend/app/api/routes/kr_stocks/positions.py) — SL/TP here was
 * structurally always a dash, and this page could disagree with the funnel
 * on the very same holding. `/operations` enriches SL/TP from the trading
 * coordinator (fallback: agent-chat PositionManager) before returning it
 * (backend/app/api/routes/trading.py `get_operations`), so switching sources
 * makes SL/TP actually render AND makes this page agree with the funnel by
 * construction (single source of truth).
 *
 * Market is pinned to 'kiwoom' regardless of the store's `activeMarket` —
 * this panel only ever shows KR holdings, but `/operations?market=coin`
 * returns `holding: null` with NO `errors.holding` entry (non-applicable,
 * not a failure — see get_operations' `market != "kiwoom"` early return).
 * Reusing the market-following `useOperations()` hook here would blank this
 * panel out whenever the coin tab is active, even though it stays visible on
 * the page (gated by `kiwoomApiConfigured`, not `activeMarket`).
 *
 * There's no separate "totals" field on `OperationsResponse` (unlike the old
 * `KRStockPositionListResponse`), so 총 평가금액/총 손익 are derived from the
 * same holdings array below — they can never drift from the per-row figures.
 */

import { useState, useEffect } from 'react';
import { pnlColor } from '../../utils/pnl';
import { TrendingUp, TrendingDown, X, RefreshCw, AlertCircle, Target, Shield, Building2 } from 'lucide-react';
import { getOperations, closeKRStockPosition } from '@/api/client';
import type { OperationsHolding } from '@/types';

interface KiwoomPositionPanelProps {
  onPositionClose?: () => void;
}

export function KiwoomPositionPanel({ onPositionClose }: KiwoomPositionPanelProps) {
  const [positions, setPositions] = useState<OperationsHolding[]>([]);
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
      const response = await getOperations('kiwoom');
      if (response.holding !== null) {
        setPositions(response.holding);
      } else {
        // Honest degrade (get_operations never fakes a 0 count on failure):
        // for market='kiwoom', holding===null only happens alongside an
        // errors.holding entry (broker fetch failed) — the "non-applicable"
        // null-with-no-error case is coin-only, so this branch is always a
        // real failure here.
        setError(response.errors.holding ?? '포지션 로드 실패');
        setPositions([]);
      }
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

  const handleClosePosition = async (ticker: string) => {
    if (confirmClose !== ticker) {
      setConfirmClose(ticker);
      return;
    }

    setClosingStock(ticker);
    setConfirmClose(null);
    try {
      await closeKRStockPosition(ticker);
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
        <div className="h-32 bg-elevated rounded" />
      </div>
    );
  }

  const totalValue = positions.reduce((sum, p) => sum + p.quantity * p.current_price, 0);
  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);
  const totalCost = positions.reduce((sum, p) => sum + p.quantity * p.avg_price, 0);
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Building2 size={18} className="text-blue-500" />
          <h3 className="font-semibold">보유 종목</h3>
          {positions.length > 0 && (
            <span className="px-2 py-0.5 bg-elevated text-muted text-xs rounded-full">
              {positions.length}
            </span>
          )}
        </div>
        <button
          onClick={() => fetchPositions(true)}
          className="p-1 hover:bg-elevated rounded transition-colors"
          title="새로고침"
          aria-label="Refresh positions"
        >
          <RefreshCw size={16} className={`text-muted ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 p-2 bg-down/10 rounded text-down text-sm">
          <AlertCircle size={14} />
          <span>{error}</span>
        </div>
      )}

      {/* Portfolio Summary */}
      {positions.length > 0 && (
        <div className="p-3 bg-elevated rounded-lg">
          <div className="flex items-center justify-between">
            <span className="text-muted">총 평가금액</span>
            <span className="font-semibold tabular-nums">{formatKRW(totalValue)}원</span>
          </div>
          <div className="flex items-center justify-between mt-1">
            <span className="text-muted">총 손익</span>
            <div className={`flex items-center gap-1 font-semibold tabular-nums ${pnlColor(totalPnl)}`}>
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
              key={position.ticker}
              className="p-3 bg-elevated rounded-lg"
            >
              {/* Stock Info */}
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="font-medium">{position.name || position.ticker}</div>
                  <div className="text-xs text-dim">{position.ticker}</div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm tabular-nums">{formatQuantity(position.quantity)}주</div>
                  <div className="text-xs text-dim tabular-nums">
                    @ {position.avg_price.toLocaleString('ko-KR')}원
                  </div>
                </div>
              </div>

              {/* Price & P&L */}
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted">현재가</span>
                <span className="tabular-nums">{position.current_price.toLocaleString('ko-KR')}원</span>
              </div>
              <div className="flex items-center justify-between text-sm mt-1">
                <span className="text-muted">평가손익</span>
                <span className={`tabular-nums ${pnlColor(position.pnl)}`}>
                  {position.pnl >= 0 ? '+' : ''}{formatKRW(position.pnl)}원
                  ({position.pnl_pct >= 0 ? '+' : ''}{position.pnl_pct.toFixed(2)}%)
                </span>
              </div>

              {/* Stop Loss / Take Profit */}
              {(position.stop_loss != null || position.take_profit != null) && (
                <div className="flex items-center gap-4 mt-2 text-xs">
                  {position.stop_loss != null && (
                    <div className={`flex items-center gap-1 ${pnlColor(-1)}`}>
                      <Shield size={12} />
                      <span className="tabular-nums">손절: {position.stop_loss.toLocaleString('ko-KR')}원</span>
                    </div>
                  )}
                  {position.take_profit != null && (
                    <div className={`flex items-center gap-1 ${pnlColor(1)}`}>
                      <Target size={12} />
                      <span className="tabular-nums">익절: {position.take_profit.toLocaleString('ko-KR')}원</span>
                    </div>
                  )}
                </div>
              )}

              {/* Close Button */}
              <div className="mt-3 pt-2 border-t border-hairline">
                {confirmClose === position.ticker ? (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-yellow-400">청산하시겠습니까?</span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setConfirmClose(null)}
                        className="px-2 py-1 text-xs bg-elevated hover:bg-hairline rounded"
                      >
                        취소
                      </button>
                      <button
                        onClick={() => handleClosePosition(position.ticker)}
                        className="px-2 py-1 text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded" // color-ok: destructive action (confirm close)
                        disabled={closingStock === position.ticker}
                      >
                        {closingStock === position.ticker ? '청산 중...' : '확인'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => handleClosePosition(position.ticker)}
                    className="w-full flex items-center justify-center gap-1 py-1 text-xs text-muted hover:text-red-400 hover:bg-red-500/10 rounded transition-colors" // color-ok: destructive action hover
                    disabled={closingStock === position.ticker}
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
        <div className="text-center py-8 text-dim">
          <Building2 size={32} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">보유 종목 없음</p>
          <p className="text-xs mt-1">분석을 시작하여 거래를 생성하세요</p>
        </div>
      )}
    </div>
  );
}
