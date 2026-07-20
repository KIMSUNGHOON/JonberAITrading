import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, renderHook, act } from '@testing-library/react';

const getOperations = vi.fn();
const submitApproval = vi.fn().mockResolvedValue({});
const cancelKRStockOrder = vi.fn().mockResolvedValue({});
const cancelQueuedTrade = vi.fn().mockResolvedValue({});
const processTradeQueue = vi.fn().mockResolvedValue({});
vi.mock('@/api/client', () => ({
  getOperations: (...a: unknown[]) => getOperations(...a),
  submitApproval: (...a: unknown[]) => submitApproval(...a),
  cancelKRStockSession: vi.fn(),
  convertWatchToQueue: vi.fn(),
  removeFromWatchList: vi.fn(),
  cancelKRStockOrder: (...a: unknown[]) => cancelKRStockOrder(...a),
  cancelQueuedTrade: (...a: unknown[]) => cancelQueuedTrade(...a),
  processTradeQueue: (...a: unknown[]) => processTradeQueue(...a),
}));
vi.mock('@/hooks/useTradeNotifications', () => ({
  useTradeNotifications: () => ({ isConnected: true, notifications: [] }),
}));
// Task 8b: WatchingColumn's re-analyze backport uses the SAME shared
// "start an analysis" hook DiscoverySection uses (wraps startKRStockAnalysis
// + session bookkeeping/WS wiring) rather than reimplementing it — mocked
// the same way DiscoverySection.test.tsx / FunnelPanel.test.tsx do.
const mockStartAnalysis = vi.fn();
vi.mock('@/hooks/useStartAnalysis', () => ({
  useStartAnalysis: () => mockStartAnalysis,
}));
const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));

// T7 review HIGH #1/#2 fix: the REAL store is used (not a bare-vi.fn()
// mock of setActiveKiwoomSession/setAwaitingApproval) so the reachability
// tests below actually exercise setActiveKiwoomSession's cache-miss no-op /
// coin's single-slot limitation instead of masking them behind a mock that
// always "succeeds". See store/index.ts injectAwaitingKiwoomSession /
// focusAwaitingCoinSession.
import { useStore } from '@/store';
import { OperationsPanel, useOperations } from './OperationsPanel';

const BASE = {
  analyzing: [], awaiting: [], watching: [],
  pending_buy: { queue: [], open_orders: [] },
  holding: [], today_fills: [], errors: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  // Full, isolated reset of both market slices — a real singleton store
  // persists mutations across tests within this file otherwise, and the
  // reachability tests below depend on starting from a clean sessions[]/
  // activeSessionId every time.
  useStore.setState({
    activeMarket: 'kiwoom',
    kiwoom: {
      sessions: [], activeSessionId: null, maxConcurrentSessions: 3,
      stk_cd: '', stk_nm: null, status: 'idle', currentStage: null,
      reasoningLog: [], analyses: [], tradeProposal: null, awaitingApproval: false,
      activePosition: null, error: null, history: [],
    },
    coin: {
      activeSessionId: null, market: '', koreanName: null, status: 'idle',
      currentStage: null, reasoningLog: [], analyses: [], tradeProposal: null,
      awaitingApproval: false, activePosition: null, error: null, history: [],
    },
  });
});

it('전 컬럼 헤더와 카운트를 렌더한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    analyzing: [{ session_id: 's1', ticker: '005930', name: '삼성전자',
                  status: 'running', current_stage: 'technical_analysis',
                  started_at: null }],
    pending_buy: {
      queue: [],
      open_orders: [{ order_id: 'o1', stk_cd: '005930', stk_nm: '삼성전자',
                      side: 'buy', price: 260000, quantity: 48,
                      remaining_quantity: 48, executed_quantity: 0,
                      created_at: null }],
    },
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/분석중 · 1/)).toBeInTheDocument());
  expect(screen.getByText(/매수대기 · 1/)).toBeInTheDocument();
  expect(screen.getByText(/미체결 48주/)).toBeInTheDocument();
});

