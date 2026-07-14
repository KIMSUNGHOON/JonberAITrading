// frontend/src/nav.ts
// Single source of truth mapping app views <-> URL paths. The store no longer tracks the active view.
//
// Nav rationalization (2026-07-14, docs/superpowers/audits/2026-07-14-dashboard-widget-cull.md
// §C-6/§C-7, user-approved): the standalone Scratchpad page (`basket` view,
// /watchlist route, BasketPage/BasketWidget) was folded into the dashboard's
// DISCOVERY Scratchpad section — its client-side research-staging list
// (`store.basket`) is now ONLY ever surfaced there. The duplicate `watchlist`
// nav item (which rendered the dashboard identically via a `?tab=` query
// param nobody consumed except its own nav-highlight) was removed alongside
// it. The SERVER watch-list still lives in the dashboard funnel's WATCHLIST
// section (FunnelPanel/OperationsPanel columns) — it just no longer has its
// own nav-rail icon or page.
export type ViewKey =
  | 'dashboard' | 'analysis' | 'analysis-detail' | 'workflow'
  | 'positions' | 'scanner' | 'agent-chat'
  | 'trading' | 'trades';

/** Static path for a view. Detail views need a sessionId. */
export function viewToPath(view: ViewKey, sessionId?: string): string {
  switch (view) {
    case 'dashboard': return '/';
    case 'analysis': return '/analysis';
    case 'analysis-detail': return sessionId ? `/analysis/${sessionId}` : '/analysis';
    case 'workflow': return sessionId ? `/workflow/${sessionId}` : '/analysis';
    case 'positions': return '/positions';
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
  if (pathname.startsWith('/scanner')) return 'scanner';
  if (pathname.startsWith('/agent-chat')) return 'agent-chat';
  if (pathname.startsWith('/trading')) return 'trading';
  if (pathname.startsWith('/trades')) return 'trades';
  return 'dashboard';
}

/** Nav-rail order + labels (icons stay in TerminalShell/Sidebar). */
export const NAV_ITEMS: { view: ViewKey; label: string }[] = [
  { view: 'dashboard', label: 'Dashboard' },
  { view: 'analysis', label: 'Analysis' },
  { view: 'positions', label: 'Positions' },
  { view: 'agent-chat', label: 'Agent Chat' },
  { view: 'scanner', label: 'Scanner' },
  { view: 'trading', label: 'Auto-trade' },
  { view: 'trades', label: 'Trades' },
];
