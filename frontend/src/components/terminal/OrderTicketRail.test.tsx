import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { OrderTicketRail } from './OrderTicketRail';

// Controlled store: `useStore` runs the real selector against `mockState`, so
// `mockState` must carry the same shape `getMarketData` expects
// (`activeMarket` + the per-market slice), not the resolved selector outputs.
let mockState: Record<string, unknown>;
vi.mock('@/store', async () => {
  const actual = await vi.importActual<any>('@/store');
  return {
    ...actual,
    useStore: (selector: (s: any) => unknown) => selector(mockState),
  };
});
vi.mock('@/hooks/useMarketHours', () => ({
  useMarketHours: () => ({ status: null, countdownFormatted: '', nextEventFormatted: '' }),
}));

beforeEach(() => {
  mockState = {
    activeMarket: 'stock',
    stock: {
      tradeProposal: null,
      activeSessionId: null,
      status: 'idle',
      currentStage: null,
    },
  };
});

describe('OrderTicketRail — idle', () => {
  it('shows NO PENDING ORDER when no active proposal', () => {
    render(<OrderTicketRail />);
    expect(screen.getByText('NO PENDING ORDER')).toBeInTheDocument();
  });
});

describe('OrderTicketRail — active', () => {
  it('renders the ticket: ACTION, symbol, SL/TP, risk, buttons', () => {
    mockState = {
      activeMarket: 'stock',
      stock: {
        tradeProposal: {
          id: 'p1',
          ticker: 'AAPL',
          action: 'BUY',
          quantity: 10,
          entry_price: 100,
          stop_loss: 90,
          take_profit: 120,
          risk_score: 5,
          position_size_pct: 10,
          rationale: 'Strong momentum with support at 95.',
          bull_case: 'Upside case',
          bear_case: 'Downside case',
          created_at: new Date().toISOString(),
        },
        activeSessionId: 'session-1',
        status: 'awaiting_approval',
        currentStage: null,
      },
    };
    render(<OrderTicketRail />);
    expect(screen.getByText('BUY')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('Medium Risk')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reject|re-analyze/i })).toBeInTheDocument();
  });
});
