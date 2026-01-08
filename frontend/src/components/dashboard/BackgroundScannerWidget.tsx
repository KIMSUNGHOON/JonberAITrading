/**
 * BackgroundScannerWidget Component
 *
 * Dashboard widget for controlling background stock scanner:
 * - Start/Stop/Pause/Resume scan
 * - Progress display
 * - Results filtering by action (BUY, SELL, etc.)
 * - Quick view of scan results
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Scan,
  Play,
  Pause,
  Square,
  RefreshCw,
  Clock,
  CheckCircle,
  AlertCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useStore } from '@/store';
import {
  startScan,
  pauseScan,
  resumeScan,
  stopScan,
  getScanProgress,
  getScanResults,
  startKRStockAnalysis,
} from '@/api/client';
import type { ScanProgressResponse, ScanResultItem, ScanStatus } from '@/types';

// -------------------------------------------
// Helper Functions
// -------------------------------------------

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  return date.toLocaleString('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatPrice(price: number): string {
  if (price >= 10000) {
    return `${(price / 10000).toFixed(1)}만`;
  }
  return price.toLocaleString('ko-KR');
}

// -------------------------------------------
// Sub-components
// -------------------------------------------

interface StatusBadgeProps {
  status: ScanStatus;
}

function StatusBadge({ status }: StatusBadgeProps) {
  const styles: Record<ScanStatus, { bg: string; text: string; label: string }> = {
    idle: { bg: 'bg-gray-500/20', text: 'text-gray-400', label: '대기' },
    running: { bg: 'bg-green-500/20', text: 'text-green-400', label: '진행중' },
    paused: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: '일시정지' },
    completed: { bg: 'bg-blue-500/20', text: 'text-blue-400', label: '완료' },
    error: { bg: 'bg-red-500/20', text: 'text-red-400', label: '오류' },
  };

  const style = styles[status] || styles.idle;

  return (
    <span className={`px-2 py-0.5 text-xs rounded-full ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

interface ActionBadgeProps {
  action: string;
  count: number;
  onClick: () => void;
  active: boolean;
}

function ActionBadge({ action, count, onClick, active }: ActionBadgeProps) {
  const colors: Record<string, string> = {
    BUY: 'bg-green-500/20 text-green-400 border-green-500/30',
    SELL: 'bg-red-500/20 text-red-400 border-red-500/30',
    HOLD: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    WATCH: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    AVOID: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  };

  const activeClass = active ? 'ring-2 ring-offset-1 ring-offset-gray-900' : '';

  return (
    <button
      onClick={onClick}
      className={`px-2 py-1 text-xs rounded border ${colors[action] || colors.HOLD} ${activeClass} transition-all`}
    >
      {action}: {count}
    </button>
  );
}

interface ResultItemProps {
  item: ScanResultItem;
  onAnalyze: (stk_cd: string, stk_nm: string) => void;
  analyzing: string | null;
}

function ResultItem({ item, onAnalyze, analyzing }: ResultItemProps) {
  const actionColors: Record<string, string> = {
    BUY: 'text-green-400',
    SELL: 'text-red-400',
    HOLD: 'text-gray-400',
    WATCH: 'text-blue-400',
    AVOID: 'text-orange-400',
  };

  return (
    <div className="flex items-center gap-3 px-3 py-2 hover:bg-gray-800/50 transition-colors">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm text-white truncate">
            {item.stk_nm}
          </span>
          <span className={`text-xs ${actionColors[item.action] || 'text-gray-400'}`}>
            {item.action}
          </span>
        </div>
        <div className="text-xs text-gray-500">
          {item.stk_cd} | {Math.round(item.confidence * 100)}%
        </div>
      </div>
      <div className="text-right">
        <div className="text-sm text-white">
          {formatPrice(item.current_price)}
        </div>
      </div>
      <button
        onClick={() => onAnalyze(item.stk_cd, item.stk_nm)}
        disabled={analyzing === item.stk_cd}
        className="p-1.5 text-blue-400 hover:bg-blue-500/20 rounded disabled:opacity-50"
        title="상세 분석"
      >
        {analyzing === item.stk_cd ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Scan className="w-4 h-4" />
        )}
      </button>
    </div>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

export function BackgroundScannerWidget() {
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const setCurrentView = useStore((state) => state.setCurrentView);
  const startKiwoomSession = useStore((state) => state.startKiwoomSession);

  const [progress, setProgress] = useState<ScanProgressResponse | null>(null);
  const [results, setResults] = useState<ScanResultItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedAction, setSelectedAction] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  // Fetch progress and results
  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [progressData, resultsData] = await Promise.all([
        getScanProgress(),
        getScanResults(selectedAction || undefined),
      ]);
      setProgress(progressData);
      setResults(resultsData.results);
    } catch (err) {
      console.error('Failed to fetch scanner data:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  }, [selectedAction]);

  useEffect(() => {
    fetchData();
    // Poll every 5 seconds when running
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Action handlers
  const handleStart = async () => {
    try {
      setActionLoading(true);
      await startScan({ notify_progress: true });
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start scan');
    } finally {
      setActionLoading(false);
    }
  };

  const handlePause = async () => {
    try {
      setActionLoading(true);
      await pauseScan();
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to pause scan');
    } finally {
      setActionLoading(false);
    }
  };

  const handleResume = async () => {
    try {
      setActionLoading(true);
      await resumeScan();
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resume scan');
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = async () => {
    try {
      setActionLoading(true);
      await stopScan();
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop scan');
    } finally {
      setActionLoading(false);
    }
  };

  const handleAnalyze = async (stk_cd: string, stk_nm: string) => {
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
  };

  const handleFilterChange = (action: string) => {
    setSelectedAction(selectedAction === action ? null : action);
  };

  if (loading && !progress) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
        <div className="flex items-center gap-2 mb-4">
          <Scan className="w-5 h-5 text-purple-400" />
          <h2 className="text-lg font-semibold text-white">Background Scanner</h2>
        </div>
        <div className="flex items-center justify-center h-24">
          <RefreshCw className="w-6 h-6 animate-spin text-purple-500" />
        </div>
      </div>
    );
  }

  const status = (progress?.status || 'idle') as ScanStatus;
  const isRunning = status === 'running';
  const isPaused = status === 'paused';

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Scan className={`w-5 h-5 ${isRunning ? 'text-green-400 animate-pulse' : 'text-purple-400'}`} />
            <h2 className="text-lg font-semibold text-white">Background Scanner</h2>
            <StatusBadge status={status} />
          </div>
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="mt-2 p-2 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-400 flex items-center gap-2">
            <AlertCircle className="w-3 h-3" />
            {error}
          </div>
        )}
      </div>

      {/* Progress Bar */}
      {isRunning && progress && (
        <div className="px-4 py-2 border-b border-gray-800">
          <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
            <span>{progress.completed} / {progress.total_stocks} 완료</span>
            <span>{progress.progress_pct.toFixed(1)}%</span>
          </div>
          <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-purple-500 to-blue-500 transition-all duration-500"
              style={{ width: `${progress.progress_pct}%` }}
            />
          </div>
          {progress.current_stocks.length > 0 && (
            <div className="mt-1 text-xs text-gray-500 truncate">
              분석중: {progress.current_stocks.join(', ')}
            </div>
          )}
        </div>
      )}

      {/* Controls */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex gap-2">
          {status === 'idle' || status === 'completed' || status === 'error' ? (
            <button
              onClick={handleStart}
              disabled={actionLoading}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg disabled:opacity-50"
            >
              {actionLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              스캔 시작
            </button>
          ) : isPaused ? (
            <>
              <button
                onClick={handleResume}
                disabled={actionLoading}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg disabled:opacity-50"
              >
                <Play className="w-4 h-4" />
                계속
              </button>
              <button
                onClick={handleStop}
                disabled={actionLoading}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded-lg disabled:opacity-50"
              >
                <Square className="w-4 h-4" />
                중지
              </button>
            </>
          ) : (
            <>
              <button
                onClick={handlePause}
                disabled={actionLoading}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-yellow-600 hover:bg-yellow-700 text-white text-sm rounded-lg disabled:opacity-50"
              >
                <Pause className="w-4 h-4" />
                일시정지
              </button>
              <button
                onClick={handleStop}
                disabled={actionLoading}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded-lg disabled:opacity-50"
              >
                <Square className="w-4 h-4" />
                중지
              </button>
            </>
          )}
        </div>
      </div>

      {/* Action Filters */}
      {progress && (progress.buy_count > 0 || progress.sell_count > 0 || progress.hold_count > 0) && (
        <div className="p-4 border-b border-gray-800">
          <div className="flex flex-wrap gap-2">
            <ActionBadge
              action="BUY"
              count={progress.buy_count}
              onClick={() => handleFilterChange('BUY')}
              active={selectedAction === 'BUY'}
            />
            <ActionBadge
              action="SELL"
              count={progress.sell_count}
              onClick={() => handleFilterChange('SELL')}
              active={selectedAction === 'SELL'}
            />
            <ActionBadge
              action="HOLD"
              count={progress.hold_count}
              onClick={() => handleFilterChange('HOLD')}
              active={selectedAction === 'HOLD'}
            />
            <ActionBadge
              action="WATCH"
              count={progress.watch_count}
              onClick={() => handleFilterChange('WATCH')}
              active={selectedAction === 'WATCH'}
            />
            <ActionBadge
              action="AVOID"
              count={progress.avoid_count}
              onClick={() => handleFilterChange('AVOID')}
              active={selectedAction === 'AVOID'}
            />
          </div>
        </div>
      )}

      {/* Results */}
      {expanded && results.length > 0 && (
        <div className="max-h-64 overflow-y-auto divide-y divide-gray-800">
          {results.slice(0, 20).map((item) => (
            <ResultItem
              key={item.stk_cd}
              item={item}
              onAnalyze={handleAnalyze}
              analyzing={analyzing}
            />
          ))}
          {results.length > 20 && (
            <div className="p-3 text-center text-xs text-gray-500">
              +{results.length - 20}개 더 있음
            </div>
          )}
        </div>
      )}

      {/* Footer Stats */}
      {progress && (
        <div className="px-4 py-3 bg-gray-800/30 text-xs text-gray-500">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              마지막 스캔: {formatDate(progress.last_scan_date)}
            </div>
            {progress.completed_at && (
              <div className="flex items-center gap-1">
                <CheckCircle className="w-3 h-3" />
                완료: {formatDate(progress.completed_at)}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
