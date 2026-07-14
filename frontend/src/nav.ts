// frontend/src/nav.ts
// Single source of truth mapping app views <-> URL paths. The store no longer tracks the active view.
//
// Naming note (P2 funnel consolidation, T3): the word "Watchlist" belongs to
// the SERVER watch-list (WATCH decisions / scanner promotions, surfaced in
// OperationsPanel's "감시" column and the /trading WatchListWidget) — NOT the
// client-side research-staging list (`store.basket`). `basket` keeps its
// internal view key / URL (`/watchlist`) for now to minimize blast radius,
// but its user-facing label is "Scratchpad". The `watchlist` view key below
// is the (new) nav entry that actually targets the server list.
export type ViewKey =
  | 'dashboard' | 'analysis' | 'analysis-detail' | 'workflow'
  | 'positions' | 'basket' | 'watchlist' | 'scanner' | 'agent-chat'
  | 'trading' | 'trades';

/** Static path for a view. Detail views need a sessionId. */
export function viewToPath(view: ViewKey, sessionId?: string): string {
  switch (view) {
    case 'dashboard': return '/';
    case 'analysis': return '/analysis';
    case 'analysis-detail': return sessionId ? `/analysis/${sessionId}` : '/analysis';
    case 'workflow': return sessionId ? `/workflow/${sessionId}` : '/analysis';
    case 'positions': return '/positions';
    case 'basket': return '/watchlist';
    // Server watch-list still lives on /trading (WatchListWidget) — no
    // dedicated page yet — but it's disambiguated from the 'trading' (Auto-
    // trade) nav entry via a `?tab=watchlist` query param (P2-T5 nav-highlight
    // fix) so the two /trading-routed nav icons resolve to distinct
    // ViewKeys instead of both collapsing onto 'trading'.
    case 'watchlist': return '/trading?tab=watchlist';
    case 'scanner': return '/scanner';
    case 'agent-chat': return '/agent-chat';
    case 'trading': return '/trading';
    case 'trades': return '/trades';
  }
}

/**
 * Top-level view for a pathname (for nav active-state). `search` is the
 * location's query string (e.g. "?tab=watchlist") — needed because
 * 'trading' and 'watchlist' both route to the /trading path; without it,
 * the 'watchlist' nav icon could never highlight (P2-T5 fix, see
 * viewToPath above).
 */
export function pathToView(pathname: string, search = ''): ViewKey {
  if (pathname === '/' || pathname === '') return 'dashboard';
  if (pathname.startsWith('/analysis')) return 'analysis';
  if (pathname.startsWith('/workflow')) return 'analysis';
  if (pathname.startsWith('/positions')) return 'positions';
  if (pathname.startsWith('/watchlist')) return 'basket';
  if (pathname.startsWith('/scanner')) return 'scanner';
  if (pathname.startsWith('/agent-chat')) return 'agent-chat';
  if (pathname.startsWith('/trading')) {
    const params = new URLSearchParams(search);
    return params.get('tab') === 'watchlist' ? 'watchlist' : 'trading';
  }
  if (pathname.startsWith('/trades')) return 'trades';
  return 'dashboard';
}

/** Nav-rail order + labels (icons stay in TerminalShell). */
export const NAV_ITEMS: { view: ViewKey; label: string }[] = [
  { view: 'dashboard', label: 'Dashboard' },
  { view: 'analysis', label: 'Analysis' },
  { view: 'positions', label: 'Positions' },
  { view: 'basket', label: 'Scratchpad' },
  { view: 'watchlist', label: 'Watchlist' },
  { view: 'agent-chat', label: 'Agent Chat' },
  { view: 'scanner', label: 'Scanner' },
  { view: 'trading', label: 'Auto-trade' },
  { view: 'trades', label: 'Trades' },
];
