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
  ArrowLeft,
  BarChart3,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ChevronRight,
  TrendingUp,
  Bitcoin,
  Building2,
  Clock,
  Eye,
} from 'lucide-react';
import { useStore, selectTickerHistory, type MarketType, type ActiveSession, type TickerHistoryItem } from '@/store';
import type { SessionStatus } from '@/types';

interface AnalysisPageProps {
  onBack?: () => void;
}

// Market type icon component
function MarketIcon({ marketType, size = 16 }: { marketType: MarketType; size?: number }) {
  const className = `text-current`;
  switch (marketType) {
    case 'stock':
      return <TrendingUp size={size} className={className} />;
    case 'coin':
      return <Bitcoin size={size} className={className} />;
    case 'kiwoom':
      return <Building2 size={size} className={className} />;
  }
}

function getMarketColor(marketType: MarketType): string {
  switch (marketType) {
    case 'stock': return 'text-green-400';
    case 'coin': return 'text-yellow-400';
    case 'kiwoom': return 'text-blue-400';
  }
}

function getMarketLabel(marketType: MarketType): string {
  switch (marketType) {
    case 'stock': return 'US Stock';
    case 'coin': return 'Crypto';
    case 'kiwoom': return 'KR Stock';
  }
}

function getStatusIcon(status: SessionStatus | string) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="w-5 h-5 text-green-400" />;
    case 'error':
      return <XCircle className="w-5 h-5 text-red-400" />;
    case 'cancelled':
      return <XCircle className="w-5 h-5 text-yellow-400" />;
    case 'running':
      return <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />;
    case 'awaiting_approval':
      return <AlertCircle className="w-5 h-5 text-yellow-400" />;
    default:
      return <Clock className="w-5 h-5 text-gray-400" />;
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
  if ('stk_nm' in item && (item as { stk_nm?: string }).stk_nm) {
    return (item as { stk_nm: string }).stk_nm;
  }
  if ('koreanName' in item && (item as { koreanName?: string }).koreanName) {
    return (item as { koreanName: string }).koreanName;
  }
  return item.ticker;
}

// Helper to get action from history item
function getAction(item: TickerHistoryItem): string | null {
  if ('action' in item && (item as { action?: string }).action) {
    return (item as { action: string }).action;
  }
  return null;
}

type FilterStatus = 'all' | 'running' | 'completed';

