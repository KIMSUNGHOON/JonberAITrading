/**
 * TradingStatusCard Component
 *
 * Compact card showing Auto Trading status on the Dashboard:
 * - Trading mode (Active/Paused/Stopped)
 * - Trade queue status
 * - Quick link to full trading dashboard
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  Play,
  Pause,
  Square,
  Clock,
  ArrowRight,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { useStore } from '@/store';
import { getTradingStatus, getTradeQueue } from '@/api/client';

interface TradingStatus {
  mode: string;
  is_active: boolean;
  started_at: string | null;
  daily_trades: number;
  max_daily_trades: number;
  pending_alerts_count: number;
}

interface QueuedTrade {
  id: string;
  ticker: string;
  stock_name: string | null;
  action: string;
  status: string;
}

export function TradingStatusCard() {
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<TradingStatus | null>(null);
  const [queueCount, setQueueCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const setCurrentView = useStore((state) => state.setCurrentView);

  const fetchStatus = useCallback(async () => {
    try {
      setError(null);
      const [statusData, queueData] = await Promise.all([
        getTradingStatus(),
        getTradeQueue().catch(() => ({ queue: [] })),
      ]);

      setStatus(statusData);
      const pendingTrades = (queueData.queue as QueuedTrade[]).filter(
        (t) => t.status === 'pending'
      );
      setQueueCount(pendingTrades.length);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    // Poll every 15 seconds
    const interval = setInterval(fetchStatus, 15000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const getStatusConfig = (mode: string) => {
    switch (mode) {
      case 'active':
        return {
          icon: <Play className="w-4 h-4" />,
          label: 'Active',
          color: 'text-green-400',
          bgColor: 'bg-green-500/10',
          borderColor: 'border-green-500/30',
        };
      case 'paused':
        return {
          icon: <Pause className="w-4 h-4" />,
          label: 'Paused',
          color: 'text-yellow-400',
          bgColor: 'bg-yellow-500/10',
          borderColor: 'border-yellow-500/30',
        };
      default:
        return {
          icon: <Square className="w-4 h-4" />,
          label: 'Stopped',
          color: 'text-gray-400',
          bgColor: 'bg-gray-500/10',
          borderColor: 'border-gray-500/30',
        };
    }
  };

  const goToTrading = () => {
    setCurrentView('trading');
  };

  if (loading) {
    return (
      <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
        <div className="flex items-center justify-center h-16">
          <RefreshCw className="w-5 h-5 animate-spin text-blue-500" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4" />
          <span>{error}</span>
        </div>
      </div>
    );
  }

  const config = getStatusConfig(status?.mode || 'stopped');

  return (
    <div
      className={`bg-gray-900 rounded-xl p-4 border ${config.borderColor} cursor-pointer hover:bg-gray-800/50 transition-colors`}
      onClick={goToTrading}
    >
      <div className="flex items-center justify-between">
        {/* Left - Status */}
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${config.bgColor} ${config.color}`}>
            <Activity className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-white">Auto Trading</span>
              <span
                className={`flex items-center gap-1 px-2 py-0.5 text-xs rounded-full ${config.bgColor} ${config.color}`}
              >
                {config.icon}
                {config.label}
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-400 mt-0.5">
              <span>
                Trades: {status?.daily_trades || 0}/{status?.max_daily_trades || 10}
              </span>
              {queueCount > 0 && (
                <span className="flex items-center gap-1 text-yellow-400">
                  <Clock className="w-3 h-3" />
                  {queueCount} queued
                </span>
              )}
              {(status?.pending_alerts_count || 0) > 0 && (
                <span className="text-orange-400">
                  {status?.pending_alerts_count} alerts
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Right - Arrow */}
        <ArrowRight className="w-5 h-5 text-gray-500" />
      </div>
    </div>
  );
}
