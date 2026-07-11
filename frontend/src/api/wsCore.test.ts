/**
 * P7 Phase 3: shared WebSocket core.
 *
 * All four FE WS clients (TradingWebSocket, TickerWebSocket,
 * useAgentChatWebSocket, useTradeNotifications) hand-rolled the same
 * URL-building / reconnect / heartbeat / cleanup skeleton with divergent
 * policies. ManagedSocket owns that skeleton once; each client passes its
 * CURRENT policy values so behavior is preserved.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ManagedSocket, buildWsUrl } from './wsCore';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  closeCalls: Array<{ code?: number; reason?: string }> = [];
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code?: number, reason?: string) {
    this.closeCalls.push({ code, reason });
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code: code ?? 1000, reason: reason ?? '' });
  }

  // --- test helpers ---
  simulateOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  simulateMessage(data: string) {
    this.onmessage?.({ data });
  }

  simulateServerClose(code = 1006) {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason: 'server closed' });
  }
}

function lastSocket(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe('buildWsUrl', () => {
  it('appends the path verbatim to VITE_WS_URL when set', () => {
    vi.stubEnv('VITE_WS_URL', 'ws://backend:8000');
    expect(buildWsUrl('/ws/session/abc')).toBe('ws://backend:8000/ws/session/abc');
    // The /api-prefixed agent-chat path must NOT be rewritten
    expect(buildWsUrl('/api/agent-chat/ws/xyz')).toBe('ws://backend:8000/api/agent-chat/ws/xyz');
  });

  it('falls back to the current host with ws: for http pages', () => {
    vi.stubEnv('VITE_WS_URL', '');
    expect(buildWsUrl('/ws/ticker')).toBe(`ws://${window.location.host}/ws/ticker`);
  });
});

describe('ManagedSocket', () => {
  it('transitions disconnected → connecting → connected and reports state changes', () => {
    const states: string[] = [];
    const socket = new ManagedSocket({
      path: '/ws/test',
      onStateChange: (s) => states.push(s),
    });

    expect(socket.state).toBe('disconnected');
    socket.connect();
    expect(socket.state).toBe('connecting');
    lastSocket().simulateOpen();
    expect(socket.state).toBe('connected');
    expect(socket.isConnected()).toBe(true);
    expect(states).toEqual(['connecting', 'connected']);
  });

  it('sends ping at the configured interval while open and swallows pong', () => {
    const received: string[] = [];
    const socket = new ManagedSocket({
      path: '/ws/test',
      pingIntervalMs: 25000,
      onMessage: (raw) => received.push(raw),
    });
    socket.connect();
    const ws = lastSocket();
    ws.simulateOpen();

    vi.advanceTimersByTime(25000);
    vi.advanceTimersByTime(25000);
    expect(ws.sent).toEqual(['ping', 'ping']);

    ws.simulateMessage('pong');
    ws.simulateMessage('{"type":"x"}');
    expect(received).toEqual(['{"type":"x"}']); // pong swallowed
  });

  it('reconnects with exponential backoff after an unexpected close', () => {
    const socket = new ManagedSocket({
      path: '/ws/test',
      baseReconnectDelayMs: 1000,
      reconnectCapMs: null,
    });
    socket.connect();
    lastSocket().simulateOpen();
    expect(FakeWebSocket.instances).toHaveLength(1);

    lastSocket().simulateServerClose();
    expect(socket.state).toBe('reconnecting');

    vi.advanceTimersByTime(999);
    expect(FakeWebSocket.instances).toHaveLength(1); // not yet
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2); // attempt 1 after 1000ms

    lastSocket().simulateServerClose(); // connection failed again
    vi.advanceTimersByTime(2000); // attempt 2 after 2000ms (doubled)
    expect(FakeWebSocket.instances).toHaveLength(3);
  });

  it('caps the backoff delay when reconnectCapMs is set', () => {
    const socket = new ManagedSocket({
      path: '/ws/test',
      baseReconnectDelayMs: 1000,
      reconnectCapMs: 30000,
      maxReconnectAttempts: 10,
    });
    socket.connect();

    // Fail 6 times: uncapped delays would be 1s,2s,4s,8s,16s,32s — the 6th
    // must be capped to 30s.
    for (let i = 0; i < 6; i++) {
      lastSocket().simulateServerClose();
      vi.advanceTimersByTime(Math.min(1000 * 2 ** i, 30000) - 1);
      expect(FakeWebSocket.instances).toHaveLength(i + 1); // not yet
      vi.advanceTimersByTime(1);
      expect(FakeWebSocket.instances).toHaveLength(i + 2); // reconnected
    }
  });

  it('gives up after maxReconnectAttempts and ends disconnected', () => {
    const states: string[] = [];
    const socket = new ManagedSocket({
      path: '/ws/test',
      maxReconnectAttempts: 2,
      baseReconnectDelayMs: 1,
      onStateChange: (s) => states.push(s),
    });
    socket.connect();

    lastSocket().simulateServerClose(); // attempt 0 used
    vi.advanceTimersByTime(10);
    lastSocket().simulateServerClose(); // attempt 1 used
    vi.advanceTimersByTime(10);
    lastSocket().simulateServerClose(); // attempts exhausted

    vi.advanceTimersByTime(60000);
    expect(FakeWebSocket.instances).toHaveLength(3); // no further sockets
    expect(socket.state).toBe('disconnected');
  });

  it('disconnect() closes cleanly and cancels any pending reconnect (no zombie)', () => {
    const socket = new ManagedSocket({ path: '/ws/test' });
    socket.connect();
    const ws = lastSocket();
    ws.simulateOpen();

    ws.simulateServerClose(); // schedules a reconnect
    socket.disconnect(); // must cancel it

    vi.advanceTimersByTime(120000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(socket.state).toBe('disconnected');
  });

  it('disconnect() closes with code 1000 and stops the heartbeat', () => {
    const socket = new ManagedSocket({ path: '/ws/test', pingIntervalMs: 1000 });
    socket.connect();
    const ws = lastSocket();
    ws.simulateOpen();

    socket.disconnect();
    expect(ws.closeCalls).toEqual([{ code: 1000, reason: 'Client disconnect' }]);

    vi.advanceTimersByTime(10000);
    expect(ws.sent).toEqual([]); // no pings after disconnect
  });

  it('does not reconnect after a clean client disconnect', () => {
    const socket = new ManagedSocket({ path: '/ws/test' });
    socket.connect();
    lastSocket().simulateOpen();
    socket.disconnect();

    vi.advanceTimersByTime(60000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('resets the backoff counter after a successful open', () => {
    const socket = new ManagedSocket({
      path: '/ws/test',
      baseReconnectDelayMs: 1000,
      maxReconnectAttempts: 5,
    });
    socket.connect();
    lastSocket().simulateServerClose();
    vi.advanceTimersByTime(1000);
    lastSocket().simulateOpen(); // success resets attempts

    lastSocket().simulateServerClose();
    vi.advanceTimersByTime(1000); // base delay again, not doubled
    expect(FakeWebSocket.instances).toHaveLength(3);
  });

  it('send() only delivers while open', () => {
    const socket = new ManagedSocket({ path: '/ws/test' });
    expect(socket.send('x')).toBe(false);

    socket.connect();
    expect(socket.send('x')).toBe(false); // still connecting

    const ws = lastSocket();
    ws.simulateOpen();
    expect(socket.send('hello')).toBe(true);
    expect(ws.sent).toContain('hello');
  });

  it('connect() while already open is a no-op (no duplicate socket)', () => {
    const socket = new ManagedSocket({ path: '/ws/test' });
    socket.connect();
    lastSocket().simulateOpen();
    socket.connect();
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('delivers onOpen/onError/onClose, with onOpen fired while the socket is sendable', () => {
    // All four adapters hang resume logic on these callbacks (buffer flush,
    // pending-subscription flush, isConnected state) — dropping or reordering
    // any of them must fail a test.
    const events: string[] = [];
    const socket: ManagedSocket = new ManagedSocket({
      path: '/ws/test',
      onOpen: () => {
        // e.g. TickerWebSocket flushes queued subscriptions from onOpen —
        // the socket must already be open when it fires.
        events.push(socket.send('sub') ? 'open:sendable' : 'open:not-sendable');
      },
      onClose: () => events.push('close'),
      onError: () => events.push('error'),
    });

    socket.connect();
    const ws = lastSocket();
    ws.simulateOpen();
    expect(events).toEqual(['open:sendable']);
    expect(ws.sent).toContain('sub');

    ws.onerror?.('boom');
    expect(events).toEqual(['open:sendable', 'error']);

    ws.simulateServerClose();
    expect(events).toEqual(['open:sendable', 'error', 'close']);
  });

  it('a reused instance reconnects on server drops after disconnect() → connect()', () => {
    // TradingWebSocket/TickerWebSocket embed ONE ManagedSocket for their
    // lifetime and forward connect()/disconnect() — the clean-shutdown latch
    // must reset on reuse or a reused socket would ignore server drops forever.
    const socket = new ManagedSocket({ path: '/ws/test', baseReconnectDelayMs: 1000 });
    socket.connect();
    lastSocket().simulateOpen();
    socket.disconnect();

    socket.connect(); // reuse the same instance
    lastSocket().simulateOpen();
    lastSocket().simulateServerClose(); // server drop after reuse

    expect(socket.state).toBe('reconnecting');
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances).toHaveLength(3); // initial + reuse + reconnect
  });

  it('recovers with backoff when the WebSocket constructor throws', () => {
    // A malformed VITE_WS_URL (SyntaxError) or ws: from an https page
    // (SecurityError) throws synchronously — the socket must retry with
    // backoff instead of freezing in 'connecting'.
    let throwOnce = true;
    class ThrowingFakeWebSocket extends FakeWebSocket {
      constructor(url: string) {
        if (throwOnce) {
          throwOnce = false;
          throw new Error('bad url');
        }
        super(url);
      }
    }
    vi.stubGlobal('WebSocket', ThrowingFakeWebSocket);

    const socket = new ManagedSocket({ path: '/ws/test', baseReconnectDelayMs: 1000 });
    socket.connect(); // constructor throws
    expect(socket.state).toBe('reconnecting');
    expect(FakeWebSocket.instances).toHaveLength(0);

    vi.advanceTimersByTime(1000); // retry succeeds
    expect(FakeWebSocket.instances).toHaveLength(1);
    lastSocket().simulateOpen();
    expect(socket.state).toBe('connected');
  });
});
