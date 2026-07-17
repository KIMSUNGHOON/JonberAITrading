/**
 * E3-5: eod_summary notification type — pure formatting/severity helpers.
 *
 * The WS dispatch itself (ManagedSocket -> handleMessage -> notificationTypes
 * allowlist) isn't exercised here (no existing precedent in this repo mocks
 * ManagedSocket at that level); this pins the two exported helpers every
 * consumer (TradeNotificationToast/NotificationBell) routes through, plus a
 * guard that 'eod_summary' is present in TradeNotificationType at the type
 * level (compile-time via the object literal below).
 */
import { describe, it, expect } from 'vitest';
import {
  formatNotificationMessage,
  getNotificationSeverity,
  type TradeNotification,
} from './useTradeNotifications';

function eodNotification(overrides: Partial<TradeNotification['data']> = {}): TradeNotification {
  return {
    type: 'eod_summary',
    data: {
      trade_date: '2026-07-16',
      headline: '당일 실현손익 +140,000원 · 총평가 500,140,000원 · 시장 RISK_ON',
      has_narrative: true,
      timestamp: new Date().toISOString(),
      ...overrides,
    },
  };
}

describe('eod_summary notification type', () => {
  it('formats a "장마감 요약" title + headline body, including trade_date', () => {
    const msg = formatNotificationMessage(eodNotification());
    expect(msg).toContain('장마감 요약');
    expect(msg).toContain('2026-07-16');
    expect(msg).toContain('당일 실현손익 +140,000원');
  });

  it('degrades gracefully when headline is missing', () => {
    const msg = formatNotificationMessage(eodNotification({ headline: undefined }));
    expect(msg).toContain('장마감 요약');
    expect(msg).not.toContain('undefined');
  });

  it('is classified as an info-severity notification', () => {
    expect(getNotificationSeverity('eod_summary')).toBe('info');
  });
});
