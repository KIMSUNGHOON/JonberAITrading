/**
 * React Hook for Agent Chat WebSocket Connection
 *
 * Manages WebSocket connection for real-time Agent Chat session updates.
 * Automatically connects/disconnects based on sessionId and
 * provides real-time message, status, and decision updates.
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { ManagedSocket } from '@/api/wsCore';
import type { ConnectionState } from '@/api/wsCore';
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
  const socketRef = useRef<ManagedSocket | null>(null);
  const connectedSessionRef = useRef<string | null>(null);

  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [lastError, setLastError] = useState<string | null>(null);

  // Handle incoming messages (heartbeat replies swallowed by the core)
  const handleMessage = useCallback((raw: string) => {
    try {
      const data: AgentChatWsMessage = JSON.parse(raw);
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

  // Connect to session
  const connectToSession = useCallback((sid: string) => {
    if (socketRef.current?.isConnected()) {
      console.warn('[AgentChatWebSocket] Already connected');
      return;
    }

    // Drop any stale socket (e.g. one still backing off) before replacing it.
    socketRef.current?.disconnect();

    // Policy values preserved from the pre-core implementation:
    // max 5 attempts, 1s base delay, UNCAPPED backoff, 30s heartbeat.
    const socket = new ManagedSocket({
      path: `/api/agent-chat/ws/${sid}`,
      label: 'AgentChatWebSocket',
      maxReconnectAttempts: 5,
      baseReconnectDelayMs: 1000,
      reconnectCapMs: null,
      pingIntervalMs: 30000,
      onOpen: () => {
        setLastError(null);
        onConnect?.();
      },
      onClose: () => onDisconnect?.(),
      onError: () => setLastError('WebSocket connection error'),
      onStateChange: setConnectionState,
      onMessage: handleMessage,
    });

    socketRef.current = socket;
    connectedSessionRef.current = sid;
    socket.connect();
  }, [handleMessage, onConnect, onDisconnect]);

  // Public connect function
  const connect = useCallback(() => {
    if (!sessionId) return;
    connectToSession(sessionId);
  }, [sessionId, connectToSession]);

  // Public disconnect function
  const disconnect = useCallback(() => {
    socketRef.current?.disconnect();
    socketRef.current = null;
    connectedSessionRef.current = null;
    setConnectionState('disconnected');
  }, []);

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
