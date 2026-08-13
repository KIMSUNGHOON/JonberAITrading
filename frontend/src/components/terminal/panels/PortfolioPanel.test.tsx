/**
 * P2-4 M1: PortfolioPanel's KR "평가손익" tile must agree with the Positions
 * tile (PositionsPanel), not diverge from it by the round-trip trading cost.
 *
 * Background: P1 (commit 6e6bf3f) wired `effective_pnl`/`effective_pnl_pct`
 * (net of KR commission + sell tax) into `GET /trading/operations` holdings
 * — the same response PositionsPanel/FunnelPanel already read. But this
 * tile still read `getKRStockAccount().total_profit_loss`, the broker's raw
 * GROSS `evlu_pfls_amt`, so an on-screen account 평가손익 would disagree
 * with the sum of the (now net) per-holding figures by exactly the
 * round-trip cost — the same class of "why don't these two numbers match"
 * bug this codebase has fixed twice before (ddfebb6, b283814).
 *
 * Fix: 평가손익 is now the SUM of `getOperations('kiwoom').holding[].pnl`
 * (one net source, shared with the holdings panels) instead of the
 * account's gross total. 총자산/보유/가용 are unchanged (still sourced from
 * getKRStockAccount — those have no gross/net ambiguity).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const getKRStockAccount = vi.fn();
const getOperations = vi.fn();
vi.mock('@/api/client', () => ({
  getKRStockAccount: (...a: unknown[]) => getKRStockAccount(...a),
  getOperations: (...a: unknown[]) => getOperations(...a),
}));

import { useStore } from '@/store';
import { PortfolioPanel } from './PortfolioPanel';

function krHolding(overrides: Record<string, unknown> = {}) {
  return {
    ticker: '005930',
    name: '삼성전자',
    quantity: 10,
    avg_price: 70000,
    current_price: 71000,
    // GROSS price-diff would be 10_000 (=(71000-70000)*10) — pnl below is
    // the NET figure (effective_pnl), deliberately different from that
    // gross number so a test that accidentally sums/reads gross would fail.
    pnl: 8_800,
    pnl_pct: 1.26,
    stop_loss: null,
    take_profit: null,
    ...overrides,
  };
}

// Mirrors OperationsResponse (frontend/src/types/index.ts).
function operationsResponse(
  holding: Array<Record<string, unknown>> | null,
  errors: Record<string, string> = {},
) {
  return {
    analyzing: null,
    awaiting: null,
    watching: null,
    pending_buy: { queue: null, open_orders: null },
    holding,
    today_fills: null,
    errors,
  };
}

function krAccount(overrides: Record<string, unknown> = {}) {
  return {
    cash: { deposit: 10_000_000, orderable_amount: 9_000_000, withdrawable_amount: 9_000_000 },
    holdings: [{ stk_cd: '005930', stk_nm: '삼성전자', quantity: 10, avg_buy_price: 70000, current_price: 71000, eval_amount: 710_000, profit_loss: 10_000, profit_loss_rate: 1.43 }],
    total_eval_amount: 710_000,
    // GROSS — must NOT be what the tile displays anymore.
    total_profit_loss: 10_000,
    total_profit_loss_rate: 1.43,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({ activeMarket: 'kiwoom' } as never);
  getKRStockAccount.mockResolvedValue(krAccount());
  getOperations.mockResolvedValue(operationsResponse([krHolding()]));
});

describe('PortfolioPanel — KR 평가손익 net-of-cost consistency (P2-4 M1)', () => {
  it('평가손익은 /operations 홀딩의 순손익(net) 합계이며, 계좌의 gross total_profit_loss가 아니다', async () => {
    render(<PortfolioPanel />);

    // net pnl (8,800, under the 만 compaction threshold) rendered, NOT the
    // gross account figure (10,000 -> '₩1만').
    expect(await screen.findByText('₩8,800')).toBeInTheDocument();
    expect(screen.queryByText('₩1만')).not.toBeInTheDocument();
  });

  it('여러 홀딩이 있으면 평가손익은 각 홀딩 pnl의 합(순손익)과 정확히 일치한다', async () => {
    getOperations.mockResolvedValue(
      operationsResponse([
        krHolding({ ticker: '005930', pnl: 120_000, avg_price: 70000, quantity: 10 }),
        krHolding({ ticker: '000660', pnl: -35_000, avg_price: 100000, quantity: 5 }),
      ]),
    );
    // Gross account total would be some other number (e.g. 100,000) — make
    // sure the tile does NOT show that.
    getKRStockAccount.mockResolvedValue(krAccount({ total_profit_loss: 100_000 }));
    render(<PortfolioPanel />);

    // net sum = 120,000 - 35,000 = 85,000 -> compact "₩9만" (85,000/10,000=8.5 -> toFixed(0) = '8' or '9'?)
    // fmtMoneyCompact: (85000/10000).toFixed(0) = '9' (8.5 rounds to 9 per standard rounding... verify banker's not used)
    await waitFor(() => expect(getOperations).toHaveBeenCalledWith('kiwoom'));
    const tile = await screen.findByText('평가손익');
    const valueEl = tile.parentElement?.querySelector('.text-\\[14px\\]');
    expect(valueEl?.textContent).toContain('₩9만'); // 85,000 net, not 100,000 gross (would be '₩10만')
  });

  it('/operations 조회가 실패하면(브로커 응답 없음) 평가손익은 gross 폴백 없이 DASH로 표시된다', async () => {
    getOperations.mockRejectedValue(new Error('네트워크 오류'));
    render(<PortfolioPanel />);

    await waitFor(() => expect(getKRStockAccount).toHaveBeenCalled());
    const tile = await screen.findByText('평가손익');
    const valueEl = tile.parentElement?.querySelector('.text-\\[14px\\]');
    await waitFor(() => expect(valueEl?.textContent).toBe('—'));
  });

  it('/operations가 holding=null(브로커 조회 실패)을 반환하면 평가손익은 DASH — gross 계좌 수치로 대체하지 않는다', async () => {
    getOperations.mockResolvedValue(operationsResponse(null, { holding: '브로커 응답 없음' }));
    render(<PortfolioPanel />);

    const tile = await screen.findByText('평가손익');
    const valueEl = tile.parentElement?.querySelector('.text-\\[14px\\]');
    await waitFor(() => expect(valueEl?.textContent).toBe('—'));
  });

  it('보유 홀딩이 없으면 평가손익은 0으로 표시된다(빈 배열도 정직한 net 값)', async () => {
    getOperations.mockResolvedValue(operationsResponse([]));
    render(<PortfolioPanel />);

    const tile = await screen.findByText('평가손익');
    const valueEl = tile.parentElement?.querySelector('.text-\\[14px\\]');
    await waitFor(() => expect(valueEl?.textContent).toContain('₩0'));
  });

  it('총자산/보유/가용은 여전히 getKRStockAccount에서 온다(변경 없음)', async () => {
    render(<PortfolioPanel />);

    expect(await screen.findByText('보유')).toBeInTheDocument();
    const holdingsTile = screen.getByText('보유').parentElement;
    await waitFor(() => expect(holdingsTile?.querySelector('.text-\\[14px\\]')?.textContent).toBe('1'));
  });
});
