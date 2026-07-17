import { it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const getPerformance = vi.fn();
const getEodReport = vi.fn();
vi.mock('@/api/client', () => ({
  getPerformance: (...a: unknown[]) => getPerformance(...a),
  getEodReport: (...a: unknown[]) => getEodReport(...a),
}));
vi.mock('@/hooks/useTradeNotifications', () => ({
  useTradeNotifications: () => ({ isConnected: true, notifications: [] }),
}));

import { PerformancePanel } from './PerformancePanel';

// Minimal getPerformance payload for the E3-5 EOD-report-focused tests below
// -- their assertions are about the EOD section, not the KPI header, so this
// mirrors the "기간 내 실현손익 발생일이 없으면…" test's shape (asset/pnl both
// present but empty/zeroed) rather than duplicating a richer fixture.
const MINIMAL_PERFORMANCE = {
  pnl: {
    strt_dt: '20260716', end_dt: '20260716',
    realized_pnl_total: 0, commission: 0, tax: 0, net_pnl: 0,
    trade_days: 0, win_days: 0, loss_days: 0, flat_days: 0, win_rate_pct: null,
    daily: [],
  },
  asset: { current_asset: 500_000_000, base_asset: 500_000_000, cumulative_return_pct: 0.0 },
  errors: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  // Every pre-existing test below predates the EOD section (E3-5) and never
  // configures getEodReport itself -- default it to the quiet "no report
  // yet" empty state so those tests keep exercising ONLY the KPI/curve
  // behavior they were written for.
  getEodReport.mockResolvedValue(null);
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

// -------------------------------------------
// E3-5: EOD 리포트 섹션
// -------------------------------------------

const EOD_DIGEST_FIXTURE = {
  trade_date: '20260716',
  watch: [
    {
      ticker: '005930', stock_name: '삼성전자', signal: 'BUY', confidence: 0.82,
      current_price: 71000, target_entry_price: 70000, gap_pct: 1.43,
    },
  ],
  account: {
    deposit: 12_000_000, total_equity: 500_140_000,
    daily_realized_pnl: 140_000, cumulative_return_pct: 0.03,
  },
  holdings: [
    {
      ticker: '000660', stock_name: 'SK하이닉스', quantity: 10,
      avg_price: 200_000, current_price: 210_000,
      unrealized_pnl: 100_000, unrealized_pnl_pct: 5.0,
      stop_loss: 190_000, take_profit: 230_000,
    },
  ],
  strategy: {
    stance: 'BULLISH', rationale_excerpt: '단기 모멘텀 강세로 판단',
    key_knobs: { stop_loss_pct: -3.0, take_profit_pct: 6.0, max_position_pct: 20.0, max_trade_notional_pct: 10.0 },
    changed: true,
  },
  regime: { label: 'RISK_ON', index_kospi_chg_pct: 0.8, index_kosdaq_chg_pct: 1.1 },
};

it('EOD 리포트: narrative가 있으면 본문을 렌더하고 staleness_note 경고줄도 함께 표시한다', async () => {
  getPerformance.mockResolvedValue(MINIMAL_PERFORMANCE);
  getEodReport.mockResolvedValue({
    trade_date: '20260716',
    created_at: '2026-07-16T09:00:00+09:00',
    digest: {
      ...EOD_DIGEST_FIXTURE,
      staleness_note: 'digest의 strategy는 20260715 기준 최신 리비전/스냅샷이며, 요청한 20260716와 다를 수 있습니다.',
    },
    narrative: '오늘 코스피는 강보합 마감했습니다. 삼성전자 관심종목 진입 신호가 유지되고 있습니다.',
  });
  render(<PerformancePanel />);
  await waitFor(() => expect(screen.getByText(/오늘 코스피는 강보합/)).toBeInTheDocument());
  expect(screen.getByText(/digest의 strategy는 20260715 기준/)).toBeInTheDocument();
  // narrative 경로에서는 digest 4블록 폴백 콘텐츠가 함께 렌더되지 않는다
  expect(screen.queryByText('SK하이닉스')).not.toBeInTheDocument();
});

it('EOD 리포트: narrative가 없으면 digest 4블록(워치·잔고·보유·전략) 템플릿을 렌더한다', async () => {
  getPerformance.mockResolvedValue(MINIMAL_PERFORMANCE);
  getEodReport.mockResolvedValue({
    trade_date: '20260716',
    created_at: '2026-07-16T09:00:00+09:00',
    digest: EOD_DIGEST_FIXTURE,
    narrative: null,
  });
  render(<PerformancePanel />);
  // 워치 표
  await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
  // 보유 표
  expect(screen.getByText('SK하이닉스')).toBeInTheDocument();
  // 전략 스탠스+노브
  expect(screen.getByText('BULLISH')).toBeInTheDocument();
  expect(screen.getByText('단기 모멘텀 강세로 판단')).toBeInTheDocument();
  // 잔고 카드 (총평가 — KPI 헤더의 현재자산 500,000,000과 구별되는 값)
  expect(screen.getByText('500,140,000')).toBeInTheDocument();
});

it('EOD 리포트: 아직 리포트가 없으면(404→null) 조용한 빈 상태를 렌더한다', async () => {
  getPerformance.mockResolvedValue(MINIMAL_PERFORMANCE);
  getEodReport.mockResolvedValue(null);
  render(<PerformancePanel />);
  await waitFor(() => expect(screen.getByText('아직 리포트 없음')).toBeInTheDocument());
});

