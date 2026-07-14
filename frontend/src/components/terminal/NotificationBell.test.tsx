import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NotificationBell } from './NotificationBell';

// Controlled store: `useStore` runs the real selector against `mockState`
// (mirrors the convention in OrderTicketRail.test.tsx).
let mockState: Record<string, unknown>;
vi.mock('@/store', async () => {
  const actual = await vi.importActual<any>('@/store');
  return {
    ...actual,
    useStore: (selector: (s: any) => unknown) => selector(mockState),
  };
});

// InlineTradeNotifications also calls useTradeNotifications (for its own
// connection badge) — the same mock backs both call sites. Keep the real
// formatNotificationMessage/getNotificationSeverity helpers (also imported
// by InlineTradeNotifications) so its render logic still works.
const useTradeNotificationsMock = vi.fn((_opts?: unknown) => ({ isConnected: true }));
vi.mock('@/hooks/useTradeNotifications', async () => {
  const actual = await vi.importActual<object>('@/hooks/useTradeNotifications');
  return {
    ...actual,
    useTradeNotifications: (opts?: unknown) => useTradeNotificationsMock(opts),
  };
});

function notif(id: string, read: boolean, ticker = '005930') {
  return {
    id,
    read,
    type: 'trade_executed' as const,
    data: {
      ticker,
      stock_name: '삼성전자',
      action: 'BUY',
      quantity: 1,
      price: 1000,
      timestamp: new Date().toISOString(),
    },
    receivedAt: new Date().toISOString(),
  };
}

beforeEach(() => {
  useTradeNotificationsMock.mockClear();
  mockState = {
    notificationPanelOpen: false,
    notifications: [] as unknown[],
    setNotificationPanelOpen: vi.fn(),
    markNotificationsRead: vi.fn(),
    addNotification: vi.fn(),
    clearAllNotifications: vi.fn(),
  };
});

describe('NotificationBell — unread badge', () => {
  it('shows no badge when there are no unread notifications', () => {
    render(<NotificationBell />);
    expect(screen.queryByTestId('notification-badge')).not.toBeInTheDocument();
  });

  it('reflects the unread count (ignores already-read items)', () => {
    mockState.notifications = [notif('1', false), notif('2', false), notif('3', true)];
    render(<NotificationBell />);
    expect(screen.getByTestId('notification-badge')).toHaveTextContent('2');
  });

  it('caps the displayed count at 99+', () => {
    mockState.notifications = Array.from({ length: 120 }, (_, i) => notif(String(i), false));
    render(<NotificationBell />);
    expect(screen.getByTestId('notification-badge')).toHaveTextContent('99+');
  });
});

describe('NotificationBell — opening the panel', () => {
  it('clicking the bell opens the panel and marks notifications read', () => {
    mockState.notifications = [notif('1', false)];
    render(<NotificationBell />);

    fireEvent.click(screen.getByRole('button', { name: /notifications/i }));

    expect(mockState.setNotificationPanelOpen).toHaveBeenCalledWith(true);
    expect(mockState.markNotificationsRead).toHaveBeenCalledTimes(1);
  });

  it('clicking the bell again while open closes it (does not mark read again)', () => {
    mockState.notificationPanelOpen = true;
    render(<NotificationBell />);

    fireEvent.click(screen.getByRole('button', { name: /notifications/i }));

    expect(mockState.setNotificationPanelOpen).toHaveBeenCalledWith(false);
    expect(mockState.markNotificationsRead).not.toHaveBeenCalled();
  });

  it('renders InlineTradeNotifications content when the panel is open', () => {
    mockState.notificationPanelOpen = true;
    mockState.notifications = [notif('1', false)];
    render(<NotificationBell />);

    expect(screen.getByRole('dialog', { name: /notifications/i })).toBeInTheDocument();
    expect(screen.getByText(/BUY 삼성전자/)).toBeInTheDocument();
  });

  it('renders the empty state inside the panel when there are no notifications', () => {
    mockState.notificationPanelOpen = true;
    mockState.notifications = [];
    render(<NotificationBell />);
    expect(screen.getByText('알림 없음')).toBeInTheDocument();
  });

  it('does not render the panel at all when closed', () => {
    mockState.notificationPanelOpen = false;
    render(<NotificationBell />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
