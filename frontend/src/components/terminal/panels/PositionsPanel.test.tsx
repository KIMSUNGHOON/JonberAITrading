/**
 * P1-4 discretionary control surface: inline STOP/TAKE edit + full close on
 * the Positions tile.
 *
 * T7 review fixes pinned here (see .superpowers/sdd/task-7-fix-findings.md):
 * - C1: a backend failure on SL/TP save (e.g. an unwatched/unstored ticker)
 *   surfaces as a real row error, never a silent success.
 * - M2: after a successful save, the field reverts to the server-fetched
 *   value on the next refetch — this is what reveals a no-op, instead of
 *   the input echoing the typed value forever.
 * - C2: 청산 is full-close only (closeKRStockPosition/closeCoinPosition, the
 *   only routes that actually reduce/delete the stored position), guarded
 *   by a two-click confirm. The old qty/%-based partial close (a raw sell
 *   order that never touched the position store) is gone.
 *
 * Cleanup Task B (dashboard-widget-cull audit §C-5, 2026-07-14): KR rows now
 * come from `getOperations('kiwoom')`, NOT `getKRStockPositions()` (the
 * latter hardcodes stop_loss/take_profit to null server-side, so a saved
 * STOP/TAKE edit used to self-revert to blank on the very next refetch).
 * `getOperations` is mocked in its place below; `getKRStockPositions` is no
 * longer imported by the component and is deliberately NOT mocked here — if
 * a regression reintroduces the old import, the real (unmocked) client call
 * would surface as a test failure.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const getOperations = vi.fn();
const getCoinPositions = vi.fn();
const updatePositionStopLoss = vi.fn();
const updatePositionTakeProfit = vi.fn();
const closeKRStockPosition = vi.fn();
const closeCoinPosition = vi.fn();
vi.mock('@/api/client', () => ({
  getOperations: (...a: unknown[]) => getOperations(...a),
  getCoinPositions: (...a: unknown[]) => getCoinPositions(...a),
  updatePositionStopLoss: (...a: unknown[]) => updatePositionStopLoss(...a),
  updatePositionTakeProfit: (...a: unknown[]) => updatePositionTakeProfit(...a),
  closeKRStockPosition: (...a: unknown[]) => closeKRStockPosition(...a),
  closeCoinPosition: (...a: unknown[]) => closeCoinPosition(...a),
}));


import { useStore } from '@/store';
import { PositionsPanel } from './PositionsPanel';

function krHolding(overrides: Record<string, unknown> = {}) {
  return {
    ticker: '005930',
    name: '삼성전자',
    quantity: 10,
    avg_price: 70000,
    current_price: 71000,
    pnl: 10000,
    pnl_pct: 1.43,
    stop_loss: 68000,
    take_profit: 75000,
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

function positionsResponse(positions: Array<Record<string, unknown>>) {
  return { positions, total_value_krw: 0, total_pnl: 0, total_pnl_pct: 0 };
}

// Mirrors OperationsResponse (frontend/src/types/index.ts) — `holding: null`
// with no `errors.holding` entry only happens for market='coin' (see
// get_operations' market != "kiwoom" early return), so for these
// market='kiwoom' tests a null `holding` is always paired with an error.
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

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({ activeMarket: 'kiwoom', chartSymbol: null } as never);
  getOperations.mockResolvedValue(operationsResponse([]));
  getCoinPositions.mockResolvedValue(positionsResponse([]));
});

describe('PositionsPanel — inline STOP/TAKE edit', () => {
  it('손절가를 편집하고 저장하면 updatePositionStopLoss가 새 값으로 호출된다', async () => {
    getOperations.mockResolvedValue(operationsResponse([krHolding()]));
    render(<PositionsPanel />);

    const stopInput = await screen.findByLabelText('손절가 편집 005930');
    fireEvent.change(stopInput, { target: { value: '65000' } });
    fireEvent.click(screen.getByLabelText('손절가 저장 005930'));

    await waitFor(() => expect(updatePositionStopLoss).toHaveBeenCalledWith('005930', 65000));
  });

  it('익절가를 편집하고 저장하면 updatePositionTakeProfit이 새 값으로 호출된다', async () => {
    getOperations.mockResolvedValue(operationsResponse([krHolding()]));
    render(<PositionsPanel />);

    const takeInput = await screen.findByLabelText('익절가 편집 005930');
    fireEvent.change(takeInput, { target: { value: '80000' } });
    fireEvent.click(screen.getByLabelText('익절가 저장 005930'));

    await waitFor(() => expect(updatePositionTakeProfit).toHaveBeenCalledWith('005930', 80000));
  });

  it('손절가에 숫자가 아닌 값을 저장하면 API를 호출하지 않고 행 오류를 보여준다', async () => {
    getOperations.mockResolvedValue(operationsResponse([krHolding()]));
    render(<PositionsPanel />);

    const stopInput = await screen.findByLabelText('손절가 편집 005930');
    fireEvent.change(stopInput, { target: { value: 'abc' } });
    fireEvent.click(screen.getByLabelText('손절가 저장 005930'));

    await waitFor(() => expect(screen.getByText(/손절가가 올바르지 않습니다/)).toBeInTheDocument());
    expect(updatePositionStopLoss).not.toHaveBeenCalled();
  });

  it('C1: 백엔드가 저장 실패를 반환하면(예: 미배선 종목) 성공으로 위장하지 않고 오류를 그대로 보여준다', async () => {
    getOperations.mockResolvedValue(operationsResponse([krHolding()]));
    updatePositionStopLoss.mockRejectedValue(
      new Error('활성 리스크 관리 대상이 아니며 저장된 포지션도 없습니다: 005930')
    );
    render(<PositionsPanel />);

    const stopInput = await screen.findByLabelText('손절가 편집 005930');
    fireEvent.change(stopInput, { target: { value: '65000' } });
    fireEvent.click(screen.getByLabelText('손절가 저장 005930'));

    await waitFor(() =>
      expect(screen.getByText(/활성 리스크 관리 대상이 아니며 저장된 포지션도 없습니다/)).toBeInTheDocument()
    );
    // The row must not have been silently marked as saved — the typed value
    // stays visible (it was never confirmed), not reverted as if it worked.
    expect(stopInput).toHaveValue('65000');
  });

  it('M2: 저장 성공 후 refetch 결과가 그대로면(사실상 무효 처리) 필드가 서버 값으로 되돌아간다 — 편집값을 무기한 에코하지 않는다', async () => {
    // Simulates the exact bug this fix closes: the update call resolves
    // ("success"), but the position that comes back from the next refetch
    // still has the OLD stop_loss — a no-op the field must reveal rather
    // than hide by continuing to display the operator's typed value.
    getOperations
      .mockResolvedValueOnce(operationsResponse([krHolding({ stop_loss: 68000 })])) // initial load
      .mockResolvedValueOnce(operationsResponse([krHolding({ stop_loss: 68000 })])); // post-save refetch
    updatePositionStopLoss.mockResolvedValue({ status: 'updated', ticker: '005930', stop_loss: 65000 });
    render(<PositionsPanel />);

    const stopInput = await screen.findByLabelText('손절가 편집 005930');
    fireEvent.change(stopInput, { target: { value: '65000' } });
    fireEvent.click(screen.getByLabelText('손절가 저장 005930'));

    await waitFor(() => expect(updatePositionStopLoss).toHaveBeenCalledWith('005930', 65000));
    await waitFor(() => expect(stopInput).toHaveValue('68000'));
  });

  it('M2: 저장 성공 후 refetch가 새 값을 반영하면 필드가 그 값으로 갱신된다', async () => {
    getOperations
      .mockResolvedValueOnce(operationsResponse([krHolding({ stop_loss: 68000 })]))
      .mockResolvedValueOnce(operationsResponse([krHolding({ stop_loss: 65000 })]));
    updatePositionStopLoss.mockResolvedValue({ status: 'updated', ticker: '005930', stop_loss: 65000 });
    render(<PositionsPanel />);

    const stopInput = await screen.findByLabelText('손절가 편집 005930');
    fireEvent.change(stopInput, { target: { value: '65000' } });
    fireEvent.click(screen.getByLabelText('손절가 저장 005930'));

    await waitFor(() => expect(stopInput).toHaveValue('65000'));
  });

  it('cleanup-B (§C-5): KR 포지션은 getOperations(\'kiwoom\')에서 조회하며 SL/TP가 항상 null이 아니라 실제 값으로 렌더된다', async () => {
    getOperations.mockResolvedValue(
      operationsResponse([krHolding({ stop_loss: 68000, take_profit: 75000 })]),
    );
    render(<PositionsPanel />);

    expect(await screen.findByLabelText('손절가 편집 005930')).toHaveValue('68000');
    expect(screen.getByLabelText('익절가 편집 005930')).toHaveValue('75000');
    expect(getOperations).toHaveBeenCalledWith('kiwoom');
  });

  it('cleanup-B (§C-5): 저장한 STOP 값이 /operations 재조회 결과에 반영되면 자기-되돌림 없이 그 값으로 표시된다(자기-되돌림 버그 회귀 방지)', async () => {
    // Before the fix, the refetch always hit /kr_stocks/positions, which
    // hardcodes stop_loss=None server-side — so a save that DID take effect
    // (in coordinator.risk_monitor._watching) would still read back blank on
    // the panel, looking like the save was ignored. With /operations wired
    // in, a save that's reflected there round-trips to the saved value.
    getOperations
      .mockResolvedValueOnce(operationsResponse([krHolding({ stop_loss: null })])) // initial: no stop yet
      .mockResolvedValueOnce(operationsResponse([krHolding({ stop_loss: 66500 })])); // post-save: risk_monitor now has it
    updatePositionStopLoss.mockResolvedValue({ status: 'updated', ticker: '005930', stop_loss: 66500 });
    render(<PositionsPanel />);

    const stopInput = await screen.findByLabelText('손절가 편집 005930');
    expect(stopInput).toHaveValue('');
    fireEvent.change(stopInput, { target: { value: '66500' } });
    fireEvent.click(screen.getByLabelText('손절가 저장 005930'));

    await waitFor(() => expect(updatePositionStopLoss).toHaveBeenCalledWith('005930', 66500));
    // The field must show the saved value, NOT revert to blank.
    await waitFor(() => expect(stopInput).toHaveValue('66500'));
  });

  it('cleanup-B: /operations가 holding=null과 errors.holding을 반환하면(브로커 조회 실패) 정직하게 오류를 보여준다', async () => {
    getOperations.mockResolvedValue(operationsResponse(null, { holding: '브로커 응답 없음' }));
    render(<PositionsPanel />);

    await waitFor(() => expect(screen.getByText(/브로커 응답 없음/)).toBeInTheDocument());
  });
});

describe('PositionsPanel — full close only (C2: partial close removed)', () => {
  it('청산 버튼은 두 번 클릭해야 실제 청산(closeKRStockPosition)이 호출된다', async () => {
    getOperations.mockResolvedValue(operationsResponse([krHolding({ quantity: 10 })]));
    closeKRStockPosition.mockResolvedValue({});
    render(<PositionsPanel />);

    const btn = await screen.findByLabelText('전량청산 005930');
    fireEvent.click(btn);
    expect(closeKRStockPosition).not.toHaveBeenCalled();
    expect(btn).toHaveTextContent('확인?');

    fireEvent.click(btn);
    await waitFor(() => expect(closeKRStockPosition).toHaveBeenCalledWith('005930'));
  });

  it('코인 시장에서는 closeCoinPosition이 호출된다', async () => {
    useStore.setState({ activeMarket: 'coin', chartSymbol: null } as never);
    getCoinPositions.mockResolvedValue(positionsResponse([coinPosition()]));
    closeCoinPosition.mockResolvedValue({});
    render(<PositionsPanel />);

    const btn = await screen.findByLabelText('전량청산 KRW-BTC');
    fireEvent.click(btn);
    fireEvent.click(btn);

    await waitFor(() => expect(closeCoinPosition).toHaveBeenCalledWith('KRW-BTC'));
  });

  it('청산 성공 후 refetch로 포지션이 사라지면 낡은 수량이 남지 않는다(오버셀 방지)', async () => {
    getOperations
      .mockResolvedValueOnce(operationsResponse([krHolding({ quantity: 10 })]))
      .mockResolvedValueOnce(operationsResponse([]));
    closeKRStockPosition.mockResolvedValue({});
    render(<PositionsPanel />);

    const btn = await screen.findByLabelText('전량청산 005930');
    fireEvent.click(btn);
    fireEvent.click(btn);

    await waitFor(() => expect(closeKRStockPosition).toHaveBeenCalledWith('005930'));
    await waitFor(() => expect(screen.getByText(/보유 포지션 없음/)).toBeInTheDocument());
  });

  it('청산 실패 시 오류를 보여주고 재확인 상태로 되돌리지 않는 낡은 상태를 남기지 않는다', async () => {
    getOperations.mockResolvedValue(operationsResponse([krHolding({ quantity: 10 })]));
    closeKRStockPosition.mockRejectedValue(new Error('청산 실패: 네트워크 오류'));
    render(<PositionsPanel />);

    const btn = await screen.findByLabelText('전량청산 005930');
    fireEvent.click(btn);
    fireEvent.click(btn);

    await waitFor(() => expect(screen.getByText(/청산 실패/)).toBeInTheDocument());
  });
});
