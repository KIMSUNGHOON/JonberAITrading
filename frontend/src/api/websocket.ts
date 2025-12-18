/**
 * WebSocket Client for Real-time Updates
 *
 * Handles:
 * - Reasoning log streaming
 * - Status updates
 * - Trade proposal notifications
 * - Position updates
 */

import type { TradeProposal, Position, SessionStatus } from '@/types';

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
  };
}

export interface ProposalMessage {
  type: 'proposal';
  data: {
    id: string;
    ticker: string;
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
}

// -------------------------------------------
// WebSocket Client Class
// -------------------------------------------

export class TradingWebSocket {
  private ws: WebSocket | null = null;
  private sessionId: string;
  private handlers: WebSocketHandlers;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private pingInterval: number | null = null;
  private isClosing = false;

  constructor(sessionId: string, handlers: WebSocketHandlers = {}) {
    this.sessionId = sessionId;
    this.handlers = handlers;
  }

  /**
   * Get WebSocket URL based on current environment.
   */
  private getWebSocketUrl(): string {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = import.meta.env.VITE_WS_URL || `${wsProtocol}//${window.location.host}`;
    return `${wsHost}/api/ws/session/${this.sessionId}`;
  }

  /**
   * Connect to WebSocket server.
   */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      console.warn('WebSocket already connected');
      return;
    }

    this.isClosing = false;
    const url = this.getWebSocketUrl();
    console.log('Connecting to WebSocket:', url);

    try {
      this.ws = new WebSocket(url);
      this.setupEventListeners();
    } catch (error) {
      console.error('WebSocket connection error:', error);
      this.handleReconnect();
    }
  }

  /**
   * Setup WebSocket event listeners.
   */
  private setupEventListeners(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.reconnectAttempts = 0;
      this.startPingInterval();
      this.handlers.onConnect?.();
    };

    this.ws.onclose = (event) => {
      console.log('WebSocket closed:', event.code, event.reason);
      this.stopPingInterval();
      this.handlers.onDisconnect?.();

      if (!this.isClosing) {
        this.handleReconnect();
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      this.handlers.onError?.(error);
    };

    this.ws.onmessage = (event) => {
      this.handleMessage(event);
    };
  }

  /**
   * Handle incoming WebSocket messages.
   */
  private handleMessage(event: MessageEvent): void {
    try {
      // Handle pong response
      if (event.data === 'pong') {
        return;
      }

      const message: WebSocketMessage = JSON.parse(event.data);

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

        default:
          console.log('Unknown message type:', message.type);
      }
    } catch (error) {
      console.error('Error parsing WebSocket message:', error);
    }
  }

  /**
   * Start ping interval to keep connection alive.
   */
  private startPingInterval(): void {
    this.pingInterval = window.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send('ping');
      }
    }, 30000);
  }

  /**
   * Stop ping interval.
   */
  private stopPingInterval(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  /**
   * Handle reconnection with exponential backoff.
   */
  private handleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached');
      return;
    }

    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts);
    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  /**
   * Request current status.
   */
  requestStatus(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send('status');
    }
  }

  /**
   * Disconnect from WebSocket server.
   */
  disconnect(): void {
    this.isClosing = true;
    this.stopPingInterval();

    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
  }

  /**
   * Check if connected.
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /**
   * Update handlers.
   */
  setHandlers(handlers: Partial<WebSocketHandlers>): void {
    this.handlers = { ...this.handlers, ...handlers };
  }
}

// -------------------------------------------
// Factory Function
// -------------------------------------------

export function createWebSocket(
  sessionId: string,
  handlers: WebSocketHandlers = {}
): TradingWebSocket {
  return new TradingWebSocket(sessionId, handlers);
}

// -------------------------------------------
// React Hook Helper
// -------------------------------------------

/**
 * Creates a WebSocket connection integrated with Zustand store.
 */
export function createStoreWebSocket(
  sessionId: string,
  store: {
    addReasoningEntry: (entry: string) => void;
    setStatus: (status: SessionStatus) => void;
    setCurrentStage: (stage: string) => void;
    setTradeProposal: (proposal: TradeProposal | null) => void;
    setAwaitingApproval: (awaiting: boolean) => void;
    setActivePosition: (position: Position | null) => void;
    setError: (error: string | null) => void;
  }
): TradingWebSocket {
  return new TradingWebSocket(sessionId, {
    onReasoning: (entry) => {
      store.addReasoningEntry(entry);
    },
    onStatus: (data) => {
      store.setStatus(data.status as SessionStatus);
      store.setCurrentStage(data.stage);
      store.setAwaitingApproval(data.awaiting_approval);
    },
    onProposal: (data) => {
      store.setTradeProposal({
        id: data.id,
        ticker: data.ticker,
        action: data.action.toUpperCase() as 'BUY' | 'SELL' | 'HOLD',
        quantity: data.quantity,
        entry_price: data.entry_price,
        stop_loss: data.stop_loss,
        take_profit: data.take_profit,
        risk_score: data.risk_score,
        position_size_pct: 0,
        rationale: data.rationale,
        bull_case: '',
        bear_case: '',
        created_at: new Date().toISOString(),
      });
    },
    onPosition: (data) => {
      store.setActivePosition({
        ticker: data.ticker,
        quantity: data.quantity,
        entry_price: data.entry_price,
        current_price: data.current_price,
        pnl: data.pnl,
        pnl_percent: data.pnl_percent,
      });
    },
    onComplete: (data) => {
      if (data.error) {
        store.setError(data.error);
      }
      store.setStatus(data.status as SessionStatus);
    },
    onError: () => {
      store.setError('WebSocket connection error');
    },
  });
}
