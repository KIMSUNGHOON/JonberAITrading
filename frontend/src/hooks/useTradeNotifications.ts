/**
 * Trade Notifications WebSocket Hook
 *
 * Provides real-time trade execution notifications via WebSocket.
 * Connects to /ws/trade-notifications endpoint.
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { ManagedSocket } from '@/api/wsCore';

// -------------------------------------------
// Types
// -------------------------------------------

export type TradeNotificationType =
  | 'trade_executed'
  | 'trade_queued'
  | 'trade_rejected'
  | 'watch_added'
  | 'stop_loss_triggered'
  | 'take_profit_triggered'
  | 'eod_summary';

export interface TradeNotification {
  type: TradeNotificationType;
  data: {
    // eod_summary (E3-5) carries no ticker/position -- it's an account-wide
    // broadcast (see broadcast_eod_summary in app/api/routes/websocket.py),
    // so these two are optional rather than the historical "always present"
    // assumption of the other 6 types.
    ticker?: string;
    stock_name?: string;
    action?: string;
    quantity?: number;
    price?: number;
    total_amount?: number;
    queue_position?: number;
    expected_execution?: string;
    reason?: string;
    signal?: string;
    confidence?: number;
    current_price?: number;
    trigger_price?: number;
    target_price?: number;
    pnl?: number;
    pnl_percent?: number;
    session_id?: string;
    // eod_summary-only fields (E3-5). See broadcast_eod_summary's FE
    // contract docstring for the exact shape.
    trade_date?: string;
    headline?: string;
    has_narrative?: boolean;
    timestamp: string;
  };
}

/**
 * Single source of truth for "every known TradeNotificationType" — the WS
 * dispatch allowlist in `handleMessage` below consumes this array instead of
 * hardcoding a second, independently-maintained list. Before this fix the
 * two lists could silently drift apart: the type union type-checks on its
 * own, so adding an 8th type to `TradeNotificationType` without also
 * remembering to touch the allowlist compiled cleanly while silently
 * dropping every real WS frame of the new type (exactly what happened with
 * `eod_summary` during E3-5 review).
 *
 * `as const satisfies readonly TradeNotificationType[]` keeps each element's
 * literal type (needed for the exhaustiveness check right below) while still
 * verifying every element is a valid TradeNotificationType.
 */
export const ALL_NOTIFICATION_TYPES = [
  'trade_executed',
  'trade_queued',
  'trade_rejected',
  'watch_added',
  'stop_loss_triggered',
  'take_profit_triggered',
  'eod_summary',
] as const satisfies readonly TradeNotificationType[];

// Compile-time drift guard, the OTHER direction from the `satisfies` above:
// catches a new TradeNotificationType member that was never added to
// ALL_NOTIFICATION_TYPES. `_MissingTypes` is `never` iff every union member
// is covered; the `[X] extends [never]` tuple wrapping avoids TS's
// distributive-conditional-over-never special case (a naked
// `X extends never ? ... : ...` always collapses to `never` when X IS
// `never`, which would defeat this check). If a type ever goes missing,
// `_ExhaustivenessCheck` resolves to a descriptive tuple instead of `true`,
// and the `const` assignment below fails to compile.
type _MissingNotificationTypes = Exclude<TradeNotificationType, (typeof ALL_NOTIFICATION_TYPES)[number]>;
type _ExhaustivenessCheck = [_MissingNotificationTypes] extends [never]
  ? true
  : ['ALL_NOTIFICATION_TYPES is missing member(s) of TradeNotificationType:', _MissingNotificationTypes];
// Exported (not just a bare local) so tsc's noUnusedLocals doesn't flag this
// compile-time-only assertion as dead code — the value is always literally
// `true` at runtime; its only job is to fail `tsc --noEmit` if the type
// above ever resolves to the "missing member" branch.
export const ALL_NOTIFICATION_TYPES_ARE_EXHAUSTIVE: _ExhaustivenessCheck = true;

export interface UseTradeNotificationsOptions {
  onNotification?: (notification: TradeNotification) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  autoConnect?: boolean;
}

export interface UseTradeNotificationsReturn {
  isConnected: boolean;
  notifications: TradeNotification[];
  connect: () => void;
  disconnect: () => void;
  clearNotifications: () => void;
}

// -------------------------------------------
// Hook Implementation
// -------------------------------------------

