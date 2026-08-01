/**
 * AnalysisPage Component
 *
 * New unified analysis page that shows:
 * - Running analyses (can click to see workflow progress)
 * - Completed analyses (can click to see detailed report)
 *
 * Replaces the ambiguous Analysis view with a clear list-based interface.
 */

import { useState, useMemo } from 'react';
import {
  BarChart3,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ChevronRight,
  Building2,
  Clock,
  Eye,
  Trash2,
} from 'lucide-react';
import { useStore, selectTickerHistory, type MarketType, type ActiveSession, type TickerHistoryItem } from '@/store';
import { useGoTo } from '@/hooks/useNav';
import { pnlColor } from '@/utils/pnl';
import type { SessionStatus } from '@/types';

interface AnalysisPageProps {
  // No props needed - navigation handled by sidebar
}

// Market type icon component (MarketType is a single-member 'kiwoom' union
// post-coin-removal — kept as a component rather than inlined so widening
// the union later doesn't require touching every call site).
function MarketIcon({ marketType: _marketType, size = 16 }: { marketType: MarketType; size?: number }) {
  return <Building2 size={size} className="text-current" />;
}

// Market identity color — not a P&L/direction value (analogous to the
// per-agent-category colors kept as-is elsewhere in the reskin), so this
// stays its distinct hue rather than routing through pnlColor.
function getMarketColor(_marketType: MarketType): string {
  return 'text-blue-400';
}

function getMarketLabel(_marketType: MarketType): string {
  return 'KR Stock';
}

// Session-status color — running/complete/error map to the semantic
// accent/up/down tokens; cancelled/awaiting_approval are genuine (non-P&L)
// warning states and route to the dedicated warn token instead of a raw
// hardcoded yellow.
function getStatusColor(status: SessionStatus | string): string {
  switch (status) {
    case 'completed': return 'text-up';
    case 'error': return 'text-down';
    case 'cancelled': return 'text-warn';
    case 'running': return 'text-accent';
    case 'awaiting_approval': return 'text-warn';
    default: return 'text-muted';
  }
}

function getStatusIcon(status: SessionStatus | string) {
  const color = getStatusColor(status);
  switch (status) {
    case 'completed':
      return <CheckCircle2 className={`w-5 h-5 ${color}`} />;
    case 'error':
      return <XCircle className={`w-5 h-5 ${color}`} />;
    case 'cancelled':
      return <XCircle className={`w-5 h-5 ${color}`} />;
    case 'running':
      return <Loader2 className={`w-5 h-5 ${color} animate-spin`} />;
    case 'awaiting_approval':
      return <AlertCircle className={`w-5 h-5 ${color}`} />;
    default:
      return <Clock className={`w-5 h-5 ${color}`} />;
  }
}

function getStatusLabel(status: SessionStatus | string, currentStage?: string | null): string {
  switch (status) {
    case 'completed': return 'Complete';
    case 'error': return 'Error';
    case 'cancelled': return 'Cancelled';
    case 'running': return currentStage || 'Analyzing...';
    case 'awaiting_approval': return 'Approval Required';
    default: return 'Queued';
  }
}

