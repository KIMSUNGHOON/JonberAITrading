/**
 * Market Status Badge Component
 *
 * Displays real-time market status for KR Stock, US Stock, and Crypto.
 * Shows open/closed status with color indicators.
 */

import { useState, useEffect } from 'react';
import {
  getAllMarketsStatus,
  type AllMarketsStatus,
  type MarketStatus,
} from '@/utils/marketHours';

interface MarketIndicatorProps {
  label: string;
  icon: React.ReactNode;
  status: MarketStatus;
  showDetails?: boolean;
}

function MarketIndicator({ label, icon, status, showDetails = false }: MarketIndicatorProps) {
  const getStatusColor = () => {
    switch (status.status) {
      case 'open':
        return 'bg-green-500';
      case 'pre-market':
      case 'after-hours':
        return 'bg-yellow-500';
      case 'closed':
        return 'bg-red-500';
      default:
        return 'bg-gray-500';
    }
  };

  const getIconColor = () => {
    switch (status.status) {
      case 'open':
        return 'text-green-400';
      case 'pre-market':
      case 'after-hours':
        return 'text-yellow-400';
      case 'closed':
        return 'text-red-400';
      default:
        return 'text-gray-400';
    }
  };

  const getStatusBgColor = () => {
    switch (status.status) {
      case 'open':
        return 'bg-green-500/10 border-green-500/30';
      case 'pre-market':
      case 'after-hours':
        return 'bg-yellow-500/10 border-yellow-500/30';
      case 'closed':
        return 'bg-red-500/10 border-red-500/30';
      default:
        return 'bg-gray-500/10 border-gray-500/30';
    }
  };

  const getTextColor = () => {
    switch (status.status) {
      case 'open':
        return 'text-green-300';
      case 'pre-market':
      case 'after-hours':
        return 'text-yellow-300';
      case 'closed':
        return 'text-red-300';
      default:
        return 'text-gray-400';
    }
  };

  return (
    <div
      className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border ${getStatusBgColor()} transition-colors cursor-default min-w-[90px]`}
      title={`${label}: ${status.statusKr}\n${status.openTime}-${status.closeTime} ${status.timezone}\n${status.nextChange}`}
    >
      <span className={`${getIconColor()} flex-shrink-0`}>{icon}</span>
      <div className="flex items-center gap-1.5 flex-1">
        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${getStatusColor()} ${status.status === 'open' ? 'animate-pulse' : ''}`} />
        {showDetails && (
          <span className={`text-xs font-medium truncate ${getTextColor()}`}>
            {status.statusKr}
          </span>
        )}
      </div>
    </div>
  );
}

export function MarketStatusBadge() {
  const [markets, setMarkets] = useState<AllMarketsStatus | null>(null);
  const [times, setTimes] = useState<{ kst: string; et: string }>({ kst: '', et: '' });

  useEffect(() => {
    // Initial fetch
    setMarkets(getAllMarketsStatus());
    updateTimes();

    // Update every minute
    const interval = setInterval(() => {
      setMarkets(getAllMarketsStatus());
      updateTimes();
    }, 60000);

    return () => clearInterval(interval);
  }, []);

  const updateTimes = () => {
    const now = new Date();

    // Korean Time (KST)
    const kst = now.toLocaleTimeString('ko-KR', {
      timeZone: 'Asia/Seoul',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });

    // US Eastern Time (ET)
    const et = now.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });

    setTimes({ kst, et });
  };

  if (!markets) return null;

  return (
    <div className="hidden md:flex items-center gap-2">
      {/* World Clocks */}
      <div className="flex items-center gap-3 px-2.5 py-1.5 bg-surface rounded-lg">
        <div className="flex items-center gap-1.5" title="Korea Standard Time (KST)">
          <span className="text-xs text-gray-500">KST</span>
          <span className="text-sm font-mono text-gray-200">{times.kst}</span>
        </div>
        <div className="w-px h-4 bg-border" />
        <div className="flex items-center gap-1.5" title="US Eastern Time (ET)">
          <span className="text-xs text-gray-500">ET</span>
          <span className="text-sm font-mono text-gray-200">{times.et}</span>
        </div>
      </div>

      {/* Divider */}
      <div className="w-px h-6 bg-border" />

      {/* Market Status Indicators */}
      <div className="flex items-center gap-2">
        {/* Korean Stock */}
        <MarketIndicator
          label="Korea (KRX)"
          icon={<span className="text-xs font-bold w-5 text-center">KR</span>}
          status={markets.kiwoom}
          showDetails
        />

        {/* US Stock */}
        <MarketIndicator
          label="US (NYSE/NASDAQ)"
          icon={<span className="text-xs font-bold w-5 text-center">US</span>}
          status={markets.stock}
          showDetails
        />

        {/* Crypto (Upbit) */}
        <MarketIndicator
          label="Upbit (Crypto)"
          icon={<span className="text-xs font-bold w-5 text-center">UB</span>}
          status={markets.coin}
          showDetails
        />
      </div>
    </div>
  );
}

/**
 * Compact version for mobile
 */
export function MarketStatusCompact() {
  const [markets, setMarkets] = useState<AllMarketsStatus | null>(null);

  useEffect(() => {
    setMarkets(getAllMarketsStatus());
    const interval = setInterval(() => {
      setMarkets(getAllMarketsStatus());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  if (!markets) return null;

  const openCount = [markets.stock, markets.kiwoom, markets.coin].filter(
    m => m.status === 'open'
  ).length;

  return (
    <div
      className="flex md:hidden items-center gap-1.5 px-2 py-1 bg-surface rounded-lg"
      title="Market Status"
    >
      <div className={`w-2 h-2 rounded-full ${
        openCount === 3 ? 'bg-green-500' :
        openCount > 0 ? 'bg-yellow-500' :
        'bg-red-500'
      }`} />
      <span className="text-xs text-gray-400">
        {openCount}/3
      </span>
    </div>
  );
}
