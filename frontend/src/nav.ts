// frontend/src/nav.ts
// Single source of truth mapping app views <-> URL paths. Retires store.currentView.
export type ViewKey =
  | 'dashboard' | 'analysis' | 'analysis-detail' | 'workflow'
  | 'positions' | 'charts' | 'basket' | 'scanner' | 'agent-chat'
  | 'trading' | 'trades' | 'history';

/** Static path for a view. Detail views need a sessionId. */
export function viewToPath(view: ViewKey, sessionId?: string): string {
  switch (view) {
    case 'dashboard': return '/';
    case 'analysis': return '/analysis';
    case 'history': return '/analysis';
    case 'analysis-detail': return sessionId ? `/analysis/${sessionId}` : '/analysis';
    case 'workflow': return sessionId ? `/workflow/${sessionId}` : '/analysis';
    case 'positions': return '/positions';
    case 'charts': return '/charts';
    case 'basket': return '/watchlist';
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
  if (pathname.startsWith('/charts')) return 'charts';
  if (pathname.startsWith('/watchlist')) return 'basket';
  if (pathname.startsWith('/scanner')) return 'scanner';
  if (pathname.startsWith('/agent-chat')) return 'agent-chat';
  if (pathname.startsWith('/trading')) return 'trading';
  if (pathname.startsWith('/trades')) return 'trades';
  return 'dashboard';
}

/** Nav-rail order + labels (icons stay in TerminalShell). */
export const NAV_ITEMS: { view: ViewKey; label: string }[] = [
  { view: 'dashboard', label: 'Dashboard' },
  { view: 'analysis', label: 'Analysis' },
  { view: 'charts', label: 'Chart' },
  { view: 'positions', label: 'Positions' },
  { view: 'basket', label: 'Watchlist' },
  { view: 'agent-chat', label: 'Agent Chat' },
  { view: 'scanner', label: 'Scanner' },
  { view: 'trading', label: 'Auto-trade' },
  { view: 'trades', label: 'Trades' },
];
