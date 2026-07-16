/**
 * RiskParamsPanel — 전체 risk-params 편집 패널 (Task 4).
 *
 * 로드(GET /trading/risk-params) → 1건당 명목 상한(%) + totalEquity로 ₩환산
 * 표시 → 편집 → 저장(PUT, 변경분만 전송)까지의 왕복을 검증한다.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { it, expect, vi } from 'vitest';
import { RiskParamsPanel } from './RiskParamsPanel';
import * as client from '../../api/client';

vi.mock('../../api/client');

it('loads pct and shows KRW conversion, saves via PUT', async () => {
  vi.mocked(client.getTradingRiskParams).mockResolvedValue({
    max_trade_notional_pct: 15,
    max_single_position_pct: 0.15,
    min_cash_ratio: 0.2,
    max_daily_loss_pct: 3,
    max_open_positions: 5,
  } as any);
  vi.mocked(client.updateTradingRiskParams).mockResolvedValue({ status: 'updated' } as any);

  render(<RiskParamsPanel totalEquity={100_000_000} />);

  await waitFor(() => expect(screen.getByText(/15%/)).toBeInTheDocument());
  expect(screen.getByText(/₩15,000,000/)).toBeInTheDocument(); // 15% × 100M

  fireEvent.change(screen.getByLabelText(/1건당 명목/), { target: { value: '20' } });
  fireEvent.click(screen.getByText(/저장/));

  await waitFor(() =>
    expect(client.updateTradingRiskParams).toHaveBeenCalledWith(
      expect.objectContaining({ max_trade_notional_pct: 20 }),
    ),
  );
});

it('범위를 벗어난 명목 상한(%)은 저장을 막고 에러를 보여준다', async () => {
  vi.mocked(client.getTradingRiskParams).mockResolvedValue({
    max_trade_notional_pct: 15,
    max_single_position_pct: 0.15,
    min_cash_ratio: 0.2,
    max_daily_loss_pct: 3,
    max_open_positions: 5,
    stop_loss_mode: 'user_approval',
    take_profit_mode: 'user_approval',
  } as any);

  render(<RiskParamsPanel totalEquity={100_000_000} />);

  await waitFor(() => expect(screen.getByText(/15%/)).toBeInTheDocument());

  fireEvent.change(screen.getByLabelText(/1건당 명목/), { target: { value: '99' } });
  fireEvent.click(screen.getByText(/저장/));

  await waitFor(() => expect(screen.getByText(/0\.5.*50/)).toBeInTheDocument());
  expect(client.updateTradingRiskParams).not.toHaveBeenCalled();
});
