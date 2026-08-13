# FE Feature c — Real Router + ⌘K Command Palette

**Date:** 2026-07-05
**Status:** Approved design (brainstorming). Implements as two checkpointed phases: **c1 router**, then **c2 palette**.
**Branch:** `read-trading-prompt-dgm5U`

## Goal

Give the terminal frontend real URLs (deep-linking, browser back/forward, shareable
links) and a fast, keyboard-driven ⌘K command palette matching the dense terminal
aesthetic. Today "routing" is a `store.currentView` string switch with no URL sync,
and the command bar in `TerminalShell` is a static placeholder.

## Decomposition

- **c1 — react-router migration** (structural; ship first). Real routes replace the
  `currentView` switch entirely.
- **c2 — ⌘K command palette** (additive; depends on c1's navigation API).

Each phase has its own build + test + browser verification checkpoint.

---

## c1 — react-router migration

### Router & layout
- Add `react-router-dom` (currently not a dependency).
- `<BrowserRouter>` wraps the app (in `main.tsx` or `App.tsx`).
- `TerminalShell` becomes the **layout route**: it renders the command bar + nav rail
  + status line and an `<Outlet/>` for the active page (instead of `{children}`).

### Route map
| Path | Component | Store view (retired) |
|---|---|---|
| `/` | `TerminalDashboard` | dashboard |
| `/analysis` | `AnalysisPage` | analysis, history |
| `/analysis/:sessionId` | `AnalysisDetailPage` | analysis-detail |
| `/workflow/:sessionId` | `WorkflowPage` | workflow |
| `/positions` | `PositionsPage` | positions |
| `/charts` | `ChartsPage` | charts |
| `/watchlist` | `BasketPage` | basket |
| `/scanner` | `ScannerResultsPage` | scanner |
| `/agent-chat` | `AgentChatDashboard` | agent-chat |
| `/trading` | `TradingDashboard` | trading |
| `/trades` | `TradesPage` | trades |
| `*` | redirect → `/` | — |

Path-based URLs (vite dev server serves the SPA fallback). `activeMarket` stays a
store toggle for c1 — deep-linking market via `?m=kr|us|coin` is a deferred nicety.

### Retire `currentView` from the store
Remove `currentView` + `setCurrentView` from `store/index.ts` (state, action, type,
initial value). Replace with two hooks (new `hooks/useNav.ts`):
- `useGoTo()` → returns `(view: ViewKey, sessionId?) => navigate(pathFor(view, sessionId))`.
  This is the drop-in replacement for `setCurrentView(x)`.
- `useActiveView()` → derives the current `ViewKey` from `useLocation()` for nav
  active-state highlighting.

A single `viewToPath` / `pathToView` map is the source of truth for both.

### Migrate call sites (~30)
Convert every `setCurrentView(x)` to `useGoTo()`/`navigate()`:
`TerminalShell` (nav rail), `Sidebar` (8, reached via `MobileNav`), pages
(`AnalysisPage`, `AnalysisDetailPage`, `ScannerResultsPage`, `PositionsPage`,
`TradesPage`, `ChartsPage`, `HistoryPage`, `BasketPage`, `WorkflowPage`), widgets
(`BasketWidget`, `AnalysisQueueWidget`, `WorkflowProgress`, `TradingStatusCard`,
`BackgroundScannerWidget`, `RecentAnalysisWidget`, `PopularStocksWidget`,
`WatchListWidget`). Reads of `currentView` exist only in `App.tsx`, `MainContent.tsx`,
and `TerminalShell.tsx` — all rewritten here.

### Detail pages & selectedSessionId
`WorkflowPage`/`AnalysisDetailPage` read `store.selectedSessionId`. Keep
`selectedSessionId` in the store (it is session state, not navigation). Add a thin
route bridge: the `/workflow/:sessionId` and `/analysis/:sessionId` elements read
`useParams().sessionId` and set `selectedSessionId` (effect) before rendering the page,
so the page internals stay unchanged.

### Retire dead/duplicated chrome
- `MainContent.tsx`: its page-switch is replaced by routes and its market-specific
  "dashboard fallback" (lines ~121–239) is already unreachable (dashboard → the mosaic).
  Retire the file.
- `Header.tsx`: confirm unused, delete.
- `Sidebar.tsx`: still used by `MobileNav` — migrate its `setCurrentView` calls to
  `useGoTo`; keep the component.

### Test
`store/navigation-bug.test.ts` drives navigation via `setCurrentView` to assert Kiwoom
sessions survive navigation. With routing off the store, navigation no longer touches
session state, so update the test to assert session preservation directly (session
mutations don't clobber `sessions[]`) without the `setCurrentView` calls.

### c1 verification gate
`npm run build` (tsc, noUnusedLocals) + `npm run test:run` + browser: deep-link to
`/positions` directly, use browser back/forward across views, confirm nav-rail active
state and mobile nav still work.

---

## c2 — ⌘K command palette

### Components
- `components/terminal/CommandPalette.tsx` — modal overlay (dense terminal style):
  single input, grouped results, keyboard nav (↑/↓, Enter, Esc), fuzzy filter.
- `components/terminal/commands.ts` — command registry: `{ id, title, group, keywords,
  run(ctx), arg? }` where `ctx` exposes `navigate`/`goTo` + store actions.
- `hooks/useCommandPalette.ts` — global ⌘K (and Ctrl+K) listener + open/close state.
  The command bar in `TerminalShell` becomes the click trigger and shows the real hint.

### Command set (core + extended)
- **Navigate** (group 이동): go to any view → `useGoTo`.
- **Market** (group 마켓): KR / US / COIN → `setActiveMarket`.
- **`:chart <symbol>`** → `setChartSymbol` (reuses feature b) + go to `/` or `/charts`.
- **`:analyze <ticker>`** → start an analysis for the active market. Extract
  `hooks/useStartAnalysis.ts` from `BasketWidget.handleAnalyze` (start API + session +
  WS wiring) so the palette and basket share one path.
- **`:scan`** → `startScan()`.
- **`:debate <ticker>`** → `startAgentChatDiscussion()` + go to `/agent-chat`.
- **Open Settings** → `setShowSettingsModal(true)`.

Input parsing: a leading `:cmd ` routes to the matching arg-command with the remainder
as its argument (e.g. `:analyze 005930`); otherwise the text fuzzy-filters titles.

### c2 verification gate
`npm run build` + browser: ⌘K opens the palette; typing filters; Enter on a nav command
routes (URL changes); `:chart 005930` charts it; `:scan` starts a scan; Esc closes.

---

## Risks / decisions
- **noUnusedLocals**: deleting `currentView`/`MainContent`/`Header` must not leave
  dangling imports — build gate catches these.
- **Path vs hash URLs**: path-based; vite dev SPA fallback handles direct navigation.
  A static prod host would need SPA fallback config (out of scope for dev).
- **`selectedSessionId`** stays in the store (bridged from route params), avoiding a
  rewrite of the detail pages.
- **`activeMarket`** stays a store toggle in c1; URL sync (`?m=`) deferred.
- **`:analyze` reuse**: the one non-trivial command; the `useStartAnalysis` extraction
  keeps a single start-analysis path shared with `BasketWidget`.
