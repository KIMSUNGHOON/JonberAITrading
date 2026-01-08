/**
 * React Hook for Agent Chat WebSocket Connection
 *
 * Manages WebSocket connection for real-time Agent Chat session updates.
 * Automatically connects/disconnects based on sessionId and
 * provides real-time message, status, and decision updates.
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import type {
  AgentChatMessage,
  AgentChatSessionDetail,
  AgentChatSessionStatus,
  AgentChatDecision,
  AgentChatVote,
} from '@/types';

// WebSocket message types from backend
type AgentChatWsMessageType = 'message' | 'status_change' | 'vote' | 'decision' | 'error';

interface AgentChatWsMessage {
  type: AgentChatWsMessageType;
  session_id: string;
  [key: string]: unknown;
}

interface MessageEvent {
  type: 'message';
  session_id: string;
  message: AgentChatMessage;
}

interface StatusChangeEvent {
  type: 'status_change';
  session_id: string;
  status: AgentChatSessionStatus;
  session: AgentChatSessionDetail;
}

interface VoteEvent {
  type: 'vote';
  session_id: string;
  vote: AgentChatVote;
}

interface DecisionEvent {
  type: 'decision';
  session_id: string;
  decision: AgentChatDecision;
}

interface ErrorEvent {
  type: 'error';
  session_id: string;
  error: string;
}

export interface UseAgentChatWebSocketOptions {
  /** Session ID to connect to */
  sessionId: string | null;
  /** Whether to auto-connect when sessionId is provided */
  autoConnect?: boolean;
  /** Callback when new message is received */
  onMessage?: (message: AgentChatMessage) => void;
  /** Callback when session status changes */
  onStatusChange?: (status: AgentChatSessionStatus, session: AgentChatSessionDetail) => void;
  /** Callback when vote is received */
  onVote?: (vote: AgentChatVote) => void;
  /** Callback when decision is made */
  onDecision?: (decision: AgentChatDecision) => void;
  /** Callback when error occurs */
  onError?: (error: string) => void;
  /** Callback when connected */
  onConnect?: () => void;
  /** Callback when disconnected */
  onDisconnect?: () => void;
}

export interface UseAgentChatWebSocketResult {
  /** Whether the WebSocket is currently connected */
  isConnected: boolean;
  /** Connection state */
  connectionState: 'disconnected' | 'connecting' | 'connected' | 'reconnecting';
  /** Manually connect to the WebSocket */
  connect: () => void;
  /** Manually disconnect from the WebSocket */
  disconnect: () => void;
  /** Last error message */
  lastError: string | null;
}

/**
 * Get WebSocket URL for Agent Chat session.
 */
function getAgentChatWebSocketUrl(sessionId: string): string {
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsHost = import.meta.env.VITE_WS_URL || `${wsProtocol}//${window.location.host}`;
  // Agent Chat WebSocket endpoint
  return `${wsHost}/api/agent-chat/ws/${sessionId}`;
}

/**
 * Hook to manage WebSocket connection for an Agent Chat session.
 *
 * @example
 * ```tsx
 * const { isConnected } = useAgentChatWebSocket({
 *   sessionId: 'abc-123',
 *   onMessage: (msg) => setMessages(prev => [...prev, msg]),
 *   onStatusChange: (status) => setSessionStatus(status),
 * });
 * ```
 */
