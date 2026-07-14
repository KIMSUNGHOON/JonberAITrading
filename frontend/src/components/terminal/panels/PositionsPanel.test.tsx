/**
 * P1-4 discretionary control surface: inline STOP/TAKE edit + partial close
 * on the Positions tile. These pin the manual-override wiring — the
 * update/order client fns are called with the operator's entered values, and
 * malformed input (bad number, qty over the held amount) is rejected with a
 * visible row-level error rather than a silent no-op or a call to the API.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const getKRStockPositions = vi.fn();
const getCoinPositions = vi.fn();
const updatePositionStopLoss = vi.fn();
const updatePositionTakeProfit = vi.fn();
const createKRStockOrder = vi.fn();
const createCoinOrder = vi.fn();
vi.mock('@/api/client', () => ({
  getKRStockPositions: (...a: unknown[]) => getKRStockPositions(...a),
  getCoinPositions: (...a: unknown[]) => getCoinPositions(...a),
  updatePositionStopLoss: (...a: unknown[]) => updatePositionStopLoss(...a),
  updatePositionTakeProfit: (...a: unknown[]) => updatePositionTakeProfit(...a),
  createKRStockOrder: (...a: unknown[]) => createKRStockOrder(...a),
  createCoinOrder: (...a: unknown[]) => createCoinOrder(...a),
}));

import { useStore } from '@/store';
import { PositionsPanel, resolvePartialQty } from './PositionsPanel';

function krPosition(overrides: Record<string, unknown> = {}) {
  return {
    stk_cd: '005930',
    stk_nm: '삼성전자',
    quantity: 10,
    avg_entry_price: 70000,
    current_price: 71000,
    unrealized_pnl: 10000,
    unrealized_pnl_pct: 1.43,
    stop_loss: 68000,
    take_profit: 75000,
    session_id: null,
    created_at: '2026-07-13T00:00:00Z',
    ...overrides,
  };
}

function coinPosition(overrides: Record<string, unknown> = {}) {
  return {
    market: 'KRW-BTC',
    currency: 'BTC',
    quantity: 0.5,
    avg_entry_price: 50_000_000,
    current_price: 51_000_000,
    unrealized_pnl: 500_000,
    unrealized_pnl_pct: 2.0,
    stop_loss: null,
    take_profit: null,
    session_id: null,
    created_at: '2026-07-13T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({ activeMarket: 'kiwoom', chartSymbol: null } as never);
  getKRStockPositions.mockResolvedValue({ positions: [], total_value_krw: 0, total_pnl: 0, total_pnl_pct: 0 });
  getCoinPositions.mockResolvedValue({ positions: [], total_value_krw: 0, total_pnl: 0, total_pnl_pct: 0 });
});

describe('PositionsPanel — inline STOP/TAKE edit', () => {
  it('손절가를 편집하고 저장하면 updatePositionStopLoss가 새 값으로 호출된다', async () => {
    getKRStockPositions.mockResolvedValue({
      positions: [krPosition()], total_value_krw: 710000, total_pnl: 10000, total_pnl_pct: 1.43,
    });
    render(<PositionsPanel />);

    const stopInput = await screen.findByLabelText('손절가 편집 005930');
    fireEvent.change(stopInput, { target: { value: '65000' } });
    fireEvent.click(screen.getByLabelText('손절가 저장 005930'));

    await waitFor(() => expect(updatePositionStopLoss).toHaveBeenCalledWith('005930', 65000));
  });

  it('익절가를 편집하고 저장하면 updatePositionTakeProfit이 새 값으로 호출된다', async () => {
    getKRStockPositions.mockResolvedValue({
      positions: [krPosition()], total_value_krw: 710000, total_pnl: 10000, total_pnl_pct: 1.43,
    });
    render(<PositionsPanel />);

    const takeInput = await screen.findByLabelText('익절가 편집 005930');
    fireEvent.change(takeInput, { target: { value: '80000' } });
    fireEvent.click(screen.getByLabelText('익절가 저장 005930'));

    await waitFor(() => expect(updatePositionTakeProfit).toHaveBeenCalledWith('005930', 80000));
  });

  it('손절가에 숫자가 아닌 값을 저장하면 API를 호출하지 않고 행 오류를 보여준다', async () => {
    getKRStockPositions.mockResolvedValue({
      positions: [krPosition()], total_value_krw: 710000, total_pnl: 10000, total_pnl_pct: 1.43,
    });
    render(<PositionsPanel />);

    const stopInput = await screen.findByLabelText('손절가 편집 005930');
    fireEvent.change(stopInput, { target: { value: 'abc' } });
    fireEvent.click(screen.getByLabelText('손절가 저장 005930'));

    await waitFor(() => expect(screen.getByText(/손절가가 올바르지 않습니다/)).toBeInTheDocument());
    expect(updatePositionStopLoss).not.toHaveBeenCalled();
  });
});

describe('PositionsPanel — partial close', () => {
  it('수량을 입력하고 청산하면 createKRStockOrder가 매도 시장가로 호출된다', async () => {
    getKRStockPositions.mockResolvedValue({
      positions: [krPosition({ quantity: 10 })], total_value_krw: 710000, total_pnl: 10000, total_pnl_pct: 1.43,
    });
    createKRStockOrder.mockResolvedValue({});
    render(<PositionsPanel />);

    const qtyInput = await screen.findByLabelText('부분청산 수량 005930');
    fireEvent.change(qtyInput, { target: { value: '4' } });
    fireEvent.click(screen.getByLabelText('부분청산 실행 005930'));

    await waitFor(() =>
      expect(createKRStockOrder).toHaveBeenCalledWith({
        stk_cd: '005930', side: 'sell', ord_type: 'market', quantity: 4,
      }));
  });

  it('%를 입력하면 보유 수량 기준으로 계산된 코인 volume으로 createCoinOrder가 호출된다', async () => {
    useStore.setState({ activeMarket: 'coin', chartSymbol: null } as never);
    getCoinPositions.mockResolvedValue({
      positions: [coinPosition({ quantity: 0.5 })], total_value_krw: 25_000_000, total_pnl: 500_000, total_pnl_pct: 2.0,
    });
    createCoinOrder.mockResolvedValue({});
    render(<PositionsPanel />);

    const qtyInput = await screen.findByLabelText('부분청산 수량 KRW-BTC');
    fireEvent.change(qtyInput, { target: { value: '50%' } });
    fireEvent.click(screen.getByLabelText('부분청산 실행 KRW-BTC'));

    await waitFor(() =>
      expect(createCoinOrder).toHaveBeenCalledWith({
        market: 'KRW-BTC', side: 'ask', ord_type: 'market', volume: 0.25,
      }));
  });

  it('보유 수량을 초과하는 청산 수량은 거부되고 API를 호출하지 않는다', async () => {
    getKRStockPositions.mockResolvedValue({
      positions: [krPosition({ quantity: 10 })], total_value_krw: 710000, total_pnl: 10000, total_pnl_pct: 1.43,
    });
    render(<PositionsPanel />);

    const qtyInput = await screen.findByLabelText('부분청산 수량 005930');
    fireEvent.change(qtyInput, { target: { value: '999' } });
    fireEvent.click(screen.getByLabelText('부분청산 실행 005930'));

    await waitFor(() => expect(screen.getByText(/청산 수량\/비율이 올바르지 않습니다/)).toBeInTheDocument());
    expect(createKRStockOrder).not.toHaveBeenCalled();
  });
});

describe('resolvePartialQty', () => {
  it('정수 보유 수량에서 %를 정수로 내림 계산한다 (KR)', () => {
    expect(resolvePartialQty('50%', 7, true)).toBe(3);
  });
  it('코인은 분수 수량을 허용한다', () => {
    expect(resolvePartialQty('50%', 0.5, false)).toBe(0.25);
  });
  it('KR에서 소수 수량은 거부한다', () => {
    expect(resolvePartialQty('3.5', 10, true)).toBeNull();
  });
  it('보유 수량을 초과하면 거부한다', () => {
    expect(resolvePartialQty('11', 10, true)).toBeNull();
  });
  it('0/음수/빈 값을 거부한다', () => {
    expect(resolvePartialQty('0', 10, true)).toBeNull();
    expect(resolvePartialQty('-1', 10, true)).toBeNull();
    expect(resolvePartialQty('', 10, true)).toBeNull();
  });
  it('100%를 초과하는 비율을 거부한다', () => {
    expect(resolvePartialQty('150%', 10, false)).toBeNull();
  });
});
