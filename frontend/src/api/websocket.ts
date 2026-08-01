/**
 * WebSocket Client for Real-time Updates
 *
 * Handles:
 * - Reasoning log streaming
 * - Status updates
 * - Trade proposal notifications
 * - Position updates
 */

import type { DetailedAnalysisResults } from '@/types';
import { ManagedSocket } from './wsCore';
import type { ConnectionState } from './wsCore';

// -------------------------------------------
// Types
// -------------------------------------------

export type WebSocketMessageType =
  | 'reasoning'
  | 'status'
  | 'proposal'
  | 'position'
  | 'complete'
  | 'not_found'
  | 'heartbeat'
  | 'sessions';

// Re-exported for existing consumers; the canonical enum lives in wsCore.
export type { ConnectionState } from './wsCore';

/**
 * Event types for EventEmitter-like pattern
 */
export interface WebSocketEvents {
  reasoning: string;
  status: StatusMessage['data'];
  proposal: ProposalMessage['data'];
  position: PositionMessage['data'];
  complete: CompleteMessage['data'];
  connectionStateChange: ConnectionState;
  error: Event | Error;
}

export interface WebSocketMessage {
  type: WebSocketMessageType;
  data: unknown;
}

export interface ReasoningMessage {
  type: 'reasoning';
  data: string;
}

export interface StatusMessage {
  type: 'status';
  data: {
    status: string;
    stage: string;
    awaiting_approval: boolean;
    // R3 autonomous mode (additive): ISO deadline of the pending auto-approve
    // grace window. Only present while an autonomous approval is pending.
    auto_approve_at?: string;
  };
}

export interface ProposalMessage {
  type: 'proposal';
  data: {
    id: string;
    ticker: string;
    display_name?: string;  // Stock name / Korean name for display
    action: string;
    quantity: number;
    entry_price: number;
    stop_loss: number;
    take_profit: number;
    risk_score: number;
    rationale: string;
  };
}

export interface PositionMessage {
  type: 'position';
  data: {
    ticker: string;
    quantity: number;
    entry_price: number;
    current_price: number;
    pnl: number;
    pnl_percent: number;
  };
}

export interface CompleteMessage {
  type: 'complete';
  data: {
    status: string;
    error?: string;
    completed_at?: string;
    analysis_results?: DetailedAnalysisResults;
    trade_proposal?: {
      id: string;
      ticker: string;
      display_name?: string;  // Stock name (종목명) — backend _serialize_proposal sends it
      action: string;
      quantity: number;
      entry_price: number | null;
      stop_loss: number | null;
      take_profit: number | null;
      risk_score: number;
      rationale: string;
      bull_case?: string;
      bear_case?: string;
    };
    reasoning_summary?: string;
  };
}

// -------------------------------------------
// Event Handlers Type
// -------------------------------------------

export interface WebSocketHandlers {
  onReasoning?: (entry: string) => void;
  onStatus?: (status: StatusMessage['data']) => void;
  onProposal?: (proposal: ProposalMessage['data']) => void;
  onPosition?: (position: PositionMessage['data']) => void;
  onComplete?: (data: CompleteMessage['data']) => void;
  onNotFound?: () => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
  onConnectionStateChange?: (state: ConnectionState) => void;
}

// -------------------------------------------
// WebSocket Client Class
// -------------------------------------------

export class TradingWebSocket {
  private socket: ManagedSocket;
  private handlers: WebSocketHandlers;
  private messageBuffer: WebSocketMessage[] = [];

  constructor(sessionId: string, handlers: WebSocketHandlers = {}) {
    this.handlers = handlers;
    // Reconnect budget: 10 attempts, 1s base delay, capped at 30s, 30s
    // heartbeat. The session stream carries proposal/removal pushes, so it
    // must outlast a backend restart — the old 5-attempt/uncapped policy gave
    // up after ~31s, less than a cold uvicorn start, leaving stale HITL cards
    // on screen until a manual refresh. ManagedSocket also revives it on the
    // 'online' event and tab-visibility regain.
    this.socket = new ManagedSocket({
      path: `/ws/session/${sessionId}`,
      label: 'WebSocket',
      maxReconnectAttempts: 10,
      baseReconnectDelayMs: 1000,
      reconnectCapMs: 30000,
      pingIntervalMs: 30000,
      onOpen: () => {
        this.flushMessageBuffer();
        this.handlers.onConnect?.();
      },
      onClose: () => this.handlers.onDisconnect?.(),
      onError: (error) => this.handlers.onError?.(error),
      onStateChange: (state) => this.handlers.onConnectionStateChange?.(state),
      onMessage: (raw) => this.handleMessage(raw),
    });
  }

  /**
   * Get current connection state.
   */
  get connectionState(): ConnectionState {
    return this.socket.state;
  }

  /**
   * Connect to WebSocket server.
   */
  connect(): void {
    this.socket.connect();
  }

  /**
   * Flush buffered messages (after reconnection).
   */
  private flushMessageBuffer(): void {
    if (this.messageBuffer.length > 0) {
      console.log(`[WebSocket] Flushing ${this.messageBuffer.length} buffered messages`);
      for (const message of this.messageBuffer) {
        this.dispatchMessage(message);
      }
      this.messageBuffer = [];
    }
  }

  /**
   * Dispatch a message to appropriate handlers.
   */
  private dispatchMessage(message: WebSocketMessage): void {
    switch (message.type) {
      case 'reasoning':
        this.handlers.onReasoning?.(message.data as string);
        break;
      case 'status':
        this.handlers.onStatus?.(message.data as StatusMessage['data']);
        break;
      case 'proposal':
        this.handlers.onProposal?.(message.data as ProposalMessage['data']);
        break;
      case 'position':
        this.handlers.onPosition?.(message.data as PositionMessage['data']);
        break;
      case 'complete':
        this.handlers.onComplete?.(message.data as CompleteMessage['data']);
        break;
      case 'not_found':
        this.handlers.onNotFound?.();
        break;
    }
  }

