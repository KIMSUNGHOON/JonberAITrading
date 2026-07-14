/**
 * A2 (page-ux-improvements, 대안2): this panel used to source KR holdings
 * from `getKRStockPositions()` -> `GET /kr_stocks/positions`, which
 * hardcodes stop_loss=None/take_profit=None
 * (backend/app/api/routes/kr_stocks/positions.py) — SL/TP here was ALWAYS a
 * dash, and this page could disagree with the dashboard funnel's PIPELINE
 * `보유` column (OperationsPanel.tsx HoldingColumn), which reads the SAME
 * broker holding from `/operations` (enriched with coordinator/
 * PositionManager SL/TP). These tests pin: (1) SL/TP now renders from
 * `/operations` for a holding that has stops — using the same session
 * example from the page-UX audit (SK하이닉스, stop 1,810,560 / take
 * 2,125,440); (2) market is pinned to 'kiwoom' regardless of any global
 * active-market state; (3) missing SL/TP still degrades to a dash (no
 * fabrication); (4) the 청산 button still calls the full-close path
 * (closeKRStockPosition) untouched; (5) totals derive from the same
 * holdings (single source of truth); (6) a broker fetch failure degrades
 * honestly instead of faking an empty/zero portfolio.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { KiwoomPositionPanel } from './KiwoomPositionPanel';
import type { OperationsResponse } from '@/types';

const getOperations = vi.fn();
const closeKRStockPosition = vi.fn();
vi.mock('@/api/client', () => ({
  getOperations: (...a: unknown[]) => getOperations(...a),
  closeKRStockPosition: (...a: unknown[]) => closeKRStockPosition(...a),
}));

const BASE: OperationsResponse = {
  analyzing: [], awaiting: [], watching: [],
  pending_buy: { queue: [], open_orders: [] },
  holding: [], today_fills: [], errors: {},
};

function withHolding(overrides: Partial<OperationsResponse> = {}): OperationsResponse {
  return {
    ...BASE,
    holding: [
      {
        ticker: '000660', name: 'SK하이닉스', quantity: 10,
        avg_price: 1_900_000, current_price: 1_968_000,
        pnl: 680_000, pnl_pct: 3.58,
        stop_loss: 1_810_560, take_profit: 2_125_440,
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  closeKRStockPosition.mockResolvedValue({});
});

describe('KiwoomPositionPanel', () => {
  it('/operations의 SL/TP를 그대로 표시한다 (더 이상 항상 대시가 아님) — 퍼널 HoldingColumn과 동일 소스/값', async () => {
    getOperations.mockResolvedValue(withHolding());
    render(<KiwoomPositionPanel />);

    await waitFor(() => expect(screen.getByText('SK하이닉스')).toBeInTheDocument());
    expect(screen.getByText(/손절: 1,810,560원/)).toBeInTheDocument();
    expect(screen.getByText(/익절: 2,125,440원/)).toBeInTheDocument();
    // KR 전용 표면 — 어떤 activeMarket 상태와도 무관하게 항상 'kiwoom'로 조회.
    expect(getOperations).toHaveBeenCalledWith('kiwoom');
  });

  it('SL/TP가 없는 보유는 여전히 대시(생략)로 표시한다 — 없는 값을 조작하지 않는다', async () => {
    getOperations.mockResolvedValue(withHolding({
      holding: [{
        ticker: '005930', name: '삼성전자', quantity: 5,
        avg_price: 70_000, current_price: 71_000,
        pnl: 5_000, pnl_pct: 1.43,
        stop_loss: null, take_profit: null,
      }],
    }));
    render(<KiwoomPositionPanel />);
    await waitFor(() => expect(screen.getByText('삼성전자')).toBeInTheDocument());
    expect(screen.queryByText(/손절:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/익절:/)).not.toBeInTheDocument();
  });

  it('청산 버튼 확인 클릭 시 closeKRStockPosition(전량매도 경로, T1b)을 호출하고 재조회한다', async () => {
    getOperations.mockResolvedValue(withHolding());
    const onPositionClose = vi.fn();
    render(<KiwoomPositionPanel onPositionClose={onPositionClose} />);
    await waitFor(() => expect(screen.getByText('SK하이닉스')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: '포지션 청산' }));
    fireEvent.click(screen.getByRole('button', { name: '확인' }));

    await waitFor(() => expect(closeKRStockPosition).toHaveBeenCalledWith('000660'));
    await waitFor(() => expect(onPositionClose).toHaveBeenCalled());
    expect(getOperations.mock.calls.length).toBeGreaterThanOrEqual(2); // 청산 후 재조회
  });

  it('총 평가금액/총 손익 헤더를 동일 holdings로부터 계산해 표시한다 (별도 소스 없음 — 드리프트 불가)', async () => {
    getOperations.mockResolvedValue(withHolding());
    render(<KiwoomPositionPanel />);
    await waitFor(() => expect(screen.getByText('총 평가금액')).toBeInTheDocument());
    // 10주 * 1,968,000원 = 19,680,000원 -> "1968만원"
    expect(screen.getByText(/1968만원/)).toBeInTheDocument();
  });

  it('holding 조회 실패(null+errors.holding)는 정직하게 오류로 표시한다 (0 위장 금지)', async () => {
    getOperations.mockResolvedValue({ ...BASE, holding: null, errors: { holding: 'kiwoom down' } });
    render(<KiwoomPositionPanel />);
    await waitFor(() => expect(screen.getByText('kiwoom down')).toBeInTheDocument());
    expect(screen.getByText('보유 종목 없음')).toBeInTheDocument();
  });
});
