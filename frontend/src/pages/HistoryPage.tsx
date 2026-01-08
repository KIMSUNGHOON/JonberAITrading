/**
 * HistoryPage Component
 *
 * Full-page view of analysis history with filtering and search.
 * - Filter by market type
 * - Filter by status (completed, cancelled, error)
 * - Search by ticker/name
 * - Detailed view of past analyses
 */

import { useState, useMemo } from 'react';
import { ArrowLeft, Search, Filter, CheckCircle2, XCircle, AlertCircle } from 'lucide-react';
import { useStore, selectTickerHistory, type MarketType } from '@/store';

interface HistoryPageProps {
  onBack?: () => void;
}

type StatusFilter = 'all' | 'completed' | 'cancelled' | 'error';

function getStatusIcon(status: string) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="w-4 h-4 text-green-400" />;
    case 'cancelled':
      return <XCircle className="w-4 h-4 text-yellow-400" />;
    case 'error':
      return <AlertCircle className="w-4 h-4 text-red-400" />;
    default:
      return null;
  }
}

function formatDate(date: Date): string {
  const d = new Date(date);
  return d.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getMarketLabel(marketType: MarketType): string {
  switch (marketType) {
    case 'stock':
      return 'US Stock';
    case 'coin':
      return 'Crypto';
    case 'kiwoom':
      return 'KR Stock';
    default:
      return marketType;
  }
}

// Helper to get display name from different history item types
function getDisplayName(item: unknown): string | null {
  if (item && typeof item === 'object') {
    if ('stk_nm' in item && (item as { stk_nm?: string }).stk_nm) {
      return (item as { stk_nm: string }).stk_nm;
    }
    if ('koreanName' in item && (item as { koreanName?: string }).koreanName) {
      return (item as { koreanName: string }).koreanName;
    }
  }
  return null;
}

// Helper to get action from history item if present
function getAction(item: unknown): string | null {
  if (item && typeof item === 'object' && 'action' in item && (item as { action?: string }).action) {
    return (item as { action: string }).action;
  }
  return null;
}

export function HistoryPage({ onBack }: HistoryPageProps) {
  const setCurrentView = useStore((state) => state.setCurrentView);
  const history = useStore(selectTickerHistory);

  const [searchQuery, setSearchQuery] = useState('');
  const [marketFilter, setMarketFilter] = useState<MarketType | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      setCurrentView('dashboard');
    }
  };

  // Filter and search history
  const filteredHistory = useMemo(() => {
    return history.filter((item) => {
      // Market filter
      if (marketFilter !== 'all') {
        const itemMarket = 'market' in item ? 'coin' : 'stk_cd' in item ? 'kiwoom' : 'stock';
        if (itemMarket !== marketFilter) return false;
      }

      // Status filter
      if (statusFilter !== 'all' && item.status !== statusFilter) {
        return false;
      }

      // Search filter
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const ticker = item.ticker.toLowerCase();
        const name = getDisplayName(item) || item.ticker;
        if (!ticker.includes(query) && !name.toLowerCase().includes(query)) {
          return false;
        }
      }

      return true;
    });
  }, [history, marketFilter, statusFilter, searchQuery]);

  // Stats
  const stats = useMemo(() => {
    const completed = history.filter((h) => h.status === 'completed').length;
    const cancelled = history.filter((h) => h.status === 'cancelled').length;
    const error = history.filter((h) => h.status === 'error').length;
    return { total: history.length, completed, cancelled, error };
  }, [history]);

  return (
    <div className="h-full flex flex-col bg-surface">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-surface-dark">
        <button
          onClick={handleBack}
          className="p-2 rounded-lg hover:bg-surface transition-colors"
          title="Back to Dashboard"
        >
          <ArrowLeft className="w-5 h-5 text-gray-400" />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-semibold">Analysis History</h1>
          <p className="text-sm text-gray-500">
            {stats.total} total analyses ({stats.completed} completed, {stats.cancelled} cancelled, {stats.error} errors)
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 px-6 py-3 border-b border-border bg-surface-dark/50">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by ticker or name..."
            className="w-full pl-10 pr-4 py-2 bg-surface border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50"
          />
        </div>

        {/* Market Filter */}
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-gray-500" />
          <select
            value={marketFilter}
            onChange={(e) => setMarketFilter(e.target.value as MarketType | 'all')}
            className="px-3 py-2 bg-surface border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50"
          >
            <option value="all">All Markets</option>
            <option value="kiwoom">KR Stocks</option>
            <option value="coin">Crypto</option>
            <option value="stock">US Stocks</option>
          </select>
        </div>

        {/* Status Filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          className="px-3 py-2 bg-surface border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50"
        >
          <option value="all">All Status</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
          <option value="error">Error</option>
        </select>
      </div>

      {/* History List */}
      <div className="flex-1 overflow-y-auto p-6">
        {filteredHistory.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            {history.length === 0 ? (
              <p>No analysis history yet. Start analyzing stocks or coins!</p>
            ) : (
              <p>No results found for your filters.</p>
            )}
          </div>
        ) : (
          <div className="max-w-4xl mx-auto space-y-3">
            {filteredHistory.map((item) => {
              const itemMarket: MarketType = 'market' in item ? 'coin' : 'stk_cd' in item ? 'kiwoom' : 'stock';
              const displayName = getDisplayName(item);
              const action = getAction(item);

              return (
                <div
                  key={item.sessionId}
                  className="flex items-center gap-4 p-4 bg-surface-dark rounded-lg border border-border hover:border-gray-600 transition-colors cursor-pointer"
                >
                  {/* Status Icon */}
                  {getStatusIcon(item.status)}

                  {/* Ticker & Name */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{displayName || item.ticker}</span>
                      {displayName && (
                        <span className="text-sm text-gray-500">({item.ticker})</span>
                      )}
                      <span className="px-2 py-0.5 text-xs bg-surface rounded text-gray-400">
                        {getMarketLabel(itemMarket)}
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      {formatDate(item.timestamp)}
                    </div>
                  </div>

                  {/* Action (optional) */}
                  {action && (
                    <span
                      className={`px-2 py-1 text-xs font-medium rounded ${
                        action === 'BUY'
                          ? 'bg-green-500/20 text-green-400'
                          : action === 'SELL'
                            ? 'bg-red-500/20 text-red-400'
                            : 'bg-gray-500/20 text-gray-400'
                      }`}
                    >
                      {action}
                    </span>
                  )}

                  {/* Status Badge */}
                  <span
                    className={`px-2 py-1 text-xs rounded ${
                      item.status === 'completed'
                        ? 'bg-green-500/20 text-green-400'
                        : item.status === 'cancelled'
                          ? 'bg-yellow-500/20 text-yellow-400'
                          : 'bg-red-500/20 text-red-400'
                    }`}
                  >
                    {item.status}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