export function useTradeNotifications(
  options: UseTradeNotificationsOptions = {}
): UseTradeNotificationsReturn {
  const {
    onNotification,
    onConnect,
    onDisconnect,
    autoConnect = true,
  } = options;

  const socketRef = useRef<ManagedSocket | null>(null);

  const [isConnected, setIsConnected] = useState(false);
  const [notifications, setNotifications] = useState<TradeNotification[]>([]);

  // Store latest callbacks in refs to avoid reconnection on callback changes
  const onNotificationRef = useRef(onNotification);
  const onConnectRef = useRef(onConnect);
  const onDisconnectRef = useRef(onDisconnect);

  useEffect(() => {
    onNotificationRef.current = onNotification;
    onConnectRef.current = onConnect;
    onDisconnectRef.current = onDisconnect;
  }, [onNotification, onConnect, onDisconnect]);

  // Heartbeat replies are swallowed by the core.
  const handleMessage = useCallback((raw: string) => {
    try {
      const message = JSON.parse(raw);

      // Skip heartbeat and connected messages
      if (message.type === 'heartbeat' || message.type === 'connected') {
        return;
      }

      // Handle trade notification types — consumes the shared
      // ALL_NOTIFICATION_TYPES constant (see its docstring above) rather
      // than a second hardcoded list, so this allowlist can't drift out of
      // sync with TradeNotificationType again.
      if (ALL_NOTIFICATION_TYPES.includes(message.type)) {
        const notification: TradeNotification = {
          type: message.type,
          data: message.data,
        };

        setNotifications((prev) => [notification, ...prev].slice(0, 50)); // Keep last 50
        onNotificationRef.current?.(notification);
      }
    } catch (error) {
      console.error('[TradeNotifications] Error parsing message:', error);
    }
  }, []);

  const connect = useCallback(() => {
    if (socketRef.current?.isConnected()) {
      console.warn('[TradeNotifications] Already connected');
      return;
    }

    // Drop any stale socket (e.g. one still backing off) before replacing it.
    socketRef.current?.disconnect();

    // Policy values preserved from the pre-core implementation:
    // max 10 attempts, 1s base delay, 30s backoff cap, 25s heartbeat.
    const socket = new ManagedSocket({
      path: '/ws/trade-notifications',
      label: 'TradeNotifications',
      maxReconnectAttempts: 10,
      baseReconnectDelayMs: 1000,
      reconnectCapMs: 30000,
      pingIntervalMs: 25000,
      onOpen: () => {
        setIsConnected(true);
        onConnectRef.current?.();
      },
      onClose: () => {
        setIsConnected(false);
        onDisconnectRef.current?.();
      },
      onMessage: handleMessage,
    });

    socketRef.current = socket;
    socket.connect();
  }, [handleMessage]);

  const disconnect = useCallback(() => {
    socketRef.current?.disconnect();
    socketRef.current = null;
    setIsConnected(false);
  }, []);

  const clearNotifications = useCallback(() => {
    setNotifications([]);
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [autoConnect]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    isConnected,
    notifications,
    connect,
    disconnect,
    clearNotifications,
  };
}

// -------------------------------------------
// Notification Formatting Helpers
// -------------------------------------------

export function formatNotificationMessage(notification: TradeNotification): string {
  const { type, data } = notification;
  const name = data.stock_name || data.ticker;

  switch (type) {
    case 'trade_executed':
      return `${data.action} ${name}: ${data.quantity}주 @ ${data.price?.toLocaleString()}원`;

    case 'trade_queued':
      return `${data.action} ${name}: ${data.quantity}주 대기열 추가`;

    case 'trade_rejected':
      return `${name} 거래 거부${data.reason ? `: ${data.reason}` : ''}`;

    case 'watch_added':
      return `${name} 관심종목 추가 (신호: ${data.signal}, 신뢰도: ${((data.confidence || 0) * 100).toFixed(0)}%)`;

    case 'stop_loss_triggered':
      return `${name} 손절 발동 @ ${data.trigger_price?.toLocaleString()}원 (손실: ${data.pnl_percent?.toFixed(1)}%)`;

    case 'take_profit_triggered':
      return `${name} 익절 발동 @ ${data.trigger_price?.toLocaleString()}원 (수익: ${data.pnl_percent?.toFixed(1)}%)`;

    case 'eod_summary':
      // 계정 단위 브로드캐스트 -- ticker/stock_name이 없으므로 위 `name`은
      // 쓰지 않는다. 제목("장마감 요약")+본문(headline)을 한 줄로 합성.
      return `장마감 요약${data.trade_date ? ` (${data.trade_date})` : ''}: ${data.headline ?? '데이터 없음'}`;

    default:
      return `${name}: 알림`;
  }
}

export function getNotificationSeverity(
  type: TradeNotificationType
): 'success' | 'warning' | 'error' | 'info' {
  switch (type) {
    case 'trade_executed':
    case 'take_profit_triggered':
      return 'success';

    case 'trade_queued':
    case 'watch_added':
      return 'info';

    case 'stop_loss_triggered':
    case 'trade_rejected':
      return 'warning';

    case 'eod_summary':
      return 'info';

    default:
      return 'info';
  }
}
