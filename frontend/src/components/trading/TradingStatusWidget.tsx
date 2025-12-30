/**
 * TradingStatusWidget Component
 *
 * Shows auto-trading agent status including:
 * - Market hours status (KRX open/closed)
 * - Trading system status
 * - Recent activity log (agent decisions)
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Bot,
  Wallet,
  ShoppingCart,
  AlertCircle,
} from 'lucide-react';
import { getTradingActivity, getMarketHours, getTradingStatus } from '@/api/client';

interface ActivityItem {
  id: string;
  activity_type: string;
  agent: string;
  ticker: string | null;
  message: string;
  details: Record<string, unknown> | null;
  timestamp: string;
}

interface MarketStatus {
  is_open: boolean;
  message: string;
  next_open: string | null;
  next_close: string | null;
}

interface TradingSystemStatus {
  mode: string;
  is_active: boolean;
  daily_trades: number;
  max_daily_trades: number;
  pending_alerts_count: number;
}

// Activity type icons and colors
const activityConfig: Record<string, { icon: React.ReactNode; color: string }> = {
  system_start: { icon: <CheckCircle className="w-4 h-4" />, color: 'text-green-400' },
  system_stop: { icon: <XCircle className="w-4 h-4" />, color: 'text-red-400' },
  system_pause: { icon: <AlertTriangle className="w-4 h-4" />, color: 'text-yellow-400' },
  system_resume: { icon: <CheckCircle className="w-4 h-4" />, color: 'text-green-400' },
  trade_approved: { icon: <CheckCircle className="w-4 h-4" />, color: 'text-blue-400' },
  trade_rejected: { icon: <XCircle className="w-4 h-4" />, color: 'text-red-400' },
  allocation_calculated: { icon: <Wallet className="w-4 h-4" />, color: 'text-purple-400' },
  order_placed: { icon: <ShoppingCart className="w-4 h-4" />, color: 'text-blue-400' },
  order_executed: { icon: <CheckCircle className="w-4 h-4" />, color: 'text-green-400' },
  order_failed: { icon: <XCircle className="w-4 h-4" />, color: 'text-red-400' },
  position_opened: { icon: <CheckCircle className="w-4 h-4" />, color: 'text-green-400' },
  position_closed: { icon: <XCircle className="w-4 h-4" />, color: 'text-gray-400' },
  risk_alert: { icon: <AlertTriangle className="w-4 h-4" />, color: 'text-yellow-400' },
  market_closed: { icon: <Clock className="w-4 h-4" />, color: 'text-orange-400' },
  account_refreshed: { icon: <RefreshCw className="w-4 h-4" />, color: 'text-gray-400' },
};

// Agent badge colors
const agentColors: Record<string, string> = {
  system: 'bg-gray-600',
  portfolio: 'bg-purple-600',
  order: 'bg-blue-600',
  risk: 'bg-yellow-600',
};

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function ActivityRow({ activity }: { activity: ActivityItem }) {
  const config = activityConfig[activity.activity_type] || {
    icon: <AlertCircle className="w-4 h-4" />,
    color: 'text-gray-400',
  };

  const agentColor = agentColors[activity.agent] || 'bg-gray-600';

  return (
    <div className="flex items-start gap-3 p-2 hover:bg-gray-800/50 rounded-lg">
      <div className={`mt-0.5 ${config.color}`}>{config.icon}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-xs px-1.5 py-0.5 rounded ${agentColor} text-white`}>
            {activity.agent}
          </span>
          {activity.ticker && (
            <span className="text-xs text-gray-400">{activity.ticker}</span>
          )}
          <span className="text-xs text-gray-500 ml-auto">{formatTime(activity.timestamp)}</span>
        </div>
        <p className="text-sm text-gray-300 mt-0.5 truncate">{activity.message}</p>
      </div>
    </div>
  );
}

export function TradingStatusWidget() {
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);
  const [tradingStatus, setTradingStatus] = useState<TradingSystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [activityData, marketData, statusData] = await Promise.all([
        getTradingActivity(20).catch(() => ({ activities: [], count: 0 })),
        getMarketHours().catch(() => null),
        getTradingStatus().catch(() => null),
      ]);

      setActivities(activityData.activities);
      if (marketData) {
        setMarketStatus(marketData.krx);
      }
      setTradingStatus(statusData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Poll every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
        <div className="flex items-center justify-center py-8">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between p-4 cursor-pointer hover:bg-gray-800/50"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <Bot className="w-5 h-5 text-blue-400" />
          <h3 className="text-sm font-medium text-white">Agent Status</h3>
        </div>
        <div className="flex items-center gap-3">
          {/* Market Status Badge */}
          {marketStatus && (
            <span
              className={`px-2 py-1 text-xs rounded-full ${
                marketStatus.is_open
                  ? 'bg-green-500/20 text-green-400'
                  : 'bg-red-500/20 text-red-400'
              }`}
            >
              KRX {marketStatus.is_open ? 'Open' : 'Closed'}
            </span>
          )}
          {/* Trading Status Badge */}
          {tradingStatus && (
            <span
              className={`px-2 py-1 text-xs rounded-full ${
                tradingStatus.mode === 'active'
                  ? 'bg-green-500/20 text-green-400'
                  : tradingStatus.mode === 'paused'
                  ? 'bg-yellow-500/20 text-yellow-400'
                  : 'bg-gray-500/20 text-gray-400'
              }`}
            >
              {tradingStatus.mode.charAt(0).toUpperCase() + tradingStatus.mode.slice(1)}
            </span>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              fetchData();
            }}
            className="p-1 text-gray-400 hover:text-white"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          )}
        </div>
      </div>

      {expanded && (
        <>
          {/* Market Info */}
          {marketStatus && (
            <div className="px-4 pb-3 border-b border-gray-800">
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Clock className="w-4 h-4" />
                <span>{marketStatus.message}</span>
              </div>
            </div>
          )}

          {/* Trading Stats */}
          {tradingStatus && (
            <div className="px-4 py-3 border-b border-gray-800 grid grid-cols-3 gap-4">
              <div className="text-center">
                <div className="text-lg font-semibold text-white">
                  {tradingStatus.daily_trades}/{tradingStatus.max_daily_trades}
                </div>
                <div className="text-xs text-gray-500">Daily Trades</div>
              </div>
              <div className="text-center">
                <div className="text-lg font-semibold text-white">
                  {tradingStatus.pending_alerts_count}
                </div>
                <div className="text-xs text-gray-500">Pending Alerts</div>
              </div>
              <div className="text-center">
                <div
                  className={`text-lg font-semibold ${
                    tradingStatus.is_active ? 'text-green-400' : 'text-gray-400'
                  }`}
                >
                  {tradingStatus.is_active ? 'Active' : 'Inactive'}
                </div>
                <div className="text-xs text-gray-500">System</div>
              </div>
            </div>
          )}

          {/* Activity Log */}
          <div className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="w-4 h-4 text-gray-400" />
              <span className="text-xs text-gray-400 font-medium">Recent Activity</span>
            </div>

            {error && (
              <div className="text-sm text-red-400 text-center py-4">{error}</div>
            )}

            {activities.length === 0 ? (
              <div className="text-sm text-gray-500 text-center py-4">
                No recent activity
              </div>
            ) : (
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {activities.map((activity) => (
                  <ActivityRow key={activity.id} activity={activity} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default TradingStatusWidget;
