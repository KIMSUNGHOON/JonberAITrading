import { describe, it, expect, vi, beforeEach } from 'vitest';

// wsManager is the shared per-session WebSocket manager; spy on has()/connect().
// vi.hoisted so the (hoisted) vi.mock factory can reference it without a TDZ.
const { mockWsManager } = vi.hoisted(() => ({
  mockWsManager: { has: vi.fn(), connect: vi.fn() },
}));
vi.mock('@/api/websocket', () => ({ wsManager: mockWsManager }));

// Controlled store: useStore(sel) runs the selector; useStore.getState() returns
// the same mockState (kiwoomSessionHandlers reads sessions/actions via getState).
let mockState: any;
vi.mock('@/store', () => ({
  useStore: Object.assign((sel: (s: any) => unknown) => sel(mockState), {
    getState: () => mockState,
  }),
}));

import { ensureKiwoomSessionStreaming } from './kiwoomSessionHandlers';

beforeEach(() => {
  vi.clearAllMocks();
  mockState = { kiwoom: { sessions: [] } };
});

describe('ensureKiwoomSessionStreaming', () => {
  it('connects the /ws/session stream when the session is in the store and not yet connected', () => {
    // Regression: Pattern-B starts (watchlist reanalyze, scanner) add the session
    // and navigate to /workflow but never connect the stream — SessionBridge must
    // connect it so the page updates instead of only Telegram firing.
    mockState.kiwoom.sessions = [{ sessionId: 'S1', marketType: 'kiwoom' }];
    mockWsManager.has.mockReturnValue(false);

    ensureKiwoomSessionStreaming('S1');

    expect(mockWsManager.connect).toHaveBeenCalledTimes(1);
    expect(mockWsManager.connect).toHaveBeenCalledWith('S1', expect.anything());
  });

  it('does not reconnect when a connection already exists (idempotent with useStartAnalysis)', () => {
    mockState.kiwoom.sessions = [{ sessionId: 'S1', marketType: 'kiwoom' }];
    mockWsManager.has.mockReturnValue(true);

    ensureKiwoomSessionStreaming('S1');

    expect(mockWsManager.connect).not.toHaveBeenCalled();
  });

  it('does nothing for a session id not present in the store', () => {
    mockState.kiwoom.sessions = [];
    mockWsManager.has.mockReturnValue(false);

    ensureKiwoomSessionStreaming('missing');

    expect(mockWsManager.connect).not.toHaveBeenCalled();
  });
});
