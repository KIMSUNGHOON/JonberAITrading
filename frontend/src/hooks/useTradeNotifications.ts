/**
 * Trade Notifications WebSocket Hook
 *
 * Provides real-time trade execution notifications via WebSocket.
 * Connects to /ws/trade-notifications endpoint.
 */

import { useEffect, useRef, useCallback, useState } from 'react';

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

  const wsRef = useRef<WebSocket | null>(null);
  const pingIntervalRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isClosingRef = useRef(false);

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

  const getWebSocketUrl = useCallback(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = import.meta.env.VITE_WS_URL || `${wsProtocol}//${window.location.host}`;
    return `${wsHost}/ws/trade-notifications`;
  }, []);

  const startPingInterval = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
    }
    pingIntervalRef.current = window.setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, 25000);
  }, []);

  const stopPingInterval = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
  }, []);

  const handleMessage = useCallback((event: MessageEvent) => {
    if (event.data === 'pong') return;

    try {
      const message = JSON.parse(event.data);

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

  const handleReconnect = useCallback(() => {
    const maxAttempts = 10;
    const baseDelay = 1000;

    if (reconnectAttemptsRef.current >= maxAttempts) {
      console.error('[TradeNotifications] Max reconnection attempts reached');
      return;
    }

    const delay = Math.min(baseDelay * Math.pow(2, reconnectAttemptsRef.current), 30000);
    console.log(`[TradeNotifications] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current + 1})`);

    setTimeout(() => {
      reconnectAttemptsRef.current++;
      connect();
    }, delay);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      console.warn('[TradeNotifications] Already connected');
      return;
    }

    isClosingRef.current = false;
    const url = getWebSocketUrl();
    console.log('[TradeNotifications] Connecting to:', url);

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[TradeNotifications] Connected');
        reconnectAttemptsRef.current = 0;
        setIsConnected(true);
        startPingInterval();
        onConnectRef.current?.();
      };

      ws.onclose = (event) => {
        console.log('[TradeNotifications] Disconnected:', event.code, event.reason);
        stopPingInterval();
        setIsConnected(false);
        onDisconnectRef.current?.();

        if (!isClosingRef.current) {
          handleReconnect();
        }
      };

      ws.onerror = (error) => {
        console.error('[TradeNotifications] Error:', error);
      };

      ws.onmessage = handleMessage;
    } catch (error) {
      console.error('[TradeNotifications] Connection error:', error);
      handleReconnect();
    }
  }, [getWebSocketUrl, startPingInterval, stopPingInterval, handleMessage, handleReconnect]);

  const disconnect = useCallback(() => {
    isClosingRef.current = true;
    stopPingInterval();

    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }
    setIsConnected(false);
  }, [stopPingInterval]);

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
