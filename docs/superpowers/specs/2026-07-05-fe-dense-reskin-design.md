# FE Feature d — Dense-Terminal Re-skin (high-traffic pages)

**Date:** 2026-07-05
**Status:** Approved design (brainstorming). Targeted re-skin, high-traffic pages first.
**Branch:** `read-trading-prompt-dgm5U`

## Goal

Bring the routed pages up to the dense-terminal design language established by the
mosaic dashboard + `components/terminal/panels/`. Feature c routed these pages under
the `TerminalShell` layout, but they still use the old marketing card look (rounded-xl
cards, `text-gray-*`, `bg-surface`, non-tabular numbers, raw green/red P&L colors).
This is a **targeted re-skin** (token swaps, keep layout) — NOT a rebuild.

## Scope (this pass — 5 high-traffic pages)

Re-skin, in order (smallest-first within priority):

1. `pages/PositionsPage.tsx` (106) + its primary content components (the Kiwoom/Coin account+position+orders panels it renders)
2. `pages/ScannerResultsPage.tsx` (449) — largely self-contained
3. `pages/WorkflowPage.tsx` (228) + the workflow/analysis components it renders
4. `pages/AnalysisPage.tsx` (511) + the analysis-list components it renders
5. `pages/AnalysisDetailPage.tsx` (792) — largest, last

Each task re-skins the **page file AND the components it renders as its primary visible
content** (so the page actually looks dense, not just its wrapper). The implementer
identifies those components from the page's imports. Shared components already used by
the terminal dashboard (e.g. `utils/pnl`, `terminal/panels/shared.tsx`) are reused, not
duplicated.

**Deferred (feature d2):** `BasketPage`, `ChartsPage`, `TradesPage`, `TradingDashboard`,
`AgentChatDashboard`.

## Re-skin rules (the token mapping — apply per file)

Applied as a consistent checklist. These are the ONLY kinds of change (plus matching
density tweaks); layout structure and behavior stay the same.

| Old | New |
|---|---|
| `bg-surface`, `bg-surface-light`, `bg-surface-dark` | `bg-card` / `bg-elevated` (elevated for hover/nested) |
| `rounded-xl`, `rounded-2xl` | `rounded` + `border border-hairline` (de-card) |
| `border-border`, `border-gray-*` | `border-hairline` |
| `text-white`, `text-gray-100/200/300` | `text-ink` |
| `text-gray-400` | `text-muted` |
| `text-gray-500/600` | `text-dim` |
| raw `text-green-400` / `text-red-400` (for P&L / change) | `pnlColor(value)` / `changeColor(dir)` from `@/utils/pnl` |
| numeric values / table cells without `tabular-nums` | add `tabular-nums` |
| ad-hoc table headers | reuse `TH` from `terminal/panels/shared.tsx` where a table fits |
| ad-hoc "no data" blocks | reuse `Awaiting` from `terminal/panels/shared.tsx` where it fits |
| ad-hoc number formatting | reuse `fmtInt` / `fmtPct` / `fmtPrice` / `fmtMoneyCompact` where they fit |

**Density:** where a page uses large marketing type/padding (`text-2xl`, `p-6`, big
gaps), tighten to the terminal scale (`text-[12px]`–`text-sm`, `px-2.5 py-1.5`) — but
only where it clearly reads as marketing, not for genuinely prominent headers.

**Honesty preserved:** P&L color MUST route through `utils/pnl` (the safety helper) — do
not reintroduce raw green/red. Do not fabricate values while re-skinning.

## Non-goals

- No layout rebuilds, no route changes, no data-flow changes, no new features.
- Do not touch pages outside the 5-page scope.
- Do not change the terminal dashboard / panels (already dense).

## Verification (per page/task)

- `npm run build` (tsc, `noUnusedLocals`) passes.
- Browser: deep-link the page (e.g. `/positions`, `/scanner`, `/analysis`) against the
  live backend (:8001) and confirm the dense look — `bg-card` panels with hairline
  borders, `ink/muted/dim` text, `tabular-nums` numbers, P&L colored via the helper —
  and no visual regressions (page still renders its data/empty states).
- Pure styling change → no new unit tests; the existing suite must stay green (1
  pre-existing `navigation-bug.test.ts` failure allowed).

## Risks / decisions

- **Shared-component scope:** re-skinning a page's primary content component (e.g.
  `KiwoomPositionPanel`) also changes how that component looks anywhere else it is used.
  That is acceptable and desirable (global consistency) — but each task must note which
  shared components it touched so the reviewer checks other usages don't break.
- **Token aliases:** `bull`/`bear`/`surface` are still aliased in `tailwind.config.js`;
  prefer the canonical `up`/`down`/`card` tokens in re-skinned code, but do not do a
  global alias removal here (out of scope).
- **Per-page independence:** each page is its own task with its own build+browser gate,
  so a page can be reviewed/accepted independently.
