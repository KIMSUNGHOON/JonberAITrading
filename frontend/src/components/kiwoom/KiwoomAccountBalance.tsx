/**
 * KiwoomAccountBalance Component
 *
 * Displays Korean stock account balance and cash information.
 * Includes rate limit handling with automatic retry.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Wallet, TrendingUp, TrendingDown, RefreshCw, AlertCircle, Banknote, PiggyBank, Clock } from 'lucide-react';
import { getKRStockAccount } from '@/api/client';
import type { KRStockAccountResponse } from '@/types';

// Rate limit retry configuration
const MAX_RETRIES = 3;
const BASE_DELAY_MS = 2000;
const REFRESH_INTERVAL_MS = 30000;
const INITIAL_DELAY_MS = 500; // Stagger initial load to avoid rate limits

export function KiwoomAccountBalance() {
  const [account, setAccount] = useState<KRStockAccountResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRateLimited, setIsRateLimited] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const retryTimeoutRef = useRef<number | null>(null);

  const fetchAccount = useCallback(async (retry = 0) => {
    setIsLoading(true);
    if (retry === 0) {
      setError(null);
      setIsRateLimited(false);
    }

    try {
      const response = await getKRStockAccount();
      setAccount(response);
      setRetryCount(0);
      setIsRateLimited(false);
      setError(null);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : '계좌 정보 로드 실패';

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
          fetchAccount(retry + 1);
        }, delay);
      } else {
        setError(isRateLimit ? 'API 요청 한도 초과. 잠시 후 다시 시도해주세요.' : errorMsg);
        setIsRateLimited(false);
        setRetryCount(0);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    // Stagger initial load with small delay
    const initialTimeout = setTimeout(() => {
      fetchAccount();
    }, INITIAL_DELAY_MS);

    const interval = setInterval(() => fetchAccount(), REFRESH_INTERVAL_MS);

    return () => {
      clearTimeout(initialTimeout);
      clearInterval(interval);
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
    };
  }, [fetchAccount]);

  const formatKRW = (value: number) => {
    const absValue = Math.abs(value);
    if (absValue >= 1e8) return `${(value / 1e8).toFixed(2)}억`;
    if (absValue >= 1e4) return `${(value / 1e4).toFixed(0)}만`;
    return value.toLocaleString('ko-KR');
  };

  if (isLoading && !account) {
    return (
      <div className="card animate-pulse">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 bg-surface rounded-lg" />
          <div className="flex-1">
            <div className="h-4 bg-surface rounded w-24 mb-2" />
            <div className="h-3 bg-surface rounded w-16" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="h-16 bg-surface rounded" />
          <div className="h-16 bg-surface rounded" />
        </div>
      </div>
    );
  }

  // Rate limit waiting state
  if (isRateLimited && retryCount > 0) {
    return (
      <div className="card">
        <div className="flex items-center gap-2 text-amber-400">
          <Clock size={18} className="animate-pulse" />
          <span className="text-sm">
            API 요청 대기 중... (재시도 {retryCount}/{MAX_RETRIES})
          </span>
        </div>
        <div className="mt-2 text-xs text-gray-500">
          요청 한도 초과로 잠시 대기 중입니다.
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <div className="flex items-center gap-2 text-red-400">
          <AlertCircle size={18} />
          <span className="text-sm">{error}</span>
        </div>
        <button
          onClick={() => fetchAccount()}
          className="mt-3 text-sm text-blue-400 hover:underline"
        >
          다시 시도
        </button>
      </div>
    );
  }

  if (!account) return null;

  const totalAssets = account.cash.deposit + account.total_eval_amount;
  const pnlColor = account.total_profit_loss >= 0 ? 'text-red-400' : 'text-blue-400';
  const PnlIcon = account.total_profit_loss >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-10 h-10 rounded-lg bg-blue-500/20 text-blue-400 flex items-center justify-center">
            <Wallet size={20} />
          </div>
          <div>
            <h3 className="font-semibold">계좌 정보</h3>
            <p className="text-xs text-gray-500">한국투자증권</p>
          </div>
        </div>
        <button
          onClick={() => fetchAccount()}
          className="p-1.5 hover:bg-surface rounded-lg transition-colors"
          title="새로고침"
          aria-label="Refresh account"
        >
          <RefreshCw size={16} className={`text-gray-400 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Total Assets */}
      <div className="p-4 bg-gradient-to-r from-blue-600/20 to-purple-600/20 rounded-lg">
        <div className="text-sm text-gray-400 mb-1">총 자산</div>
        <div className="text-2xl font-bold">{formatKRW(totalAssets)}원</div>
        <div className={`flex items-center gap-1 mt-1 ${pnlColor}`}>
          <PnlIcon size={14} />
          <span className="text-sm">
            {account.total_profit_loss >= 0 ? '+' : ''}{formatKRW(account.total_profit_loss)}원
            ({account.total_profit_loss_rate >= 0 ? '+' : ''}{account.total_profit_loss_rate.toFixed(2)}%)
          </span>
        </div>
      </div>

      {/* Cash & Stock Balance */}
      <div className="grid grid-cols-2 gap-3">
        {/* Cash Balance */}
        <div className="p-3 bg-surface rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <Banknote size={16} className="text-green-400" />
            <span className="text-xs text-gray-400">예수금</span>
          </div>
          <div className="font-semibold">{formatKRW(account.cash.deposit)}원</div>
          <div className="text-xs text-gray-500 mt-1">
            주문가능: {formatKRW(account.cash.orderable_amount)}원
          </div>
        </div>

        {/* Stock Value */}
        <div className="p-3 bg-surface rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <PiggyBank size={16} className="text-purple-400" />
            <span className="text-xs text-gray-400">주식 평가</span>
          </div>
          <div className="font-semibold">{formatKRW(account.total_eval_amount)}원</div>
          <div className="text-xs text-gray-500 mt-1">
            {account.holdings.length}종목 보유
          </div>
        </div>
      </div>

      {/* Holdings Summary */}
      {account.holdings.length > 0 && (
        <div className="space-y-2">
          <div className="text-sm font-medium text-gray-400">보유 종목</div>
          <div className="max-h-40 overflow-y-auto space-y-1">
            {account.holdings.map((holding) => (
              <div
                key={holding.stk_cd}
                className="flex items-center justify-between p-2 bg-surface rounded-lg text-sm"
              >
                <div>
                  <span className="font-medium">{holding.stk_nm}</span>
                  <span className="text-xs text-gray-500 ml-2">{holding.quantity}주</span>
                </div>
                <div className={holding.profit_loss >= 0 ? 'text-red-400' : 'text-blue-400'}>
                  {holding.profit_loss >= 0 ? '+' : ''}{holding.profit_loss_rate.toFixed(2)}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}