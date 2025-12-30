/**
 * WatchListWidget Component
 *
 * Shows stocks in watch list for monitoring:
 * - Watched stocks with analysis summary
 * - Convert to Trade Queue functionality
 * - Re-analyze button for updated analysis
 * - Remove from watch list
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Eye,
  X,
  RefreshCw,
  TrendingUp,
  ShoppingCart,
  AlertCircle,
  Search,
  Loader2,
  ArrowRight,
  Tag,
} from 'lucide-react';
import {
  getWatchList,
  removeFromWatchList,
  convertWatchToQueue,
  startKRStockAnalysis,
} from '@/api/client';
import type { WatchedStock } from '@/types';

// -------------------------------------------
// Constants
// -------------------------------------------

const SIGNAL_COLORS: Record<string, string> = {
  strong_buy: 'text-green-400 bg-green-500/10',
  buy: 'text-emerald-400 bg-emerald-500/10',
  hold: 'text-yellow-400 bg-yellow-500/10',
  sell: 'text-orange-400 bg-orange-500/10',
  strong_sell: 'text-red-400 bg-red-500/10',
};

const CONFIDENCE_COLORS: Record<string, string> = {
  high: 'text-green-400',
  medium: 'text-yellow-400',
  low: 'text-red-400',
};

// -------------------------------------------
// Helper Functions
// -------------------------------------------

function getConfidenceLevel(confidence: number): string {
  if (confidence >= 0.7) return 'high';
  if (confidence >= 0.4) return 'medium';
  return 'low';
}

function formatPrice(price: number): string {
  return new Intl.NumberFormat('ko-KR').format(price);
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// -------------------------------------------
// Sub-components
// -------------------------------------------

interface WatchItemProps {
  stock: WatchedStock;
  onRemove: (id: string) => void;
  onConvert: (id: string) => void;
  onReanalyze: (ticker: string, name: string) => void;
  removing: string | null;
  converting: string | null;
  reanalyzing: string | null;
}

function WatchItem({
  stock,
  onRemove,
  onConvert,
  onReanalyze,
  removing,
  converting,
  reanalyzing,
}: WatchItemProps) {
  const confidenceLevel = getConfidenceLevel(stock.confidence);

  return (
    <div className="p-3 rounded-lg border border-gray-700 bg-gray-800/50 hover:border-gray-600 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded bg-blue-500/20">
            <Eye className="w-4 h-4 text-blue-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-white">
                {stock.stock_name || stock.ticker}
              </span>
              <span className="text-xs text-gray-500">{stock.ticker}</span>
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`px-1.5 py-0.5 text-xs rounded ${SIGNAL_COLORS[stock.signal] || SIGNAL_COLORS.hold}`}>
                {stock.signal.toUpperCase()}
              </span>
              <span className={`text-xs ${CONFIDENCE_COLORS[confidenceLevel]}`}>
                {Math.round(stock.confidence * 100)}% 신뢰도
              </span>
            </div>
          </div>
        </div>

        {/* Remove Button */}
        <button
          onClick={() => onRemove(stock.id)}
          disabled={removing === stock.id}
          className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded disabled:opacity-50"
          title="Watch List에서 제거"
        >
          {removing === stock.id ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <X className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Price Info */}
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="text-gray-400">
          현재가: <span className="text-white">{formatPrice(stock.current_price)}원</span>
        </div>
        {stock.target_entry_price && (
          <div className="text-gray-400">
            목표가: <span className="text-green-400">{formatPrice(stock.target_entry_price)}원</span>
          </div>
        )}
        <div className="text-gray-400">
          리스크: <span className="text-white">{stock.risk_score}/10</span>
        </div>
      </div>

      {/* Stop Loss / Take Profit */}
      {(stock.stop_loss || stock.take_profit) && (
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
          {stock.stop_loss && (
            <div className="text-gray-400">
              손절: <span className="text-red-400">{formatPrice(stock.stop_loss)}원</span>
            </div>
          )}
          {stock.take_profit && (
            <div className="text-gray-400">
              익절: <span className="text-green-400">{formatPrice(stock.take_profit)}원</span>
            </div>
          )}
        </div>
      )}

      {/* Analysis Summary */}
      {stock.analysis_summary && (
        <div className="mt-3 p-2 bg-gray-900/50 rounded text-xs text-gray-300 line-clamp-2">
          {stock.analysis_summary}
        </div>
      )}

      {/* Key Factors */}
      {stock.key_factors && stock.key_factors.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {stock.key_factors.slice(0, 3).map((factor, idx) => (
            <span
              key={idx}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-700/50 text-gray-300 text-xs rounded"
            >
              <Tag className="w-3 h-3" />
              {factor}
            </span>
          ))}
          {stock.key_factors.length > 3 && (
            <span className="text-xs text-gray-500">+{stock.key_factors.length - 3}</span>
          )}
        </div>
      )}

      {/* Timestamp */}
      <div className="mt-2 text-xs text-gray-500">
        추가일: {formatDate(stock.created_at)}
      </div>

      {/* Action Buttons */}
      <div className="mt-3 flex gap-2">
        <button
          onClick={() => onConvert(stock.id)}
          disabled={converting === stock.id}
          className="flex-1 flex items-center justify-center gap-1 px-3 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg disabled:opacity-50 transition-colors"
        >
          {converting === stock.id ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <>
              <ShoppingCart className="w-4 h-4" />
              매수 대기열 추가
            </>
          )}
        </button>
        <button
          onClick={() => onReanalyze(stock.ticker, stock.stock_name || stock.ticker)}
          disabled={reanalyzing === stock.ticker}
          className="flex items-center justify-center gap-1 px-3 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 transition-colors"
          title="재분석"
        >
          {reanalyzing === stock.ticker ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Search className="w-4 h-4" />
          )}
        </button>
      </div>
    </div>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

