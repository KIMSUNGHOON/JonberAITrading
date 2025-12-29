/**
 * AnalysisQueueWidget Component
 *
 * Shopping cart style widget showing all analyzing stocks.
 * - Displays up to 3 concurrent sessions
 * - Shows progress for each session
 * - Accordion-style reasoning preview
 * - Toggle to show/hide detailed reasoning
 */

import { useState, useMemo, useCallback } from 'react';
import {
  BarChart3,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertCircle,
  Clock,
  Eye,
  X,
  TrendingUp,
  Bitcoin,
  Building2,
} from 'lucide-react';
import { useStore, type ActiveSession } from '@/store';
import type { SessionStatus } from '@/types';
import type { MarketType } from '@/store';
import { cancelKRStockSession, cancelCoinSession, cancelSession } from '@/api/client';
import { wsManager } from '@/api/websocket';

// Workflow stages for progress tracking
const WORKFLOW_STAGES = [
  { id: 'technical', label: '기술적 분석', shortLabel: 'Tech' },
  { id: 'fundamental', label: '기본적 분석', shortLabel: 'Fund' },
  { id: 'sentiment', label: '감성 분석', shortLabel: 'Sent' },
  { id: 'risk', label: '리스크 평가', shortLabel: 'Risk' },
  { id: 'decision', label: '전략 결정', shortLabel: 'Dec' },
];

interface AnalysisQueueItemProps {
  ticker: string;
  displayName?: string;
  marketType: MarketType;
  status: SessionStatus | 'idle' | 'queued';
  currentStage: string | null;
  reasoningLog: string[];
  isExpanded: boolean;
  isSelected: boolean;
  onToggleExpand: () => void;
  onSelect: () => void;
  onRemove: () => void;
  onViewDetails: () => void;
}

// Market type icon component
function MarketIcon({ marketType }: { marketType: MarketType }) {
  switch (marketType) {
    case 'stock':
      return <TrendingUp className="w-3 h-3 text-green-400" />;
    case 'coin':
      return <Bitcoin className="w-3 h-3 text-yellow-400" />;
    case 'kiwoom':
      return <Building2 className="w-3 h-3 text-blue-400" />;
  }
}

function AnalysisQueueItem({
  ticker,
  displayName,
  marketType,
  status,
  currentStage,
  reasoningLog,
  isExpanded,
  isSelected,
  onToggleExpand,
  onSelect,
  onRemove,
  onViewDetails,
}: AnalysisQueueItemProps) {
  // Calculate progress based on current stage
  const currentStageIndex = WORKFLOW_STAGES.findIndex(
    (s) => currentStage?.toLowerCase().includes(s.id)
  );
  const progress = status === 'completed' ? 100 :
    status === 'running' ? ((currentStageIndex + 1) / WORKFLOW_STAGES.length) * 100 :
    0;

  // Status icon
  const StatusIcon = () => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      case 'error':
      case 'cancelled':
        return <XCircle className="w-4 h-4 text-red-400" />;
      case 'running':
        return <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />;
      case 'awaiting_approval':
        return <AlertCircle className="w-4 h-4 text-yellow-400" />;
      default:
        return <Clock className="w-4 h-4 text-gray-400" />;
    }
  };

  // Status label
  const statusLabel = () => {
    switch (status) {
      case 'completed': return 'Complete';
      case 'error': return 'Error';
      case 'cancelled': return 'Cancelled';
      case 'running': return currentStage || 'Running';
      case 'awaiting_approval': return 'Proposal Ready';
      default: return 'Queued';
    }
  };

  // Get last few reasoning entries for preview
  const recentReasoning = reasoningLog.slice(-3);

  return (
    <div
      className={`border rounded-lg overflow-hidden transition-colors ${
        isSelected
          ? 'border-blue-500 bg-blue-500/10'
          : 'border-border hover:border-gray-600'
      }`}
    >
      {/* Header */}
      <div
        className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-surface/50"
        onClick={onSelect}
      >
        <StatusIcon />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <MarketIcon marketType={marketType} />
            <span className="font-medium text-sm truncate">
              {displayName || ticker}
            </span>
            {displayName && displayName !== ticker && (
              <span className="text-xs text-gray-500">({ticker})</span>
            )}
          </div>
          <div className="text-xs text-gray-400 mt-0.5">
            {statusLabel()}
          </div>
        </div>

        {/* Progress bar */}
        {status === 'running' && (
          <div className="w-16 h-1.5 bg-surface-dark rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-1">
          {status === 'awaiting_approval' && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onViewDetails();
              }}
              className="p-1 text-yellow-400 hover:bg-yellow-500/20 rounded"
              title="View Proposal"
            >
              <Eye className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand();
            }}
            className="p-1 text-gray-400 hover:bg-surface rounded"
            title={isExpanded ? 'Collapse' : 'Expand Reasoning'}
          >
            {isExpanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>
          {(status === 'completed' || status === 'error' || status === 'cancelled') && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
              className="p-1 text-gray-400 hover:text-red-400 hover:bg-red-500/20 rounded"
              title="Remove"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Expanded Reasoning */}
      {isExpanded && reasoningLog.length > 0 && (
        <div className="px-3 py-2 border-t border-border bg-surface-dark/50">
          <div className="space-y-1 max-h-32 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-700">
            {recentReasoning.map((entry, idx) => (
              <div
                key={idx}
                className="text-xs text-gray-400 pl-2 border-l-2 border-gray-600"
              >
                {entry}
              </div>
            ))}
          </div>
          {reasoningLog.length > 3 && (
            <button
              onClick={onViewDetails}
              className="text-xs text-blue-400 hover:text-blue-300 mt-2"
            >
              View all {reasoningLog.length} entries...
            </button>
          )}
        </div>
      )}
    </div>
  );
}

