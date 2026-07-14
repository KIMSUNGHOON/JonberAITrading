/**
 * FunnelPanel (P2 funnel-consolidation Task 5) — pins:
 *  - all 3 sections (DISCOVERY/WATCHLIST/PIPELINE) render together;
 *  - WATCHLIST rows dispatch convertWatchToQueue/removeFromWatchList keyed
 *    to the correct watch row (identified by ticker);
 *  - PIPELINE inherits OperationsPanel's per-section honest-degrade
 *    contract: one failed column shows "조회 실패" while an unrelated
 *    column that succeeded keeps rendering (no fabricated masking).
 *  - actionError (T5 review MEDIUM fix): the shared `useOperationsActions`
 *    banner is rendered ONCE at the panel level (not nested under the
 *    WATCHLIST header), since it's set by PIPELINE-only handlers
 *    (분석 취소/대기 취소/주문 취소) just as much as WATCHLIST's
 *    (큐 전환/제거) — see "actionError banner" describe block below.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// ---- DiscoverySection's deps (DISCOVERY section) ----
const startScan = vi.fn();
const pauseScan = vi.fn();
const resumeScan = vi.fn();
const stopScan = vi.fn();
const getScanProgress = vi.fn();
const getScanResults = vi.fn();
const addToWatchList = vi.fn();
const searchKRStocks = vi.fn();

// ---- OperationsPanel's deps (WATCHLIST + PIPELINE sections) ----
const getOperations = vi.fn();
const submitApproval = vi.fn().mockResolvedValue({});
const cancelKRStockSession = vi.fn().mockResolvedValue({});
const convertWatchToQueue = vi.fn().mockResolvedValue({});
const removeFromWatchList = vi.fn().mockResolvedValue({});
const cancelKRStockOrder = vi.fn().mockResolvedValue({});
// Task 8b: backported from the removed /trading TradeQueueWidget.
const cancelQueuedTrade = vi.fn().mockResolvedValue({});
const processTradeQueue = vi.fn().mockResolvedValue({});

vi.mock('@/api/client', () => ({
  startScan: (...a: unknown[]) => startScan(...a),
  pauseScan: (...a: unknown[]) => pauseScan(...a),
  resumeScan: (...a: unknown[]) => resumeScan(...a),
  stopScan: (...a: unknown[]) => stopScan(...a),
  getScanProgress: (...a: unknown[]) => getScanProgress(...a),
  getScanResults: (...a: unknown[]) => getScanResults(...a),
  addToWatchList: (...a: unknown[]) => addToWatchList(...a),
  searchKRStocks: (...a: unknown[]) => searchKRStocks(...a),
  getOperations: (...a: unknown[]) => getOperations(...a),
  submitApproval: (...a: unknown[]) => submitApproval(...a),
  cancelKRStockSession: (...a: unknown[]) => cancelKRStockSession(...a),
  convertWatchToQueue: (...a: unknown[]) => convertWatchToQueue(...a),
  removeFromWatchList: (...a: unknown[]) => removeFromWatchList(...a),
  cancelKRStockOrder: (...a: unknown[]) => cancelKRStockOrder(...a),
  cancelQueuedTrade: (...a: unknown[]) => cancelQueuedTrade(...a),
  processTradeQueue: (...a: unknown[]) => processTradeQueue(...a),
}));

const mockStart = vi.fn();
vi.mock('@/hooks/useStartAnalysis', () => ({
  useStartAnalysis: () => mockStart,
}));

vi.mock('@/hooks/useTradeNotifications', () => ({
  useTradeNotifications: () => ({ isConnected: true, notifications: [] }),
}));

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));

import { useStore } from '@/store';
import { FunnelPanel } from './FunnelPanel';

const OPERATIONS_BASE = {
  analyzing: [], awaiting: [], watching: [],
  pending_buy: { queue: [], open_orders: [] },
  holding: [], today_fills: [], errors: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  getScanProgress.mockResolvedValue({
    status: 'idle', total_stocks: 0, completed: 0, in_progress: 0, failed: 0,
    progress_pct: 0, current_stocks: [], buy_count: 0, sell_count: 0, hold_count: 0,
    watch_count: 0, avoid_count: 0, started_at: null, estimated_completion: null,
    completed_at: null, last_scan_date: null, last_error: null,
  });
  getScanResults.mockResolvedValue({ results: [], count: 0, total: 0, filter: null });
  searchKRStocks.mockResolvedValue({ stocks: [], total: 0 });
  getOperations.mockResolvedValue({ ...OPERATIONS_BASE });
  useStore.setState({
    basket: { items: [], maxItems: 10, isUpdating: false },
    activeMarket: 'kiwoom',
    // T7 review HIGH #1/#2: reset both market slices so each test starts
    // from a clean sessions[]/activeSessionId — a real singleton store
    // otherwise carries a prior test's injected/focused session forward.
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

describe('FunnelPanel — assembly', () => {
  it('renders all 3 sections: DISCOVERY, WATCHLIST, PIPELINE', async () => {
    render(<FunnelPanel />);
    expect(screen.getByText(/DISCOVERY/)).toBeInTheDocument();
    expect(screen.getByText(/WATCHLIST/)).toBeInTheDocument();
    expect(screen.getByText(/PIPELINE/)).toBeInTheDocument();
    // DISCOVERY is the real DiscoverySection (Task 4), not a stub.
    expect(screen.getByRole('button', { name: /스캔 시작/ })).toBeInTheDocument();
    await waitFor(() => expect(getOperations).toHaveBeenCalled());
  });
});

describe('FunnelPanel — WATCHLIST section (server SSOT)', () => {
  it('[큐 전환] calls convertWatchToQueue with the watch id of the clicked ticker row', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      watching: [{
        id: 'watch-1', ticker: '005930', stock_name: '삼성전자',
        current_price: 71000, target_entry_price: 70000, confidence: 0.75, status: 'active',
      }],
    });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /큐 전환.*005930/ }));
    await waitFor(() =>
      expect(convertWatchToQueue).toHaveBeenCalledWith({ watch_id: 'watch-1' }));
  });

  it('[제거] calls removeFromWatchList with the watch id of the clicked ticker row', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      watching: [{
        id: 'watch-2', ticker: '000660', stock_name: 'SK하이닉스',
        current_price: 180000, target_entry_price: 175000, confidence: 0.6, status: 'active',
      }],
    });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText('SK하이닉스')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /제거.*000660/ }));
    await waitFor(() => expect(removeFromWatchList).toHaveBeenCalledWith('watch-2'));
  });

  it('renders confidence and status alongside ticker/target_entry', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      watching: [{
        id: 'watch-3', ticker: '005930', stock_name: '삼성전자',
        current_price: 71000, target_entry_price: 70000, confidence: 0.82, status: 'active',
      }],
    });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
    expect(screen.getByText(/82%/)).toBeInTheDocument();
    expect(screen.getByText(/ACTIVE/)).toBeInTheDocument();
  });

  // Task 8b: backported from the removed /trading WatchListWidget — verifies
  // the action is reachable from FunnelPanel too (shared WatchingColumn),
  // not just OperationsPanel.
  it('[재분석] calls useStartAnalysis\'s start with kiwoom/ticker/name and navigates to the new session', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      watching: [{
        id: 'watch-4', ticker: '005930', stock_name: '삼성전자',
        current_price: 71000, target_entry_price: 70000, confidence: 0.75, status: 'active',
      }],
    });
    mockStart.mockResolvedValue({ sessionId: 'session-99', duplicate: false, positionExists: false });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /재분석.*005930/ }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledWith('kiwoom', '005930', '삼성전자'));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/workflow/session-99'));
  });
});

describe('FunnelPanel — actionError banner (panel-level, T5 review MEDIUM fix)', () => {
  it('a PIPELINE cancel-action failure (분석 취소) surfaces the error banner at the panel level, not nested under the WATCHLIST header', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      analyzing: [{ session_id: 's1', ticker: '005930', name: '삼성전자',
                    status: 'running', current_stage: 'technical_analysis', started_at: null }],
    });
    cancelKRStockSession.mockRejectedValueOnce(new Error('네트워크 오류'));
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText(/분석중 · 1/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: '분석 취소' }));
    const errorBanner = await screen.findByText(/분석 취소 실패: 네트워크 오류/);

    // Must precede (not be nested under) the WATCHLIST section header —
    // i.e. render at the panel level, not mislabeled as a WATCHLIST error.
    const watchlistHeader = screen.getByText(/WATCHLIST/);
    const bannerFollowsWatchlist = Boolean(
      watchlistHeader.compareDocumentPosition(errorBanner) & Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(bannerFollowsWatchlist).toBe(false);
    // It's the panel's first rendered element (above even DISCOVERY).
    expect(errorBanner.closest('[class*="border-hairline"]')?.previousElementSibling).toBeNull();
  });

  it('a WATCHLIST action failure (감시 제거) still shows the panel-level error banner', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      watching: [{
        id: 'watch-9', ticker: '005930', stock_name: '삼성전자',
        current_price: 71000, target_entry_price: 70000, confidence: 0.75, status: 'active',
      }],
    });
    removeFromWatchList.mockRejectedValueOnce(new Error('서버 오류'));
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /제거.*005930/ }));
    const errorBanner = await screen.findByText(/감시 제거 실패: 서버 오류/);
    // Dismissable, same as before.
    fireEvent.click(screen.getByRole('button', { name: '오류 닫기' }));
    await waitFor(() => expect(errorBanner).not.toBeInTheDocument());
  });
});

describe('FunnelPanel — PIPELINE section (honest-degrade preserved)', () => {
  it('a failed column (매수대기) shows 조회 실패 while an unaffected column (분석중) keeps rendering', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      analyzing: [{ session_id: 's1', ticker: '005930', name: '삼성전자',
                    status: 'running', current_stage: 'technical_analysis', started_at: null }],
      pending_buy: { queue: null, open_orders: [] },
      errors: { queue: 'coordinator unavailable' },
    });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText(/매수대기 · 조회 실패/)).toBeInTheDocument());
    // The failure in one column must not mask the other, healthy column.
    expect(screen.getByText(/분석중 · 1/)).toBeInTheDocument();
    // No fabricated "0" count for the failed column.
    expect(screen.queryByText(/매수대기 · 0/)).not.toBeInTheDocument();
  });

  // Task 7 (P2 funnel-consolidation): PIPELINE's 승인대기 column no longer
  // has its own 승인/거부/취소 buttons — with FunnelPanel now ALSO reusing
  // AwaitingColumn (Task 5), that would have been a THIRD place the same
  // submitApproval endpoint was directly reachable from (alongside
  // OperationsPanel and the global OrderTicketRail). Clicking a row here
  // only focuses the session + navigates to its workflow view, where the
  // rail is docked and handles the actual decision.
  //
  // T7 review HIGH #1 fix: this session is deliberately NOT in
  // kiwoom.sessions[] (FunnelPanel never called startKiwoomSession/
  // addKiwoomSession for it — it reached AWAITING_APPROVAL purely via the
  // /operations poll, e.g. an autonomous trigger this tab never streamed).
  // The pre-fix handler would have silently no-op'd here; asserting on the
  // REAL store (imported above, not a bare-fn mock) is what makes that
  // regression visible.
  it('승인대기 항목에는 승인/거부/취소 버튼이 없다 — 클릭하면 캐시에 없는 세션도 레일에 포커스하고 이동한다 (PIPELINE 재사용, 캐시 miss 봉합 확인)', async () => {
    expect(useStore.getState().kiwoom.sessions.find((s) => s.sessionId === 's2')).toBeUndefined();
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      awaiting: [{ session_id: 's2', ticker: '000660', name: 'SK하이닉스',
                   proposal: { action: 'WATCH', entry_price: 1968000,
                               stop_loss: 1810560, take_profit: 2125440, risk_score: 0.7 },
                   auto_approve_at: null }],
    });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: '승인' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '거부' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '취소' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('SK하이닉스'));
    expect(navigate).toHaveBeenCalledWith('/workflow/s2');
    expect(submitApproval).not.toHaveBeenCalled();

    const state = useStore.getState();
    expect(state.kiwoom.activeSessionId).toBe('s2'); // NOT a silent no-op
    expect(state.kiwoom.sessions.find((s) => s.sessionId === 's2')).toBeTruthy();
    expect(state.kiwoom.awaitingApproval).toBe(true);
    expect(state.kiwoom.tradeProposal).toMatchObject({ action: 'WATCH', entry_price: 1968000 });
  });

  // Task 8b: backported from the removed /trading TradeQueueWidget —
  // verifies both actions are reachable from FunnelPanel too (shared
  // PendingBuyColumn), not just OperationsPanel.
  it('[대기 취소] calls cancelQueuedTrade with the queue id of the pending trade', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      pending_buy: {
        queue: [{ id: 'q1', session_id: 's3', ticker: '005930',
                  stock_name: '삼성전자', action: 'BUY', entry_price: 260000,
                  quantity: 10, status: 'pending' }],
        open_orders: [],
      },
    });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText(/매수대기 · 1/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '대기 취소' }));
    await waitFor(() => expect(cancelQueuedTrade).toHaveBeenCalledWith('q1'));
  });

  it('[Process] appears when the queue has a pending trade and calls processTradeQueue', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      pending_buy: {
        queue: [{ id: 'q2', session_id: 's4', ticker: '005930',
                  stock_name: '삼성전자', action: 'BUY', entry_price: 260000,
                  quantity: 10, status: 'pending' }],
        open_orders: [],
      },
    });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText(/매수대기 · 1/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Process' }));
    await waitFor(() => expect(processTradeQueue).toHaveBeenCalled());
  });
});