export default function WatchListWidget() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [removing, setRemoving] = useState<string | null>(null);
  const [converting, setConverting] = useState<string | null>(null);
  const [reanalyzing, setReanalyzing] = useState<string | null>(null);
  const [watchList, setWatchList] = useState<WatchedStock[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchWatchList = useCallback(async () => {
    try {
      setError(null);
      const data = await getWatchList();
      // Filter only active items
      const activeItems = data.watch_list.filter(item => item.status === 'active');
      setWatchList(activeItems);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch watch list');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWatchList();
    // Poll every 30 seconds
    const interval = setInterval(fetchWatchList, 30000);
    return () => clearInterval(interval);
  }, [fetchWatchList]);

  const handleRemove = async (id: string) => {
    try {
      setRemoving(id);
      await removeFromWatchList(id);
      await fetchWatchList();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove from watch list');
    } finally {
      setRemoving(null);
    }
  };

  const handleConvert = async (id: string) => {
    try {
      setConverting(id);
      await convertWatchToQueue({
        watch_id: id,
        action: 'BUY',
        reason: 'User converted from watch list',
      });
      await fetchWatchList();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to convert to trade queue');
    } finally {
      setConverting(null);
    }
  };

  const handleReanalyze = async (ticker: string, name: string) => {
    try {
      setReanalyzing(ticker);
      const response = await startKRStockAnalysis({ stk_cd: ticker });
      // Navigate to analysis page
      navigate(`/analysis/${response.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start re-analysis');
    } finally {
      setReanalyzing(null);
    }
  };

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Eye className={`w-5 h-5 ${watchList.length > 0 ? 'text-blue-400' : 'text-gray-400'}`} />
            <h2 className="text-lg font-semibold text-white">Watch List</h2>
            {watchList.length > 0 && (
              <span className="px-2 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded-full">
                {watchList.length} 종목
              </span>
            )}
          </div>
          <button
            onClick={fetchWatchList}
            disabled={loading}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <p className="text-xs text-gray-500 mt-1">
          매수 대기 중인 관심 종목 목록
        </p>
      </div>

      {/* Content */}
      <div className="p-4">
        {error && (
          <div className="mb-4 p-3 bg-red-500/20 border border-red-500/30 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-red-400" />
            <span className="text-sm text-red-400">{error}</span>
            <button
              onClick={() => setError(null)}
              className="ml-auto text-red-400 hover:text-red-300"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {loading && watchList.length === 0 ? (
          <div className="text-center text-gray-400 py-8">
            <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin" />
            <p className="text-sm">Loading...</p>
          </div>
        ) : watchList.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            <Eye className="w-8 h-8 mx-auto mb-2 text-gray-600" />
            <p className="text-sm">Watch List가 비어있습니다</p>
            <p className="text-xs mt-1">WATCH 추천을 받은 종목이 여기에 표시됩니다</p>
          </div>
        ) : (
          <div className="space-y-3 max-h-[500px] overflow-y-auto">
            {watchList.map((stock) => (
              <WatchItem
                key={stock.id}
                stock={stock}
                onRemove={handleRemove}
                onConvert={handleConvert}
                onReanalyze={handleReanalyze}
                removing={removing}
                converting={converting}
                reanalyzing={reanalyzing}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer - Quick Stats */}
      {watchList.length > 0 && (
        <div className="px-4 py-3 border-t border-gray-800 bg-gray-800/30">
          <div className="flex items-center justify-between text-xs text-gray-400">
            <div className="flex items-center gap-4">
              <span>
                평균 신뢰도: {Math.round(watchList.reduce((acc, s) => acc + s.confidence, 0) / watchList.length * 100)}%
              </span>
              <span>
                평균 리스크: {(watchList.reduce((acc, s) => acc + s.risk_score, 0) / watchList.length).toFixed(1)}/10
              </span>
            </div>
            <button
              onClick={() => navigate('/trading')}
              className="flex items-center gap-1 text-blue-400 hover:text-blue-300"
            >
              Trading Dashboard
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
