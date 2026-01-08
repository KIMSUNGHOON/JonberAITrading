/**
 * ScannerResultsPage Component
 *
 * Full-page view of background scanner results from database.
 * Features:
 * - Filter by action (BUY, SELL, HOLD, WATCH, AVOID)
 * - Session selection
 * - Pagination
 * - Sortable table
 * - Click to start analysis
 */

import { useState, useEffect, useCallback } from 'react';
import {
  ArrowLeft,
  Search,
  Filter,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Eye,
  ShieldAlert,
  Pause,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { apiClient, startKRStockAnalysis } from '@/api/client';
import { useStore } from '@/store';

interface ScannerResultsPageProps {
  onBack?: () => void;
}

interface ScanResult {
  stk_cd: string;
  stk_nm: string;
  action: string;
  signal: string;
  confidence: number;
  summary: string;
  key_factors: string[];
  current_price: number;
  market_type: string;
  scanned_at: string;
}

interface ScanSession {
  id: string;
  started_at: string | null;
  completed_at: string | null;
  total_stocks: number;
  completed: number;
  failed: number;
  buy_count: number;
  sell_count: number;
  hold_count: number;
  watch_count: number;
  avoid_count: number;
  status: string;
}

type ActionFilter = 'all' | 'BUY' | 'SELL' | 'HOLD' | 'WATCH' | 'AVOID';

const ACTION_COLORS: Record<string, string> = {
  BUY: 'bg-green-500/20 text-green-400 border-green-500/30',
  SELL: 'bg-red-500/20 text-red-400 border-red-500/30',
  HOLD: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  WATCH: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  AVOID: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
};

const ACTION_ICONS: Record<string, React.ReactNode> = {
  BUY: <TrendingUp className="w-4 h-4" />,
  SELL: <TrendingDown className="w-4 h-4" />,
  HOLD: <Pause className="w-4 h-4" />,
  WATCH: <Eye className="w-4 h-4" />,
  AVOID: <ShieldAlert className="w-4 h-4" />,
};

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  return d.toLocaleDateString('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatPrice(price: number): string {
  return new Intl.NumberFormat('ko-KR').format(price);
}

export function ScannerResultsPage({ onBack }: ScannerResultsPageProps) {
  // const language = useStore((state) => state.language);
  // const t = useTranslations(language);  // TODO: Add translations for scanner page
  const setCurrentView = useStore((state) => state.setCurrentView);
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const startKiwoomSession = useStore((state) => state.startKiwoomSession);

  // State
  const [results, setResults] = useState<ScanResult[]>([]);
  const [sessions, setSessions] = useState<ScanSession[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<string | null>(null);

  // Filters
  const [actionFilter, setActionFilter] = useState<ActionFilter>('all');
  const [selectedSession, setSelectedSession] = useState<string | undefined>(undefined);
  const [searchQuery, setSearchQuery] = useState('');

  // Pagination
  const [page, setPage] = useState(0);
  const [pageSize] = useState(50);
  const [total, setTotal] = useState(0);

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
  }, []);

  // Load results when filter changes
  useEffect(() => {
    loadResults();
  }, [actionFilter, selectedSession, page]);

  const loadSessions = async () => {
    try {
      const data = await apiClient.getScanSessions(10);
      setSessions(data.sessions);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    }
  };

  const loadResults = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getScanResultsFromDb({
        action: actionFilter === 'all' ? undefined : actionFilter,
        session_id: selectedSession,
        limit: pageSize,
        offset: page * pageSize,
      });
      setResults(data.results);
      setTotal(data.total || 0);

      // Also load counts
      const countsData = await apiClient.getScanCounts(selectedSession);
      setCounts(countsData);
    } catch (err) {
      console.error('Failed to load results:', err);
      setError('결과를 불러오는데 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      setCurrentView('dashboard');
    }
  };

  const handleAnalyze = useCallback(async (stk_cd: string, stk_nm: string) => {
    try {
      setAnalyzing(stk_cd);
      setActiveMarket('kiwoom');
      const response = await startKRStockAnalysis({ stk_cd });
      startKiwoomSession(response.session_id, stk_cd, stk_nm);
      setCurrentView('workflow');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start analysis');
    } finally {
      setAnalyzing(null);
    }
  }, [setActiveMarket, startKiwoomSession, setCurrentView]);

  const filteredResults = results.filter((item) => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      item.stk_cd.toLowerCase().includes(query) ||
      item.stk_nm.toLowerCase().includes(query)
    );
  });

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white">
      {/* Header */}
      <div className="border-b border-gray-700 bg-gray-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={handleBack}
                className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
              >
                <ArrowLeft className="w-5 h-5" />
              </button>
              <div>
                <h1 className="text-xl font-bold">Scanner Results</h1>
                <p className="text-sm text-gray-400">
                  {total > 0 ? `${total}개 종목 분석 완료` : '분석 결과 없음'}
                </p>
              </div>
            </div>
            <button
              onClick={loadResults}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              새로고침
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Counts Summary */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
          {(['BUY', 'SELL', 'HOLD', 'WATCH', 'AVOID'] as const).map((action) => (
            <button
              key={action}
              onClick={() => setActionFilter(actionFilter === action ? 'all' : action)}
              className={`p-4 rounded-lg border transition-all ${
                actionFilter === action
                  ? ACTION_COLORS[action] + ' border-2'
                  : 'bg-gray-800/50 border-gray-700 hover:border-gray-600'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs uppercase font-medium">{action}</span>
                {ACTION_ICONS[action]}
              </div>
              <div className="text-2xl font-bold">
                {counts[`${action.toLowerCase()}_count`] || 0}
              </div>
            </button>
          ))}
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-4 mb-6">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="종목코드 또는 종목명 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Session Select */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <select
              value={selectedSession || ''}
              onChange={(e) => {
                setSelectedSession(e.target.value || undefined);
                setPage(0);
              }}
              className="px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:border-blue-500"
            >
              <option value="">최근 세션</option>
              {sessions.map((session) => (
                <option key={session.id} value={session.id}>
                  {formatDate(session.started_at)} ({session.completed}/{session.total_stocks})
                </option>
              ))}
            </select>
          </div>

          {/* Action Filter Chips */}
          <div className="flex gap-2">
            <button
              onClick={() => {
                setActionFilter('all');
                setPage(0);
              }}
              className={`px-3 py-1 rounded-full text-sm transition-colors ${
                actionFilter === 'all'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              전체
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-4 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400">
            {error}
          </div>
        )}

        {/* Results Table */}
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-900/50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">종목</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">시장</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-400 uppercase">액션</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase">현재가</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-400 uppercase">신뢰도</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">요약</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-400 uppercase">분석일시</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-400 uppercase">액션</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
                      로딩 중...
                    </td>
                  </tr>
                ) : filteredResults.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                      {searchQuery ? '검색 결과가 없습니다.' : '분석 결과가 없습니다.'}
                    </td>
                  </tr>
                ) : (
                  filteredResults.map((result) => (
                    <tr
                      key={`${result.stk_cd}-${result.scanned_at}`}
                      className="hover:bg-gray-700/30 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div>
                          <div className="font-medium">{result.stk_nm}</div>
                          <div className="text-xs text-gray-400">{result.stk_cd}</div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs px-2 py-1 bg-gray-700 rounded">
                          {result.market_type || '-'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                            ACTION_COLORS[result.action] || 'bg-gray-700'
                          }`}
                        >
                          {ACTION_ICONS[result.action]}
                          {result.action}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {result.current_price > 0
                          ? `₩${formatPrice(result.current_price)}`
                          : '-'}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <div className="flex items-center justify-center">
                          <div className="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
                            <div
                              className={`h-full ${
                                result.confidence >= 0.7
                                  ? 'bg-green-500'
                                  : result.confidence >= 0.5
                                  ? 'bg-yellow-500'
                                  : 'bg-red-500'
                              }`}
                              style={{ width: `${result.confidence * 100}%` }}
                            />
                          </div>
                          <span className="ml-2 text-xs text-gray-400">
                            {(result.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="max-w-xs truncate text-sm text-gray-300" title={result.summary}>
                          {result.summary || '-'}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-center text-xs text-gray-400">
                        {formatDate(result.scanned_at)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleAnalyze(result.stk_cd, result.stk_nm)}
                          disabled={analyzing === result.stk_cd}
                          className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-xs transition-colors disabled:opacity-50"
                        >
                          {analyzing === result.stk_cd ? '분석중...' : '상세분석'}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="px-4 py-3 border-t border-gray-700 flex items-center justify-between">
              <div className="text-sm text-gray-400">
                {page * pageSize + 1} - {Math.min((page + 1) * pageSize, total)} / {total}개
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(Math.max(0, page - 1))}
                  disabled={page === 0}
                  className="p-2 hover:bg-gray-700 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span className="px-4 py-2 text-sm">
                  {page + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                  disabled={page >= totalPages - 1}
                  className="p-2 hover:bg-gray-700 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ScannerResultsPage;
