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
  | 'take_profit_triggered';

export interface TradeNotification {
  type: TradeNotificationType;
  data: {
    ticker: string;
    stock_name: string;
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
    timestamp: string;
  };
}

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

      // Handle trade notification types
      const notificationTypes: TradeNotificationType[] = [
        'trade_executed',
        'trade_queued',
        'trade_rejected',
        'watch_added',
        'stop_loss_triggered',
        'take_profit_triggered',
      ];

      if (notificationTypes.includes(message.type)) {
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

    default:
      return 'info';
  }
}