// Task 7 (P2 funnel-consolidation): 승인대기 no longer carries its own
// 승인/거부/취소 buttons — the SAME submitApproval endpoint was previously
// reachable from here AND from the global OrderTicketRail simultaneously.
// This column is now a read-only summary: clicking a row focuses that
// session and navigates to its workflow view, where the rail is docked. See
// OrderTicketRail.test.tsx for the retained approve/reject/cancel coverage.
//
// T7 review HIGH #1: this session was NEVER added to kiwoom.sessions[] — it
// reached AWAITING_APPROVAL purely server-side (autonomous trigger / another
// tab / watch-monitor reanalysis) and the poll is the ONLY place this tab
// has seen it. The pre-fix handler (setActiveKiwoomSession) would silently
// no-op here since the session isn't cached — asserting on the REAL store
// (not a bare mock) is what makes that regression visible.
it('승인대기 항목에는 승인/거부/취소 버튼이 없다 — 클릭하면 로컬 캐시에 없어도 세션을 레일에 포커스하고 주문 레일로 이동한다 (캐시 miss No-op 봉합)', async () => {
  expect(useStore.getState().kiwoom.sessions).toHaveLength(0); // precondition: NOT cached
  getOperations.mockResolvedValue({
    ...BASE,
    awaiting: [{ session_id: 's2', ticker: '000660', name: 'SK하이닉스',
                 proposal: { action: 'WATCH', entry_price: 1968000,
                             stop_loss: 1810560, take_profit: 2125440,
                             risk_score: 0.7 },
                 auto_approve_at: null }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument());
  expect(screen.queryByRole('button', { name: '승인' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '거부' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '취소' })).not.toBeInTheDocument();

  fireEvent.click(screen.getByText('SK하이닉스'));

  const state = useStore.getState();
  expect(state.kiwoom.activeSessionId).toBe('s2'); // NOT a no-op
  expect(state.kiwoom.sessions.find((s) => s.sessionId === 's2')).toBeTruthy(); // injected
  expect(state.kiwoom.awaitingApproval).toBe(true);
  expect(state.kiwoom.tradeProposal).toMatchObject({ action: 'WATCH', entry_price: 1968000, stk_cd: '000660', stk_nm: 'SK하이닉스' });
  expect(navigate).toHaveBeenCalledWith('/workflow/s2');
  // The approval decision itself is NEVER submitted from this surface.
  expect(submitApproval).not.toHaveBeenCalled();
});

it('섹션 오류는 조회 실패로 정직 표기한다 (0 위장 금지)', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    pending_buy: { queue: [], open_orders: null },
    errors: { open_orders: 'kiwoom down' },
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/조회 실패/)).toBeInTheDocument());
  expect(screen.queryByText(/매수대기 · 0/)).not.toBeInTheDocument();
});

it('큐 조회 실패 시 헤더는 조회 실패, 살아있는 미체결 행은 계속 렌더한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    pending_buy: {
      queue: null,
      open_orders: [{ order_id: 'o2', stk_cd: '005930', stk_nm: '삼성전자',
                      side: 'buy', price: 260000, quantity: 48,
                      remaining_quantity: 48, executed_quantity: 0,
                      created_at: null }],
    },
    errors: { queue: 'coordinator unavailable' },
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/매수대기 · 조회 실패/)).toBeInTheDocument());
  // 합산 카운트 위장 금지
  expect(screen.queryByText(/매수대기 · \d/)).not.toBeInTheDocument();
  // 성공한 서브섹션(미체결)은 숨기지 않는다
  expect(screen.getByText(/미체결 48주/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '주문 취소' })).toBeInTheDocument();
});

it('미체결 조회 실패 시 헤더는 조회 실패, 살아있는 큐 항목은 계속 렌더한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    pending_buy: {
      queue: [{ id: 'q1', session_id: 's3', ticker: '005930',
                stock_name: '삼성전자', action: 'BUY', entry_price: 260000,
                quantity: 10, status: 'pending' }],
      open_orders: null,
    },
    errors: { open_orders: 'kiwoom down' },
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/매수대기 · 조회 실패/)).toBeInTheDocument());
  expect(screen.queryByText(/매수대기 · \d/)).not.toBeInTheDocument();
  // 성공한 서브섹션(큐)은 숨기지 않는다 — 대기 배지 + 대기 취소 버튼
  expect(screen.getByText('대기')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '대기 취소' })).toBeInTheDocument();
});

