/**
 * CoinPositionPanel Component
 *
 * Displays open positions with real-time P&L.
 * Supports closing positions with confirmation.
 */

import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, X, RefreshCw, AlertCircle, Target, Shield } from 'lucide-react';
import { getCoinPositions, closeCoinPosition } from '@/api/client';
import type { CoinPosition } from '@/types';

interface CoinPositionPanelProps {
  onPositionClose?: () => void;
}

export function CoinPositionPanel({ onPositionClose }: CoinPositionPanelProps) {
  const [positions, setPositions] = useState<CoinPosition[]>([]);
  const [totalValue, setTotalValue] = useState(0);
  const [totalPnl, setTotalPnl] = useState(0);
  const [totalPnlPct, setTotalPnlPct] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [closingMarket, setClosingMarket] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState<string | null>(null);

  const fetchPositions = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getCoinPositions();
      setPositions(response.positions);
      setTotalValue(response.total_value_krw);
      setTotalPnl(response.total_pnl);
      setTotalPnlPct(response.total_pnl_pct);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load positions');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, 10000); // Refresh every 10 seconds
    return () => clearInterval(interval);
  }, []);

  const handleClosePosition = async (market: string) => {
    if (confirmClose !== market) {
      setConfirmClose(market);
      return;
    }

    setClosingMarket(market);
    setConfirmClose(null);
    try {
      await closeCoinPosition(market);
      await fetchPositions();
      onPositionClose?.();
    } catch (err) {
      console.error('Failed to close position:', err);
      setError(err instanceof Error ? err.message : 'Failed to close position');
    } finally {
      setClosingMarket(null);
    }
  };

  const formatKRW = (value: number) => {
    const absValue = Math.abs(value);
    if (absValue >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
    if (absValue >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
    return value.toLocaleString('ko-KR', { maximumFractionDigits: 0 });
  };

  const formatCrypto = (value: number) => {
    if (value >= 1) return value.toLocaleString('ko-KR', { maximumFractionDigits: 4 });
    if (value >= 0.0001) return value.toFixed(6);
    return value.toFixed(8);
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
          <TrendingUp size={18} className="text-primary" />
          <h3 className="font-semibold">Open Positions</h3>
          {positions.length > 0 && (
            <span className="px-2 py-0.5 bg-primary/20 text-primary text-xs rounded-full">
              {positions.length}
            </span>
          )}
        </div>
        <button
          onClick={fetchPositions}
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

      {/* Portfolio Summary */}
      {positions.length > 0 && (
        <div className="p-3 bg-surface rounded-lg">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Total Value</span>
            <span className="font-semibold">{formatKRW(totalValue)} KRW</span>
          </div>
          <div className="flex items-center justify-between mt-1">
            <span className="text-gray-400">Total P&L</span>
            <div className={`flex items-center gap-1 font-semibold ${
              totalPnl >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {totalPnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              <span>{totalPnl >= 0 ? '+' : ''}{formatKRW(totalPnl)} KRW</span>
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
              key={position.market}
              className="p-3 bg-surface rounded-lg"
            >
              {/* Market Info */}
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="font-medium">{position.currency}</div>
                  <div className="text-xs text-gray-500">{position.market}</div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm">{formatCrypto(position.quantity)}</div>
                  <div className="text-xs text-gray-500">
                    @ {position.avg_entry_price.toLocaleString('ko-KR')} KRW
                  </div>
                </div>
              </div>

              {/* Price & P&L */}
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">Current</span>
                <span>{position.current_price.toLocaleString('ko-KR')} KRW</span>
              </div>
              <div className="flex items-center justify-between text-sm mt-1">
                <span className="text-gray-400">P&L</span>
                <span className={position.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                  {position.unrealized_pnl >= 0 ? '+' : ''}{formatKRW(position.unrealized_pnl)} KRW
                  ({position.unrealized_pnl_pct >= 0 ? '+' : ''}{position.unrealized_pnl_pct.toFixed(2)}%)
                </span>
              </div>

              {/* Stop Loss / Take Profit */}
              {(position.stop_loss || position.take_profit) && (
                <div className="flex items-center gap-4 mt-2 text-xs">
                  {position.stop_loss && (
                    <div className="flex items-center gap-1 text-red-400">
                      <Shield size={12} />
                      <span>SL: {position.stop_loss.toLocaleString('ko-KR')}</span>
                    </div>
                  )}
                  {position.take_profit && (
                    <div className="flex items-center gap-1 text-green-400">
                      <Target size={12} />
                      <span>TP: {position.take_profit.toLocaleString('ko-KR')}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Close Button */}
              <div className="mt-3 pt-2 border-t border-border">
                {confirmClose === position.market ? (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-yellow-400">Confirm close?</span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setConfirmClose(null)}
                        className="px-2 py-1 text-xs bg-surface hover:bg-border rounded"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleClosePosition(position.market)}
                        className="px-2 py-1 text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded"
                        disabled={closingMarket === position.market}
                      >
                        {closingMarket === position.market ? 'Closing...' : 'Confirm'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => handleClosePosition(position.market)}
                    className="w-full flex items-center justify-center gap-1 py-1 text-xs text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                    disabled={closingMarket === position.market}
                  >
                    <X size={12} />
                    <span>Close Position</span>
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">
          <TrendingUp size={32} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No open positions</p>
          <p className="text-xs mt-1">Start an analysis to create a trade</p>
        </div>
      )}
    </div>
  );
}