export function useAgentChatWebSocket({
  sessionId,
  autoConnect = true,
  onMessage,
  onStatusChange,
  onVote,
  onDecision,
  onError,
  onConnect,
  onDisconnect,
}: UseAgentChatWebSocketOptions): UseAgentChatWebSocketResult {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pingIntervalRef = useRef<number | null>(null);
  const isClosingRef = useRef(false);
  const connectedSessionRef = useRef<string | null>(null);

  const [connectionState, setConnectionState] = useState<'disconnected' | 'connecting' | 'connected' | 'reconnecting'>('disconnected');
  const [lastError, setLastError] = useState<string | null>(null);

  const maxReconnectAttempts = 5;
  const reconnectDelay = 1000;
  const pingInterval = 30000;

  // Start ping interval
  const startPingInterval = useCallback(() => {
    stopPingInterval();
    pingIntervalRef.current = window.setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, pingInterval);
  }, []);

  // Stop ping interval
  const stopPingInterval = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
  }, []);

  // Handle incoming messages
  const handleMessage = useCallback((event: globalThis.MessageEvent) => {
    try {
      // Handle pong response
      if (event.data === 'pong') {
        return;
      }

      const data: AgentChatWsMessage = JSON.parse(event.data);
      console.log('[AgentChatWebSocket] Received:', data.type);

      switch (data.type) {
        case 'message': {
          const msgEvent = data as unknown as MessageEvent;
          onMessage?.(msgEvent.message);
          break;
        }
        case 'status_change': {
          const statusEvent = data as unknown as StatusChangeEvent;
          onStatusChange?.(statusEvent.status, statusEvent.session);
          break;
        }
        case 'vote': {
          const voteEvent = data as unknown as VoteEvent;
          onVote?.(voteEvent.vote);
          break;
        }
        case 'decision': {
          const decisionEvent = data as unknown as DecisionEvent;
          onDecision?.(decisionEvent.decision);
          break;
        }
        case 'error': {
          const errorEvent = data as unknown as ErrorEvent;
          setLastError(errorEvent.error);
          onError?.(errorEvent.error);
          break;
        }
        default:
          console.log('[AgentChatWebSocket] Unknown message type:', data.type);
      }
    } catch (error) {
      console.error('[AgentChatWebSocket] Error parsing message:', error);
    }
  }, [onMessage, onStatusChange, onVote, onDecision, onError]);

  // Handle reconnection
  const handleReconnect = useCallback(() => {
    if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
      console.error('[AgentChatWebSocket] Max reconnection attempts reached');
      setConnectionState('disconnected');
      return;
    }

    setConnectionState('reconnecting');
    const delay = reconnectDelay * Math.pow(2, reconnectAttemptsRef.current);
    console.log(`[AgentChatWebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current + 1})`);

    reconnectTimeoutRef.current = window.setTimeout(() => {
      reconnectAttemptsRef.current++;
      if (connectedSessionRef.current) {
        connectToSession(connectedSessionRef.current);
      }
    }, delay);
  }, []);

  // Connect to session
  const connectToSession = useCallback((sid: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      console.warn('[AgentChatWebSocket] Already connected');
      return;
    }

    isClosingRef.current = false;
    const url = getAgentChatWebSocketUrl(sid);
    console.log('[AgentChatWebSocket] Connecting to:', url);
    setConnectionState('connecting');

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        console.log('[AgentChatWebSocket] Connected');
        reconnectAttemptsRef.current = 0;
        setConnectionState('connected');
        setLastError(null);
        startPingInterval();
        onConnect?.();
      };

      ws.onclose = (event) => {
        console.log('[AgentChatWebSocket] Closed:', event.code, event.reason);
        stopPingInterval();
        setConnectionState('disconnected');
        onDisconnect?.();

        if (!isClosingRef.current && connectedSessionRef.current) {
          handleReconnect();
        }
      };

      ws.onerror = (error) => {
        console.error('[AgentChatWebSocket] Error:', error);
        setLastError('WebSocket connection error');
      };

      ws.onmessage = handleMessage;

      wsRef.current = ws;
      connectedSessionRef.current = sid;
    } catch (error) {
      console.error('[AgentChatWebSocket] Connection error:', error);
      setConnectionState('disconnected');
      handleReconnect();
    }
  }, [handleMessage, handleReconnect, startPingInterval, stopPingInterval, onConnect, onDisconnect]);

  // Public connect function
  const connect = useCallback(() => {
    if (!sessionId) return;
    connectToSession(sessionId);
  }, [sessionId, connectToSession]);

  // Public disconnect function
  const disconnect = useCallback(() => {
    isClosingRef.current = true;
    stopPingInterval();

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }

    connectedSessionRef.current = null;
    setConnectionState('disconnected');
  }, [stopPingInterval]);

  // Auto-connect/disconnect effect
  useEffect(() => {
    if (!sessionId || !autoConnect) {
      return;
    }

    // Only connect if sessionId changed
    if (connectedSessionRef.current === sessionId) {
      return;
    }

    // Disconnect from previous session if any
    if (connectedSessionRef.current) {
      disconnect();
    }

    // Connect to new session
    connectToSession(sessionId);

    // Cleanup on unmount
    return () => {
      disconnect();
    };
  }, [sessionId, autoConnect, connectToSession, disconnect]);

  return {
    isConnected: connectionState === 'connected',
    connectionState,
    connect,
    disconnect,
    lastError,
  };
}

export default useAgentChatWebSocket;
