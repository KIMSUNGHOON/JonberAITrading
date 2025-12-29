/**
 * MarketSummaryWidget Component
 *
 * Displays market summary information based on active market:
 * - Total assets
 * - Today's profit/loss
 * - Number of holdings
 *
 * Shows API configuration warning if not configured.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  Package,
  RefreshCw,
  AlertCircle,
  Settings,
  Bitcoin,
  Building2,
  LineChart,
} from 'lucide-react';
import { useStore } from '@/store';
import { getKRStockAccount, getCoinAccounts } from '@/api/client';
import type { KRStockAccountResponse, CoinAccountListResponse } from '@/types';

interface SummaryData {
  totalAssets: number;
  profitLoss: number;
  profitLossRate: number;
  holdingsCount: number;
}

// Format KRW with 억/만 notation
function formatKRW(value: number): string {
  const absValue = Math.abs(value);
  if (absValue >= 1e8) {
    return `${(value / 1e8).toFixed(2)}억`;
  }
  if (absValue >= 1e4) {
    return `${(value / 1e4).toFixed(0)}만`;
  }
  return value.toLocaleString('ko-KR');
}

// Market icon component
function MarketIcon({ market }: { market: 'stock' | 'coin' | 'kiwoom' }) {
  switch (market) {
    case 'stock':
      return <LineChart className="w-5 h-5 text-green-400" />;
    case 'coin':
      return <Bitcoin className="w-5 h-5 text-yellow-400" />;
    case 'kiwoom':
      return <Building2 className="w-5 h-5 text-blue-400" />;
  }
}

// Market name
function getMarketName(market: 'stock' | 'coin' | 'kiwoom'): string {
  switch (market) {
    case 'stock': return 'US Stock';
    case 'coin': return 'Crypto';
    case 'kiwoom': return 'KR Stock';
  }
}

export function MarketSummaryWidget() {
  const [summaryData, setSummaryData] = useState<SummaryData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const activeMarket = useStore((state) => state.activeMarket);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);

  // Check if API is configured for current market
  const isApiConfigured =
    activeMarket === 'coin' ? upbitApiConfigured :
    activeMarket === 'kiwoom' ? kiwoomApiConfigured :
    true; // Stock doesn't need API config

  // Fetch Kiwoom account data
  const fetchKiwoomData = useCallback(async (): Promise<SummaryData | null> => {
    if (!kiwoomApiConfigured) return null;

    try {
      const response: KRStockAccountResponse = await getKRStockAccount();
      return {
        totalAssets: response.total_eval_amount,
        profitLoss: response.total_profit_loss,
        profitLossRate: response.total_profit_loss_rate,
        holdingsCount: response.holdings?.length || 0,
      };
    } catch (err) {
      throw new Error('계좌 정보를 불러올 수 없습니다');
    }
  }, [kiwoomApiConfigured]);

  // Fetch Coin account data
  const fetchCoinData = useCallback(async (): Promise<SummaryData | null> => {
    if (!upbitApiConfigured) return null;

    try {
      const response: CoinAccountListResponse = await getCoinAccounts();
      const cryptoAccounts = response.accounts.filter(a => a.currency !== 'KRW');
      const krwAccount = response.accounts.find(a => a.currency === 'KRW');

      return {
        totalAssets: response.total_krw_value || 0,
        profitLoss: 0, // Upbit doesn't provide P&L directly
        profitLossRate: 0,
        holdingsCount: cryptoAccounts.length + (krwAccount && krwAccount.balance > 0 ? 1 : 0),
      };
    } catch (err) {
      throw new Error('계좌 정보를 불러올 수 없습니다');
    }
  }, [upbitApiConfigured]);

  // Main fetch function
  const fetchData = useCallback(async () => {
    if (!isApiConfigured) {
      setIsLoading(false);
      return;
    }

    try {
      setError(null);

      let data: SummaryData | null = null;

      if (activeMarket === 'kiwoom') {
        data = await fetchKiwoomData();
      } else if (activeMarket === 'coin') {
        data = await fetchCoinData();
      } else {
        // Stock market - placeholder
        data = {
          totalAssets: 0,
          profitLoss: 0,
          profitLossRate: 0,
          holdingsCount: 0,
        };
      }

      setSummaryData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '데이터 로딩 실패');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [activeMarket, isApiConfigured, fetchKiwoomData, fetchCoinData]);

  // Refresh handler
  const handleRefresh = () => {
    setIsRefreshing(true);
    fetchData();
  };

  // Initial fetch and market change
  useEffect(() => {
    setIsLoading(true);
    setSummaryData(null);
    fetchData();
  }, [fetchData]);

  // Auto-refresh every 60 seconds
  useEffect(() => {
    if (!isApiConfigured) return;

    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData, isApiConfigured]);

  // API not configured state
  if (!isApiConfigured) {
    return (
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MarketIcon market={activeMarket} />
            <h3 className="font-semibold">마켓 요약</h3>
            <span className="px-2 py-0.5 text-xs bg-gray-600 rounded-full">
              {getMarketName(activeMarket)}
            </span>
          </div>
        </div>

        <div className="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-yellow-500 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm text-yellow-500 font-medium">
                {activeMarket === 'coin' ? 'Upbit' : 'Kiwoom'} API 미등록
              </p>
              <p className="text-xs text-gray-400 mt-1">
                계좌 정보를 보려면 API를 등록하세요
              </p>
              <button
                onClick={() => setShowSettingsModal(true)}
                className="flex items-center gap-1.5 mt-3 px-3 py-1.5 text-xs bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-400 rounded transition-colors"
              >
                <Settings className="w-3.5 h-3.5" />
                설정으로 이동
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Loading state
  if (isLoading && !summaryData) {
    return (
      <div className="card animate-pulse">
        <div className="flex items-center justify-between mb-4">
          <div className="h-6 w-32 bg-gray-700 rounded" />
          <div className="h-6 w-6 bg-gray-700 rounded" />
        </div>
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="p-4 bg-surface-dark rounded-lg">
              <div className="h-4 w-16 bg-gray-700 rounded mb-2" />
              <div className="h-6 w-24 bg-gray-700 rounded" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MarketIcon market={activeMarket} />
            <h3 className="font-semibold">마켓 요약</h3>
          </div>
        </div>
        <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg">
          <div className="flex items-center gap-2 text-red-400">
            <AlertCircle className="w-4 h-4" />
            <span className="text-sm">{error}</span>
          </div>
          <button
            onClick={handleRefresh}
            className="mt-2 text-xs text-red-400 hover:text-red-300 flex items-center gap-1"
          >
            <RefreshCw className="w-3 h-3" />
            다시 시도
          </button>
        </div>
      </div>
    );
  }

  const profitColor = (summaryData?.profitLoss ?? 0) >= 0 ? 'text-red-400' : 'text-blue-400';
  const ProfitIcon = (summaryData?.profitLoss ?? 0) >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <MarketIcon market={activeMarket} />
          <h3 className="font-semibold">마켓 요약</h3>
          <span className="px-2 py-0.5 text-xs bg-gray-600 rounded-full">
            {getMarketName(activeMarket)}
          </span>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className="p-1.5 text-gray-400 hover:text-gray-300 hover:bg-surface rounded transition-colors disabled:opacity-50"
          title="새로고침"
        >
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-3">
        {/* Total Assets */}
        <div className="p-3 bg-gradient-to-br from-blue-600/20 to-purple-600/20 rounded-lg">
          <div className="flex items-center gap-1.5 text-gray-400 mb-1">
            <Wallet className="w-4 h-4" />
            <span className="text-xs">총 자산</span>
          </div>
          <div className="text-lg font-bold">
            ₩{formatKRW(summaryData?.totalAssets ?? 0)}
          </div>
        </div>

        {/* Profit/Loss */}
        <div className="p-3 bg-surface-dark rounded-lg">
          <div className="flex items-center gap-1.5 text-gray-400 mb-1">
            <ProfitIcon className="w-4 h-4" />
            <span className="text-xs">오늘 수익</span>
          </div>
          <div className={`text-lg font-bold ${profitColor}`}>
            {(summaryData?.profitLoss ?? 0) >= 0 ? '+' : ''}₩{formatKRW(summaryData?.profitLoss ?? 0)}
          </div>
          {summaryData?.profitLossRate !== 0 && (
            <div className={`text-xs ${profitColor}`}>
              ({(summaryData?.profitLossRate ?? 0) >= 0 ? '+' : ''}{(summaryData?.profitLossRate ?? 0).toFixed(2)}%)
            </div>
          )}
        </div>

        {/* Holdings Count */}
        <div className="p-3 bg-surface-dark rounded-lg">
          <div className="flex items-center gap-1.5 text-gray-400 mb-1">
            <Package className="w-4 h-4" />
            <span className="text-xs">보유 종목</span>
          </div>
          <div className="text-lg font-bold">
            {summaryData?.holdingsCount ?? 0}개
          </div>
        </div>
      </div>
    </div>
  );
}
