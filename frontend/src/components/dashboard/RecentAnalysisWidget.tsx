/**
 * RecentAnalysisWidget Component
 *
 * Displays recent completed analyses with trade recommendations.
 * Shows BUY/SELL/HOLD signals with target prices.
 */

import { useMemo } from 'react';
import {
  ClipboardList,
  TrendingUp,
  TrendingDown,
  Minus,
  Bitcoin,
  Building2,
  LineChart,
  Eye,
  Clock,
  ChevronRight,
} from 'lucide-react';
import { useStore, type MarketType, type RecentAnalysisItem } from '@/store';
import type { TradeAction } from '@/types';

// Format relative time
function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diff = now.getTime() - new Date(date).getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}일 전`;
  if (hours > 0) return `${hours}시간 전`;
  if (minutes > 0) return `${minutes}분 전`;
  return '방금 전';
}

// Format KRW price
function formatKRW(value: number): string {
  if (value >= 1e8) {
    return `₩${(value / 1e8).toFixed(2)}억`;
  }
  if (value >= 1e4) {
    return `₩${(value / 1e4).toFixed(0)}만`;
  }
  return `₩${value.toLocaleString('ko-KR')}`;
}

// Market icon component
function MarketIcon({ marketType }: { marketType: MarketType }) {
  switch (marketType) {
    case 'stock':
      return <LineChart className="w-3.5 h-3.5 text-green-400" />;
    case 'coin':
      return <Bitcoin className="w-3.5 h-3.5 text-yellow-400" />;
    case 'kiwoom':
      return <Building2 className="w-3.5 h-3.5 text-blue-400" />;
  }
}

// Action badge component
function ActionBadge({ action, status }: { action: TradeAction | undefined; status?: string }) {
  // If we have a trade action, show it
  if (action) {
    const colors: Record<TradeAction, string> = {
      BUY: 'bg-green-500/20 text-green-400 border-green-500/30',
      SELL: 'bg-red-500/20 text-red-400 border-red-500/30',
      HOLD: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
      ADD: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
      REDUCE: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
      AVOID: 'bg-red-500/20 text-red-400 border-red-500/30',
      WATCH: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    };

    const labels: Record<TradeAction, string> = {
      BUY: '매수',
      SELL: '매도',
      HOLD: '관망',
      ADD: '추가매수',
      REDUCE: '비중축소',
      AVOID: '매수금지',
      WATCH: '관심종목',
    };

    return (
      <span className={`px-2 py-0.5 text-xs rounded-full border ${colors[action]}`}>
        {labels[action]}
      </span>
    );
  }

  // Otherwise show status-based badge
  if (status === 'completed') {
    return (
      <span className="px-2 py-0.5 text-xs rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30">
        완료
      </span>
    );
  }

  if (status === 'cancelled') {
    return (
      <span className="px-2 py-0.5 text-xs rounded-full bg-orange-500/20 text-orange-400 border border-orange-500/30">
        취소됨
      </span>
    );
  }

  if (status === 'error') {
    return (
      <span className="px-2 py-0.5 text-xs rounded-full bg-red-500/20 text-red-400 border border-red-500/30">
        오류
      </span>
    );
  }

  if (status === 'awaiting_approval') {
    return (
      <span className="px-2 py-0.5 text-xs rounded-full bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
        승인 대기
      </span>
    );
  }

  // Default: running/analyzing
  return (
    <span className="px-2 py-0.5 text-xs rounded-full bg-gray-600 text-gray-300">
      분석중
    </span>
  );
}

// Individual analysis item
function RecentAnalysisItemRow({
  item,
  onViewDetails,
}: {
  item: RecentAnalysisItem;
  onViewDetails?: () => void;
}) {
  // Extract action from trade proposal
  const action = item.tradeProposal?.action as TradeAction | undefined;

  // Get entry and stop loss prices based on market type
  const entryPrice = item.tradeProposal?.entry_price;
  const stopLoss = item.tradeProposal?.stop_loss;

  // Status icon
  const StatusIcon = () => {
    if (action === 'BUY') return <TrendingUp className="w-4 h-4 text-green-400" />;
    if (action === 'SELL') return <TrendingDown className="w-4 h-4 text-red-400" />;
    return <Minus className="w-4 h-4 text-gray-400" />;
  };

  return (
    <div className="p-3 hover:bg-surface/50 rounded-lg transition-colors group">
      <div className="flex items-start justify-between gap-2">
        {/* Left side - Stock info */}
        <div className="flex items-start gap-2 flex-1 min-w-0">
          <StatusIcon />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <MarketIcon marketType={item.marketType} />
              <span className="font-medium text-sm truncate">{item.displayName}</span>
              {item.displayName !== item.ticker && (
                <span className="text-xs text-gray-500">({item.ticker})</span>
              )}
            </div>

            {/* Price targets */}
            {item.tradeProposal && (action === 'BUY' || action === 'SELL') && (
              <div className="text-xs text-gray-400 mt-1">
                {entryPrice && <span>목표: {formatKRW(entryPrice)}</span>}
                {stopLoss && <span className="ml-2">손절: {formatKRW(stopLoss)}</span>}
              </div>
            )}

            {action === 'HOLD' && (
              <div className="text-xs text-gray-500 mt-1">
                관망 권장 - 추가 모니터링 필요
              </div>
            )}
          </div>
        </div>

        {/* Right side - Action & Time */}
        <div className="flex flex-col items-end gap-1">
          <ActionBadge action={action} status={item.status} />
          <div className="flex items-center gap-1 text-xs text-gray-500">
            <Clock className="w-3 h-3" />
            {formatRelativeTime(item.timestamp)}
          </div>
        </div>
      </div>

      {/* View details button (on hover) */}
      {onViewDetails && (
        <button
          onClick={onViewDetails}
          className="opacity-0 group-hover:opacity-100 mt-2 flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-opacity"
        >
          <Eye className="w-3 h-3" />
          상세 보기
        </button>
      )}
    </div>
  );
}

export function RecentAnalysisWidget() {
  // Navigation action
  const setCurrentView = useStore((state) => state.setCurrentView);

  // Get recent analyses from store - use useMemo to stabilize the reference
  const stockHistory = useStore((state) => state.stock.history);
  const coinHistory = useStore((state) => state.coin.history);
  const kiwoomHistory = useStore((state) => state.kiwoom.history);
  const stockProposal = useStore((state) => state.stock.tradeProposal);
  const coinProposal = useStore((state) => state.coin.tradeProposal);
  const kiwoomProposal = useStore((state) => state.kiwoom.tradeProposal);
  const stockActiveSession = useStore((state) => state.stock.activeSessionId);
  const coinActiveSession = useStore((state) => state.coin.activeSessionId);
  const kiwoomActiveSession = useStore((state) => state.kiwoom.activeSessionId);

  const recentAnalyses = useMemo((): RecentAnalysisItem[] => {
    const allHistory: RecentAnalysisItem[] = [];

    // Stock history - include completed, awaiting_approval, and cancelled
    stockHistory.forEach((h) => {
      if (h.status === 'completed' || h.status === 'awaiting_approval' || h.status === 'cancelled') {
        allHistory.push({
          sessionId: h.sessionId,
          ticker: h.ticker,
          displayName: h.ticker,
          marketType: 'stock',
          timestamp: h.timestamp,
          status: h.status,
          tradeProposal: h.sessionId === stockActiveSession ? stockProposal : null,
        });
      }
    });

    // Coin history - include completed, awaiting_approval, and cancelled
    coinHistory.forEach((h) => {
      if (h.status === 'completed' || h.status === 'awaiting_approval' || h.status === 'cancelled') {
        allHistory.push({
          sessionId: h.sessionId,
          ticker: h.ticker,
          displayName: h.koreanName || h.ticker.replace('KRW-', ''),
          marketType: 'coin',
          timestamp: h.timestamp,
          status: h.status,
          tradeProposal: h.sessionId === coinActiveSession ? coinProposal : null,
        });
      }
    });

    // Kiwoom history - include completed, awaiting_approval, and cancelled
    kiwoomHistory.forEach((h) => {
      if (h.status === 'completed' || h.status === 'awaiting_approval' || h.status === 'cancelled') {
        allHistory.push({
          sessionId: h.sessionId,
          ticker: h.stk_cd,
          displayName: h.stk_nm || h.stk_cd,
          marketType: 'kiwoom',
          timestamp: h.timestamp,
          status: h.status,
          tradeProposal: h.sessionId === kiwoomActiveSession ? kiwoomProposal : null,
        });
      }
    });

    // Sort by timestamp (most recent first) and take top 5
    return allHistory
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, 5);
  }, [
    stockHistory, coinHistory, kiwoomHistory,
    stockProposal, coinProposal, kiwoomProposal,
    stockActiveSession, coinActiveSession, kiwoomActiveSession,
  ]);

  // Empty state
  if (recentAnalyses.length === 0) {
    return (
      <div className="card">
        <div className="flex items-center gap-2 mb-4">
          <ClipboardList className="w-5 h-5 text-purple-400" />
          <h3 className="font-semibold">최근 분석 결과</h3>
        </div>

        <div className="text-center py-8 text-gray-500">
          <ClipboardList className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">분석 기록이 없습니다</p>
          <p className="text-xs mt-1">종목을 분석하면 여기에 표시됩니다</p>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ClipboardList className="w-5 h-5 text-purple-400" />
          <h3 className="font-semibold">최근 분석 결과</h3>
          <span className="px-1.5 py-0.5 text-xs bg-purple-600 text-white rounded-full">
            {recentAnalyses.length}
          </span>
        </div>
        <button
          onClick={() => setCurrentView('history')}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-blue-400 transition-colors"
        >
          더보기
          <ChevronRight className="w-3 h-3" />
        </button>
      </div>

      {/* Analysis List */}
      <div className="space-y-1 -mx-1">
        {recentAnalyses.map((item) => (
          <RecentAnalysisItemRow
            key={item.sessionId}
            item={item}
          />
        ))}
      </div>
    </div>
  );
}
