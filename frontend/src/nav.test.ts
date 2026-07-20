// frontend/src/nav.test.ts
import { describe, it, expect } from 'vitest';
import { viewToPath, pathToView, NAV_ITEMS } from './nav';

describe('nav map', () => {
  it('maps views to paths', () => {
    expect(viewToPath('dashboard')).toBe('/');
    expect(viewToPath('positions')).toBe('/positions');
    expect(viewToPath('scanner')).toBe('/scanner');
    expect(viewToPath('workflow', 'abc')).toBe('/workflow/abc');
    expect(viewToPath('analysis-detail', 'xyz')).toBe('/analysis/xyz');
    expect(viewToPath('workflow')).toBe('/analysis'); // no id -> list
  });

  it('derives the top-level view from a pathname', () => {
    expect(pathToView('/')).toBe('dashboard');
    expect(pathToView('/positions')).toBe('positions');
    expect(pathToView('/scanner')).toBe('scanner');
    expect(pathToView('/analysis/abc')).toBe('analysis');
    expect(pathToView('/workflow/abc')).toBe('analysis');
    expect(pathToView('/trading')).toBe('trading');
    expect(pathToView('/unknown')).toBe('dashboard');
  });

  // Nav rationalize (2026-07-14, docs/superpowers/audits/2026-07-14-dashboard
  // -widget-cull.md, user-approved): the standalone Scratchpad page (`basket`
  // view, /watchlist route) was folded into the dashboard's DISCOVERY
  // Scratchpad section, and the duplicate `watchlist` nav item (which
  // rendered the dashboard identically via a `?tab=` query param nobody
  // consumed except its own nav-highlight) was removed alongside it.
  describe('basket/watchlist removal (nav-rationalize)', () => {
    it('NAV_ITEMS no longer has a "basket" entry', () => {
      expect(NAV_ITEMS.some((n) => (n.view as string) === 'basket')).toBe(false);
    });

    it('NAV_ITEMS no longer has a "Watchlist"-labeled entry', () => {
      expect(NAV_ITEMS.some((n) => n.label === 'Watchlist')).toBe(false);
    });

    // FI-4 (2026-07-20) added the 'discovery' ledger page as an 8th
    // nav-rail/⌘K entry -- this pin was bumped from 7 to 8 alongside it.
    it('NAV_ITEMS has exactly 8 items in the expected order', () => {
      expect(NAV_ITEMS.map((n) => n.view)).toEqual([
        'dashboard', 'analysis', 'positions', 'agent-chat', 'scanner', 'discovery', 'trading', 'trades',
      ]);
    });

    it('/watchlist is no longer a resolvable path (falls back to dashboard)', () => {
      expect(pathToView('/watchlist')).toBe('dashboard');
    });
  });
});
