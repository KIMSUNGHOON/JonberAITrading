/**
 * Shared WebSocket core (P7 Phase 3).
 *
 * Owns the connection skeleton every FE WS client used to hand-roll:
 * URL building, connect/close with a clean-shutdown guard, exponential
 * reconnect backoff, the text 'ping'/'pong' heartbeat, connection-state
 * tracking, and timer cleanup. Clients (TradingWebSocket, TickerWebSocket,
 * useAgentChatWebSocket, useTradeNotifications) are thin adapters that pass
 * their own policy values — behavior per client is unchanged.
 */

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

export interface ManagedSocketOptions {
  /** Path appended VERBATIM to the ws host (e.g. '/ws/session/abc', '/api/agent-chat/ws/x'). */
  path: string;
  /** Console log prefix (defaults to 'WebSocket'). */
  label?: string;
  /** Give up reconnecting after this many attempts (default 5). */
  maxReconnectAttempts?: number;
  /** First reconnect delay; doubles each attempt (default 1000ms). */
  baseReconnectDelayMs?: number;
  /** Backoff ceiling; null = uncapped (default null). */
  reconnectCapMs?: number | null;
  /** Text-'ping' heartbeat cadence while open (default 30000ms). */
  pingIntervalMs?: number;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  onStateChange?: (state: ConnectionState) => void;
  /** Raw message payload. Text 'pong' heartbeat replies are swallowed by the core. */
  onMessage?: (raw: string) => void;
}

/**
 * Build a WebSocket URL for a backend path.
 *
 * VITE_WS_URL (base origin, no trailing path) wins; otherwise the current
 * host is used (proxied by Vite in dev). The path is appended verbatim —
 * some endpoints live under /ws, others under /api (agent-chat).
 */
export function buildWsUrl(path: string): string {
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsHost = import.meta.env.VITE_WS_URL || `${wsProtocol}//${window.location.host}`;
  return `${wsHost}${path}`;
}

export class ManagedSocket {
  private ws: WebSocket | null = null;
  private readonly path: string;
  private readonly label: string;
  private readonly maxReconnectAttempts: number;
  private readonly baseReconnectDelayMs: number;
  private readonly reconnectCapMs: number | null;
  private readonly pingIntervalMs: number;
  private readonly handlers: Pick<
    ManagedSocketOptions,
    'onOpen' | 'onClose' | 'onError' | 'onStateChange' | 'onMessage'
  >;

  private reconnectAttempts = 0;
  private reconnectTimeout: number | null = null;
  private pingTimer: number | null = null;
  private isClosing = false;
  private _state: ConnectionState = 'disconnected';
  private reviveListenersAttached = false;

  constructor(options: ManagedSocketOptions) {
    this.path = options.path;
    this.label = options.label ?? 'WebSocket';
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5;
    this.baseReconnectDelayMs = options.baseReconnectDelayMs ?? 1000;
    this.reconnectCapMs = options.reconnectCapMs ?? null;
    this.pingIntervalMs = options.pingIntervalMs ?? 30000;
    this.handlers = {
      onOpen: options.onOpen,
      onClose: options.onClose,
      onError: options.onError,
      onStateChange: options.onStateChange,
      onMessage: options.onMessage,
    };
  }

  get state(): ConnectionState {
    return this._state;
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /** Send raw text if the socket is open. Returns whether it was sent. */
  send(data: string): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(data);
      return true;
    }
    return false;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      console.warn(`[${this.label}] Already connected`);
      return;
    }

    this.isClosing = false;
    this.attachReviveListeners();
    const url = buildWsUrl(this.path);
    console.log(`[${this.label}] Connecting to:`, url);
    this.setState('connecting');

    try {
      this.ws = new WebSocket(url);
      this.setupEventListeners();
    } catch (error) {
      console.error(`[${this.label}] Connection error:`, error);
      this.setState('disconnected');
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.isClosing = true;
    this.stopHeartbeat();
    this.detachReviveListeners();

    if (this.reconnectTimeout !== null) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.setState('disconnected');
  }

  // --- Revival: nudge a socket that gave up (or is mid-backoff) back to life
  // when the environment changes for the better. Without this, a socket that
  // exhausts maxReconnectAttempts stays dead until a manual page refresh — so a
  // backend restart outlasting the reconnect budget freezes the whole UI. The
  // browser firing 'online' (network restored) or the tab regaining visibility
  // (user came back) are exactly the moments a fresh attempt is worth making.
  private readonly handleOnline = (): void => {
    this.revive();
  };

  private readonly handleVisibility = (): void => {
    if (typeof document === 'undefined' || document.visibilityState === 'visible') {
      this.revive();
    }
  };

  private attachReviveListeners(): void {
    if (this.reviveListenersAttached) return;
    if (typeof window !== 'undefined') {
      window.addEventListener('online', this.handleOnline);
    }
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', this.handleVisibility);
    }
    this.reviveListenersAttached = true;
  }

  private detachReviveListeners(): void {
    if (!this.reviveListenersAttached) return;
    if (typeof window !== 'undefined') {
      window.removeEventListener('online', this.handleOnline);
    }
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.handleVisibility);
    }
    this.reviveListenersAttached = false;
  }

  /**
   * Reconnect immediately with a fresh backoff budget, unless the socket is
   * intentionally closed, already open, or a connect is already in flight. A
   * pending backoff timer is cancelled so recovery is instant rather than
   * waiting out the (possibly 30s) delay.
   */
  private revive(): void {
    if (this.isClosing) return;
    if (this.ws?.readyState === WebSocket.OPEN) return;
    if (this._state === 'connecting') return;
    if (this.reconnectTimeout !== null) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    this.reconnectAttempts = 0;
    this.connect();
  }

  private setState(state: ConnectionState): void {
    if (this._state !== state) {
      this._state = state;
      this.handlers.onStateChange?.(state);
    }
  }

  private setupEventListeners(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      console.log(`[${this.label}] Connected`);
      this.reconnectAttempts = 0;
      this.setState('connected');
      this.startHeartbeat();
      this.handlers.onOpen?.();
    };

    this.ws.onclose = (event) => {
      console.log(`[${this.label}] Closed:`, event.code, event.reason);
      this.stopHeartbeat();
      this.setState('disconnected');
      this.handlers.onClose?.();

      if (!this.isClosing) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (error) => {
      console.error(`[${this.label}] Error:`, error);
      this.handlers.onError?.(error);
    };

    this.ws.onmessage = (event) => {
      // Heartbeat reply — never surfaces to clients.
      if (event.data === 'pong') {
        return;
      }
      this.handlers.onMessage?.(event.data);
    };
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingTimer = window.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send('ping');
      }
    }, this.pingIntervalMs);
  }

  private stopHeartbeat(): void {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(`[${this.label}] Max reconnection attempts reached`);
      this.setState('disconnected');
      return;
    }

    this.setState('reconnecting');
    let delay = this.baseReconnectDelayMs * Math.pow(2, this.reconnectAttempts);
    if (this.reconnectCapMs !== null) {
      delay = Math.min(delay, this.reconnectCapMs);
    }
    console.log(`[${this.label}] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimeout = window.setTimeout(() => {
      this.reconnectTimeout = null;
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }
}
