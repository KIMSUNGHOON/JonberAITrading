/**
 * PopularStocksWidget Component
 *
 * Dashboard widget showing popular Korean stocks in flightboard style:
 * - Single API call to get all tickers
 * - 1-minute auto refresh or manual refresh
 * - Flightboard animation effect
 * - Click to analyze
 */

import { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  BarChart2,
  Clock,
} from 'lucide-react';
import { useStore } from '@/store';
import { getKRStocks, startKRStockAnalysis } from '@/api/client';

interface StockItem {
  stk_cd: string;
  stk_nm: string;
  cur_prc: number;
  prdy_ctrt: number;
  prdy_vrss: number;
  trde_qty: number;
  trde_prica: number;
}

export function PopularStocksWidget() {
  const [stocks, setStocks] = useState<StockItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const setCurrentView = useStore((state) => state.setCurrentView);
  const startKiwoomSession = useStore((state) => state.startKiwoomSession);

  const fetchStocks = useCallback(async (isManual = false) => {
    try {
      if (isManual) {
        setRefreshing(true);
      }
      setError(null);

      const response = await getKRStocks();
      setStocks(response.stocks);
      setLastUpdate(new Date());
    } catch (err) {
      console.error('Failed to fetch popular stocks:', err);
      setError(err instanceof Error ? err.message : 'Failed to load stocks');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchStocks();

    // Auto refresh every 1 minute
    const interval = setInterval(() => fetchStocks(), 60000);
    return () => clearInterval(interval);
  }, [fetchStocks]);

  const handleRefresh = () => {
    fetchStocks(true);
  };

  const handleStockClick = async (stock: StockItem) => {
    try {
      // Set market to kiwoom and start analysis
      setActiveMarket('kiwoom');
      const response = await startKRStockAnalysis({ stk_cd: stock.stk_cd });
      startKiwoomSession(response.session_id, stock.stk_cd, stock.stk_nm);
      setCurrentView('workflow');
    } catch (err) {
      console.error('Failed to start analysis:', err);
    }
  };

  const formatPrice = (price: number) => {
    if (price >= 10000) {
      return `${(price / 10000).toFixed(1)}만`;
    }
    return price.toLocaleString('ko-KR');
  };

  const getChangeIcon = (change: number) => {
    if (change > 0) return <TrendingUp className="w-3 h-3" />;
    if (change < 0) return <TrendingDown className="w-3 h-3" />;
    return <Minus className="w-3 h-3" />;
  };

  const getChangeColor = (change: number) => {
    if (change > 0) return 'text-green-400';
    if (change < 0) return 'text-red-400';
    return 'text-gray-400';
  };

  if (loading && stocks.length === 0) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <BarChart2 className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-semibold text-white">Popular Stocks</h2>
          </div>
        </div>
        <div className="flex items-center justify-center h-48">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart2 className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-semibold text-white">Popular Stocks</h2>
            <span className="px-2 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded-full">
              KRX
            </span>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdate && (
              <div className="flex items-center gap-1 text-xs text-gray-500">
                <Clock className="w-3 h-3" />
                {lastUpdate.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
              </div>
            )}
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors disabled:opacity-50"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Content - Compact List View */}
      <div className="max-h-64 overflow-y-auto">
        {error ? (
          <div className="text-center text-red-400 py-4 text-sm">{error}</div>
        ) : (
          <div className="divide-y divide-gray-800">
            {stocks.map((stock, index) => (
              <div
                key={stock.stk_cd}
                onClick={() => handleStockClick(stock)}
                className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-800/50 transition-colors"
              >
                {/* Rank */}
                <span className="w-5 text-xs font-medium text-gray-500 text-center">
                  {index + 1}
                </span>

                {/* Stock Name */}
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-white truncate">
                    {stock.stk_nm}
                  </div>
                  <div className="text-xs text-gray-500">{stock.stk_cd}</div>
                </div>

                {/* Price & Change */}
                <div className="text-right">
                  <div className="text-sm font-medium text-white">
                    {stock.cur_prc > 0 ? `₩${formatPrice(stock.cur_prc)}` : '-'}
                  </div>
                  <div className={`flex items-center justify-end gap-0.5 text-xs ${getChangeColor(stock.prdy_vrss)}`}>
                    {getChangeIcon(stock.prdy_vrss)}
                    <span>
                      {stock.prdy_ctrt > 0 ? '+' : ''}
                      {stock.prdy_ctrt.toFixed(2)}%
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
