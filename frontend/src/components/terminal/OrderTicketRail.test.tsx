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
