import { it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const getOperations = vi.fn();
const submitApproval = vi.fn().mockResolvedValue({});
const cancelKRStockOrder = vi.fn().mockResolvedValue({});
vi.mock('@/api/client', () => ({
  getOperations: (...a: unknown[]) => getOperations(...a),
  submitApproval: (...a: unknown[]) => submitApproval(...a),
  cancelKRStockSession: vi.fn(),
  convertWatchToQueue: vi.fn(),
  removeFromWatchList: vi.fn(),
  dismissTrade: vi.fn(),
  cancelKRStockOrder: (...a: unknown[]) => cancelKRStockOrder(...a),
}));
vi.mock('@/hooks/useTradeNotifications', () => ({
  useTradeNotifications: () => ({ isConnected: true, notifications: [] }),
}));
const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));
let mockState: Record<string, unknown>;
vi.mock('@/store', async () => {
  const actual = await vi.importActual<object>('@/store');
  return {
    ...actual,
    useStore: (sel: (s: unknown) => unknown) => sel(mockState),
  };
});

import { OperationsPanel } from './OperationsPanel';

const BASE = {
  analyzing: [], awaiting: [], watching: [],
  pending_buy: { queue: [], open_orders: [] },
  holding: [], today_fills: [], errors: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  mockState = { activeMarket: 'kiwoom' };
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

it('승인대기 항목의 승인 버튼이 submitApproval을 호출한다', async () => {
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
  fireEvent.click(screen.getByRole('button', { name: '승인' }));
  await waitFor(() =>
    expect(submitApproval).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: 's2', decision: 'approved' })));
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

it('거부 액션 실패 시 오류를 표시하고 컬럼은 계속 렌더한다', async () => {
  submitApproval.mockRejectedValueOnce(new Error('network down'));
  getOperations.mockResolvedValue({
    ...BASE,
    awaiting: [{ session_id: 's4', ticker: '000660', name: 'SK하이닉스',
                 proposal: { action: 'WATCH', entry_price: 1968000,
                             stop_loss: 1810560, take_profit: 2125440,
                             risk_score: 0.7 },
                 auto_approve_at: null }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '거부' }));
  await waitFor(() => expect(screen.getByText(/거부 실패/)).toBeInTheDocument());
  expect(screen.getByText(/network down/)).toBeInTheDocument();
  // 보드는 계속 렌더한다 — 오류가 컬럼을 가리지 않는다
  expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument();
});

it('승인대기 항목의 취소 버튼이 cancelled decision으로 submitApproval을 호출하고 재조회한다', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    awaiting: [{ session_id: 's5', ticker: '000660', name: 'SK하이닉스',
                 proposal: { action: 'WATCH', entry_price: 1968000,
                             stop_loss: 1810560, take_profit: 2125440,
                             risk_score: 0.7 },
                 auto_approve_at: null }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: '취소' }));
  await waitFor(() =>
    expect(submitApproval).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: 's5', decision: 'cancelled' })));
  expect(getOperations.mock.calls.length).toBeGreaterThanOrEqual(2); // 액션 후 재조회
});

it('actionable=false인 승인대기 항목은 승인/거부가 비활성화되고 취소만 가능하다 (좀비 부활 방지)', async () => {
  getOperations.mockResolvedValue({
    ...BASE,
    awaiting: [{ session_id: 's6', ticker: '005930', name: '삼성전자',
                 proposal: { action: 'BUY', entry_price: 70000 },
                 auto_approve_at: null, actionable: false }],
  });
  render(<OperationsPanel />);
  await waitFor(() => expect(screen.getByText(/승인대기 · 1/)).toBeInTheDocument());
  expect(screen.getByRole('button', { name: '승인' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '거부' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '취소' })).not.toBeDisabled();
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
