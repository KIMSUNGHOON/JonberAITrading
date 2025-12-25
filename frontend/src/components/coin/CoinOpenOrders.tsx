/**
 * CoinOpenOrders Component
 *
 * Displays open orders with cancel functionality.
 */

import { useState, useEffect } from 'react';
import { Clock, X, RefreshCw, AlertCircle } from 'lucide-react';
import { getCoinOrders, cancelCoinOrder } from '@/api/client';
import type { CoinOrder } from '@/types';

interface CoinOpenOrdersProps {
  market?: string;
  onOrderCancel?: () => void;
}

export function CoinOpenOrders({ market, onOrderCancel }: CoinOpenOrdersProps) {
  const [orders, setOrders] = useState<CoinOrder[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const fetchOrders = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getCoinOrders({
        market,
        state: 'wait',
        limit: 50,
      });
      setOrders(response.orders);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load orders');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders();
    const interval = setInterval(fetchOrders, 10000); // Refresh every 10 seconds
    return () => clearInterval(interval);
  }, [market]);

  const handleCancelOrder = async (orderId: string) => {
    setCancellingId(orderId);
    try {
      await cancelCoinOrder(orderId);
      await fetchOrders();
      onOrderCancel?.();
    } catch (err) {
      console.error('Failed to cancel order:', err);
      setError(err instanceof Error ? err.message : 'Failed to cancel order');
    } finally {
      setCancellingId(null);
    }
  };

  const formatKRW = (value: number | null) => {
    if (value === null) return '-';
    return value.toLocaleString('ko-KR', { maximumFractionDigits: 0 });
  };

  const formatVolume = (value: number | null) => {
    if (value === null) return '-';
    if (value >= 1) return value.toLocaleString('ko-KR', { maximumFractionDigits: 4 });
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

  const getProgress = (order: CoinOrder) => {
    if (!order.volume || !order.executed_volume) return 0;
    return (order.executed_volume / order.volume) * 100;
  };

  if (isLoading && orders.length === 0) {
    return (
      <div className="card animate-pulse">
        <div className="h-24 bg-surface rounded" />
      </div>
    );
  }

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock size={18} className="text-primary" />
          <h3 className="font-semibold">Open Orders</h3>
          {orders.length > 0 && (
            <span className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 text-xs rounded-full">
              {orders.length}
            </span>
          )}
        </div>
        <button
          onClick={fetchOrders}
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

      {/* Order List */}
      {orders.length > 0 ? (
        <div className="space-y-2 max-h-60 overflow-y-auto">
          {orders.map((order) => (
            <div
              key={order.uuid}
              className="p-3 bg-surface rounded-lg"
            >
              {/* Order Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    order.side === 'bid'
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-red-500/20 text-red-400'
                  }`}>
                    {order.side === 'bid' ? 'BUY' : 'SELL'}
                  </span>
                  <span className="font-medium">{order.market}</span>
                </div>
                <button
                  onClick={() => handleCancelOrder(order.uuid)}
                  className="p-1 text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                  disabled={cancellingId === order.uuid}
                  title="Cancel order"
                >
                  {cancellingId === order.uuid ? (
                    <RefreshCw size={14} className="animate-spin" />
                  ) : (
                    <X size={14} />
                  )}
                </button>
              </div>

              {/* Order Details */}
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-gray-400">Price</span>
                  <div className="font-mono">{formatKRW(order.price)} KRW</div>
                </div>
                <div>
                  <span className="text-gray-400">Volume</span>
                  <div className="font-mono">{formatVolume(order.volume)}</div>
                </div>
              </div>

              {/* Progress */}
              {order.executed_volume && order.executed_volume > 0 && (
                <div className="mt-2">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">Filled</span>
                    <span>{getProgress(order).toFixed(1)}%</span>
                  </div>
                  <div className="h-1 bg-border rounded overflow-hidden">
                    <div
                      className="h-full bg-primary transition-all"
                      style={{ width: `${getProgress(order)}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Time */}
              <div className="mt-2 text-xs text-gray-500">
                {formatDate(order.created_at)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-6 text-gray-500">
          <Clock size={24} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No open orders</p>
        </div>
      )}
    </div>
  );
}