// T7 review HIGH #1 (continued): with TWO concurrent kiwoom awaiting
// sessions, neither cached locally, each row click must target ITS OWN
// session on the rail (both individually reachable), and switching between
// them must actually retarget the rail (not stick to whichever was
// clicked first).
it('세션이 두 개 이상 승인대기 중이어도 각 행이 각자의 세션으로 포커스한다 (전부 도달 가능, 캐시 miss여도)', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    awaiting: [
      { session_id: 's4', ticker: '000660', name: 'SK하이닉스',
        proposal: { action: 'WATCH', entry_price: 1968000 }, auto_approve_at: null },
      { session_id: 's5', ticker: '005930', name: '삼성전자',
        proposal: { action: 'BUY', entry_price: 70000 }, auto_approve_at: null },
    ],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/승인대기 · 2/)).toBeInTheDocument());

  fireEvent.click(screen.getByText('삼성전자'));
  expect(useStore.getState().kiwoom.activeSessionId).toBe('s5');
  expect(useStore.getState().kiwoom.tradeProposal).toMatchObject({ action: 'BUY', entry_price: 70000 });
  expect(navigate).toHaveBeenCalledWith('/workflow/s5');

  fireEvent.click(screen.getByText('SK하이닉스'));
  expect(useStore.getState().kiwoom.activeSessionId).toBe('s4');
  expect(useStore.getState().kiwoom.tradeProposal).toMatchObject({ action: 'WATCH', entry_price: 1968000 });
  expect(navigate).toHaveBeenCalledWith('/workflow/s4');

  // Both sessions ended up injected — neither click was a no-op.
  const sessionIds = useStore.getState().kiwoom.sessions.map((s) => s.sessionId);
  expect(sessionIds).toEqual(expect.arrayContaining(['s4', 's5']));
});

it('actionable=false인 승인대기 항목은 버튼 없이 상태 불일치만 안내하고, 클릭 시에도 여전히 레일로 포커스한다 (좀비 부활 방지 정보는 유지, 액션은 이중화하지 않음)', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    awaiting: [{ session_id: 's6', ticker: '005930', name: '삼성전자',
                 proposal: { action: 'BUY', entry_price: 70000 },
                 auto_approve_at: null, actionable: false }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument());
  expect(screen.getByText(/세션 상태 불일치/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '승인' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '거부' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '취소' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('삼성전자'));
  expect(useStore.getState().kiwoom.activeSessionId).toBe('s6');
  expect(submitApproval).not.toHaveBeenCalled();
});

// T7 review HIGH #1/#2 fix, requirement #4: when the row genuinely lacks
// proposal detail (a real state-inconsistency case, not a cache issue), the
// click must surface an HONEST error rather than silently pretending the
// rail now shows something.
it('proposal이 없는 승인대기 행은 클릭 시 무음 no-op 대신 오류 배너를 표시한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    awaiting: [{ session_id: 's7', ticker: '005930', name: '삼성전자',
                 proposal: null, auto_approve_at: null }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument());
  fireEvent.click(screen.getByText('삼성전자'));
  await screen.findByText(/제안 데이터가 없어 주문 레일에 표시할 수 없습니다/);
  expect(submitApproval).not.toHaveBeenCalled();
});

it('미체결 취소 버튼이 cancelKRStockOrder를 호출하고 재조회한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    pending_buy: {
      queue: [],
      open_orders: [{ order_id: 'o9', stk_cd: '005930', stk_nm: '삼성전자',
                      side: 'buy', price: 260000, quantity: 48,
                      remaining_quantity: 48, executed_quantity: 0,
                      created_at: null }],
    },
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/매수대기 · 1/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '주문 취소' }));
  await waitFor(() => expect(cancelKRStockOrder).toHaveBeenCalledWith('o9'));
  expect(getOperations.mock.calls.length).toBeGreaterThanOrEqual(2); // 액션 후 재조회
});

// -------------------------------------------
// Task 8b (P2 funnel-consolidation, final): actions backported from the
// removed /trading WatchListWidget/TradeQueueWidget.
// -------------------------------------------

it('감시 항목의 재분석 버튼이 useStartAnalysis의 start를 kiwoom/티커로 호출하고 새 세션의 워크플로우로 이동한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    watching: [{
      id: 'watch-1', ticker: '005930', stock_name: '삼성전자',
      current_price: 71000, target_entry_price: 70000, confidence: 0.75, status: 'active',
    }],
  });
  mockStartAnalysis.mockResolvedValue({ sessionId: 'session-42', duplicate: false, positionExists: false });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '재분석 005930' }));
  await waitFor(() => expect(mockStartAnalysis).toHaveBeenCalledWith('kiwoom', '005930', '삼성전자'));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/workflow/session-42'));
});

