/**
 * Sidebar (mobile hamburger menu) — nav-rationalize, 2026-07-14.
 * The Sidebar used to hardcode its own 8-item nav list (missing `watchlist`,
 * with a stale "Charts" doc-comment) and could drift from the desktop
 * TerminalShell rail. It now renders directly from NAV_ITEMS (frontend/src/
 * nav.ts) — the same single source of truth as the rail and the ⌘K palette
 * — so the two can never disagree again.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { useStore } from '@/store';
import { NAV_ITEMS } from '@/nav';
import { Sidebar } from './Sidebar';

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>
  );
}

describe('Sidebar renders from NAV_ITEMS (single source)', () => {
  beforeEach(() => {
    useStore.setState({
      kiwoomApiConfigured: false,
      activeMarket: 'kiwoom',
    });
  });

  it('renders every NAV_ITEMS label', () => {
    renderSidebar();
    for (const item of NAV_ITEMS) {
      expect(screen.getByText(item.label)).toBeInTheDocument();
    }
  });

  it('renders exactly NAV_ITEMS.length primary nav buttons (no extra hardcoded entries)', () => {
    renderSidebar();
    for (const item of NAV_ITEMS) {
      expect(screen.getAllByText(item.label)).toHaveLength(1);
    }
  });

  it('does not render a "Charts" entry (stale — no Charts view exists)', () => {
    renderSidebar();
    expect(screen.queryByText('Charts')).not.toBeInTheDocument();
  });

  it('does not render "Scratchpad" or "Watchlist" (folded into the dashboard / removed)', () => {
    renderSidebar();
    expect(screen.queryByText('Scratchpad')).not.toBeInTheDocument();
    expect(screen.queryByText('Watchlist')).not.toBeInTheDocument();
  });
});
