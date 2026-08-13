/**
 * PositionMonitor Component
 *
 * Displays monitored positions and position events for Agent Chat.
 * Shows real-time P&L, stop-loss/take-profit status, and triggered events.
 */

import { useState, useEffect, useCallback } from 'react';
import { pnlColor as pnlColorOf } from '../../utils/pnl';
import {
  Activity,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Bell,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Target,
  Shield,
  Clock,
  Zap,
} from 'lucide-react';
import {
  getAgentChatPositionSummary,
  getAgentChatPositionEvents,
} from '@/api/client';
import type {
  AgentChatPositionSummary,
  AgentChatMonitoredPosition,
  AgentChatPositionEvent,
  AgentChatPositionEventType,
  AgentChatActiveDiscussion,
  AgentChatSessionSummary,
} from '@/types';

const eventTypeConfig: Record<
  AgentChatPositionEventType,
  { icon: React.ReactNode; color: string; bgColor: string; label: string }
> = {
  stop_loss_near: {
    icon: <AlertTriangle className="w-4 h-4" />,
    color: 'text-warn', // status: caution / near-threshold
    bgColor: 'bg-warn/20',
    label: 'Stop Loss Near',
  },
  stop_loss_hit: {
    icon: <Shield className="w-4 h-4" />,
    color: 'text-down', // status: stop-loss triggered
    bgColor: 'bg-down/20',
    label: 'Stop Loss Hit',
  },
  take_profit_near: {
    icon: <Target className="w-4 h-4" />,
    color: 'text-up', // status: take-profit approaching
    bgColor: 'bg-up/20',
    label: 'Take Profit Near',
  },
  take_profit_hit: {
    icon: <Target className="w-4 h-4" />,
    color: 'text-up', // status: take-profit triggered
    bgColor: 'bg-up/20',
    label: 'Take Profit Hit',
  },
  significant_gain: {
    icon: <TrendingUp className="w-4 h-4" />,
    color: 'text-up', // directional: gain
    bgColor: 'bg-up/20',
    label: 'Significant Gain',
  },
  significant_loss: {
    icon: <TrendingDown className="w-4 h-4" />,
    color: 'text-down', // directional: loss
    bgColor: 'bg-down/20',
    label: 'Significant Loss',
  },
  trailing_stop_update: {
    icon: <Activity className="w-4 h-4" />,
    color: 'text-accent', // status: informational update, folded into accent
    bgColor: 'bg-accent/20',
    label: 'Trailing Stop Updated',
  },
  holding_period_long: {
    icon: <Clock className="w-4 h-4" />,
    color: 'text-warn', // status: caution (aging position)
    bgColor: 'bg-warn/20',
    label: 'Long Holding Period',
  },
  volatility_spike: {
    icon: <Zap className="w-4 h-4" />,
    color: 'text-purple-400', // color-ok: event-category identity, not directional
    bgColor: 'bg-purple-500/20', // color-ok: event-category identity, not directional
    label: 'Volatility Spike',
  },
};

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0,
  }).format(value);
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function PositionCard({ position }: { position: AgentChatMonitoredPosition }) {
  const [expanded, setExpanded] = useState(false);
  const pnlColor = pnlColorOf(position.unrealized_pnl);

  return (
    <div className="bg-elevated rounded-lg p-4">
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-ink font-medium truncate">{position.stock_name}</span>
            <span className="text-dim text-sm">({position.ticker})</span>
          </div>
          <div className="flex items-center gap-4 mt-1 text-sm">
            <span className="text-muted tabular-nums">{position.quantity}주</span>
            <span className={pnlColor}>{formatPercent(position.unrealized_pnl_pct)}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className={`font-medium ${pnlColor}`}>
              {formatCurrency(position.unrealized_pnl)}
            </div>
            <div className="text-xs text-dim tabular-nums">
              {formatCurrency(position.position_value)}
            </div>
          </div>
          {expanded ? (
            <ChevronUp className="w-5 h-5 text-dim" />
          ) : (
            <ChevronDown className="w-5 h-5 text-dim" />
          )}
        </div>
      </div>

      {expanded && (
        <div className="mt-4 pt-4 border-t border-hairline grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-dim">Avg Price</span>
            <div className="text-ink tabular-nums">{formatCurrency(position.avg_price)}</div>
          </div>
          <div>
            <span className="text-dim">Current Price</span>
            <div className="text-ink tabular-nums">
              {position.current_price ? formatCurrency(position.current_price) : '-'}
            </div>
          </div>
          <div>
            <span className="text-dim">Stop Loss</span>
            <div className="text-down tabular-nums">
              {position.stop_loss ? formatCurrency(position.stop_loss) : '-'}
            </div>
          </div>
          <div>
            <span className="text-dim">Take Profit</span>
            <div className="text-up tabular-nums">
              {position.take_profit ? formatCurrency(position.take_profit) : '-'}
            </div>
          </div>
          <div>
            <span className="text-dim">Holding Days</span>
            <div className="text-ink tabular-nums">{position.holding_days}일</div>
          </div>
          <div>
            <span className="text-dim">Discussions</span>
            <div className="text-ink tabular-nums">{position.discussion_count}회</div>
          </div>
          {position.trailing_stop_price && (
            <>
              <div>
                <span className="text-dim">Trailing Stop</span>
                <div className="text-warn tabular-nums">
                  {formatCurrency(position.trailing_stop_price)}
                </div>
              </div>
              <div>
                <span className="text-dim">Highest Price</span>
                <div className="text-ink tabular-nums">
                  {position.highest_price ? formatCurrency(position.highest_price) : '-'}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function EventItem({
  event,
  onDiscussionRequired,
}: {
  event: AgentChatPositionEvent;
  /** B3: "Discussion Required" used to be static text with no onClick — a
   *  dead end that gave the operator no next action. Clicking it now hands
   *  the event back up so the parent can either open the matching session
   *  or start a new debate for this ticker (see PositionMonitor's
   *  `handleDiscussionRequired`). */
  onDiscussionRequired?: (event: AgentChatPositionEvent) => void;
}) {
  const config = eventTypeConfig[event.event_type] || eventTypeConfig.significant_gain;

  return (
    <div className="flex items-start gap-3 p-3 bg-elevated rounded-lg">
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${config.bgColor}`}>
        {config.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${config.color}`}>{config.label}</span>
          <span className="text-xs text-dim">{event.ticker}</span>
        </div>
        <p className="text-sm text-muted mt-1">{event.message}</p>
        <div className="flex items-center gap-4 mt-2 text-xs text-dim">
          <span>{formatTime(event.timestamp)}</span>
          {event.requires_discussion && (
            <button
              type="button"
              onClick={() => onDiscussionRequired?.(event)}
              className="px-1.5 py-0.5 bg-accent/20 text-accent rounded hover:bg-accent/30"
            >
              Discussion Required →
            </button>
          )}
          {event.auto_execute && (
            <span className="px-1.5 py-0.5 bg-warn/20 text-warn rounded">
              Auto Execute
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

interface PositionMonitorProps {
  /** Compact mode for dashboard sidebar */
  compact?: boolean;
  /** B3: active + recent sessions, used to resolve a "Discussion Required"
   *  event's ticker to an already-running/recent session so the badge can
   *  open it directly instead of being a dead end. Passed down by
   *  AgentChatDashboard (the same data it already fetches for its own
   *  Active Discussions / session list — no duplicate fetch here). */
  activeDiscussions?: AgentChatActiveDiscussion[];
  sessions?: AgentChatSessionSummary[];
  /** Opens a session in the master-detail view (AgentChatDashboard's
   *  `selectSession`). */
  onOpenSession?: (sessionId: string) => void;
  /** Starts a new debate for a ticker (AgentChatDashboard's
   *  `handleStartDebate`) — the fallback when no session matches. */
  onStartDebate?: (ticker: string, stockName?: string) => void;
}

export function PositionMonitor({
  compact = false,
  activeDiscussions = [],
  sessions = [],
  onOpenSession,
  onStartDebate,
}: PositionMonitorProps) {
  const [summary, setSummary] = useState<AgentChatPositionSummary | null>(null);
  const [events, setEvents] = useState<AgentChatPositionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showPositions, setShowPositions] = useState(!compact);
  const [showEvents, setShowEvents] = useState(!compact);

  // B3: resolve "Discussion Required" to a real next action — open the
  // matching session if one exists (checking the currently-active
  // discussions first since those are the freshest signal, then recent
  // session history), otherwise start a brand-new debate for that ticker so
  // the badge is never a dead end.
  const handleDiscussionRequired = useCallback(
    (event: AgentChatPositionEvent) => {
      const activeMatch = activeDiscussions.find((d) => d.ticker === event.ticker);
      if (activeMatch) {
        onOpenSession?.(activeMatch.session_id);
        return;
      }
      const sessionMatch = sessions.find((s) => s.ticker === event.ticker);
      if (sessionMatch) {
        onOpenSession?.(sessionMatch.id);
        return;
      }
      const stockName = (event.data?.stock_name as string | undefined) ?? event.ticker;
      onStartDebate?.(event.ticker, stockName);
    },
    [activeDiscussions, sessions, onOpenSession, onStartDebate],
  );

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [summaryData, eventsData] = await Promise.all([
        getAgentChatPositionSummary().catch(() => null),
        getAgentChatPositionEvents({ limit: 10 }).catch(() => ({ events: [], count: 0 })),
      ]);

      if (summaryData) {
        setSummary(summaryData);
      }
      setEvents(eventsData.events);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch positions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30 seconds
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="bg-card rounded border border-hairline p-6">
        <div className="flex items-center justify-center py-8">
          <RefreshCw className="w-6 h-6 animate-spin text-accent" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-card rounded border border-hairline p-6">
        <div className="flex items-center gap-3 text-down">
          <AlertTriangle className="w-5 h-5" />
          {error}
        </div>
      </div>
    );
  }

  if (!summary || summary.position_count === 0) {
    return (
      <div className="bg-card rounded border border-hairline p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium text-ink flex items-center gap-2">
            <Activity className="w-5 h-5 text-accent" />
            Position Monitor
          </h3>
          <button
            onClick={fetchData}
            className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
        <div className="text-center py-8 text-dim">
          <Activity className="w-10 h-10 mx-auto mb-3 opacity-50" />
          <p>모니터링 중인 포지션이 없습니다</p>
          {/* B3: this used to say "Add positions to start monitoring" — but
              there is no "Add positions" UI anywhere in the app. Positions
              are actually populated by coordinator.start() ->
              sync_from_account(), so the text says that instead. */}
          <p className="text-sm mt-1">코디네이터 시작 시 계좌에서 자동 동기화됩니다</p>
        </div>
      </div>
    );
  }

  const pnlColor = pnlColorOf(summary.total_unrealized_pnl);

  return (
    <div className="bg-card rounded border border-hairline p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-ink flex items-center gap-2">
          <Activity className="w-5 h-5 text-accent" />
          Position Monitor
          {summary.is_running && (
            <span className="w-2 h-2 bg-accent rounded-full animate-pulse" />
          )}
        </h3>
        <button
          onClick={fetchData}
          className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-elevated rounded-lg p-3 text-center">
          <div className="text-xl font-bold text-ink tabular-nums">{summary.position_count}</div>
          <div className="text-xs text-muted">Positions</div>
        </div>
        <div className="bg-elevated rounded-lg p-3 text-center">
          <div className={`text-xl font-bold ${pnlColor}`}>
            {formatPercent(summary.total_unrealized_pnl_pct)}
          </div>
          <div className="text-xs text-muted">Total P&L</div>
        </div>
        <div className="bg-elevated rounded-lg p-3 text-center">
          <div className="text-xl font-bold text-ink tabular-nums">{summary.event_count}</div>
          <div className="text-xs text-muted">Events</div>
        </div>
      </div>

      {/* Total Value */}
      <div className="bg-elevated rounded-lg p-4">
        <div className="flex items-center justify-between">
          <span className="text-muted">Total Value</span>
          <span className="text-xl font-bold text-ink tabular-nums">{formatCurrency(summary.total_value)}</span>
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-muted">Unrealized P&L</span>
          <span className={`font-medium ${pnlColor}`}>
            {formatCurrency(summary.total_unrealized_pnl)}
          </span>
        </div>
      </div>

      {/* Positions Section */}
      <div>
        <button
          onClick={() => setShowPositions(!showPositions)}
          className="flex items-center justify-between w-full text-left py-2"
        >
          <span className="text-sm font-medium text-ink">
            Positions ({summary.position_count})
          </span>
          {showPositions ? (
            <ChevronUp className="w-4 h-4 text-dim" />
          ) : (
            <ChevronDown className="w-4 h-4 text-dim" />
          )}
        </button>
        {showPositions && (
          <div className="space-y-2 mt-2">
            {summary.positions.map((position) => (
              <PositionCard key={position.ticker} position={position} />
            ))}
          </div>
        )}
      </div>

      {/* Events Section */}
      {events.length > 0 && (
        <div>
          <button
            onClick={() => setShowEvents(!showEvents)}
            className="flex items-center justify-between w-full text-left py-2"
          >
            <span className="text-sm font-medium text-ink flex items-center gap-2">
              <Bell className="w-4 h-4 text-accent" />
              Recent Events ({events.length})
            </span>
            {showEvents ? (
              <ChevronUp className="w-4 h-4 text-dim" />
            ) : (
              <ChevronDown className="w-4 h-4 text-dim" />
            )}
          </button>
          {showEvents && (
            <div className="space-y-2 mt-2 max-h-[400px] overflow-y-auto">
              {events.map((event) => (
                <EventItem
                  key={event.id}
                  event={event}
                  onDiscussionRequired={handleDiscussionRequired}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default PositionMonitor;
