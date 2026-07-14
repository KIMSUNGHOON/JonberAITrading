/**
 * FunnelPanel (P2 funnel-consolidation Task 5) — pins:
 *  - all 3 sections (DISCOVERY/WATCHLIST/PIPELINE) render together;
 *  - WATCHLIST rows dispatch convertWatchToQueue/removeFromWatchList keyed
 *    to the correct watch row (identified by ticker);
 *  - PIPELINE inherits OperationsPanel's per-section honest-degrade
 *    contract: one failed column shows "조회 실패" while an unrelated
 *    column that succeeded keeps rendering (no fabricated masking).
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
const dismissTrade = vi.fn().mockResolvedValue({});
const cancelKRStockOrder = vi.fn().mockResolvedValue({});

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
  dismissTrade: (...a: unknown[]) => dismissTrade(...a),
  cancelKRStockOrder: (...a: unknown[]) => cancelKRStockOrder(...a),
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
  useStore.setState({ basket: { items: [], maxItems: 10, isUpdating: false }, activeMarket: 'kiwoom' });
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

  it('승인 버튼이 submitApproval을 호출한다 (PIPELINE 재사용 확인)', async () => {
    getOperations.mockResolvedValue({
      ...OPERATIONS_BASE,
      awaiting: [{ session_id: 's2', ticker: '000660', name: 'SK하이닉스',
                   proposal: { action: 'WATCH', entry_price: 1968000,
                               stop_loss: 1810560, take_profit: 2125440, risk_score: 0.7 },
                   auto_approve_at: null }],
    });
    render(<FunnelPanel />);
    await waitFor(() => expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '승인' }));
    await waitFor(() =>
      expect(submitApproval).toHaveBeenCalledWith(
        expect.objectContaining({ session_id: 's2', decision: 'approved' })));
  });
});