interface AnalysisQueueWidgetProps {
  onViewDetails?: () => void;
}

export function AnalysisQueueWidget({ onViewDetails }: AnalysisQueueWidgetProps) {
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  // Get individual state for each market to avoid infinite loop from selector returning new array
  const stockSession = useStore((state) => state.stock);
  const coinSession = useStore((state) => state.coin);
  const kiwoomState = useStore((state) => state.kiwoom);

  // Navigation and market actions
  const setCurrentView = useStore((state) => state.setCurrentView);
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const setActiveKiwoomSession = useStore((state) => state.setActiveKiwoomSession);

  // Session removal actions
  const removeKiwoomSession = useStore((state) => state.removeKiwoomSession);
  const resetStock = useStore((state) => state.resetStock);
  const resetCoin = useStore((state) => state.resetCoin);

  // Build active sessions with useMemo for stable reference
  // Only include sessions that are actively running or awaiting approval
  const allActiveSessions = useMemo((): ActiveSession[] => {
    const sessions: ActiveSession[] = [];
    const addedSessionIds = new Set<string>();

    // Debug logging
    console.log('[AnalysisQueueWidget] Building active sessions:', {
      kiwoomSessions: kiwoomState.sessions.map(s => ({ id: s.sessionId, ticker: s.ticker, status: s.status })),
      kiwoomLegacy: { activeSessionId: kiwoomState.activeSessionId, status: kiwoomState.status },
      stockSession: { activeSessionId: stockSession.activeSessionId, status: stockSession.status },
      coinSession: { activeSessionId: coinSession.activeSessionId, status: coinSession.status },
    });

    // Stock session - only running or awaiting_approval
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

    // Coin session - only running or awaiting_approval
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

    // Kiwoom multi-sessions - only running or awaiting_approval
    kiwoomState.sessions.forEach((s) => {
      if (s.status === 'running' || s.status === 'awaiting_approval') {
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

    // Kiwoom legacy single session - only running or awaiting_approval
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

    console.log('[AnalysisQueueWidget] Active sessions result:', sessions.length, sessions.map(s => ({ id: s.sessionId, ticker: s.ticker, status: s.status })));
    return sessions;
  }, [stockSession, coinSession, kiwoomState]);

  const toggleExpand = (sessionId: string) => {
    setExpandedSessions((prev) => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  };

  const handleViewDetails = () => {
    onViewDetails?.();
  };

  /**
   * Handle session removal from the queue.
   * - Calls cancel API if session is still running
   * - Disconnects WebSocket
   * - Removes session from store
   */
  const handleRemove = useCallback(async (session: ActiveSession) => {
    const { sessionId, marketType, status } = session;

    try {
      // 1. Cancel the session on backend if it's still running/awaiting
      if (status === 'running' || status === 'awaiting_approval') {
        try {
          if (marketType === 'kiwoom') {
            await cancelKRStockSession(sessionId);
          } else if (marketType === 'coin') {
            await cancelCoinSession(sessionId);
          } else {
            await cancelSession(sessionId);
          }
        } catch (error) {
          // Log but don't block removal - session might already be cancelled/completed
          console.warn(`[AnalysisQueue] Failed to cancel session ${sessionId}:`, error);
        }
      }

      // 2. Disconnect WebSocket connection
      if (wsManager.has(sessionId)) {
        wsManager.disconnect(sessionId);
      }

      // 3. Remove session from store
      if (marketType === 'kiwoom') {
        removeKiwoomSession(sessionId);
      } else if (marketType === 'coin') {
        resetCoin();
      } else {
        resetStock();
      }

      // 4. Clear from expanded sessions UI state
      setExpandedSessions((prev) => {
        const next = new Set(prev);
        next.delete(sessionId);
        return next;
      });

      // 5. Clear selection if this was the selected session
      if (selectedSessionId === sessionId) {
        setSelectedSessionId(null);
      }

      console.log(`[AnalysisQueue] Removed session ${sessionId} (${marketType})`);
    } catch (error) {
      console.error(`[AnalysisQueue] Error removing session ${sessionId}:`, error);
    }
  }, [removeKiwoomSession, resetCoin, resetStock, selectedSessionId]);

  // Handle session selection - navigate to Analysis page
  const handleSelectSession = (session: ActiveSession) => {
    // Set the active market for this session
    setActiveMarket(session.marketType);

    // Set the active session for the market (for kiwoom multi-session)
    if (session.marketType === 'kiwoom') {
      setActiveKiwoomSession(session.sessionId);
    }

    // Navigate to Analysis page
    setCurrentView('analysis');
    // Track selected session
    setSelectedSessionId(session.sessionId);
  };

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-400" />
          <h3 className="font-semibold text-sm">분석 중인 종목</h3>
          {allActiveSessions.length > 0 && (
            <span className="px-1.5 py-0.5 text-xs bg-blue-600 text-white rounded-full animate-pulse">
              {allActiveSessions.length}
            </span>
          )}
        </div>
        {allActiveSessions.length > 0 && (
          <span className="text-xs text-green-400 flex items-center gap-1">
            <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
            분석 진행 중
          </span>
        )}
      </div>

      {/* Empty State */}
      {allActiveSessions.length === 0 ? (
        <div className="text-center py-4">
          <BarChart3 className="w-8 h-8 mx-auto mb-2 text-gray-600" />
          <p className="text-sm text-gray-500">분석 중인 종목이 없습니다</p>
          <p className="text-xs text-gray-600 mt-1">My Basket에서 종목을 선택하여 분석을 시작하세요</p>
        </div>
      ) : (
        <>
          {/* Session List - Shows ALL markets */}
          <div className="space-y-2">
            {allActiveSessions.map((session) => (
              <AnalysisQueueItem
                key={session.sessionId}
                ticker={session.ticker}
                displayName={session.displayName}
                marketType={session.marketType}
                status={session.status}
                currentStage={session.currentStage}
                reasoningLog={session.reasoningLog}
                isExpanded={expandedSessions.has(session.sessionId)}
                isSelected={selectedSessionId === session.sessionId}
                onToggleExpand={() => toggleExpand(session.sessionId)}
                onSelect={() => handleSelectSession(session)}
                onRemove={() => handleRemove(session)}
                onViewDetails={handleViewDetails}
              />
            ))}
          </div>
        </>
      )}

      {/* Info text */}
      <div className="mt-3 text-xs text-gray-500 border-t border-border pt-2">
        최대 3개 종목을 동시에 분석할 수 있습니다
      </div>
    </div>
  );
}
