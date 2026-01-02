/**
 * MarketStatusBanner Component
 *
 * Displays current market status with real-time countdown.
 * Shows whether market is open/closed and time until next state change.
 */

import { Clock, AlertCircle, CheckCircle, RefreshCw } from 'lucide-react';
import { useMarketHours } from '@/hooks/useMarketHours';

interface MarketStatusBannerProps {
  /** Market type to monitor (default: 'krx') */
  market?: string;
  /** Show compact version */
  compact?: boolean;
  /** Additional class names */
  className?: string;
}

export function MarketStatusBanner({
  market = 'krx',
  compact = false,
  className = '',
}: MarketStatusBannerProps) {
  const {
    status,
    loading,
    error,
    countdownFormatted,
    nextEventFormatted,
  } = useMarketHours({ market });

  if (loading) {
    return (
      <div className={`flex items-center gap-2 text-gray-400 ${className}`}>
        <RefreshCw className="w-4 h-4 animate-spin" />
        <span className="text-sm">Loading...</span>
      </div>
    );
  }

  if (error || !status) {
    return null;
  }

  const isOpen = status.is_open;

  // Compact version for sidebars or small spaces
  if (compact) {
    return (
      <div
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm ${
          isOpen
            ? 'bg-green-500/10 text-green-400'
            : 'bg-red-500/10 text-red-400'
        } ${className}`}
      >
        <div
          className={`w-2 h-2 rounded-full ${
            isOpen ? 'bg-green-500 animate-pulse' : 'bg-red-500'
          }`}
        />
        <span>{isOpen ? '장 운영 중' : '장 마감'}</span>
        <span className="text-gray-400">|</span>
        <span className="text-gray-300">{countdownFormatted}</span>
      </div>
    );
  }

  // Full banner version
  return (
    <div
      className={`flex items-center justify-between p-3 rounded-lg border ${
        isOpen
          ? 'bg-green-500/5 border-green-500/20'
          : 'bg-red-500/5 border-red-500/20'
      } ${className}`}
    >
      <div className="flex items-center gap-3">
        {/* Status indicator */}
        <div
          className={`flex items-center justify-center w-8 h-8 rounded-full ${
            isOpen ? 'bg-green-500/20' : 'bg-red-500/20'
          }`}
        >
          {isOpen ? (
            <CheckCircle className="w-5 h-5 text-green-400" />
          ) : (
            <AlertCircle className="w-5 h-5 text-red-400" />
          )}
        </div>

        {/* Status text */}
        <div>
          <div className="flex items-center gap-2">
            <span
              className={`font-medium ${
                isOpen ? 'text-green-400' : 'text-red-400'
              }`}
            >
              {isOpen ? '장 운영 중' : '장 마감 중'}
            </span>
            <span className="text-gray-500 text-sm">
              ({status.name})
            </span>
          </div>
          <div className="text-sm text-gray-400 flex items-center gap-1">
            <Clock className="w-3.5 h-3.5" />
            {isOpen ? (
              <span>마감: {nextEventFormatted}</span>
            ) : (
              <span>다음 개장: {nextEventFormatted}</span>
            )}
          </div>
        </div>
      </div>

      {/* Countdown badge */}
      <div
        className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
          isOpen
            ? 'bg-green-500/10 text-green-400'
            : 'bg-red-500/10 text-red-400'
        }`}
      >
        {countdownFormatted}
      </div>
    </div>
  );
}

/**
 * Inline market status indicator for headers or toolbars
 */
export function MarketStatusIndicator({
  market = 'krx',
  className = '',
}: {
  market?: string;
  className?: string;
}) {
  const { status, loading } = useMarketHours({
    market,
    enableCountdown: false,
    refreshInterval: 120000, // Less frequent updates
  });

  if (loading || !status) {
    return null;
  }

  const isOpen = status.is_open;

  return (
    <div
      className={`flex items-center gap-1.5 text-xs ${className}`}
      title={status.message}
    >
      <div
        className={`w-1.5 h-1.5 rounded-full ${
          isOpen ? 'bg-green-500' : 'bg-red-500'
        }`}
      />
      <span className={isOpen ? 'text-green-400' : 'text-red-400'}>
        {isOpen ? '장중' : '장마감'}
      </span>
    </div>
  );
}

export default MarketStatusBanner;
