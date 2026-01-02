/**
 * useMarketHours Hook
 *
 * Provides real-time market status with countdown timer.
 * Features:
 * - Fetches market status from API
 * - Manages countdown timer with 1-second updates
 * - Auto-refreshes data periodically
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { getMarketStatus } from '@/api/client';
import type { MarketStatus } from '@/types';

export interface UseMarketHoursOptions {
  /** Market type to monitor (default: 'krx') */
  market?: string;
  /** Refresh interval in milliseconds (default: 60000 = 1 minute) */
  refreshInterval?: number;
  /** Enable countdown timer with 1-second updates (default: true) */
  enableCountdown?: boolean;
}

export interface UseMarketHoursResult {
  /** Current market status */
  status: MarketStatus | null;
  /** Loading state */
  loading: boolean;
  /** Error message if any */
  error: string | null;
  /** Current countdown in seconds (updates every second) */
  countdown: number;
  /** Formatted countdown string (e.g., "2시간 30분") */
  countdownFormatted: string;
  /** Formatted time until next event (e.g., "09:00 (2시간 30분 후)") */
  nextEventFormatted: string;
  /** Manually refresh market status */
  refresh: () => Promise<void>;
}

/**
 * Format seconds to Korean time string
 */
function formatCountdown(seconds: number): string {
  if (seconds <= 0) return '0분';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours}시간`);
  if (minutes > 0) parts.push(`${minutes}분`);
  if (hours === 0 && secs > 0) parts.push(`${secs}초`);

  return parts.join(' ') || '0분';
}

/**
 * Format next event time with countdown
 */
function formatNextEvent(status: MarketStatus | null, countdown: number): string {
  if (!status) return '';

  const targetTime = status.is_open ? status.next_close : status.next_open;
  if (!targetTime) return '';

  try {
    const date = new Date(targetTime);
    const timeStr = date.toLocaleTimeString('ko-KR', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });

    // Check if it's a different day
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    const isTomorrow =
      date.toDateString() ===
      new Date(now.getTime() + 24 * 60 * 60 * 1000).toDateString();

    let prefix = '';
    if (!isToday) {
      if (isTomorrow) {
        prefix = '내일 ';
      } else {
        prefix = date.toLocaleDateString('ko-KR', {
          month: 'short',
          day: 'numeric',
        }) + ' ';
      }
    }

    return `${prefix}${timeStr} (${formatCountdown(countdown)} 후)`;
  } catch {
    return '';
  }
}

export function useMarketHours(options: UseMarketHoursOptions = {}): UseMarketHoursResult {
  const {
    market = 'krx',
    refreshInterval = 60000,
    enableCountdown = true,
  } = options;

  const [status, setStatus] = useState<MarketStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(0);

  const countdownRef = useRef(0);

  const fetchStatus = useCallback(async () => {
    try {
      setError(null);
      const data = await getMarketStatus(market);
      setStatus(data);
      setCountdown(data.countdown_seconds);
      countdownRef.current = data.countdown_seconds;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch market status');
    } finally {
      setLoading(false);
    }
  }, [market]);

  // Initial fetch
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Periodic refresh
  useEffect(() => {
    const interval = setInterval(fetchStatus, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, refreshInterval]);

  // Countdown timer (1-second updates)
  useEffect(() => {
    if (!enableCountdown) return;

    const timer = setInterval(() => {
      setCountdown((prev) => {
        const newValue = Math.max(0, prev - 1);
        countdownRef.current = newValue;
        return newValue;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [enableCountdown]);

  return {
    status,
    loading,
    error,
    countdown,
    countdownFormatted: formatCountdown(countdown),
    nextEventFormatted: formatNextEvent(status, countdown),
    refresh: fetchStatus,
  };
}

export default useMarketHours;
