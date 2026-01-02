/**
 * PositionMonitor Component
 *
 * Displays monitored positions and position events for Agent Chat.
 * Shows real-time P&L, stop-loss/take-profit status, and triggered events.
 */

import { useState, useEffect, useCallback } from 'react';
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
} from '@/types';

const eventTypeConfig: Record<
  AgentChatPositionEventType,
  { icon: React.ReactNode; color: string; bgColor: string; label: string }
> = {
  stop_loss_near: {
    icon: <AlertTriangle className="w-4 h-4" />,
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/20',
    label: 'Stop Loss Near',
  },
  stop_loss_hit: {
    icon: <Shield className="w-4 h-4" />,
    color: 'text-red-400',
    bgColor: 'bg-red-500/20',
    label: 'Stop Loss Hit',
  },
  take_profit_near: {
    icon: <Target className="w-4 h-4" />,
    color: 'text-green-400',
    bgColor: 'bg-green-500/20',
    label: 'Take Profit Near',
  },
  take_profit_hit: {
    icon: <Target className="w-4 h-4" />,
    color: 'text-green-400',
    bgColor: 'bg-green-500/20',
    label: 'Take Profit Hit',
  },
  significant_gain: {
    icon: <TrendingUp className="w-4 h-4" />,
    color: 'text-green-400',
    bgColor: 'bg-green-500/20',
    label: 'Significant Gain',
  },
  significant_loss: {
    icon: <TrendingDown className="w-4 h-4" />,
    color: 'text-red-400',
    bgColor: 'bg-red-500/20',
    label: 'Significant Loss',
  },
  trailing_stop_update: {
    icon: <Activity className="w-4 h-4" />,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/20',
    label: 'Trailing Stop Updated',
  },
  holding_period_long: {
    icon: <Clock className="w-4 h-4" />,
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/20',
    label: 'Long Holding Period',
  },
  volatility_spike: {
    icon: <Zap className="w-4 h-4" />,
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/20',
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
  const pnlColor = position.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400';

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-white font-medium truncate">{position.stock_name}</span>
            <span className="text-gray-500 text-sm">({position.ticker})</span>
          </div>
          <div className="flex items-center gap-4 mt-1 text-sm">
            <span className="text-gray-400">{position.quantity}주</span>
            <span className={pnlColor}>{formatPercent(position.unrealized_pnl_pct)}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className={`font-medium ${pnlColor}`}>
              {formatCurrency(position.unrealized_pnl)}
            </div>
            <div className="text-xs text-gray-500">
              {formatCurrency(position.position_value)}
            </div>
          </div>
          {expanded ? (
            <ChevronUp className="w-5 h-5 text-gray-500" />
          ) : (
            <ChevronDown className="w-5 h-5 text-gray-500" />
          )}
        </div>
      </div>

      {expanded && (
        <div className="mt-4 pt-4 border-t border-gray-700 grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-gray-500">Avg Price</span>
            <div className="text-white">{formatCurrency(position.avg_price)}</div>
          </div>
          <div>
            <span className="text-gray-500">Current Price</span>
            <div className="text-white">
              {position.current_price ? formatCurrency(position.current_price) : '-'}
            </div>
          </div>
          <div>
            <span className="text-gray-500">Stop Loss</span>
            <div className="text-red-400">
              {position.stop_loss ? formatCurrency(position.stop_loss) : '-'}
            </div>
          </div>
          <div>
            <span className="text-gray-500">Take Profit</span>
            <div className="text-green-400">
              {position.take_profit ? formatCurrency(position.take_profit) : '-'}
            </div>
          </div>
          <div>
            <span className="text-gray-500">Holding Days</span>
            <div className="text-white">{position.holding_days}일</div>
          </div>
          <div>
            <span className="text-gray-500">Discussions</span>
            <div className="text-white">{position.discussion_count}회</div>
          </div>
          {position.trailing_stop_price && (
            <>
              <div>
                <span className="text-gray-500">Trailing Stop</span>
                <div className="text-yellow-400">
                  {formatCurrency(position.trailing_stop_price)}
                </div>
              </div>
              <div>
                <span className="text-gray-500">Highest Price</span>
                <div className="text-white">
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

function EventItem({ event }: { event: AgentChatPositionEvent }) {
  const config = eventTypeConfig[event.event_type] || eventTypeConfig.significant_gain;

  return (
    <div className="flex items-start gap-3 p-3 bg-gray-800 rounded-lg">
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${config.bgColor}`}>
        {config.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${config.color}`}>{config.label}</span>
          <span className="text-xs text-gray-500">{event.ticker}</span>
        </div>
        <p className="text-sm text-gray-400 mt-1">{event.message}</p>
        <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
          <span>{formatTime(event.timestamp)}</span>
          {event.requires_discussion && (
            <span className="px-1.5 py-0.5 bg-blue-500/20 text-blue-400 rounded">
              Discussion Required
            </span>
          )}
          {event.auto_execute && (
            <span className="px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">
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
}

export function PositionMonitor({ compact = false }: PositionMonitorProps) {
  const [summary, setSummary] = useState<AgentChatPositionSummary | null>(null);
  const [events, setEvents] = useState<AgentChatPositionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showPositions, setShowPositions] = useState(!compact);
  const [showEvents, setShowEvents] = useState(!compact);

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
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div className="flex items-center justify-center py-8">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div className="flex items-center gap-3 text-red-400">
          <AlertTriangle className="w-5 h-5" />
          {error}
        </div>
      </div>
    );
  }

  if (!summary || summary.position_count === 0) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium text-white flex items-center gap-2">
            <Activity className="w-5 h-5 text-blue-400" />
            Position Monitor
          </h3>
          <button
            onClick={fetchData}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
        <div className="text-center py-8 text-gray-500">
          <Activity className="w-10 h-10 mx-auto mb-3 opacity-50" />
          <p>No positions being monitored</p>
          <p className="text-sm mt-1">Add positions to start monitoring</p>
        </div>
      </div>
    );
  }

  const pnlColor = summary.total_unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400';

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-white flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-400" />
          Position Monitor
          {summary.is_running && (
            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          )}
        </h3>
        <button
          onClick={fetchData}
          className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-800 rounded-lg p-3 text-center">
          <div className="text-xl font-bold text-white">{summary.position_count}</div>
          <div className="text-xs text-gray-400">Positions</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-3 text-center">
          <div className={`text-xl font-bold ${pnlColor}`}>
            {formatPercent(summary.total_unrealized_pnl_pct)}
          </div>
          <div className="text-xs text-gray-400">Total P&L</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-3 text-center">
          <div className="text-xl font-bold text-white">{summary.event_count}</div>
          <div className="text-xs text-gray-400">Events</div>
        </div>
      </div>

      {/* Total Value */}
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <span className="text-gray-400">Total Value</span>
          <span className="text-xl font-bold text-white">{formatCurrency(summary.total_value)}</span>
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-gray-400">Unrealized P&L</span>
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
          <span className="text-sm font-medium text-gray-300">
            Positions ({summary.position_count})
          </span>
          {showPositions ? (
            <ChevronUp className="w-4 h-4 text-gray-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-500" />
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
            <span className="text-sm font-medium text-gray-300 flex items-center gap-2">
              <Bell className="w-4 h-4 text-yellow-400" />
              Recent Events ({events.length})
            </span>
            {showEvents ? (
              <ChevronUp className="w-4 h-4 text-gray-500" />
            ) : (
              <ChevronDown className="w-4 h-4 text-gray-500" />
            )}
          </button>
          {showEvents && (
            <div className="space-y-2 mt-2 max-h-[400px] overflow-y-auto">
              {events.map((event) => (
                <EventItem key={event.id} event={event} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default PositionMonitor;
