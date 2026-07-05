// frontend/src/components/terminal/commands.ts
// Pure, testable core of the ⌘K command palette: a static registry of
// commands plus a fuzzy/arg-aware filter. No React/UI here — the palette
// component (later task) owns rendering and key handling.
import { NAV_ITEMS, type ViewKey } from '@/nav';
import type { MarketType } from '@/store';

export type CommandCtx = {
  goTo: (v: ViewKey, id?: string) => void;
  setActiveMarket: (m: MarketType) => void;
  setChartSymbol: (s: string) => void;
  setShowSettingsModal: (b: boolean) => void;
  startAnalysis: (ticker: string) => void;
  startScan: () => void;
  startDebate: (ticker: string) => void;
};

export type Command = {
  id: string;
  title: string;
  group: string;
  keywords?: string[];
  arg?: 'ticker' | 'symbol';
  run: (ctx: CommandCtx, arg?: string) => void;
};

// `ctx` isn't read directly here — each Command's `run` receives its own
// ctx at call time (see CommandCtx/Command above) so the registry stays
// static and immune to stale closures across renders. The parameter is
// kept so the exported signature matches the palette's call site.
export function buildCommands(_ctx: CommandCtx): Command[] {
  const nav: Command[] = NAV_ITEMS.map(({ view, label }) => ({
    id: `go:${view}`,
    title: label,
    group: '이동',
    run: (c) => c.goTo(view),
  }));

  const market: Command[] = [
    { id: 'market:kr', title: 'KR', group: '마켓', run: (c) => c.setActiveMarket('kiwoom') },
    { id: 'market:us', title: 'US', group: '마켓', run: (c) => c.setActiveMarket('stock') },
    { id: 'market:coin', title: 'COIN', group: '마켓', run: (c) => c.setActiveMarket('coin') },
  ];

  const actions: Command[] = [
    {
      id: 'chart',
      title: ':chart',
      group: '액션',
      arg: 'symbol',
      run: (c, a) => { if (a) { c.setChartSymbol(a); c.goTo('dashboard'); } },
    },
    {
      id: 'analyze',
      title: ':analyze',
      group: '액션',
      arg: 'ticker',
      run: (c, a) => { if (a) c.startAnalysis(a); },
    },
    {
      id: 'scan',
      title: ':scan',
      group: '액션',
      run: (c) => c.startScan(),
    },
    {
      id: 'debate',
      title: ':debate',
      group: '액션',
      arg: 'ticker',
      run: (c, a) => { if (a) { c.startDebate(a); c.goTo('agent-chat'); } },
    },
    {
      id: 'settings',
      title: '설정 열기',
      group: '액션',
      run: (c) => c.setShowSettingsModal(true),
    },
  ];

  return [...nav, ...market, ...actions];
}

export function filterCommands(
  commands: Command[],
  query: string,
): { command: Command; arg?: string }[] {
  const trimmed = query.trim();

  if (trimmed.startsWith(':')) {
    const spaceIdx = trimmed.indexOf(' ');
    const typedId = (spaceIdx === -1 ? trimmed.slice(1) : trimmed.slice(1, spaceIdx)).toLowerCase();
    const rest = spaceIdx === -1 ? '' : trimmed.slice(spaceIdx + 1).trim();
    const match = commands.find((c) => c.title.startsWith(':') && c.title.slice(1).toLowerCase() === typedId);
    if (match) {
      return [{ command: match, arg: rest || undefined }];
    }
    return [];
  }

  const needle = trimmed.toLowerCase();
  if (!needle) {
    return commands.map((command) => ({ command }));
  }
  return commands
    .filter((c) => {
      const haystack = [c.title, ...(c.keywords ?? [])].join(' ').toLowerCase();
      return haystack.includes(needle);
    })
    .map((command) => ({ command }));
}
