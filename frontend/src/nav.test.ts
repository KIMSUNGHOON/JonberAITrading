// frontend/src/nav.test.ts
import { describe, it, expect } from 'vitest';
import { viewToPath, pathToView, NAV_ITEMS } from './nav';

describe('nav map', () => {
  it('maps views to paths', () => {
    expect(viewToPath('dashboard')).toBe('/');
    expect(viewToPath('positions')).toBe('/positions');
    expect(viewToPath('basket')).toBe('/watchlist');
    expect(viewToPath('workflow', 'abc')).toBe('/workflow/abc');
    expect(viewToPath('analysis-detail', 'xyz')).toBe('/analysis/xyz');
    expect(viewToPath('workflow')).toBe('/analysis'); // no id -> list
  });
  it('derives the top-level view from a pathname', () => {
    expect(pathToView('/')).toBe('dashboard');
    expect(pathToView('/positions')).toBe('positions');
    expect(pathToView('/watchlist')).toBe('basket');
    expect(pathToView('/analysis/abc')).toBe('analysis');
    expect(pathToView('/workflow/abc')).toBe('analysis');
    expect(pathToView('/unknown')).toBe('dashboard');
  });

  // P2-T3: the word "Watchlist" belongs to the SERVER watch-list, not the
  // client basket — the nav rail must reflect the split.
  describe('basket → Scratchpad / Watchlist re-point (P2-T3)', () => {
    it('labels the client basket entry "Scratchpad", not "Watchlist"/"Basket"', () => {
      const basketItem = NAV_ITEMS.find((n) => n.view === 'basket');
      expect(basketItem?.label).toBe('Scratchpad');
    });

    it('has a distinct "Watchlist" nav entry that targets the server watch-list view, not the basket page', () => {
      const watchlistItem = NAV_ITEMS.find((n) => n.label === 'Watchlist');
      expect(watchlistItem).toBeDefined();
      expect(watchlistItem?.view).not.toBe('basket');
      expect(viewToPath(watchlistItem!.view)).not.toBe('/watchlist');
      // Today the server watch-list lives on /trading (WatchListWidget).
      expect(viewToPath('watchlist')).toBe('/trading');
    });

    it('no nav entry is labeled "Basket" anymore', () => {
      expect(NAV_ITEMS.some((n) => n.label === 'Basket')).toBe(false);
    });
  });
});
