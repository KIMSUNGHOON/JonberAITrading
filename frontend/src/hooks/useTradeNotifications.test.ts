/**
 * E3-5: eod_summary notification type — pure formatting/severity helpers,
 * plus (review fix) a runtime drift guard for ALL_NOTIFICATION_TYPES, the
 * shared constant the WS dispatch allowlist in `handleMessage` now consumes
 * instead of a second hand-maintained list (see its docstring in
 * useTradeNotifications.ts for the bug this closes: a type added to the
 * TradeNotificationType union but never to the allowlist type-checked fine
 * while silently dropping every real WS frame of that type).
 *
 * The WS dispatch itself (ManagedSocket -> handleMessage) isn't exercised
 * here (no existing precedent in this repo mocks ManagedSocket at that
 * level); this pins the two exported formatting helpers every consumer
 * (TradeNotificationToast/NotificationBell) routes through, plus the
 * ALL_NOTIFICATION_TYPES <-> TradeNotificationType consistency check.
 */
import { describe, it, expect } from 'vitest';
import {
  formatNotificationMessage,
  getNotificationSeverity,
  ALL_NOTIFICATION_TYPES,
  type TradeNotification,
  type TradeNotificationType,
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

describe('ALL_NOTIFICATION_TYPES drift guard (review fix)', () => {
  it('matches the TradeNotificationType union exactly — length + membership', () => {
    // Deliberately duplicated here rather than derived from the source
    // array: the point is an INDEPENDENT pin that must be hand-updated
    // whenever TradeNotificationType gains/loses a member, mirroring the
    // compile-time exhaustiveness check (_ExhaustivenessCheck) in
    // useTradeNotifications.ts. If you just added a new notification type
    // and only this test is failing, you forgot to add it to
    // ALL_NOTIFICATION_TYPES in the source file (the tsc-level check would
    // have already caught a member missing from the source array itself —
    // this test additionally catches the source array and this list
    // drifting apart from each other).
    const expected: readonly TradeNotificationType[] = [
      'trade_executed',
      'trade_queued',
      'trade_rejected',
      'watch_added',
      'stop_loss_triggered',
      'take_profit_triggered',
      'eod_summary',
    ];
    expect(ALL_NOTIFICATION_TYPES).toHaveLength(expected.length);
    expect([...ALL_NOTIFICATION_TYPES].sort()).toEqual([...expected].sort());
  });
});