it('재분석 실패 시 액션 오류 배너를 표시하고 이동하지 않는다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    watching: [{
      id: 'watch-1', ticker: '005930', stock_name: '삼성전자',
      current_price: 71000, target_entry_price: 70000, confidence: 0.75, status: 'active',
    }],
  });
  mockStartAnalysis.mockRejectedValue(new Error('세션 한도 초과'));
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '재분석 005930' }));
  await screen.findByText(/재분석 실패: 세션 한도 초과/);
  expect(navigate).not.toHaveBeenCalledWith(expect.stringContaining('/workflow/'));
});

it('매수대기 큐 항목의 대기 취소 버튼이 cancelQueuedTrade를 호출한다 (dismissTrade 아님 — 대기 상태 취소만 처리)', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    pending_buy: {
      queue: [{ id: 'q1', session_id: 's3', ticker: '005930',
                stock_name: '삼성전자', action: 'BUY', entry_price: 260000,
                quantity: 10, status: 'pending' }],
      open_orders: [],
    },
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/매수대기 · 1/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '대기 취소' }));
  await waitFor(() => expect(cancelQueuedTrade).toHaveBeenCalledWith('q1'));
  expect(getOperations.mock.calls.length).toBeGreaterThanOrEqual(2); // 액션 후 재조회
});

it('큐에 대기 항목이 있으면 Process 버튼이 나타나고 클릭 시 processTradeQueue를 호출한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    pending_buy: {
      queue: [{ id: 'q2', session_id: 's4', ticker: '005930',
                stock_name: '삼성전자', action: 'BUY', entry_price: 260000,
                quantity: 10, status: 'pending' }],
      open_orders: [],
    },
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/매수대기 · 1/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'Process' }));
  await waitFor(() => expect(processTradeQueue).toHaveBeenCalled());
});

it('큐가 비어있으면 Process 버튼을 렌더하지 않는다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    pending_buy: {
      queue: [],
      open_orders: [{ order_id: 'o10', stk_cd: '005930', stk_nm: '삼성전자',
                      side: 'buy', price: 260000, quantity: 48,
                      remaining_quantity: 48, executed_quantity: 0,
                      created_at: null }],
    },
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/매수대기 · 1/)).toBeInTheDocument());
  expect(screen.queryByRole('button', { name: 'Process' })).not.toBeInTheDocument();
});

// -------------------------------------------
// FI-3: 감시 항목 provenance 배지 -- source='discovery'(regime-weighted
// ranking auto-promotion)는 "발굴" 배지, 'manual'/미지정은 무배지.
// -------------------------------------------

it('감시 항목의 source가 discovery이면 "발굴" 배지를 렌더한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    watching: [{
      id: 'watch-1', ticker: '005930', stock_name: '삼성전자',
      current_price: 71000, target_entry_price: 70000, confidence: 0.75, status: 'active',
      source: 'discovery',
    }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
  expect(screen.getByText('발굴')).toBeInTheDocument();
});

it('감시 항목의 source가 manual이면 배지를 렌더하지 않는다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    watching: [{
      id: 'watch-1', ticker: '005930', stock_name: '삼성전자',
      current_price: 71000, target_entry_price: 70000, confidence: 0.75, status: 'active',
      source: 'manual',
    }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
  expect(screen.queryByText('발굴')).not.toBeInTheDocument();
});

it('감시 항목에 source가 아예 없으면(레거시) manual과 동일하게 배지를 렌더하지 않는다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    watching: [{
      id: 'watch-1', ticker: '005930', stock_name: '삼성전자',
      current_price: 71000, target_entry_price: 70000, confidence: 0.75, status: 'active',
    }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
  expect(screen.queryByText('발굴')).not.toBeInTheDocument();
});

// -------------------------------------------
// T7 review HIGH #2: coin has no sessions[] array — a single active-session
// slot. Two concurrent AWAITING_APPROVAL coin sessions both render a row,
// but the slot can only ever reflect one. Before this fix, clicking the
// row that ISN'T the currently-focused one was a pure no-op (no store
// action existed to retarget the slot from a row the FE never started/
// streamed itself) — the second session's approval had no path. This pins
// that BOTH are individually reachable (one at a time, per the spec).
// -------------------------------------------

