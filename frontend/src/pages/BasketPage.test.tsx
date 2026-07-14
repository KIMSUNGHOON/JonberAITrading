/**
 * P2-T3: the client basket's user-facing label is "Scratchpad" — the word
 * "Watchlist" (and the old "Basket" wording) must not leak into its labels
 * anymore, since "Watchlist" now belongs to the SERVER watch-list (see
 * nav.ts). This pins the rendered labels on the full-page basket view.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { useStore } from '@/store';
import { BasketPage } from './BasketPage';

function renderBasketPage() {
  return render(
    <MemoryRouter>
      <BasketPage />
    </MemoryRouter>
  );
}

describe('BasketPage labels (P2-T3 basket → Scratchpad)', () => {
  // Keep the store's basket empty + APIs unconfigured so BasketWidget doesn't
  // attempt network calls on mount (see fetchCoinPrices/searchStocks guards).
  beforeEach(() => {
    useStore.setState({
      basket: { items: [], maxItems: 10, isUpdating: false },
      upbitApiConfigured: false,
      kiwoomApiConfigured: false,
    });
  });

  it('renders "Scratchpad" as the page/widget title', () => {
    renderBasketPage();
    expect(screen.getAllByText('Scratchpad').length).toBeGreaterThan(0);
  });

  it('never renders the old "My Basket"/"Basket" wording', () => {
    renderBasketPage();
    expect(screen.queryByText(/My Basket/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Basket$/i)).not.toBeInTheDocument();
  });

  it('never renders "Watchlist" — that word now belongs to the server watch-list', () => {
    renderBasketPage();
    expect(screen.queryByText(/Watchlist/i)).not.toBeInTheDocument();
  });

  it('shows the renamed empty-state copy, not the old 바스켓/관심종목 wording', () => {
    renderBasketPage();
    expect(screen.getByText('스크래치패드가 비어있습니다')).toBeInTheDocument();
    expect(screen.queryByText(/바스켓/)).not.toBeInTheDocument();
    expect(screen.queryByText(/관심종목/)).not.toBeInTheDocument();
  });
});
