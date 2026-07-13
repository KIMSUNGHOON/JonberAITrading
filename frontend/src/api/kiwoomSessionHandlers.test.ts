import { describe, it, expect, vi, beforeEach } from 'vitest';

// wsManager is the shared per-session WebSocket manager; spy on has()/connect().
// vi.hoisted so the (hoisted) vi.mock factory can reference it without a TDZ.
const { mockWsManager } = vi.hoisted(() => ({
  mockWsManager: { has: vi.fn(), connect: vi.fn() },
}));
vi.mock('@/api/websocket', () => ({ wsManager: mockWsManager }));

// getOperations is the /trading/operations client used by rehydrateKiwoomSessions.
// vi.hoisted for the same TDZ-safety reason as mockWsManager above.
const { getOperations } = vi.hoisted(() => ({ getOperations: vi.fn() }));
vi.mock('@/api/client', () => ({
  getOperations: (...a: unknown[]) => getOperations(...a),
}));

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

describe('rehydrateKiwoomSessions', () => {
  it('서버의 running/awaiting 세션을 스토어에 재수화하고 running은 WS 재연결한다', async () => {
    // 실제 스토어처럼 sessions[]에 push해야 ensureKiwoomSessionStreaming이 세션을 찾음
    const addKiwoomSession = vi.fn((s: { sessionId: string; awaitingApproval?: boolean }) => {
      (mockState.kiwoom as { sessions: unknown[] }).sessions.push(s);
      return true;
    });
    const setKiwoomSessionProposal = vi.fn();
    const setKiwoomSessionAwaitingApproval = vi.fn();
    const setKiwoomSessionAutoApproveAt = vi.fn();
    const setKiwoomSessionStage = vi.fn();
    mockState = {
      kiwoom: { sessions: [] },
      addKiwoomSession, setKiwoomSessionProposal,
      setKiwoomSessionAwaitingApproval, setKiwoomSessionAutoApproveAt,
      updateKiwoomSessionStage: setKiwoomSessionStage,
    };
    getOperations.mockResolvedValue({
      analyzing: [{ session_id: 'run-1', ticker: '005930', name: '삼성전자',
                    status: 'running', current_stage: 'sentiment_analysis',
                    started_at: '2026-07-13T02:13:42+00:00' }],
      awaiting: [{ session_id: 'aw-1', ticker: '000660', name: 'SK하이닉스',
                   proposal: { id: 'p1', action: 'WATCH', quantity: 0,
                               entry_price: 1968000, stop_loss: 1810560,
                               take_profit: 2125440, risk_score: 0.7,
                               rationale: '관망' },
                   auto_approve_at: null }],
      watching: [], pending_buy: { queue: [], open_orders: [] },
      holding: [], today_fills: [], errors: {},
    });
    mockWsManager.has.mockReturnValue(false);

    const { rehydrateKiwoomSessions } = await import('./kiwoomSessionHandlers');
    await rehydrateKiwoomSessions();

    // running 먼저, awaiting 마지막(activeSessionId가 awaiting이 되어 레일 미러 성립)
    expect(addKiwoomSession).toHaveBeenCalledTimes(2);
    expect(addKiwoomSession.mock.calls[0][0].sessionId).toBe('run-1');
    expect(addKiwoomSession.mock.calls[1][0].sessionId).toBe('aw-1');
    expect(addKiwoomSession.mock.calls[1][0].awaitingApproval).toBe(true);
    expect(setKiwoomSessionProposal).toHaveBeenCalledWith('aw-1',
      expect.objectContaining({ action: 'WATCH', stk_cd: '000660' }));
    expect(setKiwoomSessionAwaitingApproval).toHaveBeenCalledWith('aw-1', true);
    // running 세션만 WS 재연결 (awaiting은 상태 변화가 approval API로 옴)
    expect(mockWsManager.connect).toHaveBeenCalledTimes(2); // run-1 + aw-1 (거부→재분석 스트림 대비)
  });

  it('이미 스토어에 있는 세션은 중복 추가하지 않는다', async () => {
    const addKiwoomSession = vi.fn().mockReturnValue(true);
    mockState = {
      kiwoom: { sessions: [{ sessionId: 'run-1' }] },
      addKiwoomSession,
      setKiwoomSessionProposal: vi.fn(),
      setKiwoomSessionAwaitingApproval: vi.fn(),
      setKiwoomSessionAutoApproveAt: vi.fn(),
      updateKiwoomSessionStage: vi.fn(),
    };
    getOperations.mockResolvedValue({
      analyzing: [{ session_id: 'run-1', ticker: '005930', name: null,
                    status: 'running', current_stage: null, started_at: null }],
      awaiting: [], watching: [], pending_buy: { queue: [], open_orders: [] },
      holding: [], today_fills: [], errors: {},
    });
    const { rehydrateKiwoomSessions } = await import('./kiwoomSessionHandlers');
    await rehydrateKiwoomSessions();
    expect(addKiwoomSession).not.toHaveBeenCalled();
  });
});
