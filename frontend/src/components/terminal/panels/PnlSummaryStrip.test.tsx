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
    day: { pct: 0.0139, basis: 'prior_close' },
    week: { pct: 0.4692, basis: 'prior_close' },
    month: { pct: -0.4479, basis: 'base_asset' },
    total: { pct: -0.4479, basis: 'base_asset' },
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

it('실현손익 섹션만 실패하면 그 칸만 조회 실패로 강등한다', async () => {
  getPnlSummary.mockResolvedValue({
    ...FULL, realized: null, errors: { realized: 'ka10074 boom' },
  });
  render(<PnlSummaryStrip unrealized={213306} holdings={1} />);

  await waitFor(() => expect(screen.getAllByText('조회 실패')).toHaveLength(4));
  // 평가금 수익률은 살아 있다
  expect(screen.getByText('+0.01%')).toBeInTheDocument();
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