export function AnalysisPage({ onBack }: AnalysisPageProps) {
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');

  // Store state - use global selectedSessionId for navigation between pages
  const selectedSessionId = useStore((state) => state.selectedSessionId);
  const setSelectedSessionId = useStore((state) => state.setSelectedSessionId);
  const setCurrentView = useStore((state) => state.setCurrentView);
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const setActiveKiwoomSession = useStore((state) => state.setActiveKiwoomSession);
  const setShowApprovalDialog = useStore((state) => state.setShowApprovalDialog);

  // Get individual market states
  const stockSession = useStore((state) => state.stock);
  const coinSession = useStore((state) => state.coin);
  const kiwoomState = useStore((state) => state.kiwoom);

  // Get history
  const history = useStore(selectTickerHistory);

  // Build active sessions list
  const activeSessions = useMemo((): ActiveSession[] => {
    const sessions: ActiveSession[] = [];
    const addedSessionIds = new Set<string>();

    // Stock session - only include running or awaiting_approval
    if (stockSession.activeSessionId &&
        (stockSession.status === 'running' || stockSession.status === 'awaiting_approval')) {
      sessions.push({
        sessionId: stockSession.activeSessionId,
        ticker: stockSession.ticker,
        displayName: stockSession.ticker,
        marketType: 'stock',
        status: stockSession.status,
        currentStage: stockSession.currentStage,
        reasoningLog: stockSession.reasoningLog,
      });
      addedSessionIds.add(stockSession.activeSessionId);
    }

    // Coin session - only include running or awaiting_approval
    if (coinSession.activeSessionId &&
        (coinSession.status === 'running' || coinSession.status === 'awaiting_approval')) {
      sessions.push({
        sessionId: coinSession.activeSessionId,
        ticker: coinSession.market,
        displayName: coinSession.koreanName || coinSession.market.replace('KRW-', ''),
        marketType: 'coin',
        status: coinSession.status,
        currentStage: coinSession.currentStage,
        reasoningLog: coinSession.reasoningLog,
      });
      addedSessionIds.add(coinSession.activeSessionId);
    }

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
  }, [stockSession, coinSession, kiwoomState]);

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

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      setCurrentView('dashboard');
    }
  };

  // Handle clicking on a running session - navigate to workflow view
  const handleSelectRunning = (session: ActiveSession) => {
    setActiveMarket(session.marketType);
    if (session.marketType === 'kiwoom') {
      setActiveKiwoomSession(session.sessionId);
    }
    setSelectedSessionId(session.sessionId);

    // If awaiting approval, show the dialog
    if (session.status === 'awaiting_approval') {
      setShowApprovalDialog(true);
    }

    // Navigate to workflow view
    setCurrentView('workflow');
  };

  // Handle clicking on a completed analysis - navigate to detail view
  const handleSelectCompleted = (item: TickerHistoryItem) => {
    // Navigate to analysis detail page
    setCurrentView('analysis-detail');
    // Store the selected session ID for the detail page
    setSelectedSessionId(item.sessionId);
  };

  // Count running vs completed
  const runningCount = activeSessions.filter(
    (s) => s.status === 'running' || s.status === 'awaiting_approval'
  ).length;
  const completedCount = history.filter(
    (h) => h.status === 'completed' || h.status === 'cancelled' || h.status === 'error'
  ).length;

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
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-blue-400" />
            Analysis
          </h1>
          <p className="text-sm text-gray-500">
            {runningCount > 0 && (
              <span className="text-blue-400">{runningCount} running</span>
            )}
            {runningCount > 0 && completedCount > 0 && ' · '}
            {completedCount > 0 && (
              <span className="text-gray-400">{completedCount} completed</span>
            )}
          </p>
        </div>

        {/* Filter Tabs */}
        <div className="flex items-center gap-1 bg-surface rounded-lg p-1">
          <button
            onClick={() => setFilterStatus('all')}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              filterStatus === 'all'
                ? 'bg-blue-600 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            All
          </button>
          <button
            onClick={() => setFilterStatus('running')}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1 ${
              filterStatus === 'running'
                ? 'bg-blue-600 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            Running
            {runningCount > 0 && (
              <span className="px-1.5 py-0.5 text-xs bg-blue-500/50 rounded-full">
                {runningCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setFilterStatus('completed')}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              filterStatus === 'completed'
                ? 'bg-blue-600 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            Completed
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {/* Running Analyses Section */}
          {filteredActiveSessions.length > 0 && (
            <section>
              <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
                분석 중인 종목
                <span className="px-2 py-0.5 text-xs bg-blue-600 text-white rounded-full">
                  {filteredActiveSessions.length}
                </span>
              </h2>
              <div className="space-y-2">
                {filteredActiveSessions.map((session) => (
                  <button
                    key={session.sessionId}
                    onClick={() => handleSelectRunning(session)}
                    className={`w-full flex items-center gap-4 p-4 bg-surface-dark rounded-lg border transition-all hover:border-blue-500/50 ${
                      selectedSessionId === session.sessionId
                        ? 'border-blue-500 bg-blue-500/10'
                        : 'border-border'
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
                        <span className="font-medium">{session.displayName}</span>
                        {session.displayName !== session.ticker && (
                          <span className="text-sm text-gray-500">({session.ticker})</span>
                        )}
                        <span className="px-2 py-0.5 text-xs bg-surface rounded text-gray-400">
                          {getMarketLabel(session.marketType)}
                        </span>
                      </div>
                      <div className="text-xs text-gray-500 mt-1">
                        {getStatusLabel(session.status, session.currentStage)}
                      </div>
                    </div>

                    {/* Progress indicator */}
                    {session.status === 'running' && (
                      <div className="w-20 h-1.5 bg-surface rounded-full overflow-hidden">
                        <div className="h-full bg-blue-500 animate-pulse" style={{ width: '60%' }} />
                      </div>
                    )}

                    {/* Approval badge */}
                    {session.status === 'awaiting_approval' && (
                      <span className="flex items-center gap-1 px-2 py-1 text-xs bg-yellow-500/20 text-yellow-400 rounded">
                        <Eye className="w-3 h-3" />
                        승인 대기
                      </span>
                    )}

                    <ChevronRight className="w-5 h-5 text-gray-500" />
                  </button>
                ))}
              </div>
            </section>
          )}

          {/* Completed Analyses Section */}
          {completedAnalyses.length > 0 && (
            <section>
              <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-green-400" />
                완료된 분석
              </h2>
              <div className="space-y-2">
                {completedAnalyses.map((item) => {
                  const displayName = getDisplayName(item);
                  const action = getAction(item);
                  const itemMarket: MarketType = 'market' in item ? 'coin' : 'stk_cd' in item ? 'kiwoom' : 'stock';

                  return (
                    <button
                      key={item.sessionId}
                      onClick={() => handleSelectCompleted(item)}
                      className="w-full flex items-center gap-4 p-4 bg-surface-dark rounded-lg border border-border transition-all hover:border-gray-600"
                    >
                      {/* Status Icon */}
                      {getStatusIcon(item.status)}

                      {/* Ticker & Name */}
                      <div className="flex-1 text-left min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={getMarketColor(itemMarket)}>
                            <MarketIcon marketType={itemMarket} />
                          </span>
                          <span className="font-medium">{displayName}</span>
                          {displayName !== item.ticker && (
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

                      {/* Action badge */}
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

                      <ChevronRight className="w-5 h-5 text-gray-500" />
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          {/* Empty State */}
          {filteredActiveSessions.length === 0 && completedAnalyses.length === 0 && (
            <div className="text-center py-12 text-gray-500">
              <BarChart3 className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p className="text-lg">분석 내역이 없습니다</p>
              <p className="text-sm mt-2">
                Dashboard에서 종목을 검색하여 분석을 시작하세요
              </p>
              <button
                onClick={() => setCurrentView('dashboard')}
                className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white text-sm transition-colors"
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