it('coin: 두 개의 동시 승인대기 세션이 있어도 각 행 클릭이 그 세션을 레일에 포커스한다 (두 번째 세션도 도달 가능)', async () => {
  useStore.setState({ activeMarket: 'coin' });
  getOperations.mockResolvedValue({
    ...BASE,
    awaiting: [
      { session_id: 'c1', ticker: 'KRW-BTC', name: '비트코인',
        proposal: { action: 'BUY', entry_price: 100_000_000, stop_loss: 95_000_000, take_profit: 110_000_000, risk_score: 4 },
        auto_approve_at: null },
      { session_id: 'c2', ticker: 'KRW-ETH', name: '이더리움',
        proposal: { action: 'BUY', entry_price: 4_000_000, stop_loss: 3_800_000, take_profit: 4_400_000, risk_score: 3 },
        auto_approve_at: null },
    ],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/승인대기 · 2/)).toBeInTheDocument());

  fireEvent.click(screen.getByText('비트코인'));
  expect(useStore.getState().coin.activeSessionId).toBe('c1');
  expect(useStore.getState().coin.tradeProposal).toMatchObject({ market: 'KRW-BTC', korean_name: '비트코인', entry_price: 100_000_000 });
  expect(useStore.getState().coin.awaitingApproval).toBe(true);
  expect(navigate).toHaveBeenCalledWith('/workflow/c1');

  fireEvent.click(screen.getByText('이더리움'));
  expect(useStore.getState().coin.activeSessionId).toBe('c2');
  expect(useStore.getState().coin.tradeProposal).toMatchObject({ market: 'KRW-ETH', korean_name: '이더리움', entry_price: 4_000_000 });
  expect(useStore.getState().coin.awaitingApproval).toBe(true);
  expect(navigate).toHaveBeenCalledWith('/workflow/c2');

  // Switching back to the first must retarget again (proves it's not stuck).
  fireEvent.click(screen.getByText('비트코인'));
  expect(useStore.getState().coin.activeSessionId).toBe('c1');
});

// -------------------------------------------
// Monitoring-cadence tuning (final task of the arc): the shared
// useOperations poll is the single biggest steady Kiwoom QUERY-budget
// consumer per the audit. Slow it to 10s and pause it while the tab is
// hidden — reclaiming budget for the autonomous monitoring loops when
// nobody's looking at the screen — while an immediate refetch on
// regaining visibility keeps the board from looking stale on return.
// -------------------------------------------
describe('useOperations 폴링 주기(10s) + 탭 가시성 게이팅', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function setVisibility(state: DocumentVisibilityState) {
    Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
  }

  it('폴 간격은 10_000ms — 9_999ms 경과로는 재조회 없음, +1ms에 재조회', async () => {
    getOperations.mockResolvedValue(BASE);
    setVisibility('visible');
    renderHook(() => useOperations());
    await act(() => vi.advanceTimersByTimeAsync(0)); // flush mount-time refetch(true)
    expect(getOperations).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(9_999));
    expect(getOperations).toHaveBeenCalledTimes(1); // still not due

    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(getOperations).toHaveBeenCalledTimes(2); // due at exactly 10_000ms
  });

  it('탭이 hidden이면 폴 타이머가 지나도 데이터 재조회를 하지 않는다', async () => {
    getOperations.mockResolvedValue(BASE);
    setVisibility('hidden');
    renderHook(() => useOperations());
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(getOperations).toHaveBeenCalledTimes(1); // mount refetch(true) unaffected by visibility

    await act(() => vi.advanceTimersByTimeAsync(30_000)); // 3 poll ticks worth, all hidden
    expect(getOperations).toHaveBeenCalledTimes(1); // no polling while hidden
  });

  it('hidden → visible 전환 시 visibilitychange 이벤트로 즉시 재조회한다', async () => {
    getOperations.mockResolvedValue(BASE);
    setVisibility('hidden');
    renderHook(() => useOperations());
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(getOperations).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(getOperations).toHaveBeenCalledTimes(1); // confirm still gated before the flip

    setVisibility('visible');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(getOperations).toHaveBeenCalledTimes(2); // immediate refetch on regaining visibility
  });
});
