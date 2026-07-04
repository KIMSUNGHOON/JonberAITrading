# FE Phase 1 — Tokens, Color-Safety, De-card: Implementation Plan

> Execute task-by-task. Frontend restyle → verify with `npm run build` (tsc+vite) + `npm run lint` + grep gates (no classic TDD for CSS; the color-safety helper IS unit-tested).

**Goal:** Flip the app onto the "Dense Terminal Shell" token ramp + tabular numerals + de-carded dense tables, and fix the P&L color safety bug — the mechanical, high-value Phase 1 that "ships a visibly different app fast."

**Strategy (key lever):** the 3-gray triad + radius live in `tailwind.config.js` as tokens, so **re-pointing token aliases + capping radius at the config level flips the whole app's palette+radius in ONE commit** (`bull/bear/surface/border` stay as aliases → the 353 raw green/red + 250 surface sites don't break). Per-file cleanup lands after.

**Design spec:** `docs/superpowers/specs/2026-07-05-frontend-redesign-design.md`. **Facts source:** gather workflow `gather-fe-phase1-facts` (2026-07-05) — exact current code + full inventory.

## Global Constraints
- CWD `frontend/`. Verify: `npm run build` (`tsc && vite build`), `npm run lint` (`--max-warnings 0` — delete unused vars/imports), `npm run test:run` (vitest). Node at `/opt/homebrew/bin/node`.
- Trading colors are **TEXT ONLY** (never fill/badge bg) — the `/20` tint removals are per-file cleanup, keep them until their file is touched.
- Primary text token is named **`ink`** (NOT `text` — `text` would generate confusing `text-text`/`bg-text`).
- Fonts (Inter/JetBrains Mono) are **declared but not loaded** (silent system fallback). `tabular-nums` still works on system fonts; self-hosting fonts is a Phase-2 follow-up.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Do NOT touch backend, live trading, or the agent-lane/HITL redesign (Phase 3).

---

### Task 1: Token system config lever (flips palette + radius + de-cards globally)

**Files:** `frontend/tailwind.config.js`, `frontend/src/index.css`, `frontend/src/components/analysis/AnalysisPanel.tsx`, `frontend/src/components/analysis/WelcomePanel.tsx`, `frontend/src/components/chart/TradingChart.tsx`.

**1a. `tailwind.config.js` — replace `theme.extend.colors` + add `borderRadius`:**
```js
colors: {
  // ── Dense Terminal Shell: single dark ramp ──
  canvas:'#0b0e11', card:'#161a1f', elevated:'#1c222a', hairline:'#242c37',
  ink:'#e8ecf1', muted:'#7b8794', dim:'#565e6b',
  accent:'#f0b90b',                 // the ONE accent — focus/active/CTA only
  up:'#0ecb81', down:'#f6465d', warn:'#f0a63a', info:'#4b9fff',  // trading = TEXT ONLY
  // migration aliases (keep names alive so 353 green/red + 250 surface sites survive):
  bull:{DEFAULT:'#0ecb81',light:'#0ecb81',dark:'#0ecb81'},
  bear:{DEFAULT:'#f6465d',light:'#f6465d',dark:'#f6465d'},
  surface:{DEFAULT:'#161a1f',light:'#1c222a',dark:'#0b0e11'},
  border:{DEFAULT:'#242c37',light:'#242c37'},
},
borderRadius: { DEFAULT:'4px', sm:'3px', md:'4px', lg:'6px', xl:'6px', '2xl':'6px', '3xl':'6px' },
```

**1b. `src/index.css`:** add `:root` CSS vars (for chart/non-Tailwind consumers) + `.num` utility; retarget body; de-card `.card`; move `.signal-hold` off yellow; DELETE `.text-gradient` (101-104) + `.glass` (106-109, 0 usages):
```css
:root{ --canvas:#0b0e11;--card:#161a1f;--elevated:#1c222a;--hairline:#242c37;
  --ink:#e8ecf1;--muted:#7b8794;--dim:#565e6b;--accent:#f0b90b;--up:#0ecb81;--down:#f6465d;--warn:#f0a63a;--info:#4b9fff; }
body{ @apply bg-canvas text-ink; font-feature-settings:"rlig" 1,"calt" 1; }   /* was bg-surface text-gray-100 */
.card{ @apply bg-card rounded-md border border-hairline p-3; }                 /* was bg-surface-light rounded-xl border-border p-4 */
.signal-hold{ @apply bg-elevated text-muted border border-hairline; }          /* was yellow-500 */
@layer utilities{ .num{ font-variant-numeric: tabular-nums; } }
/* DELETE .text-gradient and .glass blocks */
```

