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

  const formatVolume = (volume: number) => {
    if (volume >= 100000000000) {
      return `${(volume / 100000000000).toFixed(1)}천억`;
    }
    if (volume >= 100000000) {
      return `${(volume / 100000000).toFixed(1)}억`;
    }
    return volume.toLocaleString('ko-KR');
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

  const getChangeBgColor = (change: number) => {
    if (change > 0) return 'bg-green-500/10';
    if (change < 0) return 'bg-red-500/10';
    return 'bg-gray-500/10';
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

      {/* Content */}
      <div className="p-2">
        {error ? (
          <div className="text-center text-red-400 py-8 text-sm">{error}</div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
            {stocks.map((stock, index) => (
              <div
                key={stock.stk_cd}
                onClick={() => handleStockClick(stock)}
                className={`relative p-3 rounded-lg cursor-pointer transition-all hover:scale-[1.02] hover:shadow-lg ${getChangeBgColor(stock.prdy_vrss)} border border-gray-700/50 hover:border-gray-600`}
                style={{
                  animation: `flightboard-flip 0.3s ease-out ${index * 0.05}s both`,
                }}
              >
                {/* Stock Name */}
                <div className="font-medium text-sm text-white truncate mb-1">
                  {stock.stk_nm}
                </div>

                {/* Price */}
                <div className="text-lg font-bold text-white">
                  {stock.cur_prc > 0 ? (
                    <>₩{formatPrice(stock.cur_prc)}</>
                  ) : (
                    <span className="text-gray-500">-</span>
                  )}
                </div>

                {/* Change */}
                <div className={`flex items-center gap-1 text-xs mt-1 ${getChangeColor(stock.prdy_vrss)}`}>
                  {getChangeIcon(stock.prdy_vrss)}
                  <span>
                    {stock.prdy_ctrt > 0 ? '+' : ''}
                    {stock.prdy_ctrt.toFixed(2)}%
                  </span>
                </div>

                {/* Volume */}
                {stock.trde_prica > 0 && (
                  <div className="text-xs text-gray-500 mt-1">
                    거래 {formatVolume(stock.trde_prica)}
                  </div>
                )}

                {/* Rank Badge */}
                <div className="absolute top-1 right-1 w-5 h-5 flex items-center justify-center text-xs font-bold text-gray-600 bg-gray-800/50 rounded">
                  {index + 1}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* CSS for flightboard animation */}
      <style>{`
        @keyframes flightboard-flip {
          0% {
            opacity: 0;
            transform: rotateX(-90deg) translateY(-10px);
          }
          100% {
            opacity: 1;
            transform: rotateX(0) translateY(0);
          }
        }
      `}</style>
    </div>
  );
}
