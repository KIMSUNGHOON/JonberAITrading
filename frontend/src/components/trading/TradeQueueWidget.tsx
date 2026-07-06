/**
 * TradeQueueWidget Component
 *
 * Shows trades waiting in queue for market open:
 * - Pending trades with details
 * - Cancel functionality
 * - Manual queue processing
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Clock,
  X,
  Play,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  CheckCircle,
  Loader2,
  Trash2,
  XCircle,
  Timer,
} from 'lucide-react';
import { getTradeQueue, cancelQueuedTrade, processTradeQueue, dismissTrade } from '@/api/client';
import { useMarketHours } from '@/hooks/useMarketHours';
import { pnlColor } from '@/utils/pnl';

// -------------------------------------------
// Types
// -------------------------------------------

interface QueuedTrade {
  id: string;
  session_id: string;
  ticker: string;
  stock_name: string | null;
  action: string;
  entry_price: number;
  quantity: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_score: number;
  status: string;
  reason: string;
  queued_at: string;
  executed_at: string | null;
  error_message: string | null;
}

// -------------------------------------------
// Constants
// -------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-warn bg-warn/10',
  processing: 'text-accent bg-accent/10',
  completed: 'text-up bg-up/10',
  failed: 'text-down bg-down/10',
  cancelled: 'text-muted bg-muted/10',
};

// -------------------------------------------
// Sub-components
// -------------------------------------------

interface QueueItemProps {
  trade: QueuedTrade;
  onCancel: (id: string) => void;
  onDismiss: (id: string) => void;
  cancelling: string | null;
  dismissing: string | null;
  /** Expected execution time (next market open) */
  nextExecutionTime?: string;
  /** Position in queue (1-based) */
  queuePosition?: number;
}

