/**
 * KiwoomOpenOrders Component
 *
 * Displays pending Korean stock orders with cancel functionality.
 * Includes rate limit handling with automatic retry.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Clock, X, RefreshCw, AlertCircle, ArrowUpCircle, ArrowDownCircle } from 'lucide-react';
import { getKRStockOrders, cancelKRStockOrder } from '@/api/client';
import type { KRStockOrder } from '@/types';

// Rate limit retry configuration
const MAX_RETRIES = 3;
const BASE_DELAY_MS = 2000;
const REFRESH_INTERVAL_MS = 15000; // Increased from 5s to 15s to reduce rate limit hits
const INITIAL_DELAY_MS = 1500; // Stagger after account balance loads first

interface KiwoomOpenOrdersProps {
  onOrderCancel?: () => void;
}

export function KiwoomOpenOrders({ onOrderCancel }: KiwoomOpenOrdersProps) {
  const [orders, setOrders] = useState<KRStockOrder[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRateLimited, setIsRateLimited] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [cancellingOrder, setCancellingOrder] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState<string | null>(null);
  const retryTimeoutRef = useRef<number | null>(null);

  const fetchOrders = useCallback(async (retry = 0, showLoading = false) => {
    // Only show loading spinner on manual refresh or initial load
    if (showLoading) {
      setIsLoading(true);
    }
    if (retry === 0) {
      setError(null);
      setIsRateLimited(false);
    }

    try {
      const response = await getKRStockOrders({ status: 'pending' });
      setOrders(response.orders);
      setRetryCount(0);
      setIsRateLimited(false);
      setError(null);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : '주문 내역 로드 실패';

      // Check for rate limit error
      const isRateLimit = errorMsg.includes('503') ||
                          errorMsg.includes('429') ||
                          errorMsg.includes('요청 개수') ||
                          errorMsg.includes('Rate');

      if (isRateLimit && retry < MAX_RETRIES) {
        setIsRateLimited(true);
        setRetryCount(retry + 1);

        // Exponential backoff with jitter
        const delay = BASE_DELAY_MS * Math.pow(2, retry) + Math.random() * 500;

        retryTimeoutRef.current = setTimeout(() => {
          fetchOrders(retry + 1, false);
        }, delay);
      } else {
        // For rate limit errors, show previous data with warning instead of clearing
        if (!isRateLimit) {
          setError(errorMsg);
        }
        setIsRateLimited(false);
        setRetryCount(0);
      }
    } finally {
      if (showLoading) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    // Stagger initial load with delay to avoid rate limits
    const initialTimeout = setTimeout(() => {
      fetchOrders(0, true); // Initial load with loading indicator
    }, INITIAL_DELAY_MS);

    // Silent refresh for interval (no loading spinner)
    const interval = setInterval(() => fetchOrders(0, false), REFRESH_INTERVAL_MS);

    return () => {
      clearTimeout(initialTimeout);
      clearInterval(interval);
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
    };
  }, [fetchOrders]);

  const handleCancelOrder = async (orderId: string) => {
    if (confirmCancel !== orderId) {
      setConfirmCancel(orderId);
      return;
    }

    setCancellingOrder(orderId);
    setConfirmCancel(null);
    try {
      await cancelKRStockOrder(orderId);
      await fetchOrders(0, true);
      onOrderCancel?.();
    } catch (err) {
      console.error('Failed to cancel order:', err);
      setError(err instanceof Error ? err.message : '주문 취소 실패');
    } finally {
      setCancellingOrder(null);
    }
  };

  const formatKRW = (value: number) => {
    return value.toLocaleString('ko-KR');
  };

  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
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
          <Clock size={18} className="text-amber-500" />
          <h3 className="font-semibold">미체결 주문</h3>
          {orders.length > 0 && (
            <span className="px-2 py-0.5 bg-amber-500/20 text-amber-400 text-xs rounded-full">
              {orders.length}
            </span>
          )}
        </div>
        <button
          onClick={() => fetchOrders(0, true)}
          className="p-1 hover:bg-surface rounded transition-colors"
          title="새로고침"
          aria-label="Refresh orders"
        >
          <RefreshCw size={16} className={`text-gray-400 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Rate Limit Waiting */}
      {isRateLimited && retryCount > 0 && (
        <div className="flex items-center gap-2 p-2 bg-amber-500/10 rounded text-amber-400 text-sm">
          <Clock size={14} className="animate-pulse" />
          <span>API 요청 대기 중... (재시도 {retryCount}/{MAX_RETRIES})</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 p-2 bg-red-500/10 rounded text-red-400 text-sm">
          <AlertCircle size={14} />
          <span>{error}</span>
        </div>
      )}

      {/* Order List */}
      {orders.length > 0 ? (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {orders.map((order) => {
            const isBuy = order.side === 'buy';
            const SideIcon = isBuy ? ArrowUpCircle : ArrowDownCircle;
            const sideColor = isBuy ? 'text-red-400' : 'text-blue-400';
            const sideBg = isBuy ? 'bg-red-500/10' : 'bg-blue-500/10';

            return (
              <div
                key={order.order_id}
                className="p-3 bg-surface rounded-lg"
              >
                {/* Order Info */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className={`p-1 rounded ${sideBg}`}>
                      <SideIcon size={14} className={sideColor} />
                    </div>
                    <div>
                      <div className="font-medium text-sm">{order.stk_nm || order.stk_cd}</div>
                      <div className="text-xs text-gray-500">{order.stk_cd}</div>
                    </div>
                  </div>
                  <div className={`text-xs px-2 py-0.5 rounded ${sideBg} ${sideColor}`}>
                    {isBuy ? '매수' : '매도'}
                  </div>
                </div>

                {/* Order Details */}
                <div className="grid grid-cols-2 gap-2 text-xs mb-2">
                  <div>
                    <span className="text-gray-500">주문가: </span>
                    <span>{order.price ? `${formatKRW(order.price)}원` : '시장가'}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">수량: </span>
                    <span>{formatKRW(order.quantity)}주</span>
                  </div>
                  <div>
                    <span className="text-gray-500">체결: </span>
                    <span>{formatKRW(order.executed_quantity)}주</span>
                  </div>
                  <div>
                    <span className="text-gray-500">미체결: </span>
                    <span>{formatKRW(order.remaining_quantity)}주</span>
                  </div>
                </div>

                {/* Time & Status */}
                <div className="flex items-center justify-between text-xs text-gray-500 mb-2">
                  <span>{formatTime(order.created_at)}</span>
                  <span className="capitalize">
                    {order.status === 'pending' ? '대기중' :
                     order.status === 'partial' ? '부분체결' : order.status}
                  </span>
                </div>

                {/* Cancel Button */}
                <div className="pt-2 border-t border-border">
                  {confirmCancel === order.order_id ? (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-yellow-400">취소하시겠습니까?</span>
                      <div className="flex gap-2">
                        <button
                          onClick={() => setConfirmCancel(null)}
                          className="px-2 py-1 text-xs bg-surface-light hover:bg-border rounded"
                        >
                          아니오
                        </button>
                        <button
                          onClick={() => handleCancelOrder(order.order_id)}
                          className="px-2 py-1 text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded"
                          disabled={cancellingOrder === order.order_id}
                        >
                          {cancellingOrder === order.order_id ? '취소 중...' : '예'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => handleCancelOrder(order.order_id)}
                      className="w-full flex items-center justify-center gap-1 py-1 text-xs text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                      disabled={cancellingOrder === order.order_id}
                    >
                      <X size={12} />
                      <span>주문 취소</span>
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-center py-6 text-gray-500">
          <Clock size={28} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">미체결 주문 없음</p>
        </div>
      )}
    </div>
  );
}