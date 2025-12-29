/**
 * Market Hours Utility
 *
 * Provides market open/close times and status for different markets.
 *
 * Market Hours:
 * - US Stock (NYSE/NASDAQ): 9:30 AM - 4:00 PM ET (Eastern Time)
 *   - Pre-market: 4:00 AM - 9:30 AM ET
 *   - After-hours: 4:00 PM - 8:00 PM ET
 * - Korean Stock (KRX): 9:00 AM - 3:30 PM KST (Korea Standard Time)
 *   - Pre-market: 8:30 AM - 9:00 AM KST
 *   - After-hours: 3:40 PM - 6:00 PM KST (단일가)
 * - Crypto: 24/7 (always open)
 */

export type MarketType = 'stock' | 'kiwoom' | 'coin';

export interface MarketStatus {
  isOpen: boolean;
  status: 'open' | 'closed' | 'pre-market' | 'after-hours';
  statusKr: string;
  openTime: string;
  closeTime: string;
  nextChange: string; // Time until next status change
  timezone: string;
}

export interface AllMarketsStatus {
  stock: MarketStatus;
  kiwoom: MarketStatus;
  coin: MarketStatus;
}

/**
 * Get current time in a specific timezone
 */
function getTimeInTimezone(timezone: string): Date {
  const now = new Date();
  const options: Intl.DateTimeFormatOptions = {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  };

  const parts = new Intl.DateTimeFormat('en-US', options).formatToParts(now);
  const values: Record<string, string> = {};
  parts.forEach(part => {
    values[part.type] = part.value;
  });

  return new Date(
    parseInt(values.year),
    parseInt(values.month) - 1,
    parseInt(values.day),
    parseInt(values.hour),
    parseInt(values.minute),
    parseInt(values.second)
  );
}

/**
 * Check if today is a weekday (Monday-Friday)
 */
function isWeekday(date: Date): boolean {
  const day = date.getDay();
  return day !== 0 && day !== 6; // 0 = Sunday, 6 = Saturday
}

/**
 * Format time difference as human-readable string
 */
function formatTimeDiff(ms: number): string {
  if (ms <= 0) return '지금';

  const hours = Math.floor(ms / (1000 * 60 * 60));
  const minutes = Math.floor((ms % (1000 * 60 * 60)) / (1000 * 60));

  if (hours > 0) {
    return `${hours}시간 ${minutes}분`;
  }
  return `${minutes}분`;
}

/**
 * Get US Stock Market (NYSE/NASDAQ) status
 * Trading hours: 9:30 AM - 4:00 PM ET
 */
export function getUSStockMarketStatus(): MarketStatus {
  const etTimezone = 'America/New_York';
  const now = getTimeInTimezone(etTimezone);
  const hours = now.getHours();
  const minutes = now.getMinutes();
  const currentMinutes = hours * 60 + minutes;

  // Market times in minutes from midnight
  const preMarketStart = 4 * 60; // 4:00 AM
  const marketOpen = 9 * 60 + 30; // 9:30 AM
  const marketClose = 16 * 60; // 4:00 PM
  const afterHoursEnd = 20 * 60; // 8:00 PM

  const isWeekdayNow = isWeekday(now);

  let status: MarketStatus['status'];
  let statusKr: string;
  let nextChange: string;

  if (!isWeekdayNow) {
    status = 'closed';
    statusKr = '휴장 (주말)';
    nextChange = '월요일 개장';
  } else if (currentMinutes < preMarketStart) {
    status = 'closed';
    statusKr = '휴장';
    const diff = (preMarketStart - currentMinutes) * 60 * 1000;
    nextChange = `프리마켓 ${formatTimeDiff(diff)} 후`;
  } else if (currentMinutes < marketOpen) {
    status = 'pre-market';
    statusKr = '프리마켓';
    const diff = (marketOpen - currentMinutes) * 60 * 1000;
    nextChange = `정규장 ${formatTimeDiff(diff)} 후`;
  } else if (currentMinutes < marketClose) {
    status = 'open';
    statusKr = '장중';
    const diff = (marketClose - currentMinutes) * 60 * 1000;
    nextChange = `마감 ${formatTimeDiff(diff)} 후`;
  } else if (currentMinutes < afterHoursEnd) {
    status = 'after-hours';
    statusKr = '애프터마켓';
    const diff = (afterHoursEnd - currentMinutes) * 60 * 1000;
    nextChange = `종료 ${formatTimeDiff(diff)} 후`;
  } else {
    status = 'closed';
    statusKr = '휴장';
    nextChange = '내일 프리마켓';
  }

  return {
    isOpen: status === 'open',
    status,
    statusKr,
    openTime: '09:30',
    closeTime: '16:00',
    nextChange,
    timezone: 'ET',
  };
}

