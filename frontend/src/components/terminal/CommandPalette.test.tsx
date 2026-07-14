/**
 * M1 (T7 review): :buy/:sell used to be fire-and-forget — the palette
 * closed immediately after running the command and neither success nor
 * failure of the underlying order-create call was ever surfaced to the
 * operator. These tests pin the fix: a visible toast reports the real
 * outcome, and it survives the palette closing (which happens synchronously,
 * well before the order promise settles).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const createKRStockOrder = vi.fn();
const createCoinOrder = vi.fn();
vi.mock('@/api/client', () => ({
  createKRStockOrder: (...a: unknown[]) => createKRStockOrder(...a),
  createCoinOrder: (...a: unknown[]) => createCoinOrder(...a),
  startScan: vi.fn(),
  startAgentChatDiscussion: vi.fn(),
}));

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => navigate,
  useLocation: () => ({ pathname: '/' }),
}));

import { useStore } from '@/store';
import { CommandPalette } from './CommandPalette';

const PLACEHOLDER = ':analyze 005930 · :go positions · posi';

function typeAndRun(cmd: string) {
  const input = screen.getByPlaceholderText(PLACEHOLDER);
  fireEvent.change(input, { target: { value: cmd } });
  fireEvent.keyDown(input, { key: 'Enter' });
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({ activeMarket: 'kiwoom' } as never);
});

describe('CommandPalette — :buy/:sell result feedback', () => {
  it('주문 성공 시 접수 완료 토스트를 보여준다', async () => {
    createKRStockOrder.mockResolvedValue({ order_id: 'mock-1', status: 'completed' });
    render(<CommandPalette open onClose={() => {}} />);

    typeAndRun(':buy 005930 10');

    await waitFor(() => expect(createKRStockOrder).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/:buy 005930 10 주문 접수 완료/)).toBeInTheDocument());
  });

  it('주문 실패 시 실패 사유를 담은 토스트를 보여준다(무음 실패 없음)', async () => {
    createKRStockOrder.mockRejectedValue(new Error('잔고 부족'));
    render(<CommandPalette open onClose={() => {}} />);

    typeAndRun(':sell 005930 10');

    await waitFor(() => expect(createKRStockOrder).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/:sell 005930 주문 실패: 잔고 부족/)).toBeInTheDocument());
  });

  it('코인 시장에서도 주문 결과를 보여준다', async () => {
    useStore.setState({ activeMarket: 'coin' } as never);
    createCoinOrder.mockResolvedValue({});
    render(<CommandPalette open onClose={() => {}} />);

    typeAndRun(':sell KRW-BTC 0.5 50000000');

    await waitFor(() => expect(createCoinOrder).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/:sell KRW-BTC 0\.5 @ 50000000 주문 접수 완료/)).toBeInTheDocument());
  });

  it('팔레트가 닫힌 후에도(onClose가 동기 호출됨) 주문 결과 토스트는 살아남는다', async () => {
    createKRStockOrder.mockResolvedValue({});
    const onClose = vi.fn();
    const { rerender } = render(<CommandPalette open onClose={onClose} />);

    typeAndRun(':buy 005930 10');
    expect(onClose).toHaveBeenCalled();

    // Simulate the parent actually closing the palette (open -> false) —
    // the component instance itself stays mounted (TerminalShell always
    // renders <CommandPalette>), so its local toast state must survive.
    rerender(<CommandPalette open={false} onClose={onClose} />);

    await waitFor(() => expect(screen.getByText(/주문 접수 완료/)).toBeInTheDocument());
  });
});