function formatDate(date: Date): string {
  const d = new Date(date);
  return d.toLocaleString('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// Helper to get display name from history item
function getDisplayName(item: TickerHistoryItem): string {
  return item.stk_nm || item.ticker;
}

// Helper to get action from history item
function getAction(item: TickerHistoryItem): string | null {
  if ('action' in item && (item as { action?: string }).action) {
    return (item as { action: string }).action;
  }
  return null;
}

type FilterStatus = 'all' | 'running' | 'completed';

export function AnalysisPage(_props: AnalysisPageProps) {
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');

  // Store state - use global selectedSessionId for navigation between pages
  const selectedSessionId = useStore((state) => state.selectedSessionId);
  const setSelectedSessionId = useStore((state) => state.setSelectedSessionId);
  const goTo = useGoTo();
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const setActiveKiwoomSession = useStore((state) => state.setActiveKiwoomSession);
  const setAwaitingApproval = useStore((state) => state.setAwaitingApproval);

  const kiwoomState = useStore((state) => state.kiwoom);

  // Get history
  const history = useStore(selectTickerHistory);

  // Get remove actions for delete functionality
  const removeKiwoomHistoryItem = useStore((state) => state.removeKiwoomHistoryItem);

  // Build active sessions list
  const activeSessions = useMemo((): ActiveSession[] => {
    const sessions: ActiveSession[] = [];
    const addedSessionIds = new Set<string>();

    // Kiwoom multi-sessions - only include running or awaiting_approval
    kiwoomState.sessions.forEach((s) => {
      if (!addedSessionIds.has(s.sessionId) &&
          (s.status === 'running' || s.status === 'awaiting_approval')) {
        sessions.push({
          sessionId: s.sessionId,
          ticker: s.ticker,
          displayName: s.displayName,
          marketType: 'kiwoom',
          status: s.status,
          currentStage: s.currentStage,
          reasoningLog: s.reasoningLog,
        });
        addedSessionIds.add(s.sessionId);
      }
    });

    // Kiwoom legacy single session - only include running or awaiting_approval
    if (
      kiwoomState.activeSessionId &&
      (kiwoomState.status === 'running' || kiwoomState.status === 'awaiting_approval') &&
      !addedSessionIds.has(kiwoomState.activeSessionId)
    ) {
      sessions.push({
        sessionId: kiwoomState.activeSessionId,
        ticker: kiwoomState.stk_cd,
        displayName: kiwoomState.stk_nm || kiwoomState.stk_cd,
        marketType: 'kiwoom',
        status: kiwoomState.status,
        currentStage: kiwoomState.currentStage,
        reasoningLog: kiwoomState.reasoningLog,
      });
    }

    return sessions;
  }, [kiwoomState]);

  // Filter sessions based on status filter
  const filteredActiveSessions = useMemo(() => {
    if (filterStatus === 'completed') return [];
    return activeSessions.filter((s) =>
      filterStatus === 'all' ||
      s.status === 'running' ||
      s.status === 'awaiting_approval'
    );
  }, [activeSessions, filterStatus]);

  // Filter history for completed/cancelled/error analyses (exclude running - those are in activeSessions)
  const completedAnalyses = useMemo(() => {
    if (filterStatus === 'running') return [];
    // Only show non-running items from history (completed, cancelled, error)
    return history.filter((h) =>
      h.status === 'completed' || h.status === 'cancelled' || h.status === 'error'
    ).slice(0, 20); // Show last 20
  }, [history, filterStatus]);

  // Handle clicking on a running session - navigate to workflow view
  const handleSelectRunning = (session: ActiveSession) => {
    setActiveMarket(session.marketType);
    if (session.marketType === 'kiwoom') {
      setActiveKiwoomSession(session.sessionId);
    }
    setSelectedSessionId(session.sessionId);

    // If awaiting approval, surface the order-ticket rail
    if (session.status === 'awaiting_approval') {
      setAwaitingApproval(true);
    }

    // Navigate to workflow view
    goTo('workflow', session.sessionId);
  };

  // Handle clicking on a completed analysis - navigate to detail view
  const handleSelectCompleted = (item: TickerHistoryItem) => {
    // Navigate to analysis detail page
    goTo('analysis-detail', item.sessionId);
    // Store the selected session ID for the detail page
    setSelectedSessionId(item.sessionId);
  };

  // Handle delete completed analysis item
  const handleDeleteItem = (e: React.MouseEvent, item: TickerHistoryItem) => {
    e.stopPropagation(); // Prevent triggering the row click

    const displayName = getDisplayName(item);
    if (!confirm(`"${displayName}" 분석 내역을 삭제하시겠습니까?`)) {
      return;
    }

    removeKiwoomHistoryItem(item.sessionId);
  };

  // Count running vs completed
  const runningCount = activeSessions.filter(
    (s) => s.status === 'running' || s.status === 'awaiting_approval'
  ).length;
  const completedCount = history.filter(
    (h) => h.status === 'completed' || h.status === 'cancelled' || h.status === 'error'
  ).length;

  return (
    <div className="h-full flex flex-col bg-canvas">
      {/* Header */}
      <div className="flex-none border-b border-hairline bg-card">
        <div className="max-w-4xl mx-auto px-4 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BarChart3 className="w-4 h-4 text-accent" />
            <h1 className="text-sm font-semibold text-ink">Analysis</h1>
            <span className="text-xs text-dim tabular-nums">
              {runningCount > 0 && <span className="text-accent">{runningCount} running</span>}
              {runningCount > 0 && completedCount > 0 && ' · '}
              {completedCount > 0 && <span className="text-muted">{completedCount} completed</span>}
            </span>
          </div>
          {/* Filter Tabs */}
          <div className="flex items-center gap-1 bg-elevated rounded p-1">
            <button
              onClick={() => setFilterStatus('all')}
              className={`px-2.5 py-1 text-xs rounded transition-colors ${
                filterStatus === 'all' ? 'bg-accent text-canvas' : 'text-muted hover:text-ink'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setFilterStatus('running')}
              className={`px-2.5 py-1 text-xs rounded transition-colors flex items-center gap-1 ${
                filterStatus === 'running' ? 'bg-accent text-canvas' : 'text-muted hover:text-ink'
              }`}
            >
              Running
              {runningCount > 0 && (
                <span className="px-1 py-0.5 text-[10px] bg-accent/30 rounded-full tabular-nums">{runningCount}</span>
              )}
            </button>
            <button
              onClick={() => setFilterStatus('completed')}
              className={`px-2.5 py-1 text-xs rounded transition-colors ${
                filterStatus === 'completed' ? 'bg-accent text-canvas' : 'text-muted hover:text-ink'
              }`}
            >
              Completed
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-4xl mx-auto space-y-4">
          {/* Running Analyses Section */}
          {filteredActiveSessions.length > 0 && (
            <section>
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted mb-2 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
                분석 중인 종목
                <span className="px-1.5 py-0.5 text-[10px] bg-accent text-canvas rounded-full tabular-nums">
                  {filteredActiveSessions.length}
                </span>
              </h2>
              <div className="space-y-2">
                {filteredActiveSessions.map((session) => (
                  <button
                    key={session.sessionId}
                    onClick={() => handleSelectRunning(session)}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 bg-card rounded border transition-all hover:border-accent/50 ${
                      selectedSessionId === session.sessionId
                        ? 'border-accent bg-accent/10'
                        : 'border-hairline'
                    }`}
                  >
                    {/* Status Icon */}
                    {getStatusIcon(session.status)}

                    {/* Ticker & Name */}
                    <div className="flex-1 text-left min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={getMarketColor(session.marketType)}>
                          <MarketIcon marketType={session.marketType} />
                        </span>
                        <span className="font-medium text-ink">{session.displayName}</span>
                        {session.displayName !== session.ticker && (
                          <span className="text-xs text-dim">({session.ticker})</span>
                        )}
                        <span className="px-1.5 py-0.5 text-[10px] bg-elevated rounded text-muted">
                          {getMarketLabel(session.marketType)}
                        </span>
                      </div>
                      <div className="text-xs text-dim mt-1">
                        {getStatusLabel(session.status, session.currentStage)}
                      </div>
                    </div>

                    {/* Progress indicator */}
                    {session.status === 'running' && (
                      <div className="w-20 h-1.5 bg-elevated rounded-full overflow-hidden">
                        <div className="h-full bg-accent animate-pulse" style={{ width: '60%' }} />
                      </div>
                    )}

                    {/* Approval badge */}
                    {session.status === 'awaiting_approval' && (
                      <span className="flex items-center gap-1 px-2 py-1 text-xs bg-warn/20 text-warn rounded">
                        <Eye className="w-3 h-3" />
                        승인 대기
                      </span>
                    )}

                    <ChevronRight className="w-4 h-4 text-dim" />
                  </button>
                ))}
              </div>
            </section>
          )}

          {/* Completed Analyses Section */}
          {completedAnalyses.length > 0 && (
            <section>
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted mb-2 flex items-center gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-up" />
                완료된 분석
              </h2>
              <div className="space-y-2">
                {completedAnalyses.map((item) => {
                  const displayName = getDisplayName(item);
                  const action = getAction(item);
                  const itemMarket: MarketType = 'kiwoom';

                  return (
                    <button
                      key={item.sessionId}
                      onClick={() => handleSelectCompleted(item)}
                      className="w-full flex items-center gap-3 px-3 py-2.5 bg-card rounded border border-hairline transition-all hover:border-dim"
                    >
                      {/* Status Icon */}
                      {getStatusIcon(item.status)}

                      {/* Ticker & Name */}
                      <div className="flex-1 text-left min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={getMarketColor(itemMarket)}>
                            <MarketIcon marketType={itemMarket} />
                          </span>
                          <span className="font-medium text-ink">{displayName}</span>
                          {displayName !== item.ticker && (
                            <span className="text-xs text-dim">({item.ticker})</span>
                          )}
                          <span className="px-1.5 py-0.5 text-[10px] bg-elevated rounded text-muted">
                            {getMarketLabel(itemMarket)}
                          </span>
                        </div>
                        <div className="text-xs text-dim mt-1">
                          {formatDate(item.timestamp)}
                        </div>
                      </div>

                      {/* Action badge — BUY/SELL are genuinely bullish/bearish, so route
                          through the shared pnlColor helper (single source of truth for
                          up/down). Text-only chip on a neutral bg-elevated/border-hairline
                          background, matching the trading-color convention elsewhere. */}
                      {action && (
                        <span
                          className={`px-2 py-0.5 text-[11px] font-medium rounded border border-hairline bg-elevated ${
                            action === 'BUY'
                              ? pnlColor(1)
                              : action === 'SELL'
                                ? pnlColor(-1)
                                : 'text-muted'
                          }`}
                        >
                          {action}
                        </span>
                      )}

                      {/* Status Badge */}
                      <span
                        className={`px-2 py-0.5 text-[11px] rounded border border-hairline bg-elevated ${getStatusColor(item.status)}`}
                      >
                        {item.status}
                      </span>

                      {/* Delete Button */}
                      <button
                        onClick={(e) => handleDeleteItem(e, item)}
                        className="p-1.5 rounded-md text-dim hover:text-red-400 hover:bg-red-500/10 transition-colors" // color-ok: destructive action (delete) hover
                        title="삭제"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>

                      <ChevronRight className="w-4 h-4 text-dim" />
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          {/* Empty State */}
          {filteredActiveSessions.length === 0 && completedAnalyses.length === 0 && (
            <div className="text-center py-12 text-dim">
              <BarChart3 className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p className="text-lg">분석 내역이 없습니다</p>
              <p className="text-sm mt-2">
                Dashboard에서 종목을 검색하여 분석을 시작하세요
              </p>
              <button
                onClick={() => goTo('dashboard')}
                className="mt-4 px-4 py-2 bg-accent hover:bg-accent/90 rounded-lg text-canvas text-sm transition-colors"
              >
                Dashboard로 이동
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
