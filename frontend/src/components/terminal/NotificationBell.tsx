/**
 * NotificationBell — the terminal shell's Bell icon, unread badge, and the
 * notification-center dropdown (P1-3).
 *
 * Keeps ONE persistent /ws/trade-notifications subscription alive for as
 * long as the shell is mounted (i.e. the whole app session), capturing every
 * notification into the Zustand store regardless of whether the dropdown is
 * open. That's the point: a trade fired while nobody was watching still
 * shows up as unread afterward, and the bounded history survives a refresh
 * (see store/index.ts `notifications` + partialize).
 */
import { Bell } from 'lucide-react';
import { useStore } from '@/store';
import { useTradeNotifications } from '@/hooks/useTradeNotifications';
import { InlineTradeNotifications } from '@/components/ui/TradeNotificationToast';

export function NotificationBell() {
  const notificationPanelOpen = useStore((s) => s.notificationPanelOpen);
  const setNotificationPanelOpen = useStore((s) => s.setNotificationPanelOpen);
  const markNotificationsRead = useStore((s) => s.markNotificationsRead);
  const addNotification = useStore((s) => s.addNotification);
  const unreadCount = useStore((s) => s.notifications.reduce((c, n) => (n.read ? c : c + 1), 0));

  useTradeNotifications({ autoConnect: true, onNotification: addNotification });

  const toggle = () => {
    const next = !notificationPanelOpen;
    setNotificationPanelOpen(next);
    if (next) markNotificationsRead();
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={toggle}
        title="Notifications"
        aria-label="Notifications"
        className="relative text-muted hover:text-ink p-1"
      >
        <Bell size={15} />
        {unreadCount > 0 && (
          <span
            data-testid="notification-badge"
            className="absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] px-[3px] rounded-full bg-down text-canvas text-[9px] leading-[14px] text-center font-bold"
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {notificationPanelOpen && (
        <>
          {/* Click-outside-to-close backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setNotificationPanelOpen(false)}
            aria-hidden="true"
          />
          <div
            role="dialog"
            aria-label="Notifications"
            className="absolute right-0 top-full mt-1 w-80 max-h-96 overflow-y-auto bg-card border border-hairline rounded shadow-lg z-50 p-3"
          >
            <InlineTradeNotifications maxItems={20} />
          </div>
        </>
      )}
    </div>
  );
}
