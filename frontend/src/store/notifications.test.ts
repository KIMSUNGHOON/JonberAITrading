/**
 * P1-3 notification-center store slice.
 *
 * Covers:
 * - addNotification prepends, marks read/unread based on panel-open state,
 *   and bounds the list to MAX_PERSISTED_NOTIFICATIONS.
 * - markNotificationsRead / clearAllNotifications.
 * - Persistence: partialize includes `notifications`, and a persisted blob
 *   rehydrates (bounded defensively even if it somehow exceeds the cap).
 */

import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { useStore, selectUnreadNotificationCount } from './index';

const STORAGE_KEY = 'agentic-trading-storage';

function baseNotification(overrides: Partial<{ type: string; ticker: string }> = {}) {
  return {
    type: overrides.type ?? 'trade_executed',
    data: {
      ticker: overrides.ticker ?? '005930',
      stock_name: '삼성전자',
      action: 'BUY',
      quantity: 1,
      price: 1000,
      timestamp: new Date().toISOString(),
    },
  } as never;
}

describe('notification center actions', () => {
  beforeEach(() => {
    useStore.setState({ notifications: [], notificationPanelOpen: false });
  });

  it('addNotification prepends a new unread item when the panel is closed', () => {
    useStore.getState().addNotification(baseNotification());
    const list = useStore.getState().notifications;
    expect(list).toHaveLength(1);
    expect(list[0].read).toBe(false);
    expect(selectUnreadNotificationCount(useStore.getState())).toBe(1);
  });

  it('marks a captured notification read immediately if the panel is open', () => {
    useStore.setState({ notificationPanelOpen: true });
    useStore.getState().addNotification(baseNotification());
    expect(useStore.getState().notifications[0].read).toBe(true);
    expect(selectUnreadNotificationCount(useStore.getState())).toBe(0);
  });

  it('caps the list at MAX_PERSISTED_NOTIFICATIONS (30), most recent first', () => {
    for (let i = 0; i < 35; i++) {
      useStore.getState().addNotification(baseNotification({ ticker: `T${i}` }));
    }
    const list = useStore.getState().notifications;
    expect(list).toHaveLength(30);
    // Most recent (T34) is first.
    expect(list[0].data.ticker).toBe('T34');
  });

  it('markNotificationsRead clears the unread count', () => {
    useStore.getState().addNotification(baseNotification());
    useStore.getState().addNotification(baseNotification());
    expect(selectUnreadNotificationCount(useStore.getState())).toBe(2);

    useStore.getState().markNotificationsRead();
    expect(selectUnreadNotificationCount(useStore.getState())).toBe(0);
    expect(useStore.getState().notifications.every((n) => n.read)).toBe(true);
  });

  it('clearAllNotifications empties the list', () => {
    useStore.getState().addNotification(baseNotification());
    useStore.getState().clearAllNotifications();
    expect(useStore.getState().notifications).toEqual([]);
  });
});

describe('notification center persistence', () => {
  /** test/setup.ts replaces localStorage with vi.fn() mocks — feed getItem. */
  function seedStorage(payload: unknown) {
    (window.localStorage.getItem as Mock).mockImplementation((key: string) =>
      key === STORAGE_KEY ? JSON.stringify(payload) : null
    );
  }

  beforeEach(() => {
    vi.resetModules();
  });

  it('rehydrates a persisted notifications array', async () => {
    seedStorage({
      version: 1,
      state: {
        notifications: [
          {
            id: 'n1',
            type: 'trade_executed',
            data: { ticker: '005930', stock_name: '삼성전자', timestamp: new Date().toISOString() },
            receivedAt: new Date().toISOString(),
            read: false,
          },
        ],
      },
    });

    const { useStore: freshStore } = await import('./index');
    const list = freshStore.getState().notifications;
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe('n1');
    expect(list[0].read).toBe(false);
  });

  it('defensively bounds an oversized persisted payload to the cap on rehydrate', async () => {
    const oversized = Array.from({ length: 40 }, (_, i) => ({
      id: `n${i}`,
      type: 'trade_executed',
      data: { ticker: `T${i}`, stock_name: '삼성전자', timestamp: new Date().toISOString() },
      receivedAt: new Date().toISOString(),
      read: false,
    }));
    seedStorage({ version: 1, state: { notifications: oversized } });

    const { useStore: freshStore } = await import('./index');
    expect(freshStore.getState().notifications).toHaveLength(30);
  });

  it('defaults to an empty list when nothing was persisted', async () => {
    seedStorage({ version: 1, state: {} });
    const { useStore: freshStore } = await import('./index');
    expect(freshStore.getState().notifications).toEqual([]);
  });
});
