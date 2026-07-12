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
import { useGoTo } from '@/hooks/useNav';
import { pnlColor } from '@/utils/pnl';
import { Awaiting, TH } from '@/components/terminal/panels/shared';

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

// Action -> text color. BUY/SELL genuinely express bullish/bearish direction,
// so they route through the shared P&L helper (single source of truth for
// up/down semantics); HOLD/WATCH/AVOID are non-directional and use the
// dedicated semantic tokens. Trading colors are TEXT ONLY (never a fill), so
// badges below sit on a neutral bg-elevated/border-hairline chip.
const ACTION_TEXT_COLOR: Record<string, string> = {
  BUY: pnlColor(1), // bullish -> text-up (western convention)
  SELL: pnlColor(-1), // bearish -> text-down
  HOLD: 'text-muted',
  WATCH: 'text-warn',
  AVOID: 'text-accent',
};

// Border accent for the selected stat-tile (borders aren't a "fill", so the
// text-only trading-color rule doesn't restrict them here).
const ACTION_BORDER_COLOR: Record<string, string> = {
  BUY: 'border-up',
  SELL: 'border-down',
  HOLD: 'border-dim',
  WATCH: 'border-warn',
  AVOID: 'border-accent',
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
  const goTo = useGoTo();
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
      goTo('dashboard');
    }
  };

  const handleAnalyze = useCallback(async (stk_cd: string, stk_nm: string) => {
    try {
      setAnalyzing(stk_cd);
      setActiveMarket('kiwoom');
      const response = await startKRStockAnalysis({ stk_cd });
      startKiwoomSession(response.session_id, stk_cd, stk_nm);
      goTo('workflow', response.session_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start analysis');
    } finally {
      setAnalyzing(null);
    }
  }, [setActiveMarket, startKiwoomSession, goTo]);

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
    <div className="h-full flex flex-col bg-canvas">
      {/* Header */}
      <div className="flex-none border-b border-hairline bg-card sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={handleBack}
                className="p-1.5 hover:bg-elevated rounded transition-colors"
              >
                <ArrowLeft className="w-4 h-4 text-muted" />
              </button>
              <div>
                <h1 className="text-sm font-semibold text-ink">Scanner Results</h1>
                <p className="text-[11px] text-dim">
                  {total > 0 ? `${total}개 종목 분석 완료` : '분석 결과 없음'}
                </p>
              </div>
            </div>
            <button
              onClick={loadResults}
              className="flex items-center gap-2 px-3 py-1.5 bg-accent hover:bg-accent/90 text-canvas text-xs font-medium rounded transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              새로고침
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
      <div className="max-w-7xl mx-auto">
        {/* Counts Summary */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-4">
          {(['BUY', 'SELL', 'HOLD', 'WATCH', 'AVOID'] as const).map((action) => (
            <button
              key={action}
              onClick={() => setActionFilter(actionFilter === action ? 'all' : action)}
              className={`p-3 rounded-lg border transition-all ${
                actionFilter === action
                  ? `bg-elevated border-2 ${ACTION_BORDER_COLOR[action]} ${ACTION_TEXT_COLOR[action]}`
                  : 'bg-card border-hairline hover:border-dim text-ink'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] uppercase tracking-wide font-medium">{action}</span>
                {ACTION_ICONS[action]}
              </div>
              <div className="text-lg font-bold tabular-nums">
                {counts[`${action.toLowerCase()}_count`] || 0}
              </div>
            </button>
          ))}
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-4">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
            <input
              type="text"
              placeholder="종목코드 또는 종목명 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-card border border-hairline rounded-lg text-ink placeholder:text-dim focus:outline-none focus:border-accent"
            />
          </div>

          {/* Session Select */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-muted" />
            <select
              value={selectedSession || ''}
              onChange={(e) => {
                setSelectedSession(e.target.value || undefined);
                setPage(0);
              }}
              className="px-4 py-2 bg-card border border-hairline rounded-lg text-ink focus:outline-none focus:border-accent"
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
                  ? 'bg-accent text-canvas'
                  : 'bg-elevated text-ink hover:bg-hairline'
              }`}
            >
              전체
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-4 bg-down/20 border border-down/30 rounded-lg text-down">
            {error}
          </div>
        )}

        {/* Results Table */}
        <div className="bg-card rounded-lg border border-hairline overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className={`${TH} text-left`}>종목</th>
                  <th className={`${TH} text-left`}>시장</th>
                  <th className={`${TH} text-center`}>액션</th>
                  <th className={TH}>현재가</th>
                  <th className={`${TH} text-center`}>신뢰도</th>
                  <th className={`${TH} text-left`}>요약</th>
                  <th className={`${TH} text-center`}>분석일시</th>
                  <th className={`${TH} text-center`}>액션</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-dim">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
                      로딩 중...
                    </td>
                  </tr>
                ) : filteredResults.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="p-0">
                      <Awaiting
                        label={searchQuery ? '검색 결과가 없습니다.' : '분석 결과가 없습니다.'}
                      />
                    </td>
                  </tr>
                ) : (
                  filteredResults.map((result) => {
                    // 감사 발견: 분석 실패(인증 오류 등) 행이 "HOLD 50%"처럼
                    // 표시돼 실패가 분석 결과로 위장됨 — 실패는 실패로 표기.
                    const isFailed = (result.summary || '').startsWith('분석 실패');
                    return (
                    <tr
                      key={`${result.stk_cd}-${result.scanned_at}`}
                      className="hover:bg-elevated/40 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div>
                          <div className="font-medium text-ink">{result.stk_nm}</div>
                          <div className="text-xs text-muted">{result.stk_cd}</div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs px-2 py-1 bg-elevated rounded text-muted">
                          {result.market_type || '-'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {isFailed ? (
                          <span className="inline-flex items-center gap-1 px-2 py-1 rounded border border-down/40 bg-elevated text-xs font-medium text-down">
                            실패
                          </span>
                        ) : (
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-1 rounded border border-hairline bg-elevated text-xs font-medium ${
                            ACTION_TEXT_COLOR[result.action] ?? 'text-muted'
                          }`}
                        >
                          {ACTION_ICONS[result.action]}
                          {result.action}
                        </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums text-ink">
                        {result.current_price > 0
                          ? `₩${formatPrice(result.current_price)}`
                          : '-'}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {isFailed ? (
                          <span className="text-xs text-dim">—</span>
                        ) : (
                        <div className="flex items-center justify-center">
                          <div className="w-16 h-2 bg-elevated rounded-full overflow-hidden">
                            <div
                              className={`h-full ${
                                result.confidence >= 0.7
                                  ? 'bg-up'
                                  : result.confidence >= 0.5
                                  ? 'bg-warn'
                                  : 'bg-down'
                              }`}
                              style={{ width: `${result.confidence * 100}%` }}
                            />
                          </div>
                          <span className="ml-2 text-xs text-muted tabular-nums">
                            {(result.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="max-w-xs truncate text-sm text-ink" title={result.summary}>
                          {result.summary || '-'}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-center text-xs text-muted">
                        {formatDate(result.scanned_at)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleAnalyze(result.stk_cd, result.stk_nm)}
                          disabled={analyzing === result.stk_cd}
                          className="px-3 py-1 bg-accent hover:bg-accent/90 text-canvas rounded text-xs font-medium transition-colors disabled:opacity-50"
                        >
                          {analyzing === result.stk_cd ? '분석중...' : '상세분석'}
                        </button>
                      </td>
                    </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="px-4 py-3 border-t border-hairline flex items-center justify-between">
              <div className="text-sm text-muted tabular-nums">
                {page * pageSize + 1} - {Math.min((page + 1) * pageSize, total)} / {total}개
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(Math.max(0, page - 1))}
                  disabled={page === 0}
                  className="p-2 hover:bg-elevated rounded disabled:opacity-50 disabled:cursor-not-allowed text-muted"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span className="px-4 py-2 text-sm tabular-nums text-ink">
                  {page + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                  disabled={page >= totalPages - 1}
                  className="p-2 hover:bg-elevated rounded disabled:opacity-50 disabled:cursor-not-allowed text-muted"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}

export default ScannerResultsPage;