function QueueItem({ trade, onCancel, onDismiss, cancelling, dismissing, nextExecutionTime, queuePosition }: QueueItemProps) {
  const formatTime = (timeStr: string) => {
    const date = new Date(timeStr);
    return date.toLocaleString('ko-KR', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatPrice = (price: number) => {
    return new Intl.NumberFormat('ko-KR').format(price);
  };

  const isBuy = trade.action === 'BUY';
  const isPending = trade.status === 'pending';
  const isProcessing = trade.status === 'processing';
  const isFailed = trade.status === 'failed';
  const isCompleted = trade.status === 'completed';
  const isCancelled = trade.status === 'cancelled';
  const canDismiss = isFailed || isCompleted || isCancelled;

  // Status-specific border colors
  const getBorderClass = () => {
    if (isFailed) return 'border-down/40 bg-down/5';
    if (isCompleted) return 'border-up/30 bg-up/5';
    if (isProcessing) return 'border-accent/30 bg-accent/5';
    if (isPending) return 'border-warn/30 bg-warn/5';
    return 'border-hairline bg-elevated/50';
  };

  // Status label in Korean
  const getStatusLabel = () => {
    switch (trade.status) {
      case 'pending': return '대기';
      case 'processing': return '처리중';
      case 'completed': return '완료';
      case 'failed': return '실패';
      case 'cancelled': return '취소됨';
      default: return trade.status;
    }
  };

  return (
    <div className={`p-3 rounded-lg border ${getBorderClass()}`}>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded bg-elevated">
            {isFailed ? (
              <XCircle className="w-4 h-4 text-down" />
            ) : isBuy ? (
              <TrendingUp className={`w-4 h-4 ${pnlColor(1)}`} />
            ) : (
              <TrendingDown className={`w-4 h-4 ${pnlColor(-1)}`} />
            )}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-ink">
                {trade.stock_name || trade.ticker}
              </span>
              <span className={`px-1.5 py-0.5 text-xs rounded ${STATUS_COLORS[trade.status] || STATUS_COLORS.pending}`}>
                {getStatusLabel()}
              </span>
            </div>
            <div className="text-xs text-muted">
              {trade.action} @ <span className="tabular-nums">{formatPrice(trade.entry_price)}</span>원
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {isPending && (
            <button
              onClick={() => onCancel(trade.id)}
              disabled={cancelling === trade.id}
              className="p-1.5 text-muted hover:text-down hover:bg-down/10 rounded disabled:opacity-50"
              title="취소"
            >
              {cancelling === trade.id ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <X className="w-4 h-4" />
              )}
            </button>
          )}
          {canDismiss && (
            <button
              onClick={() => onDismiss(trade.id)}
              disabled={dismissing === trade.id}
              className="p-1.5 text-muted hover:text-ink hover:bg-elevated rounded disabled:opacity-50"
              title="목록에서 제거"
            >
              {dismissing === trade.id ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
            </button>
          )}
        </div>
      </div>

      {/* Details - hide for failed/cancelled */}
      {!isFailed && !isCancelled && (
        <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
          {trade.stop_loss && (
            <div className="text-muted">
              손절: <span className="text-down tabular-nums">{formatPrice(trade.stop_loss)}</span>
            </div>
          )}
          {trade.take_profit && (
            <div className="text-muted">
              익절: <span className="text-up tabular-nums">{formatPrice(trade.take_profit)}</span>
            </div>
          )}
          <div className="text-muted">
            리스크: <span className="text-ink tabular-nums">{trade.risk_score}/10</span>
          </div>
        </div>
      )}

      {/* Execution info - only show for pending */}
      {isPending && (
        <div className="mt-2 space-y-1">
          {/* Queue position and expected execution */}
          {nextExecutionTime && (
            <div className="flex items-center gap-2 text-xs">
              <Timer className="w-3 h-3 text-accent" />
              <span className="text-muted">예상 실행:</span>
              <span className="text-accent font-medium tabular-nums">{nextExecutionTime}</span>
              {queuePosition && (
                <span className="px-1.5 py-0.5 bg-accent/20 text-accent rounded text-xs tabular-nums">
                  #{queuePosition}
                </span>
              )}
            </div>
          )}
          {/* Queued time and reason */}
          <div className="text-xs text-dim">
            <Clock className="w-3 h-3 inline mr-1" />
            {formatTime(trade.queued_at)} - {trade.reason}
          </div>
        </div>
      )}

      {/* Error message for failed trades - prominent display */}
      {isFailed && trade.error_message && (
        <div className="mt-2 p-2.5 bg-down/10 border border-down/30 rounded">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-down mt-0.5 flex-shrink-0" />
            <div>
              <div className="text-sm text-down font-medium">실패 사유</div>
              <div className="text-xs text-down mt-1">
                {trade.error_message}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Completed message */}
      {isCompleted && (
        <div className="mt-2 p-2 bg-up/10 border border-up/30 rounded text-xs text-up flex items-center gap-2">
          <CheckCircle className="w-4 h-4" />
          <span>주문 완료 - {trade.executed_at ? formatTime(trade.executed_at) : ''}</span>
        </div>
      )}
    </div>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

export default function TradeQueueWidget() {
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [dismissing, setDismissing] = useState<string | null>(null);
  const [queue, setQueue] = useState<QueuedTrade[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Get market status for showing expected execution time
  const { status: marketStatus, countdownFormatted, nextEventFormatted } = useMarketHours({
    market: 'krx',
    enableCountdown: true,
  });

  const isMarketOpen = marketStatus?.is_open ?? false;

  // Format next open time for display
  const formatNextOpenTime = () => {
    if (!marketStatus?.next_open) return '';
    try {
      const date = new Date(marketStatus.next_open);
      return date.toLocaleTimeString('ko-KR', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      });
    } catch {
      return '';
    }
  };

  const fetchQueue = useCallback(async () => {
    try {
      setError(null);
      // Fetch all trades including FAILED/COMPLETED/CANCELLED
      const data = await getTradeQueue(true);
      setQueue(data.queue);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch queue');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchQueue();
    // Poll every 5 seconds
    const interval = setInterval(fetchQueue, 5000);
    return () => clearInterval(interval);
  }, [fetchQueue]);

  const handleCancel = async (id: string) => {
    try {
      setCancelling(id);
      await cancelQueuedTrade(id);
      await fetchQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel trade');
    } finally {
      setCancelling(null);
    }
  };

  const handleDismiss = async (id: string) => {
    try {
      setDismissing(id);
      await dismissTrade(id);
      await fetchQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to dismiss trade');
    } finally {
      setDismissing(null);
    }
  };

  const handleProcess = async () => {
    try {
      setProcessing(true);
      await processTradeQueue();
      await fetchQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to process queue');
    } finally {
      setProcessing(false);
    }
  };

  const pendingCount = queue.filter(t => t.status === 'pending').length;
  const failedCount = queue.filter(t => t.status === 'failed').length;

  return (
    <div className="bg-card rounded border border-hairline">
      {/* Header */}
      <div className="p-4 border-b border-hairline">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className={`w-5 h-5 ${pendingCount > 0 ? 'text-warn' : failedCount > 0 ? 'text-down' : 'text-muted'}`} />
            <h2 className="text-lg font-semibold text-ink">Trade Queue</h2>
            {/* Market status indicator (market-state LEVEL, not P&L) */}
            <div
              className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-xs ${
                isMarketOpen
                  ? 'bg-up/20 text-up'
                  : 'bg-down/20 text-down'
              }`}
            >
              <div
                className={`w-1.5 h-1.5 rounded-full ${
                  isMarketOpen ? 'bg-up' : 'bg-down'
                }`}
              />
              {isMarketOpen ? '장중' : '장마감'}
            </div>
            {pendingCount > 0 && (
              <span className="px-2 py-0.5 text-xs bg-warn/20 text-warn rounded-full tabular-nums">
                {pendingCount} 대기
              </span>
            )}
            {failedCount > 0 && (
              <span className="px-2 py-0.5 text-xs bg-down/20 text-down rounded-full tabular-nums">
                {failedCount} 실패
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {pendingCount > 0 && isMarketOpen && (
              <button
                onClick={handleProcess}
                disabled={processing}
                className="flex items-center gap-1 px-3 py-1.5 text-sm bg-accent hover:bg-accent/90 text-canvas rounded-lg disabled:opacity-50"
              >
                {processing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                Process
              </button>
            )}
            <button
              onClick={fetchQueue}
              disabled={loading}
              className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Market closed banner with countdown */}
        {!isMarketOpen && pendingCount > 0 && (
          <div className="mt-3 p-2.5 bg-warn/10 border border-warn/20 rounded-lg">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <Timer className="w-4 h-4 text-warn" />
                <span className="text-warn">다음 실행 예정: {nextEventFormatted}</span>
              </div>
              <span className="text-warn font-medium tabular-nums">{countdownFormatted}</span>
            </div>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-4">
        {error && (
          <div className="mb-4 p-3 bg-down/20 border border-down/30 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-down" />
            <span className="text-sm text-down">{error}</span>
          </div>
        )}

        {loading && queue.length === 0 ? (
          <div className="text-center text-muted py-8">
            <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin" />
            <p className="text-sm">Loading...</p>
          </div>
        ) : queue.length === 0 ? (
          <div className="text-center text-dim py-8">
            <CheckCircle className="w-8 h-8 mx-auto mb-2 text-dim" />
            <p className="text-sm">No trades in queue</p>
            <p className="text-xs mt-1">Trades will appear here when market is closed</p>
          </div>
        ) : (
          <div className="space-y-3 max-h-80 overflow-y-auto">
            {queue.map((trade) => {
              // Calculate queue position for pending trades
              const pendingTrades = queue.filter(t => t.status === 'pending');
              const pendingIndex = pendingTrades.findIndex(t => t.id === trade.id);
              const queuePosition = trade.status === 'pending' && pendingIndex >= 0 ? pendingIndex + 1 : undefined;

              return (
                <QueueItem
                  key={trade.id}
                  trade={trade}
                  onCancel={handleCancel}
                  onDismiss={handleDismiss}
                  cancelling={cancelling}
                  dismissing={dismissing}
                  nextExecutionTime={!isMarketOpen ? formatNextOpenTime() : undefined}
                  queuePosition={queuePosition}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
