/**
 * Trade Notification Toast Component
 *
 * Displays real-time trade execution notifications as toast messages.
 * Integrates with useTradeNotifications hook.
 */

import { useEffect, useState, useCallback } from 'react';
import { X, TrendingUp, TrendingDown, Clock, Eye, AlertTriangle, CheckCircle, Wifi, WifiOff } from 'lucide-react';
import {
  useTradeNotifications,
  formatNotificationMessage,
  getNotificationSeverity,
  type TradeNotification,
  type TradeNotificationType,
} from '@/hooks/useTradeNotifications';

// -------------------------------------------
// Types
// -------------------------------------------

interface ToastItem {
  id: string;
  notification: TradeNotification;
  isExiting: boolean;
}

interface TradeNotificationToastProps {
  maxToasts?: number;
  duration?: number; // 0 for persistent
  position?: 'top-right' | 'top-center' | 'bottom-right' | 'bottom-center';
  showConnectionStatus?: boolean;
}

// -------------------------------------------
// Icon Mapping
// -------------------------------------------

const iconMap: Record<TradeNotificationType, typeof TrendingUp> = {
  trade_executed: CheckCircle,
  trade_queued: Clock,
  trade_rejected: AlertTriangle,
  watch_added: Eye,
  stop_loss_triggered: TrendingDown,
  take_profit_triggered: TrendingUp,
};

const severityStyles: Record<'success' | 'warning' | 'error' | 'info', string> = {
  success: 'bg-green-600/95 border-green-500',
  warning: 'bg-amber-600/95 border-amber-500',
  error: 'bg-red-600/95 border-red-500',
  info: 'bg-blue-600/95 border-blue-500',
};

const positionStyles: Record<string, string> = {
  'top-right': 'top-20 right-4',
  'top-center': 'top-20 left-1/2 -translate-x-1/2',
  'bottom-right': 'bottom-4 right-4',
  'bottom-center': 'bottom-4 left-1/2 -translate-x-1/2',
};

// -------------------------------------------
// Toast Item Component
// -------------------------------------------

interface ToastItemProps {
  item: ToastItem;
  onClose: (id: string) => void;
}

function ToastItemComponent({ item, onClose }: ToastItemProps) {
  const { notification, isExiting, id } = item;
  const severity = getNotificationSeverity(notification.type);
  const Icon = iconMap[notification.type];
  const message = formatNotificationMessage(notification);

  // Format timestamp
  const timestamp = new Date(notification.data.timestamp).toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <div
      role="alert"
      aria-live="polite"
      className={`
        flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg border
        text-white min-w-[320px] max-w-[420px]
        transition-all duration-300
        ${severityStyles[severity]}
        ${isExiting ? 'opacity-0 translate-x-4' : 'opacity-100 translate-x-0'}
      `}
    >
      <Icon className="w-5 h-5 flex-shrink-0 mt-0.5" aria-hidden="true" />

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium leading-tight">{message}</p>
        <p className="text-xs text-white/70 mt-1">{timestamp}</p>
      </div>

      <button
        onClick={() => onClose(id)}
        className="p-1 hover:bg-white/20 rounded-lg transition-colors flex-shrink-0"
        aria-label="Close notification"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// -------------------------------------------
// Connection Status Badge
// -------------------------------------------

interface ConnectionBadgeProps {
  isConnected: boolean;
}

function ConnectionBadge({ isConnected }: ConnectionBadgeProps) {
  return (
    <div
      className={`
        flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium
        ${isConnected
          ? 'bg-green-500/20 text-green-400'
          : 'bg-red-500/20 text-red-400'
        }
      `}
    >
      {isConnected ? (
        <>
          <Wifi className="w-3 h-3" />
          <span>실시간 연결</span>
        </>
      ) : (
        <>
          <WifiOff className="w-3 h-3" />
          <span>연결 끊김</span>
        </>
      )}
    </div>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

export function TradeNotificationToast({
  maxToasts = 5,
  duration = 5000,
  position = 'top-right',
  showConnectionStatus = false,
}: TradeNotificationToastProps) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const handleNotification = useCallback((notification: TradeNotification) => {
    const id = `${notification.type}-${notification.data.ticker}-${Date.now()}`;

    setToasts((prev) => {
      // Add new toast at the beginning
      const newToasts = [{ id, notification, isExiting: false }, ...prev];
      // Keep only maxToasts
      return newToasts.slice(0, maxToasts);
    });
  }, [maxToasts]);

  const { isConnected } = useTradeNotifications({
    onNotification: handleNotification,
    autoConnect: true,
  });

  const handleClose = useCallback((id: string) => {
    // Start exit animation
    setToasts((prev) =>
      prev.map((t) => (t.id === id ? { ...t, isExiting: true } : t))
    );

    // Remove after animation
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 300);
  }, []);

  // Auto-dismiss toasts
  useEffect(() => {
    if (duration <= 0) return;

    const timers: number[] = [];

    for (const toast of toasts) {
      if (!toast.isExiting) {
        const timer = window.setTimeout(() => {
          handleClose(toast.id);
        }, duration);
        timers.push(timer);
      }
    }

    return () => {
      for (const timer of timers) {
        clearTimeout(timer);
      }
    };
  }, [toasts, duration, handleClose]);

  return (
    <div className={`fixed z-50 ${positionStyles[position]} flex flex-col gap-2`}>
      {showConnectionStatus && (
        <div className="flex justify-end mb-1">
          <ConnectionBadge isConnected={isConnected} />
        </div>
      )}

      {toasts.map((item, index) => (
        <div
          key={item.id}
          style={{
            transform: `translateY(${index * 4}px)`,
            zIndex: maxToasts - index,
          }}
        >
          <ToastItemComponent item={item} onClose={handleClose} />
        </div>
      ))}
    </div>
  );
}

// -------------------------------------------
// Inline Toast (for embedding in other components)
// -------------------------------------------

interface InlineTradeNotificationsProps {
  maxItems?: number;
}

export function InlineTradeNotifications({ maxItems = 10 }: InlineTradeNotificationsProps) {
  const { notifications, isConnected, clearNotifications } = useTradeNotifications({
    autoConnect: true,
  });

  const displayItems = notifications.slice(0, maxItems);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-400">실시간 알림</span>
          <ConnectionBadge isConnected={isConnected} />
        </div>
        {notifications.length > 0 && (
          <button
            onClick={clearNotifications}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            모두 지우기
          </button>
        )}
      </div>

      {displayItems.length === 0 ? (
        <p className="text-sm text-gray-500 py-4 text-center">알림 없음</p>
      ) : (
        <div className="space-y-1">
          {displayItems.map((notification, index) => {
            const severity = getNotificationSeverity(notification.type);
            const Icon = iconMap[notification.type];
            const message = formatNotificationMessage(notification);
            const timestamp = new Date(notification.data.timestamp).toLocaleTimeString('ko-KR', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            });

            return (
              <div
                key={`${notification.type}-${notification.data.ticker}-${index}`}
                className={`
                  flex items-start gap-2 p-2 rounded-lg text-sm
                  ${severity === 'success' ? 'bg-green-500/10 text-green-400' : ''}
                  ${severity === 'warning' ? 'bg-amber-500/10 text-amber-400' : ''}
                  ${severity === 'error' ? 'bg-red-500/10 text-red-400' : ''}
                  ${severity === 'info' ? 'bg-blue-500/10 text-blue-400' : ''}
                `}
              >
                <Icon className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="leading-tight">{message}</p>
                  <p className="text-xs opacity-60 mt-0.5">{timestamp}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default TradeNotificationToast;
