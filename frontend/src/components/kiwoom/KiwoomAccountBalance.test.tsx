/**
 * A1 (page-ux-improvements, 대안2): the account card is account-summary-only.
 *
 * The left "계좌 정보/계좌 요약" card used to also render a "보유 종목"
 * mini-list (stk_nm/quantity/profit_loss_rate) duplicating the same kt00004
 * holdings shown in the right KiwoomPositionPanel. This test pins that the
 * mini-list is gone while the account-summary numbers (총자산/예수금/주식
 * 평가) still render correctly from the same holdings-bearing response.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { KiwoomAccountBalance } from './KiwoomAccountBalance';
import type { KRStockAccountResponse } from '@/types';

const getKRStockAccount = vi.fn();
vi.mock('@/api/client', () => ({
  getKRStockAccount: (...a: unknown[]) => getKRStockAccount(...a),
}));

function baseAccount(overrides: Partial<KRStockAccountResponse> = {}): KRStockAccountResponse {
  return {
    cash: {
      deposit: 10_000_000,
      orderable_amount: 9_000_000,
      withdrawable_amount: 9_000_000,
    },
    holdings: [
      {
        stk_cd: '005930',
        stk_nm: '삼성전자',
        quantity: 10,
        avg_buy_price: 70_000,
        current_price: 71_000,
        eval_amount: 710_000,
        profit_loss: 10_000,
        profit_loss_rate: 1.43,
      },
    ],
    total_eval_amount: 710_000,
    total_profit_loss: 10_000,
    total_profit_loss_rate: 1.43,
    ...overrides,
  };
}

beforeEach(() => {
  getKRStockAccount.mockReset();
});

describe('KiwoomAccountBalance', () => {
  it('renders account-summary values without the per-holding mini-list', async () => {
    getKRStockAccount.mockResolvedValue(baseAccount());
    render(<KiwoomAccountBalance />);

    // Account summary must still render (총자산/예수금/주식평가).
    await waitFor(() => expect(screen.getByText('계좌 요약')).toBeInTheDocument());
    expect(screen.getByText('총 자산')).toBeInTheDocument();
    expect(screen.getByText('예수금')).toBeInTheDocument();
    expect(screen.getByText('주식 평가')).toBeInTheDocument();
    expect(screen.getByText('1종목 보유')).toBeInTheDocument();

    // The duplicate "보유 종목" mini-list (name/qty/pnl% per holding) must
    // be gone — neither the section label nor a per-holding row renders.
    expect(screen.queryByText('보유 종목')).not.toBeInTheDocument();
    expect(screen.queryByText('삼성전자')).not.toBeInTheDocument();
    expect(screen.queryByText('10주')).not.toBeInTheDocument();
  });

  it('renders the account summary even with zero holdings', async () => {
    getKRStockAccount.mockResolvedValue(
      baseAccount({ holdings: [], total_eval_amount: 0, total_profit_loss: 0, total_profit_loss_rate: 0 }),
    );
    render(<KiwoomAccountBalance />);

    await waitFor(() => expect(screen.getByText('계좌 요약')).toBeInTheDocument());
    expect(screen.getByText('0종목 보유')).toBeInTheDocument();
    expect(screen.queryByText('보유 종목')).not.toBeInTheDocument();
  });
});
