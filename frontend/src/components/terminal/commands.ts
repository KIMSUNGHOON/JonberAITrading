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
  // P1-4 discretionary control surface: manual order placement. Market is
  // resolved by the ctx implementation from the current activeMarket (same
  // convention as startAnalysis) — the command itself is market-agnostic.
  placeOrder: (side: 'buy' | 'sell', sym: string, qty: number, px?: number) => void;
  // Synchronous, visible error surface for malformed command args — distinct
  // from the async `fail()` wrapper CommandPalette uses for API rejections,
  // but rendered through the same error Toast so neither path is silent.
  reportError: (msg: string) => void;
};

export type Command = {
  id: string;
  title: string;
  group: string;
  keywords?: string[];
  arg?: 'ticker' | 'symbol' | 'order';
  run: (ctx: CommandCtx, arg?: string) => void;
};

/**
 * Parses the `SYM QTY [PX]` argument string for :buy/:sell. Pure and
 * market-agnostic (qty may be fractional — coin volumes are — so integer
 * enforcement is left to the market-specific caller). Returns a discriminated
 * result so malformed input (missing qty, non-numeric qty/px) can be surfaced
 * as an honest, visible error instead of a silent no-op.
 */
export type OrderArgsResult =
  | { ok: true; sym: string; qty: number; px?: number }
  | { ok: false; error: string };

export function parseOrderArgs(raw: string | undefined): OrderArgsResult {
  const tokens = (raw ?? '').trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) {
    return { ok: false, error: '심볼과 수량을 입력하세요 (형식: SYM QTY [PX])' };
  }
  const [sym, qtyStr, pxStr] = tokens;
  if (!qtyStr) {
    return { ok: false, error: `수량을 입력하세요 (형식: ${sym} QTY [PX])` };
  }
  const qty = Number(qtyStr);
  if (!Number.isFinite(qty) || qty <= 0) {
    return { ok: false, error: `수량이 올바르지 않습니다: "${qtyStr}"` };
  }
  let px: number | undefined;
  if (pxStr !== undefined) {
    px = Number(pxStr);
    if (!Number.isFinite(px) || px <= 0) {
      return { ok: false, error: `가격이 올바르지 않습니다: "${pxStr}"` };
    }
  }
  return { ok: true, sym: sym.toUpperCase(), qty, px };
}

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

  // 코인 동결(freeze) 이후 마켓은 KR 하나뿐 — market:coin 항목은 fix round 1에서
  // 제거됐다(⌘K를 통해 setActiveMarket('coin')을 호출하던 배선, 리뷰 발견).
  const market: Command[] = [
    { id: 'market:kr', title: 'KR', group: '마켓', run: (c) => c.setActiveMarket('kiwoom') },
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
    {
      id: 'buy',
      title: ':buy',
      group: '액션',
      arg: 'order',
      run: (c, a) => {
        const parsed = parseOrderArgs(a);
        if (!parsed.ok) { c.reportError(`:buy — ${parsed.error}`); return; }
        c.placeOrder('buy', parsed.sym, parsed.qty, parsed.px);
      },
    },
    {
      id: 'sell',
      title: ':sell',
      group: '액션',
      arg: 'order',
      run: (c, a) => {
        const parsed = parseOrderArgs(a);
        if (!parsed.ok) { c.reportError(`:sell — ${parsed.error}`); return; }
        c.placeOrder('sell', parsed.sym, parsed.qty, parsed.px);
      },
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
    // No exact `:id` match (e.g. still typing `:anal`) — fall through to the
    // substring branch below so incremental typing progressively surfaces
    // `:analyze`/`:chart`/`:debate`/`:scan` instead of showing nothing until
    // the id is fully typed. The substring match runs over title+keywords,
    // which includes the leading `:`, so `:anal` still matches `:analyze`.
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
