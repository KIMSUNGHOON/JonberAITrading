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
          message.type !== 'complete') {
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
// Ticker WebSocket Client (Real-time Price Updates)
// -------------------------------------------

export interface TickerData {
  type: 'ticker';
  market: string;
  trade_price: number;
  change: 'RISE' | 'EVEN' | 'FALL';
  change_rate: number;
  change_price: number;
  high_price: number;
  low_price: number;
  acc_trade_volume_24h: number;
  acc_trade_price_24h: number;
  trade_timestamp: number;
  stream_type: 'SNAPSHOT' | 'REALTIME';
}

export interface TickerWebSocketHandlers {
  onTicker?: (ticker: TickerData) => void;
  onSubscribed?: (markets: string[]) => void;
  onUnsubscribed?: (markets: string[]) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event | string) => void;
}

/**
 * WebSocket client for real-time ticker data from Upbit.
 *
 * Supports multiple subscribers with callback-based architecture.
 * The WebSocket stays connected as long as there are active subscribers
 * or until explicitly closed.
 *
 * Usage:
 *   const ws = getTickerWebSocket();
 *   const unsubscribe = ws.addTickerCallback(['KRW-BTC'], (data) => console.log(data));
 *   // later...
 *   unsubscribe(); // Remove this callback
 */
export class TickerWebSocket {
  private socket: ManagedSocket;
  private handlers: TickerWebSocketHandlers;
  private pendingSubscriptions: string[] = [];

  // Track subscriptions per market with reference counting
  private marketSubscribers: Map<string, Set<(ticker: TickerData) => void>> = new Map();

  // Debounce unsubscription to prevent rapid subscribe/unsubscribe cycles during page navigation
  private pendingUnsubscriptions: Map<string, number> = new Map();
  private readonly unsubscribeDelay = 150; // ms to wait before actually unsubscribing

  constructor(handlers: TickerWebSocketHandlers = {}) {
    this.handlers = handlers;
    // Policy values preserved from the pre-core implementation:
    // max 10 attempts, 1s base delay, 30s backoff cap, 25s heartbeat.
    this.socket = new ManagedSocket({
      path: '/ws/ticker',
      label: 'TickerWebSocket',
      maxReconnectAttempts: 10,
      baseReconnectDelayMs: 1000,
      reconnectCapMs: 30000,
      pingIntervalMs: 25000,
      onOpen: () => {
        this.handlers.onConnect?.();
        // Subscribe to pending markets
        if (this.pendingSubscriptions.length > 0) {
          this.subscribe(this.pendingSubscriptions);
          this.pendingSubscriptions = [];
        }
      },
      onClose: () => this.handlers.onDisconnect?.(),
      onError: (error) => this.handlers.onError?.(error),
      onMessage: (raw) => this.handleMessage(raw),
    });
  }

  /**
   * Add a ticker callback for specific markets.
   * Returns an unsubscribe function to remove the callback.
   */
  addTickerCallback(
    markets: string[],
    callback: (ticker: TickerData) => void
  ): () => void {
    const normalizedMarkets = markets.map(m => m.toUpperCase());
    const newMarkets: string[] = [];

    for (const market of normalizedMarkets) {
      // Cancel any pending unsubscription for this market
      const pendingTimeout = this.pendingUnsubscriptions.get(market);
      if (pendingTimeout) {
        clearTimeout(pendingTimeout);
        this.pendingUnsubscriptions.delete(market);
      }

      if (!this.marketSubscribers.has(market)) {
        this.marketSubscribers.set(market, new Set());
        newMarkets.push(market);
      }
      this.marketSubscribers.get(market)!.add(callback);
    }

    // Subscribe to new markets
    if (newMarkets.length > 0) {
      this.subscribe(newMarkets);
    }

    // Return unsubscribe function
    return () => {
      for (const market of normalizedMarkets) {
        const subscribers = this.marketSubscribers.get(market);
        if (subscribers) {
          subscribers.delete(callback);
          // Only schedule unsubscription if no more callbacks
          if (subscribers.size === 0) {
            this.marketSubscribers.delete(market);
            // Debounce the unsubscription to prevent thrashing during page navigation
            this.scheduleUnsubscribe(market);
          }
        }
      }
    };
  }

