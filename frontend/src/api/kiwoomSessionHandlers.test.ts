import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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

import { createKiwoomWebSocketHandlers, ensureKiwoomSessionStreaming } from './kiwoomSessionHandlers';

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
    mockState = {
      kiwoom: { sessions: [] },
      addKiwoomSession, setKiwoomSessionProposal,
      setKiwoomSessionAwaitingApproval, setKiwoomSessionAutoApproveAt,
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
    // running과 awaiting 모두 WS 재연결 (awaiting도 거부→재분석 시 스트림 필요)
    expect(mockWsManager.connect).toHaveBeenCalledTimes(2); // run-1 + aw-1
  });

  it('이미 스토어에 있는 세션은 중복 추가하지 않는다', async () => {
    const addKiwoomSession = vi.fn().mockReturnValue(true);
    mockState = {
      kiwoom: { sessions: [{ sessionId: 'run-1' }] },
      addKiwoomSession,
      setKiwoomSessionProposal: vi.fn(),
      setKiwoomSessionAwaitingApproval: vi.fn(),
      setKiwoomSessionAutoApproveAt: vi.fn(),
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

  // P0-2: purge — restart-orphaned zombie session cards must disappear from
  // the store instead of lingering to 404 on click. The server's operations
  // board (analyzing ∪ awaiting) is truth; a non-terminal store session it no
  // longer lists is gone server-side and must be removed here.
  it('서버가 더 이상 나열하지 않는 비터미널 스토어 세션은 removeKiwoomSession으로 제거한다', async () => {
    const removeKiwoomSession = vi.fn();
    mockState = {
      kiwoom: {
        sessions: [
          { sessionId: 'A', status: 'running' },
          { sessionId: 'B', status: 'awaiting_approval' },
        ],
      },
      addKiwoomSession: vi.fn().mockReturnValue(true),
      setKiwoomSessionProposal: vi.fn(),
      setKiwoomSessionAwaitingApproval: vi.fn(),
      setKiwoomSessionAutoApproveAt: vi.fn(),
      removeKiwoomSession,
    };
    // Server only still knows about A — B is a zombie left over from a
    // restart (or the awaiting proposal was resolved while we were offline).
    getOperations.mockResolvedValue({
      analyzing: [{ session_id: 'A', ticker: '005930', name: null,
                    status: 'running', current_stage: null, started_at: null }],
      awaiting: [], watching: [], pending_buy: { queue: [], open_orders: [] },
      holding: [], today_fills: [], errors: {},
    });

    const { rehydrateKiwoomSessions } = await import('./kiwoomSessionHandlers');
    await rehydrateKiwoomSessions();

    expect(removeKiwoomSession).toHaveBeenCalledTimes(1);
    expect(removeKiwoomSession).toHaveBeenCalledWith('B');
  });

  // CRITICAL regression: the backend collects the sessions section
  // independently and, on failure, returns HTTP 200 with analyzing/awaiting =
  // null + errors.sessions set (a DEGRADED snapshot, not an empty one). The
  // outer try/catch here only catches the request THROWING — a 200 resolves
  // fine. Treating null/null as "server lists nothing" would purge every live
  // card, and this fires exactly during a backend restart — which is also when
  // the WS-reconnect trigger runs rehydrate. Purge MUST be skipped.
  it('세션 섹션이 실패(HTTP 200 + errors.sessions)하면 퍼지를 건너뛴다 — 라이브 카드 대량 삭제 방지', async () => {
    const removeKiwoomSession = vi.fn();
    mockState = {
      kiwoom: { sessions: [{ sessionId: 'X', status: 'running' }] },
      addKiwoomSession: vi.fn().mockReturnValue(true),
      setKiwoomSessionProposal: vi.fn(),
      setKiwoomSessionAwaitingApproval: vi.fn(),
      setKiwoomSessionAutoApproveAt: vi.fn(),
      removeKiwoomSession,
    };
    getOperations.mockResolvedValue({
      analyzing: null, awaiting: null, watching: [],
      pending_buy: { queue: [], open_orders: [] },
      holding: [], today_fills: [], errors: { sessions: 'boom' },
    });

    const { rehydrateKiwoomSessions } = await import('./kiwoomSessionHandlers');
    await rehydrateKiwoomSessions();

    expect(removeKiwoomSession).not.toHaveBeenCalled();
  });

  // Guard is keyed specifically on errors.sessions — an error in an UNRELATED
  // section (queue, broker, …) must NOT suppress the purge, since the sessions
  // section is still authoritative.
  it('errors에 sessions 이외 키만 있으면(예: queue 실패) 퍼지는 정상 수행된다', async () => {
    const removeKiwoomSession = vi.fn();
    mockState = {
      kiwoom: {
        sessions: [
          { sessionId: 'A', status: 'running' },
          { sessionId: 'B', status: 'awaiting_approval' },
        ],
      },
      addKiwoomSession: vi.fn().mockReturnValue(true),
      setKiwoomSessionProposal: vi.fn(),
      setKiwoomSessionAwaitingApproval: vi.fn(),
      setKiwoomSessionAutoApproveAt: vi.fn(),
      removeKiwoomSession,
    };
    getOperations.mockResolvedValue({
      analyzing: [{ session_id: 'A', ticker: '005930', name: null,
                    status: 'running', current_stage: null, started_at: null }],
      awaiting: [], watching: [], pending_buy: { queue: [], open_orders: [] },
      holding: [], today_fills: [], errors: { queue: 'boom' },
    });

    const { rehydrateKiwoomSessions } = await import('./kiwoomSessionHandlers');
    await rehydrateKiwoomSessions();

    expect(removeKiwoomSession).toHaveBeenCalledTimes(1);
    expect(removeKiwoomSession).toHaveBeenCalledWith('B');
  });

  it('터미널 상태(completed/cancelled/error) 스토어 세션은 서버 목록에 없어도 제거하지 않는다(히스토리 보존)', async () => {
    const removeKiwoomSession = vi.fn();
    mockState = {
      kiwoom: {
        sessions: [
          { sessionId: 'C', status: 'completed' },
          { sessionId: 'D', status: 'cancelled' },
          { sessionId: 'E', status: 'error' },
        ],
      },
      addKiwoomSession: vi.fn().mockReturnValue(true),
      setKiwoomSessionProposal: vi.fn(),
      setKiwoomSessionAwaitingApproval: vi.fn(),
      setKiwoomSessionAutoApproveAt: vi.fn(),
      removeKiwoomSession,
    };
    // Server knows about none of them (fully finished/history-only sessions
    // drop out of the operations board) — must NOT be treated as zombies.
    getOperations.mockResolvedValue({
      analyzing: [], awaiting: [], watching: [], pending_buy: { queue: [], open_orders: [] },
      holding: [], today_fills: [], errors: {},
    });

    const { rehydrateKiwoomSessions } = await import('./kiwoomSessionHandlers');
    await rehydrateKiwoomSessions();

    expect(removeKiwoomSession).not.toHaveBeenCalled();
  });
});

describe('createKiwoomWebSocketHandlers — WS reconnect re-triggers rehydrate', () => {
  it('does NOT rehydrate on the initial connect (connecting → connected, no reconnecting in between)', async () => {
    mockState = {
      kiwoom: { sessions: [{ sessionId: 'RC-1', status: 'running' }] },
      addKiwoomSession: vi.fn().mockReturnValue(true),
      setKiwoomSessionProposal: vi.fn(),
      setKiwoomSessionAwaitingApproval: vi.fn(),
      setKiwoomSessionAutoApproveAt: vi.fn(),
      removeKiwoomSession: vi.fn(),
    };
    getOperations.mockResolvedValue({
      analyzing: [], awaiting: [], watching: [], pending_buy: { queue: [], open_orders: [] },
      holding: [], today_fills: [], errors: {},
    });

    const handlers = createKiwoomWebSocketHandlers('RC-1');
    handlers.onConnectionStateChange?.('connecting');
    handlers.onConnectionStateChange?.('connected');
    await new Promise((r) => setTimeout(r, 0));

    expect(getOperations).not.toHaveBeenCalled();
  });

  it('re-runs rehydrateKiwoomSessions once the socket recovers from a genuine drop (…→reconnecting→…→connected)', async () => {
    const removeKiwoomSession = vi.fn();
    mockState = {
      // RC-1 itself is gone server-side by the time it reconnects (e.g. the
      // backend restarted while the socket was down) — the reconnect-driven
      // rehydrate must purge it, proving the full pipeline ran, not just a
      // bare getOperations ping.
      kiwoom: { sessions: [{ sessionId: 'RC-1', status: 'running' }] },
      addKiwoomSession: vi.fn().mockReturnValue(true),
      setKiwoomSessionProposal: vi.fn(),
      setKiwoomSessionAwaitingApproval: vi.fn(),
      setKiwoomSessionAutoApproveAt: vi.fn(),
      removeKiwoomSession,
    };
    getOperations.mockResolvedValue({
      analyzing: [], awaiting: [], watching: [], pending_buy: { queue: [], open_orders: [] },
      holding: [], today_fills: [], errors: {},
    });

    const handlers = createKiwoomWebSocketHandlers('RC-1');
    // Initial connect — must not fire.
    handlers.onConnectionStateChange?.('connecting');
    handlers.onConnectionStateChange?.('connected');
    // Drop + recover cycle, matching ManagedSocket's real state sequence.
    handlers.onConnectionStateChange?.('disconnected');
    handlers.onConnectionStateChange?.('reconnecting');
    handlers.onConnectionStateChange?.('connecting');
    handlers.onConnectionStateChange?.('connected');
    await new Promise((r) => setTimeout(r, 0));

    expect(getOperations).toHaveBeenCalledTimes(1);
    expect(removeKiwoomSession).toHaveBeenCalledWith('RC-1');
  });
});

describe('createKiwoomWebSocketHandlers — reasoning delta batching', () => {
  // Perf fix: every reasoning WS delta used to call the store directly (one
  // store-wide re-render per streamed token/chunk). onReasoning now buffers
  // entries per session and flushes them as ONE batch call after a 300ms
  // window (or immediately, out-of-band, ahead of a status/proposal/complete
  // frame for the same session so those can never overtake buffered lines).
  let addKiwoomSessionReasoningBatch: ReturnType<typeof vi.fn>;
  let updateKiwoomSessionStatus: ReturnType<typeof vi.fn>;
  let updateKiwoomSessionStage: ReturnType<typeof vi.fn>;
  let setKiwoomSessionAwaitingApproval: ReturnType<typeof vi.fn>;
  let setKiwoomSessionAutoApproveAt: ReturnType<typeof vi.fn>;
  let setKiwoomSessionProposal: ReturnType<typeof vi.fn>;
  let setKiwoomSessionError: ReturnType<typeof vi.fn>;
  const callOrder: string[] = [];

  beforeEach(() => {
    vi.useFakeTimers();
    callOrder.length = 0;
    addKiwoomSessionReasoningBatch = vi.fn(() => callOrder.push('batch'));
    updateKiwoomSessionStatus = vi.fn(() => callOrder.push('status'));
    updateKiwoomSessionStage = vi.fn();
    setKiwoomSessionAwaitingApproval = vi.fn();
    setKiwoomSessionAutoApproveAt = vi.fn();
    setKiwoomSessionProposal = vi.fn(() => callOrder.push('proposal'));
    setKiwoomSessionError = vi.fn();
    mockState = {
      kiwoom: { sessions: [] },
      addKiwoomSessionReasoningBatch,
      updateKiwoomSessionStatus,
      updateKiwoomSessionStage,
      setKiwoomSessionAwaitingApproval,
      setKiwoomSessionAutoApproveAt,
      setKiwoomSessionProposal,
      setKiwoomSessionError,
    };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('buffers reasoning deltas and flushes them as one batch call after the window', () => {
    const handlers = createKiwoomWebSocketHandlers('S1');

    handlers.onReasoning?.('[Technical] line one');
    handlers.onReasoning?.('[Technical] line two');

    // Within the 300ms window: no store call yet.
    expect(addKiwoomSessionReasoningBatch).not.toHaveBeenCalled();

    vi.advanceTimersByTime(300);

    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledTimes(1);
    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledWith('S1', [
      '[Technical] line one',
      '[Technical] line two',
    ]);
  });

  it('flushes the buffer BEFORE handling a status update that arrives mid-window', () => {
    const handlers = createKiwoomWebSocketHandlers('S1');

    handlers.onReasoning?.('[Risk] buffered line');
    // Status frame arrives before the 300ms timer fires.
    handlers.onStatus?.({ status: 'running', stage: 'risk_assessment', awaiting_approval: false });

    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledTimes(1);
    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledWith('S1', ['[Risk] buffered line']);
    expect(callOrder).toEqual(['batch', 'status']); // reasoning lands before the status update
    expect(updateKiwoomSessionStatus).toHaveBeenCalledTimes(1);

    // The pending timer for the flushed buffer must be cleared — advancing
    // past the original window must not cause a second (empty) batch call.
    vi.advanceTimersByTime(300);
    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledTimes(1);
  });

  it('flushes the buffer BEFORE handling a proposal that arrives mid-window', () => {
    const handlers = createKiwoomWebSocketHandlers('S1');

    handlers.onReasoning?.('[Strategic] weighing entry');
    handlers.onProposal?.({
      id: 'p1', ticker: '005930', action: 'buy', quantity: 10,
      entry_price: 70000, stop_loss: 68000, take_profit: 75000,
      risk_score: 0.4, rationale: 'momentum',
    });

    expect(callOrder).toEqual(['batch', 'proposal']);
  });

  it('flushes any remaining buffer on onComplete', () => {
    const handlers = createKiwoomWebSocketHandlers('S1');

    handlers.onReasoning?.('[Execution] final line');
    handlers.onComplete?.({ status: 'completed' });

    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledTimes(1);
    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledWith('S1', ['[Execution] final line']);
  });

  it('flushes any remaining buffer on onDisconnect (socket close)', () => {
    const handlers = createKiwoomWebSocketHandlers('S1');

    handlers.onReasoning?.('[Sentiment] last streamed line');
    handlers.onDisconnect?.();

    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledTimes(1);
    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledWith('S1', ['[Sentiment] last streamed line']);
  });

  it('does not call the batch action when onStatus arrives with an empty buffer', () => {
    const handlers = createKiwoomWebSocketHandlers('S1');

    handlers.onStatus?.({ status: 'running', stage: 'technical_analysis', awaiting_approval: false });

    expect(addKiwoomSessionReasoningBatch).not.toHaveBeenCalled();
    expect(updateKiwoomSessionStatus).toHaveBeenCalledTimes(1);
  });

  it('keeps separate sessions independent (no cross-session buffer bleed)', () => {
    const h1 = createKiwoomWebSocketHandlers('S1');
    const h2 = createKiwoomWebSocketHandlers('S2');

    h1.onReasoning?.('[Technical] s1 line');
    h2.onReasoning?.('[Technical] s2 line a');
    h2.onReasoning?.('[Technical] s2 line b');

    h2.onComplete?.({ status: 'completed' }); // flush only S2's buffer

    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledTimes(1);
    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledWith('S2', [
      '[Technical] s2 line a',
      '[Technical] s2 line b',
    ]);

    vi.advanceTimersByTime(300); // S1's own timer still fires independently
    expect(addKiwoomSessionReasoningBatch).toHaveBeenCalledTimes(2);
    expect(addKiwoomSessionReasoningBatch).toHaveBeenLastCalledWith('S1', ['[Technical] s1 line']);
  });
});