  /**
   * Handle incoming WebSocket messages (heartbeat replies already swallowed
   * by the core).
   */
  private handleMessage(raw: string): void {
    try {
      const message: WebSocketMessage = JSON.parse(raw);
      console.log('[WebSocket] Received message:', message.type, message.data);

      if (message.type === 'status') {
        console.log('[WebSocket] Status update - stage:', (message.data as StatusMessage['data']).stage);
      }

      // Dispatch using the unified handler
      this.dispatchMessage(message);

      if (message.type !== 'reasoning' && message.type !== 'status' &&
          message.type !== 'proposal' && message.type !== 'position' &&
          message.type !== 'complete' && message.type !== 'not_found') {
        console.log('Unknown message type:', message.type);
      }
    } catch (error) {
      console.error('Error parsing WebSocket message:', error);
    }
  }

  /**
   * Request current status.
   */
  requestStatus(): void {
    this.socket.send('status');
  }

  /**
   * Disconnect from WebSocket server.
   */
  disconnect(): void {
    this.messageBuffer = []; // Clear any buffered messages
    this.socket.disconnect();
  }

  /**
   * Check if connected.
   */
  isConnected(): boolean {
    return this.socket.isConnected();
  }

  /**
   * Update handlers.
   */
  setHandlers(handlers: Partial<WebSocketHandlers>): void {
    this.handlers = { ...this.handlers, ...handlers };
  }
}

// -------------------------------------------
// WebSocket Manager for Multi-Session Support
// -------------------------------------------

/**
 * Manages multiple WebSocket connections for parallel analysis sessions.
 * Each session gets its own WebSocket connection.
 *
 * Usage:
 *   wsManager.connect(sessionId, handlers);
 *   wsManager.disconnect(sessionId);
 *   wsManager.disconnectAll();
 */
export class WebSocketManager {
  private connections: Map<string, TradingWebSocket> = new Map();
  private maxConnections: number = 5;

  /**
   * Connect to a session WebSocket.
   * If a connection already exists for this session, it will be disconnected first.
   */
  connect(sessionId: string, handlers: WebSocketHandlers): TradingWebSocket {
    // Disconnect existing connection if any
    const existing = this.connections.get(sessionId);
    if (existing) {
      console.log(`[WebSocketManager] Replacing existing connection for session ${sessionId}`);
      existing.disconnect();
      this.connections.delete(sessionId);
    }

    // Check max connections
    if (this.connections.size >= this.maxConnections) {
      console.warn(`[WebSocketManager] Max connections (${this.maxConnections}) reached`);
      // Disconnect oldest idle connection if possible
      const oldestIdle = this.findOldestIdleConnection();
      if (oldestIdle) {
        console.log(`[WebSocketManager] Disconnecting idle session ${oldestIdle}`);
        this.disconnect(oldestIdle);
      }
    }

    const ws = new TradingWebSocket(sessionId, handlers);
    this.connections.set(sessionId, ws);
    ws.connect();
    console.log(`[WebSocketManager] Connected session ${sessionId}, total: ${this.connections.size}`);
    return ws;
  }

  /**
   * Disconnect a specific session WebSocket.
   */
  disconnect(sessionId: string): void {
    const ws = this.connections.get(sessionId);
    if (ws) {
      ws.disconnect();
      this.connections.delete(sessionId);
      console.log(`[WebSocketManager] Disconnected session ${sessionId}, remaining: ${this.connections.size}`);
    }
  }

  /**
   * Disconnect all WebSocket connections.
   */
  disconnectAll(): void {
    console.log(`[WebSocketManager] Disconnecting all ${this.connections.size} connections`);
    for (const [, ws] of this.connections) {
      ws.disconnect();
    }
    this.connections.clear();
  }

  /**
   * Get WebSocket connection for a session.
   */
  get(sessionId: string): TradingWebSocket | undefined {
    return this.connections.get(sessionId);
  }

  /**
   * Check if a session has an active connection.
   */
  has(sessionId: string): boolean {
    return this.connections.has(sessionId);
  }

  /**
   * Check if a session is connected.
   */
  isConnected(sessionId: string): boolean {
    const ws = this.connections.get(sessionId);
    return ws?.isConnected() ?? false;
  }

  /**
   * Get the number of active connections.
   */
  getActiveCount(): number {
    return this.connections.size;
  }

  /**
   * Get all active session IDs.
   */
  getActiveSessionIds(): string[] {
    return Array.from(this.connections.keys());
  }

  /**
   * Get available connection slots.
   */
  getAvailableSlots(): number {
    return Math.max(0, this.maxConnections - this.connections.size);
  }

  /**
   * Set max concurrent connections.
   */
  setMaxConnections(max: number): void {
    this.maxConnections = max;
  }

  /**
   * Find the oldest idle connection (for cleanup when at max capacity).
   * For now, just returns the first one. Could be improved with LRU tracking.
   */
  private findOldestIdleConnection(): string | null {
    for (const [sessionId, ws] of this.connections) {
      if (!ws.isConnected()) {
        return sessionId;
      }
    }
    return null;
  }

  /**
   * Update handlers for a specific session.
   */
  updateHandlers(sessionId: string, handlers: Partial<WebSocketHandlers>): void {
    const ws = this.connections.get(sessionId);
    if (ws) {
      ws.setHandlers(handlers);
    }
  }
}

// Singleton instance for global access
export const wsManager = new WebSocketManager();