  /**
   * Schedule a debounced unsubscription for a market.
   * If a new subscription comes in before the delay, the unsubscription is cancelled.
   */
  private scheduleUnsubscribe(market: string): void {
    // Cancel any existing pending unsubscription for this market
    const existingTimeout = this.pendingUnsubscriptions.get(market);
    if (existingTimeout) {
      clearTimeout(existingTimeout);
    }

    // Schedule the unsubscription
    const timeoutId = window.setTimeout(() => {
      this.pendingUnsubscriptions.delete(market);
      // Only unsubscribe if still no subscribers
      if (!this.marketSubscribers.has(market)) {
        this.unsubscribe([market]);
      }
    }, this.unsubscribeDelay);

    this.pendingUnsubscriptions.set(market, timeoutId);
  }

  /**
   * Get the number of active subscribers for a market.
   */
  getSubscriberCount(market: string): number {
    return this.marketSubscribers.get(market.toUpperCase())?.size || 0;
  }

  /**
   * Check if there are any active subscriptions.
   */
  hasActiveSubscriptions(): boolean {
    return this.marketSubscribers.size > 0;
  }

  /**
   * Connect to WebSocket server.
   */
  connect(): void {
    this.socket.connect();
  }

  /**
   * Handle incoming WebSocket messages (heartbeat replies already swallowed
   * by the core).
   */
  private handleMessage(raw: string): void {
    try {
      const message = JSON.parse(raw);

      switch (message.type) {
        case 'ticker': {
          const ticker = message as TickerData;
          // Call all registered callbacks for this market
          const subscribers = this.marketSubscribers.get(ticker.market);
          if (subscribers) {
            for (const callback of subscribers) {
              try {
                callback(ticker);
              } catch (err) {
                console.error('Ticker callback error:', err);
              }
            }
          }
          // Also call the legacy handler if set
          this.handlers.onTicker?.(ticker);
          break;
        }

        case 'subscribed':
          this.handlers.onSubscribed?.(message.markets);
          break;

        case 'unsubscribed':
          this.handlers.onUnsubscribed?.(message.markets);
          break;

        case 'heartbeat':
          // Server heartbeat, ignore
          break;

        case 'error':
          console.error('Ticker error:', message.message);
          this.handlers.onError?.(message.message);
          break;

        default:
          console.log('Unknown ticker message type:', message.type);
      }
    } catch (error) {
      console.error('Error parsing ticker message:', error);
    }
  }

  /**
   * Subscribe to market tickers.
   */
  subscribe(markets: string[]): void {
    if (!markets.length) return;

    const payload = JSON.stringify({
      action: 'subscribe',
      markets: markets.map(m => m.toUpperCase()),
    });
    if (!this.socket.send(payload)) {
      // Queue for when connected
      this.pendingSubscriptions.push(...markets);
    }
  }

  /**
   * Unsubscribe from market tickers.
   */
  unsubscribe(markets: string[]): void {
    if (!markets.length) return;

    this.socket.send(JSON.stringify({
      action: 'unsubscribe',
      markets: markets.map(m => m.toUpperCase()),
    }));

    // Remove from pending
    this.pendingSubscriptions = this.pendingSubscriptions.filter(
      m => !markets.includes(m.toUpperCase())
    );
  }

  /**
   * Disconnect from WebSocket server.
   */
  disconnect(): void {
    // Clear all pending unsubscriptions
    for (const timeoutId of this.pendingUnsubscriptions.values()) {
      clearTimeout(timeoutId);
    }
    this.pendingUnsubscriptions.clear();

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
  setHandlers(handlers: Partial<TickerWebSocketHandlers>): void {
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

// Singleton instance for shared ticker connection
let tickerWebSocketInstance: TickerWebSocket | null = null;

/**
 * Get or create the shared ticker WebSocket instance.
 */
export function getTickerWebSocket(): TickerWebSocket {
  if (!tickerWebSocketInstance) {
    tickerWebSocketInstance = new TickerWebSocket();
  }
  return tickerWebSocketInstance;
}

/**
 * Explicitly close the ticker WebSocket.
 * Only call this on logout or when the user explicitly wants to disconnect.
 */
export function closeTickerWebSocket(): void {
  if (tickerWebSocketInstance) {
    tickerWebSocketInstance.disconnect();
    tickerWebSocketInstance = null;
  }
}
