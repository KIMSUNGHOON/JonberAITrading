/**
 * TradingDashboard Component
 *
 * Main auto-trading dashboard showing:
 * - Trading system status and controls
 * - Portfolio summary
 * - Managed positions with P&L
 * - Pending alerts
 * - Risk parameters
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Play,
  Pause,
  Square,
  RefreshCw,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Activity,
  Settings,
  Bell,
} from 'lucide-react';
import AgentStatusWidget from './AgentStatusWidget';
import TradeQueueWidget from './TradeQueueWidget';
import StrategyConfigWidget from './StrategyConfigWidget';
import {
  getTradingStatus,
  getTradingPortfolio,
  getTradingAlerts,
  startTrading,
  stopTrading,
  pauseTrading,
  resumeTrading,
} from '@/api/client';
import type {
  TradingMode,
  ManagedPosition,
  TradingAlert,
} from '@/types';

// -------------------------------------------
// Sub-components
// -------------------------------------------

interface StatusBadgeProps {
  mode: TradingMode | string;
}

function StatusBadge({ mode }: StatusBadgeProps) {
  const styles: Record<string, string> = {
    active: 'bg-green-500/20 text-green-400 border-green-500/30',
    paused: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    stopped: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  };

  const labels: Record<string, string> = {
    active: 'Active',
    paused: 'Paused',
    stopped: 'Stopped',
  };

  return (
    <span
      className={`px-3 py-1 rounded-full text-sm font-medium border ${
        styles[mode] || styles.stopped
      }`}
    >
      {labels[mode] || mode}
    </span>
  );
}

interface PositionRowProps {
  position: ManagedPosition;
}

function PositionRow({ position }: PositionRowProps) {
  const pnlColor =
    position.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400';
  const pnlIcon =
    position.unrealized_pnl >= 0 ? (
      <TrendingUp className="w-4 h-4" />
    ) : (
      <TrendingDown className="w-4 h-4" />
    );

  return (
    <div className="flex items-center justify-between p-3 bg-gray-800/50 rounded-lg">
      <div className="flex-1">
        <div className="font-medium text-white">{position.stock_name}</div>
        <div className="text-sm text-gray-400">{position.ticker}</div>
      </div>
      <div className="text-right">
        <div className="text-sm text-gray-300">
          {position.quantity}주 @ ₩{position.avg_price.toLocaleString()}
        </div>
        <div className={`flex items-center justify-end gap-1 ${pnlColor}`}>
          {pnlIcon}
          <span>
            ₩{Math.abs(position.unrealized_pnl).toLocaleString()} (
            {position.unrealized_pnl_pct >= 0 ? '+' : ''}
            {position.unrealized_pnl_pct.toFixed(2)}%)
          </span>
        </div>
      </div>
    </div>
  );
}

interface AlertItemProps {
  alert: TradingAlert;
}

function AlertItem({ alert }: AlertItemProps) {
  const typeColors: Record<string, string> = {
    stop_loss_triggered: 'border-red-500/50 bg-red-500/10',
    take_profit_triggered: 'border-green-500/50 bg-green-500/10',
    sudden_move_up: 'border-yellow-500/50 bg-yellow-500/10',
    sudden_move_down: 'border-orange-500/50 bg-orange-500/10',
    news_alert: 'border-blue-500/50 bg-blue-500/10',
  };

  return (
    <div
      className={`p-3 rounded-lg border ${
        typeColors[alert.alert_type] || 'border-gray-700 bg-gray-800/50'
      }`}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 mt-0.5 text-yellow-400" />
        <div className="flex-1">
          <div className="font-medium text-white">{alert.title}</div>
          <div className="text-sm text-gray-300">{alert.message}</div>
          {alert.ticker && (
            <div className="text-xs text-gray-400 mt-1">{alert.ticker}</div>
          )}
        </div>
      </div>
    </div>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

export default function TradingDashboard() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Trading state
  const [status, setStatus] = useState<{
    mode: string;
    is_active: boolean;
    started_at: string | null;
    daily_trades: number;
    max_daily_trades: number;
    pending_alerts_count: number;
  } | null>(null);

  const [portfolio, setPortfolio] = useState<{
    total_equity: number;
    cash: number;
    cash_ratio: number;
    stock_value: number;
    stock_ratio: number;
    positions: ManagedPosition[];
    total_unrealized_pnl: number;
    total_unrealized_pnl_pct: number;
    daily_trades: number;
    max_daily_trades: number;
  } | null>(null);

  const [alerts, setAlerts] = useState<TradingAlert[]>([]);
  const [actionLoading, setActionLoading] = useState(false);

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [statusData, portfolioData, alertsData] = await Promise.all([
        getTradingStatus(),
        getTradingPortfolio().catch(() => null),
        getTradingAlerts().catch(() => ({ alerts: [], count: 0 })),
      ]);

      setStatus(statusData);
      if (portfolioData) {
        setPortfolio({
          ...portfolioData,
          positions: portfolioData.positions as ManagedPosition[],
        });
      } else {
        setPortfolio(null);
      }
      setAlerts((alertsData.alerts as TradingAlert[]) || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch trading data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Poll every 10 seconds
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Actions
  const handleStart = async () => {
    setActionLoading(true);
    try {
      await startTrading();
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start trading');
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = async () => {
    setActionLoading(true);
    try {
      await stopTrading();
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop trading');
    } finally {
      setActionLoading(false);
    }
  };

  const handlePause = async () => {
    setActionLoading(true);
    try {
      await pauseTrading('Manual pause');
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to pause trading');
    } finally {
      setActionLoading(false);
    }
  };

  const handleResume = async () => {
    setActionLoading(true);
    try {
      await resumeTrading();
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resume trading');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="p-4 lg:p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl lg:text-2xl font-bold text-white">Auto-Trading</h1>
          <p className="text-sm text-gray-400">Automated trading management</p>
        </div>
        <button
          onClick={fetchData}
          className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
        >
          <RefreshCw className="w-5 h-5" />
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Main Grid Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left Column - Controls & Status */}
        <div className="space-y-4">
          {/* Status Card - Compact */}
          <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-white flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" />
                Status
              </h2>
              <StatusBadge mode={status?.mode || 'stopped'} />
            </div>

            <div className="space-y-2 text-sm mb-4">
              <div className="flex justify-between">
                <span className="text-gray-400">Started</span>
                <span className="text-white">
                  {status?.started_at
                    ? new Date(status.started_at).toLocaleTimeString()
                    : '-'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Trades</span>
                <span className="text-white">
                  {status?.daily_trades || 0}/{status?.max_daily_trades || 10}
                </span>
              </div>
            </div>

            {/* Control Buttons */}
            <div className="flex gap-2">
              {status?.mode === 'stopped' ? (
                <button
                  onClick={handleStart}
                  disabled={actionLoading}
                  className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg disabled:opacity-50"
                >
                  <Play className="w-4 h-4" />
                  Start
                </button>
              ) : status?.mode === 'paused' ? (
                <>
                  <button
                    onClick={handleResume}
                    disabled={actionLoading}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg disabled:opacity-50"
                  >
                    <Play className="w-4 h-4" />
                    Resume
                  </button>
                  <button
                    onClick={handleStop}
                    disabled={actionLoading}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded-lg disabled:opacity-50"
                  >
                    <Square className="w-4 h-4" />
                    Stop
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
                    Pause
                  </button>
                  <button
                    onClick={handleStop}
                    disabled={actionLoading}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded-lg disabled:opacity-50"
                  >
                    <Square className="w-4 h-4" />
                    Stop
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Portfolio Summary - Compact */}
          <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
            <h2 className="font-semibold text-white flex items-center gap-2 mb-3">
              <DollarSign className="w-4 h-4 text-green-400" />
              Portfolio
            </h2>

            {portfolio ? (
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Equity</span>
                  <span className="text-white font-medium">
                    ₩{portfolio.total_equity.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Cash</span>
                  <span className="text-white">
                    {(portfolio.cash_ratio * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex justify-between pt-2 border-t border-gray-700">
                  <span className="text-gray-400">P&L</span>
                  <span className={portfolio.total_unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                    {portfolio.total_unrealized_pnl >= 0 ? '+' : ''}
                    {portfolio.total_unrealized_pnl_pct.toFixed(2)}%
                  </span>
                </div>
              </div>
            ) : (
              <div className="text-gray-400 text-center py-4 text-sm">No data</div>
            )}
          </div>

          {/* Trade Queue Widget */}
          <TradeQueueWidget />
        </div>

        {/* Middle Column - Agent Status & Positions */}
        <div className="space-y-4">
          {/* Agent Status Widget */}
          <AgentStatusWidget />

          {/* Positions */}
          <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
            <h2 className="font-semibold text-white flex items-center gap-2 mb-3">
              <TrendingUp className="w-4 h-4 text-blue-400" />
              Positions
              {portfolio?.positions && portfolio.positions.length > 0 && (
                <span className="text-sm text-gray-400">
                  ({portfolio.positions.length})
                </span>
              )}
            </h2>

            {portfolio?.positions && portfolio.positions.length > 0 ? (
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {portfolio.positions.map((position, idx) => (
                  <PositionRow key={position.ticker || idx} position={position} />
                ))}
              </div>
            ) : (
              <div className="text-gray-400 text-center py-6 text-sm">
                No active positions
              </div>
            )}
          </div>

          {/* Alerts */}
          {alerts.length > 0 && (
            <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
              <h2 className="font-semibold text-white flex items-center gap-2 mb-3">
                <Bell className="w-4 h-4 text-yellow-400" />
                Alerts
                <span className="text-sm text-gray-400">({alerts.length})</span>
              </h2>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {alerts.map((alert) => (
                  <AlertItem key={alert.id} alert={alert} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right Column - Strategy Configuration */}
        <div>
          <StrategyConfigWidget />
        </div>
      </div>
    </div>
  );
}
