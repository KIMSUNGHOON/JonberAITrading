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
    // Server watch-list has no dedicated page yet (funnel task, P2-T5) — it
    // lives on /trading (WatchListWidget) today, so route there.
    case 'watchlist': return '/trading';
    case 'scanner': return '/scanner';
    case 'agent-chat': return '/agent-chat';
    case 'trading': return '/trading';
    case 'trades': return '/trades';
  }
}

/** Top-level view for a pathname (for nav active-state). */
export function pathToView(pathname: string): ViewKey {
  if (pathname === '/' || pathname === '') return 'dashboard';
  if (pathname.startsWith('/analysis')) return 'analysis';
  if (pathname.startsWith('/workflow')) return 'analysis';
  if (pathname.startsWith('/positions')) return 'positions';
  if (pathname.startsWith('/watchlist')) return 'basket';
  if (pathname.startsWith('/scanner')) return 'scanner';
  if (pathname.startsWith('/agent-chat')) return 'agent-chat';
  // /trading is shared by 'trading' (Auto-trade controls) and 'watchlist'
  // (server watch-list nav entry) — 'trading' wins for active-state until
  // the funnel task gives the watch-list its own route.
  if (pathname.startsWith('/trading')) return 'trading';
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