**1c. `AnalysisPanel.tsx:155` + `:163`:** `barColor:'bg-yellow-500'` → `barColor:'bg-hairline'`; `barColor:'bg-gray-500'` → `barColor:'bg-hairline'`.
**1d. `WelcomePanel.tsx:43`:** `<span className="text-gradient">` → `<span className="text-accent">`.
**1e. `TradingChart.tsx:58`:** `color:'#0f1419'` → `color:'#0b0e11'`.

- [ ] **Steps:** apply 1a–1e → `npm run build` (must pass; catches config/TS) → `npm run lint` → grep gates: `grep -rn "text-gradient\|\.glass" frontend/src` = 0, `grep -rn "0f1419\|bg-yellow-500" frontend/src/components/analysis/AnalysisPanel.tsx frontend/src/components/chart/TradingChart.tsx` = 0 → `npm run test:run` → commit `feat(fe): dense-terminal token ramp + de-card primitive + kill glass/gradient`.

---

### Task 2: P&L color safety fix (single toggle-aware helper)

**Root cause:** same profit shows RED in KR-convention files (`MarketSummaryWidget.tsx:266`, `KiwoomPositionPanel.tsx:135/175`) and GREEN in Western files (`PopularTickerBar.tsx:212`, `PositionMonitor.tsx:118/322`, `PopularStocksWidget.tsx:100`). All are RAW `text-red-400/blue-400/green-400` — a token remap does NOT catch them.

**Files:** create `frontend/src/utils/pnl.ts` + `frontend/src/utils/pnl.test.ts`; store flag in `src/store/index.ts`; switch the ~10 sites.

**2a. `src/utils/pnl.ts`** (single source of truth):
```ts
export type PnlConvention = 'western' | 'korean';  // western: up=green ; korean: up=red
// returns a Tailwind text-color class for a signed value under the active convention
export function pnlColor(value: number, convention: PnlConvention = 'western'): string {
  if (value === 0) return 'text-muted';
  const up = value > 0;
  const green = convention === 'western' ? up : !up;
  return green ? 'text-up' : 'text-down';
}
// RISE/FALL string variant for tickers
export function changeColor(dir: 'RISE' | 'FALL' | string, convention: PnlConvention = 'western'): string {
  if (dir === 'RISE') return convention === 'western' ? 'text-up' : 'text-down';
  if (dir === 'FALL') return convention === 'western' ? 'text-down' : 'text-up';
  return 'text-muted';
}
```

**2b. `src/utils/pnl.test.ts`** (vitest):
```ts
import { describe, it, expect } from 'vitest';
import { pnlColor, changeColor } from './pnl';
describe('pnlColor', () => {
  it('western: gain green, loss red', () => { expect(pnlColor(100)).toBe('text-up'); expect(pnlColor(-100)).toBe('text-down'); });
  it('korean: gain red, loss green', () => { expect(pnlColor(100,'korean')).toBe('text-down'); expect(pnlColor(-100,'korean')).toBe('text-up'); });
  it('zero is neutral', () => { expect(pnlColor(0)).toBe('text-muted'); });
  it('changeColor RISE/FALL respects convention', () => {
    expect(changeColor('RISE')).toBe('text-up'); expect(changeColor('RISE','korean')).toBe('text-down');
  });
});
```

**2c. Store:** add `pnlConvention: PnlConvention = 'western'` + `setPnlConvention` to `src/store/index.ts` (default western per decision; KR toggle available in settings later).

