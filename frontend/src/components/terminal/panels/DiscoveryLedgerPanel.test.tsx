/**
 * FI-4: 전용 발굴 조회 페이지 — 날짜/승격 필터, 후보 테이블, 전략별 성과
 * 요약, 로딩/빈/에러 상태를 검증한다. FI-2의 candidates/performance 라우트를
 * 소비하는 client.ts 함수는 @/api/client 목으로 대체(PerformancePanel.test.tsx
 * 관례와 동일) — 실제 axios/네트워크 무접촉.
 */
import { it, expect, vi, beforeEach, describe } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const getDiscoveryCandidates = vi.fn();
const getDiscoveryPerformance = vi.fn();
vi.mock('@/api/client', () => ({
  getDiscoveryCandidates: (...a: unknown[]) => getDiscoveryCandidates(...a),
  getDiscoveryPerformance: (...a: unknown[]) => getDiscoveryPerformance(...a),
}));

import { DiscoveryLedgerPanel, promotedFilterToParam } from './DiscoveryLedgerPanel';

function renderPanel() {
  return render(
    <MemoryRouter>
      <DiscoveryLedgerPanel />
    </MemoryRouter>
  );
}

const EMPTY_CANDIDATES = { candidates: [], count: 0 };
const EMPTY_PERFORMANCE = { days: 14, by_strategy_tag: {} };

const ONE_CANDIDATE = {
  candidates: [
    {
      id: 'x1', trade_date: '2026-07-18', ticker: '005930', name: '삼성전자',
      composite_score: 0.723, top_strategy_tag: 'momentum', regime_label: 'neutral',
      rank: 1, promoted: true, skip_reason: null, close_price: 70000,
      fwd_1d: 0.0123, fwd_5d: 0.03, fwd_20d: null,
    },
  ],
  count: 1,
};

const ONE_PERFORMANCE_BUCKET = {
  days: 14,
  by_strategy_tag: {
    momentum: { candidates: 2, promoted: 1, avg_fwd_1d: -0.005, avg_fwd_5d: 0.01, hit_rate_5d: 0.5 },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ── 필터 상태 로직(순수 함수, 렌더 무관) ─────────────────────────────
describe('promotedFilterToParam', () => {
  it("'all' -> undefined(필터 미적용)", () => {
    expect(promotedFilterToParam('all')).toBeUndefined();
  });
  it("'promoted' -> true", () => {
    expect(promotedFilterToParam('promoted')).toBe(true);
  });
  it("'skipped' -> false", () => {
    expect(promotedFilterToParam('skipped')).toBe(false);
  });
});

// ── 로딩/빈/에러 상태 ──────────────────────────────────────────────
it('빈 원장이면 "발굴 이력 없음"을 표시한다', async () => {
  getDiscoveryCandidates.mockResolvedValue(EMPTY_CANDIDATES);
  getDiscoveryPerformance.mockResolvedValue(EMPTY_PERFORMANCE);
  renderPanel();
  await waitFor(() => expect(screen.getByText('발굴 이력 없음')).toBeInTheDocument());
});

it('candidates 조회 실패 시 에러 상태를 표시한다', async () => {
  getDiscoveryCandidates.mockRejectedValue(new Error('network down'));
  getDiscoveryPerformance.mockResolvedValue(EMPTY_PERFORMANCE);
  renderPanel();
  await waitFor(() =>
    expect(screen.getByText('발굴 후보를 불러오지 못했습니다.')).toBeInTheDocument()
  );
});

it('performance 조회 실패 시 에러 상태를 표시한다', async () => {
  getDiscoveryCandidates.mockResolvedValue(EMPTY_CANDIDATES);
  getDiscoveryPerformance.mockRejectedValue(new Error('network down'));
  renderPanel();
  await waitFor(() =>
    expect(screen.getByText('전략별 성과를 불러오지 못했습니다.')).toBeInTheDocument()
  );
});

it('후보가 있으면 ticker·composite·전략태그·close_price·fwd를 렌더한다', async () => {
  getDiscoveryCandidates.mockResolvedValue(ONE_CANDIDATE);
  getDiscoveryPerformance.mockResolvedValue(EMPTY_PERFORMANCE);
  renderPanel();
  await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
  expect(screen.getByText('005930')).toBeInTheDocument();
  expect(screen.getByText('0.723')).toBeInTheDocument();
  expect(screen.getByText('momentum')).toBeInTheDocument();
  // fwd_1d = 0.0123 raw fraction -> +1.23% (NOT +0.01%, the fmtPct trap FI-3 flagged)
  expect(screen.getByText('+1.23%')).toBeInTheDocument();
});

it('전략별 성과 요약을 렌더한다', async () => {
  getDiscoveryCandidates.mockResolvedValue(EMPTY_CANDIDATES);
  getDiscoveryPerformance.mockResolvedValue(ONE_PERFORMANCE_BUCKET);
  renderPanel();
  await waitFor(() => expect(screen.getByText('momentum')).toBeInTheDocument());
  // hit_rate_5d = 0.5 raw fraction -> 50%
  expect(screen.getByText('50%')).toBeInTheDocument();
});

it('승격 필터 클릭 시 promoted=true로 재조회한다', async () => {
  getDiscoveryCandidates.mockResolvedValue(EMPTY_CANDIDATES);
  getDiscoveryPerformance.mockResolvedValue(EMPTY_PERFORMANCE);
  renderPanel();
  await waitFor(() => expect(getDiscoveryCandidates).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByText('승격만'));
  await waitFor(() =>
    expect(getDiscoveryCandidates).toHaveBeenLastCalledWith(
      expect.objectContaining({ promoted: true, offset: 0 })
    )
  );
});

it('날짜 선택 시 trade_date로 재조회한다', async () => {
  getDiscoveryCandidates.mockResolvedValue(EMPTY_CANDIDATES);
  getDiscoveryPerformance.mockResolvedValue(EMPTY_PERFORMANCE);
  renderPanel();
  await waitFor(() => expect(getDiscoveryCandidates).toHaveBeenCalledTimes(1));
  const dateInput = screen.getByLabelText('날짜');
  fireEvent.change(dateInput, { target: { value: '2026-07-18' } });
  await waitFor(() =>
    expect(getDiscoveryCandidates).toHaveBeenLastCalledWith(
      expect.objectContaining({ trade_date: '2026-07-18' })
    )
  );
});
