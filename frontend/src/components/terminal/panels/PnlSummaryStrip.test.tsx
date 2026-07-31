import { it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const getPnlSummary = vi.fn();
vi.mock('@/api/client', () => ({
  getPnlSummary: (...a: unknown[]) => getPnlSummary(...a),
}));

import { PnlSummaryStrip } from './PnlSummaryStrip';

const FULL = {
  realized: { day: 984533, week: 1403483, month: 1403483, total: 1403483 },
  equity_return: {
    day: { pct: 0.0139, basis: 'prior_close', trade_date: '2026-07-31' },
    week: { pct: 0.4692, basis: 'prior_close', trade_date: '2026-07-31' },
    month: { pct: -0.4479, basis: 'base_asset', trade_date: '2026-07-31' },
    total: { pct: -0.4479, basis: 'base_asset', trade_date: '2026-07-31' },
  },
  as_of: '2026-07-31',
  errors: {},
};

beforeEach(() => {
  getPnlSummary.mockReset();
});

it('네 버킷의 수익률과 실현손익을 보여준다', async () => {
  getPnlSummary.mockResolvedValue(FULL);
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  await waitFor(() => expect(screen.getByText('+0.01%')).toBeInTheDocument());
  expect(screen.getByText('+0.47%')).toBeInTheDocument();
  expect(screen.getAllByText('-0.45%')).toHaveLength(2); // 월간·누적
  expect(screen.getByText('+984,533')).toBeInTheDocument();
});

it('미실현손익과 보유 종목 수를 prop에서 그린다', async () => {
  getPnlSummary.mockResolvedValue(FULL);
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  await waitFor(() => expect(screen.getByText('+213,306')).toBeInTheDocument());
  expect(screen.getByText('1종목')).toBeInTheDocument();
});

it('기준자산이 분모인 버킷은 그 사실을 화면에 표기한다', async () => {
  getPnlSummary.mockResolvedValue(FULL);
  render(<PnlSummaryStrip unrealized={0} holdings={0} />);

  // 월간·누적 두 칸이 base_asset이다
  await waitFor(() => expect(screen.getAllByText('기준자산')).toHaveLength(2));
});

it('평가금 수익률 옆에 기준 거래일(trade_date)을 함께 표시한다 — 장중엔 직전 종가 기준임을 알 수 있게', async () => {
  getPnlSummary.mockResolvedValue(FULL);
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  // 네 버킷 모두 같은 스냅샷(07-31)에서 나왔다
  await waitFor(() => expect(screen.getAllByText('2026-07-31')).toHaveLength(4));
});

it('0%는 이웃 fmtPct와 같은 부호("+0.00%")로 표시된다(부호 없는 "0.00%" 아님)', async () => {
  getPnlSummary.mockResolvedValue({
    ...FULL,
    equity_return: {
      ...FULL.equity_return,
      day: { pct: 0, basis: 'prior_close', trade_date: '2026-07-31' },
    },
  });
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  await waitFor(() => expect(screen.getByText('+0.00%')).toBeInTheDocument());
  expect(screen.queryByText('0.00%')).not.toBeInTheDocument();
});

it('실현손익 섹션만 실패하면 그 칸만 조회 실패로 강등하고, 사유를 title로 보여주며 text-down으로 표시한다', async () => {
  getPnlSummary.mockResolvedValue({
    ...FULL, realized: null, errors: { realized: 'ka10074 boom' },
  });
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  const fails = await screen.findAllByText('조회 실패');
  expect(fails).toHaveLength(4);
  fails.forEach((el) => {
    expect(el).toHaveAttribute('title', 'ka10074 boom');
    expect(el).toHaveClass('text-down');
  });
  // 평가금 수익률은 살아 있다
  expect(screen.getByText('+0.01%')).toBeInTheDocument();
});

it('평가금 수익률 섹션만 실패하면 그 칸만 조회 실패로 강등하고, 사유를 title로 보여주며 text-down으로 표시한다', async () => {
  const reason = '평가금 스냅샷 없음 (또는 조회 실패 — 원인 구분 불가)';
  getPnlSummary.mockResolvedValue({
    ...FULL, equity_return: null, errors: { equity_return: reason },
  });
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  const fails = await screen.findAllByText('조회 실패');
  expect(fails).toHaveLength(4);
  fails.forEach((el) => {
    expect(el).toHaveAttribute('title', reason);
    expect(el).toHaveClass('text-down');
  });
  // 실현손익은 살아 있다
  expect(screen.getByText('+984,533')).toBeInTheDocument();
});

it('data_start 불명으로 누적이 월간과 같은 창이면 그 사실을 누적 칸의 title로 표시한다', async () => {
  const reason = '데이터 시작일 불명 — 누적이 이번 달로 제한됨';
  getPnlSummary.mockResolvedValue({
    ...FULL, errors: { realized_total_scope: reason },
  });
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  await waitFor(() => expect(screen.getAllByText('+1,403,483')).toHaveLength(3)); // 주·월·누적 동일값
  const marked = screen.getAllByText('+1,403,483').find((el) => el.getAttribute('title') === reason);
  expect(marked).toBeDefined();
});

it('미실현손익이 null이면 그 칸만 강등하고 버킷은 계속 보여준다', async () => {
  getPnlSummary.mockResolvedValue(FULL);
  render(<PnlSummaryStrip unrealized={null} holdings={0} />);

  await waitFor(() => expect(screen.getByText('+0.01%')).toBeInTheDocument());
  expect(screen.getByText('조회 실패')).toBeInTheDocument();
});

it('요청 자체가 실패해도 미실현손익은 계속 보여준다', async () => {
  getPnlSummary.mockRejectedValue(new Error('네트워크 실패'));
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  await waitFor(() => expect(screen.getByText('+213,306')).toBeInTheDocument());
  expect(screen.getAllByText('조회 실패').length).toBeGreaterThan(0);
});