**2d. Switch sites** to `pnlColor(value, pnlConvention)` / `changeColor(dir, pnlConvention)`:
- `MarketSummaryWidget.tsx:266` `const profitColor = (pnl>=0)?'text-red-400':'text-blue-400'` → `pnlColor(pnl, pnlConvention)`.
- `KiwoomPositionPanel.tsx:135/175` (pnl) → `pnlColor(...)`; `:185` stop / `:191` take keep their semantic (stop=down, take=up) but recolor to `text-down`/`text-up`.
- `PopularTickerBar.tsx:212-216` `getChangeColor` → `changeColor(change, pnlConvention)`.
- `PositionMonitor.tsx:118` `'text-green-400':'text-red-400'` → `pnlColor(pnl, pnlConvention)`; `:322` same.
- `PopularStocksWidget.tsx:100-104` → `pnlColor`/`changeColor`.

- [ ] **Steps:** write helper + test → `npm run test:run` (RED→GREEN on pnl.test) → add store flag → switch the ~10 sites → `npm run build` + `npm run lint` → grep guard: `grep -rn "text-red-400.*text-blue-400\|text-blue-400.*text-red-400" frontend/src` = 0 (no raw KR-red-up literals remain in switched files) → commit `fix(fe): unify P&L color convention (Western green=up) via single helper — safety bug`.

---

### Task 3: tabular-nums rollout (`.num`)
Apply `tabular-nums` / `.num` at the container level of every number surface: markets/ticker table, positions table, metric strips, chart axis labels, agent vote/confidence numbers. Inventory: `tabular-nums` currently 0 in src. Priority containers first (positions, ticker, metric strip). **Verify:** visual (digits align/right-align), build. Commit `feat(fe): tabular numerals across data surfaces`.

### Task 4: de-card metric strips + positions blotter + ticker table
Per gather §de-card (exact JSX provided): MarketSummaryWidget metric strip → flat KV row (drop gradient/rounded boxes); KiwoomPositionPanel + PositionMonitor + PositionCard + CoinPositionPanel per-position cards → `top`-style multi-row blotter table (Symbol/Qty/Entry/Cur/P&L/%/Stop/Take), right-aligned tabular; PopularTickerBar marquee → static sortable dense table (delete `@keyframes scroll`, `displayTickers` dup, fade edges, pause state). Also de-card `rounded-xl` shells: TradingStatusCard, PopularStocksWidget, BackgroundScannerWidget, PositionMonitor panels, MainContent inline wrapper. **Verify:** build+lint (unused vars from deleted marquee state), visual, grep `rounded-xl` = 0 in de-carded files, no horizontal page scroll. Commit per sub-area.

### Task 5: chart retheme + real bug fix
`TradingChart.tsx`: bg/candles/grid → tokens (up `#0ecb81`/down `#f6465d`, hairline grid, mono axis via CSS vars); add `series.update()` for incremental ticks; make Refresh a real refetch (kill fake 1s icon spin); remove decorative pulse dots (bind "live" to real connection). (Read gather `fe:chart` for exact current code.) **Verify:** build, chart renders on new bg, tick updates. Commit `fix(fe): retheme chart + real series.update / refresh (kill fake live)`.

### Task 6: fake-data [SIMULATED] labels + kill decorative live pulse
Label `Math.random` US candles / null US ticker / zeroed US account with a visible `[SIMULATED]` badge (do NOT fabricate real data). Replace decorative `animate-pulse` "live" dots + `.live-indicator::before` with connection-bound status. (Read gather `fe:fake-data-and-live` for exact sites.) **Verify:** build, US surfaces show SIMULATED, no fake pulse where not connected. Commit `fix(fe): label simulated US data + remove decorative live indicators`.

---

## Final verification
- [ ] `npm run build` + `npm run lint` + `npm run test:run` all green.
- [ ] `npm run dev` visual: canvas #0b0e11, flat dense panels (no rounded-xl cards), tabular right-aligned numbers, HOLD neutral (not yellow), accent-yellow only on focus/active, one consistent green/up-red/down convention everywhere, ticker is a static sortable table, US data labeled [SIMULATED].
- [ ] grep gates: `text-gradient`/`.glass` = 0; no raw KR-red-up literal pairs in switched files.

## Notes
- Tasks 1–2 (config lever + color safety) are the highest-value + lowest-risk and deliver the visible transformation + fix the safety bug; do them first.
- Phase 2 (command palette + status line + router + WS consolidation) and Phase 3 (agent-lane dual-mode + HITL order ticket) are separate plans.
