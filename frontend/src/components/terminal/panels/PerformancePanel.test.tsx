import { it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const getPerformance = vi.fn();
vi.mock('@/api/client', () => ({
  getPerformance: (...a: unknown[]) => getPerformance(...a),
}));
vi.mock('@/hooks/useTradeNotifications', () => ({
  useTradeNotifications: () => ({ isConnected: true, notifications: [] }),
}));

import { PerformancePanel } from './PerformancePanel';

beforeEach(() => {
  vi.clearAllMocks();
});

it('실현손익·누적수익률·승률을 렌더한다', async () => {
  getPerformance.mockResolvedValue({
    pnl: {
      strt_dt: '20260613', end_dt: '20260713',
      realized_pnl_total: 140_000, commission: 400, tax: 800, net_pnl: 138_800,
      trade_days: 4, win_days: 2, loss_days: 1, flat_days: 1, win_rate_pct: 66.7,
      daily: [
        { dt: '20260706', pnl: 50_000, cumulative_pnl: 50_000 },
        { dt: '20260707', pnl: -30_000, cumulative_pnl: 20_000 },
        { dt: '20260708', pnl: 0, cumulative_pnl: 20_000 },
        { dt: '20260709', pnl: 120_000, cumulative_pnl: 140_000 },
      ],
    },
    asset: { current_asset: 500_140_000, base_asset: 500_000_000, cumulative_return_pct: 0.028 },
    errors: {},
  });
  render(<PerformancePanel />);
  await waitFor(() => expect(screen.getByText('140,000')).toBeInTheDocument());
  expect(screen.getByText('66.7%')).toBeInTheDocument();
  expect(screen.getByText(/\+0\.03%/)).toBeInTheDocument();
  expect(screen.getByText('500,140,000')).toBeInTheDocument();
  // daily curve renders one bar per day
  expect(document.querySelectorAll('rect').length).toBe(4);
});

it('pnl 섹션 실패 시 실현손익·승률·일별곡선은 조회 실패로 정직 강등하고 자산은 정상 렌더한다', async () => {
  getPerformance.mockResolvedValue({
    pnl: null,
    asset: { current_asset: 500_000_000, base_asset: 500_000_000, cumulative_return_pct: 0.0 },
    errors: { pnl: 'kiwoom down' },
  });
  render(<PerformancePanel />);
  await waitFor(() => expect(screen.getAllByText('조회 실패').length).toBeGreaterThan(0));
  // 실현손익 + 승률 둘 다 조회 실패로 표기 (0/가짜 값 위장 금지)
  expect(screen.getAllByText('조회 실패').length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText(/일별 곡선 조회 실패/)).toBeInTheDocument();
  // 자산 섹션은 살아있다
  expect(screen.getByText('500,000,000')).toBeInTheDocument();
});

it('asset 섹션 실패 시 누적수익률·현재자산만 조회 실패, 실현손익/승률은 정상 렌더한다', async () => {
  getPerformance.mockResolvedValue({
    pnl: {
      strt_dt: '20260706', end_dt: '20260706',
      realized_pnl_total: 10_000, commission: 0, tax: 0, net_pnl: 10_000,
      trade_days: 1, win_days: 1, loss_days: 0, flat_days: 0, win_rate_pct: 100.0,
      daily: [{ dt: '20260706', pnl: 10_000, cumulative_pnl: 10_000 }],
    },
    asset: null,
    errors: { asset: 'account down' },
  });
  render(<PerformancePanel />);
  await waitFor(() => expect(screen.getByText('10,000')).toBeInTheDocument());
  expect(screen.getByText('100.0%')).toBeInTheDocument();
  expect(screen.getAllByText('조회 실패').length).toBe(2); // 누적수익률 + 현재자산
});

it('기간 내 실현손익 발생일이 없으면 곡선은 가짜 평탄선 대신 정직한 빈 상태를 렌더한다', async () => {
  getPerformance.mockResolvedValue({
    pnl: {
      strt_dt: '20260706', end_dt: '20260713',
      realized_pnl_total: 0, commission: 0, tax: 0, net_pnl: 0,
      trade_days: 0, win_days: 0, loss_days: 0, flat_days: 0, win_rate_pct: null,
      daily: [],
    },
    asset: { current_asset: 500_000_000, base_asset: 500_000_000, cumulative_return_pct: 0.0 },
    errors: {},
  });
  render(<PerformancePanel />);
  await waitFor(() => expect(screen.getByText(/표시할 일별 손익 없음/)).toBeInTheDocument());
  // 승부 없음 -> 승률은 DASH, "조회 실패"로 위장하지 않는다
  expect(screen.getByText('—')).toBeInTheDocument();
  expect(document.querySelectorAll('rect').length).toBe(0);
});

it('로드 실패 시 오류 메시지를 정직하게 렌더한다', async () => {
  getPerformance.mockRejectedValue(new Error('network down'));
  render(<PerformancePanel />);
  await waitFor(() => expect(screen.getByText(/성과 로드 오류/)).toBeInTheDocument());
  expect(screen.getByText(/network down/)).toBeInTheDocument();
});