/**
 * Get Korean Stock Market (KRX) status
 * Trading hours: 9:00 AM - 3:30 PM KST
 */
export function getKRStockMarketStatus(): MarketStatus {
  const kstTimezone = 'Asia/Seoul';
  const now = getTimeInTimezone(kstTimezone);
  const hours = now.getHours();
  const minutes = now.getMinutes();
  const currentMinutes = hours * 60 + minutes;

  // Market times in minutes from midnight
  const preMarketStart = 8 * 60 + 30; // 8:30 AM
  const marketOpen = 9 * 60; // 9:00 AM
  const marketClose = 15 * 60 + 30; // 3:30 PM
  const afterHoursEnd = 18 * 60; // 6:00 PM

  const isWeekdayNow = isWeekday(now);

  let status: MarketStatus['status'];
  let statusKr: string;
  let nextChange: string;

  if (!isWeekdayNow) {
    status = 'closed';
    statusKr = '휴장 (주말)';
    nextChange = '월요일 개장';
  } else if (currentMinutes < preMarketStart) {
    status = 'closed';
    statusKr = '휴장';
    const diff = (preMarketStart - currentMinutes) * 60 * 1000;
    nextChange = `장전 ${formatTimeDiff(diff)} 후`;
  } else if (currentMinutes < marketOpen) {
    status = 'pre-market';
    statusKr = '장전 동시호가';
    const diff = (marketOpen - currentMinutes) * 60 * 1000;
    nextChange = `개장 ${formatTimeDiff(diff)} 후`;
  } else if (currentMinutes < marketClose) {
    status = 'open';
    statusKr = '장중';
    const diff = (marketClose - currentMinutes) * 60 * 1000;
    nextChange = `마감 ${formatTimeDiff(diff)} 후`;
  } else if (currentMinutes < afterHoursEnd) {
    status = 'after-hours';
    statusKr = '시간외 단일가';
    const diff = (afterHoursEnd - currentMinutes) * 60 * 1000;
    nextChange = `종료 ${formatTimeDiff(diff)} 후`;
  } else {
    status = 'closed';
    statusKr = '휴장';
    nextChange = '내일 개장';
  }

  return {
    isOpen: status === 'open',
    status,
    statusKr,
    openTime: '09:00',
    closeTime: '15:30',
    nextChange,
    timezone: 'KST',
  };
}

/**
 * Get Crypto Market status
 * Trading hours: 24/7
 */
export function getCryptoMarketStatus(): MarketStatus {
  return {
    isOpen: true,
    status: 'open',
    statusKr: '24시간',
    openTime: '00:00',
    closeTime: '24:00',
    nextChange: '항상 거래 가능',
    timezone: 'UTC',
  };
}

/**
 * Get market status for a specific market type
 */
export function getMarketStatus(marketType: MarketType): MarketStatus {
  switch (marketType) {
    case 'stock':
      return getUSStockMarketStatus();
    case 'kiwoom':
      return getKRStockMarketStatus();
    case 'coin':
      return getCryptoMarketStatus();
    default:
      return getCryptoMarketStatus();
  }
}

/**
 * Get status for all markets
 */
export function getAllMarketsStatus(): AllMarketsStatus {
  return {
    stock: getUSStockMarketStatus(),
    kiwoom: getKRStockMarketStatus(),
    coin: getCryptoMarketStatus(),
  };
}

/**
 * Check if trading is allowed for a market
 * Returns true for open, pre-market, and after-hours (with warning)
 */
export function isTradingAllowed(marketType: MarketType): {
  allowed: boolean;
  warning?: string;
} {
  const status = getMarketStatus(marketType);

  if (marketType === 'coin') {
    return { allowed: true };
  }

  if (status.status === 'open') {
    return { allowed: true };
  }

  if (status.status === 'pre-market' || status.status === 'after-hours') {
    return {
      allowed: true,
      warning: marketType === 'kiwoom'
        ? `현재 ${status.statusKr} 시간입니다. 일부 주문이 제한될 수 있습니다.`
        : `Currently in ${status.status}. Some orders may be restricted.`,
    };
  }

  return {
    allowed: false,
    warning: marketType === 'kiwoom'
      ? `현재 장이 마감되었습니다 (${status.statusKr}). ${status.nextChange}`
      : `Market is closed (${status.statusKr}). ${status.nextChange}`,
  };
}

/**
 * Get current time string for display
 */
export function getCurrentTimeString(timezone: string): string {
  const options: Intl.DateTimeFormatOptions = {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  };
  return new Date().toLocaleTimeString('en-US', options);
}
