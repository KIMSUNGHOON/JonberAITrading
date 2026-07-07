# FE feature e1 (remainder) — Agent-Lane Dual-Mode Completion (vote blotter · consensus ticket · tail -f reasoning wire) — Design

> Part of the frontend redesign's **Phase 3 "AI 레인"** / the "Dense Terminal Shell, **Editorial Agent Lane**" direction (`docs/superpowers/specs/2026-07-05-frontend-redesign-design.md` §5). e1 (core) — `2026-07-07-fe-editorial-reading-pane-design.md` — delivered the editorial **prose bodies** (agent message + report). This spec covers the **remainder** of e1, which completes Phase 3: the dense-mono structure around those editorial bodies — the **vote blotter**, the **consensus ticket**, the surrounding **ChatSessionViewer chrome de-card**, and the promotion of the streaming reasoning log from a closed slide-out modal to an **always-on `tail -f` wire**.

## Goal

Give the "AI 화면" (agent-chat + analysis reasoning) its full **dual-mode identity**: everything is **dense monospace** — timestamps, agent handles, votes, decision, stats, connection status — **except** the prose bodies (message/report/rationale), which stay **editorial** (`ReadingPane`, done in e1-core). Today the structure around the editorial bodies is still the old card style (`bg-card rounded border p-6`, card grids, big badges), and the reasoning stream hides behind a slide-out modal. This spec finishes the transformation.

## The problem today

- **Votes** render as a `VoteCard` grid (`ChatSessionViewer.tsx:129`, 2/4-col rounded-lg cards, one card per vote) — low density, not the §5 "투표 blotter (AGENT·VOTE·CONF·WGT·SCORE)".
- **Decision** renders as a big `p-6` card with a 2xl action badge wrapped in `bg-up/20 border-up/30` (`ChatSessionViewer.tsx:173`) — verbose, and the colored card background **violates the §2 "트레이딩 색 text-only, never a card/button background" convention**.
- **Surrounding chrome** — header (Back/WS pills/Refresh), session-info card, 4-col stat grid, section headers with icons — is all old card style; a dense blotter/ticket dropped into it reads as an awkward mix.
- **Reasoning stream** (`ReasoningSlidePanel.tsx`) is a **slide-out modal** with a backdrop, toggled by a button in `WorkflowPage` (`showReasoningPanel`). It is built entirely on **old debt tokens** (`bg-surface-dark`, `border-border`, `text-blue-400`, `text-gray-*`, `bg-black/50`). §5 calls for promoting it to an **always-on `tail -f` wire**. The dashboard `ReasoningPanel` tile already **is** such a wire (dense tokens, `[Agent]` prefix colorize, auto-scroll) — but its render core is not shared, so the promotion would duplicate it.

Data is ready: `AgentChatVote` already carries `agent_type`, `vote`, `confidence`, `weight`, `weighted_score`, `reasoning` (`src/types/index.ts`) — all five blotter columns exist. `AgentChatDecision` carries `action`, `confidence`, `consensus_level`, `entry_price`, `stop_loss`, `take_profit`, `rationale`, `key_factors[]`, `dissenting_opinions[]`.

## Approach

**Presentation-only re-skin + one shared extraction. Zero behavior/data/logic change.** No new fetch, no vote aggregation, no `react-markdown` rewrite (all YAGNI). Reuse existing primitives: directional color `@/utils/pnl` (`pnlColor`), the token ramp (canvas/card/elevated/hairline/ink/muted/dim/accent/up/down), `ReadingPane` + `MarkdownRenderer` (e1-core), the `DebatePanel` tile's consensus bar + 75%-gate marker, and the `OrderTicketRail` dense-KV-ticket idiom. Regression risk is low — each touched component is consumed only by its own view.

## Design

### Part ① — `ChatSessionViewer` full dual-mode

`ChatSessionViewer.tsx` is the agent lane (it already hosts the e1-core editorial message bodies). Restructure its non-prose surface to dense mono.

#### (a) Vote blotter (`VoteCard` grid → dense table)

Replace the `VoteCard` grid with a dense mono table. Map `session.votes` **directly** (no fabricated fixed rows, no synthetic aggregation — one row per real vote; honest to data):

```
AGENT VOTES                                       4 votes
─────────────────────────────────────────────────────────
AGENT          VOTE     CONF     WGT     SCORE
● TECHNICAL    BUY       72%    0.30      0.85
● FUNDAMENTAL  S.BUY     88%    0.30      1.20
● SENTIMENT    HOLD      55%    0.20      0.00
● RISK         SELL      40%    0.20     -0.60
```

- Columns: **AGENT** (`●` dot in the agent's **identity** color from `agentConfig` per §4 partition palette + name), **VOTE** (directional `pnlColor`: STRONG_BUY/BUY→up, SELL/STRONG_SELL→down, HOLD→muted, ABSTAIN→dim; label reuse `DebatePanel`'s `VOTE_LABEL` — S.BUY/BUY/HOLD/SELL/S.SELL/ABS), **CONF** (`confidence*100` %), **WGT** (`weight`, 2dp), **SCORE** (`weighted_score`, 2dp).
- `tabular-nums`, numeric columns right-aligned, ALL-CAPS `text-dim` header row, hairline row separators, ~24px rows.
- `reasoning` is **dropped** from the blotter (the full analyst prose lives in the Discussion messages below; matches the dashboard `DebatePanel` tile).
- No filtering: if a `moderator` vote exists in `session.votes` it appears with the moderator **muted** identity color (honest to data). `voteColor`/identity discipline: VOTE cell = directional (`pnlColor`), AGENT dot = identity (raw hue, `color-ok`), never conflated.

#### (b) Consensus ticket (`DecisionPanel` card → dense KV ticket)

Replace the big `p-6` card with a dense bordered KV ticket (the `OrderTicketRail` idiom):

```
┌ DECISION ─────────────────────────────────────┐
│ BUY   삼성전자 (005930)               CONF 82% │
│ CONSENSUS  72%  [██████████░░░│░░]  gate 75%   │
│ ENTRY  71,500   STOP  68,000   TAKE  79,000    │
│ ────────────────────────────────────────────── │
│ RATIONALE                                       │
│   <ReadingPane + MarkdownRenderer editorial>    │
│ KEY FACTORS   · RSI반등 · 거래량↑ · 실적서프    │
│ DISSENT       · RISK: 단기 과열 우려            │
└─────────────────────────────────────────────────┘
```

- Ticket container: **neutral `bg-card` + `border-hairline`** — **NOT** the current `bg-up/20 border-up/30` wrap. This fixes a §2 convention violation (trading color as a card background) and is a color-discipline win.
- **ACTION**: `decision.action` as a **text-only** `pnlColor` badge (BUY/ADD→up, SELL/REDUCE→down, else muted) — same app-wide `ACTION` map already used here; keep the direction icon (TrendingUp/Down/Minus).
- **CONSENSUS**: `consensus_level*100` % + a bar with the **75% gate marker** reused from the `DebatePanel` tile (the gate is a **display constant**, not an enforced backend threshold — label it as such, consistent with the tile).
- **ENTRY / STOP / TAKE**: dense KV; STOP → `text-down`, TAKE → `text-up` (unchanged semantics), `tabular-nums`, reuse the existing `formatPrice`.
- **RATIONALE**: it is **prose** → wrap in `ReadingPane` + `MarkdownRenderer` (editorial, extending the e1-core dual-mode rule; today it is a plain `<p>`). This makes the decision rationale read like the report bodies.
- **KEY FACTORS / DISSENT**: short bullet items → keep as dense mono lists (`text-muted`, `·`/hairline), not editorial.
- `confidence` shown once in the ticket header (avoid duplicating in a metric grid).

#### (c) Chrome de-card

Convert the remaining card chrome to dense mono:
- **Header**: Back button + WS status + Refresh → a dense mono bar. The WS `Live / Connecting / Polling` pills → status-line-style mono tokens (`●live` up / `connecting…` warn / `polling` muted) rather than rounded pill chips.
- **Session-info card + 4-col stat grid** (Rounds / Messages / Votes / Consensus) → a dense mono header strip (stock name + ticker + session id + status token) with the counts as an inline KV row (`ROUNDS 3 · MSGS 12 · VOTES 4 · CONSENSUS 72%`).
- **Section headers** ("Agent Votes", "Discussion" + lucide icons) → small ALL-CAPS mono labels with a count.
- `space-y-6` + `bg-card rounded border p-6` sections → tighter hairline-separated dense sections.
- **Keep unchanged**: `MessageBubble` editorial bodies (e1-core `ReadingPane`), the per-agent identity colors (`agentConfig`), all data flow / WebSocket wiring / polling / auto-scroll.

### Part ② — Reasoning tail -f wire (shared component, promoted from slide-out)

- **New `ReasoningWire`** — a **presentation-only** component. Props: `entries: string[]`, `running: boolean`, `currentStage?: string`, `className?: string` (the consumer passes the height/layout classes — `h-full` for the tile, a bounded `max-h-*` for the page). The empty state stays in the *consumer* (the tile keeps its own `Awaiting`), not in the wire — so no `emptyLabel` prop is needed. Its render core is **extracted from the dashboard `ReasoningPanel` tile** (numbered line prefix, `[Agent]`-prefix colorize via `prefixColor`, pulsing running head, auto-scroll to newest, dense mono). Location: `src/components/common/ReasoningWire.tsx` (shared across the tile and the page).
- **`ReasoningPanel`** (dashboard tile) → a thin store-subscriber wrapper that reads `selectReasoningLog` / `selectStatus` / `currentStage` and feeds `ReasoningWire`. Rendered output **byte-identical** to today (its empty label + prefix colors preserved).
- **`WorkflowPage`** → remove the slide-out modal; render `ReasoningWire` **inline, always-on** in the layout, fed by the active-market reasoning state (the same `useShallow` switch `ReasoningSlidePanel` used). Delete `showReasoningPanel` state + the toggle. The `AnalysisQueueWidget onViewDetails` / `handleViewReasoningDetails` path (which only opened the modal) becomes redundant with an always-on wire → either drop the prop or repoint it to scroll-to-wire (decided in T2; prefer the simplest honest wiring — likely drop the "view details" affordance since the wire is always visible).
- **Delete** `src/components/analysis/ReasoningSlidePanel.tsx` + its `analysis/index.ts` export (removes ~15 old-debt-token lines and a modal from the app).
- Net: DRY (one wire, two call sites), less duplication, the reasoning stream is always visible during analysis, and dense tokens are already applied.

### Dual-mode invariant (unchanged from e1-core)

Only message/report/**rationale** prose bodies are editorial (proportional via `ReadingPane`, the sole `font-sans` site). Everything else — blotter, ticket KV, agent handles, timestamps, stats, WS status, the reasoning wire — is dense monospace. Per-agent identity color survives **only** inside the agent lane (§4 partition palette).

## Color / lint discipline

- All **directional** colors go through `@/utils/pnl` (`pnlColor`) — VOTE cell, ACTION badge, STOP/TAKE (already the case in the current VoteCard/DecisionPanel; preserved, no flip). Agent **identity** hues stay raw with a `color-ok:` annotation (they are category identity, not directional — same treatment as the existing `agentConfig` block).
- `ChatSessionViewer.tsx`, `ReasoningPanel.tsx`, and `WorkflowPage.tsx` are **already in** the `check-trading-colors.mjs` `CLEAN_SET` (verified) — they must **stay** clean through this work. Only the new `ReasoningWire.tsx` needs **adding** to the set. `ReasoningSlidePanel.tsx` is not in the set; deleting it removes its raw-color debt from the codebase.
- `npm run lint:colors` must exit 0.

## SDD task breakdown (5 tasks — consistent with prior features d/d2/e2/e1-core)

- **T1** — Extract `ReasoningWire` (presentation-only) + repoint `ReasoningPanel` tile to it (rendered output byte-identical) + unit test (`ReasoningWire.test.tsx`: entries render, prefix colorize, running head, empty label).
- **T2** — `WorkflowPage`: inline always-on `ReasoningWire`; delete `ReasoningSlidePanel` + `showReasoningPanel` toggle + resolve `onViewDetails`; update `analysis/index.ts`.
- **T3** — `ChatSessionViewer` **vote blotter** (`VoteCard` grid → dense table) + unit/render assertions (directional VOTE color, identity dot, tabular numerics, WGT/SCORE present).
- **T4** — `ChatSessionViewer` **consensus ticket** (`DecisionPanel` card → dense KV ticket; neutral bg [color-discipline fix], ACTION text-only pnl, consensus bar + 75% gate marker, RATIONALE → `ReadingPane`).
- **T5** — `ChatSessionViewer` **chrome de-card** (header / WS status / session-info / stat grid / section labels) + confirm the gate: add `ReasoningWire.tsx` to `check-trading-colors.mjs` `CLEAN_SET` (the other touched files are already gated) and keep every gated file clean (`lint:colors` exit 0).

Each task: fresh implementer + reviewer (subagent-driven-development), review-clean before the next. Whole-feature opus review at the end, then checkpoint.

## Testing / gates

- `npm run build` PASS (tsc `noUnusedLocals` — delete unused imports, e.g. removed `VoteCard` icons after the blotter swap).
- `npm run test:run` green except the 1 known pre-existing `navigation-bug.test.ts` failure.
- `npm run lint:colors` exit 0 (all touched files in `CLEAN_SET`).
- Unit: `ReasoningWire` (T1), blotter (T3), ticket (T4) as above.
- Browser (if the Chrome extension connects): an agent-chat session reads as a dense blotter + KV ticket + editorial message bodies with mono chrome; `WorkflowPage` shows the reasoning as an always-on inline wire (no modal). Else code + build + unit tests carry it (office IP / ext availability noted in project memory).

## Out of scope (YAGNI — deferred)

- Any backend / data / API change; new vote aggregation or consensus math; enforcing the 75% gate (it stays a display constant).
- Converting `MarkdownRenderer` to `react-markdown`.
- Web-font loading (system `font-sans` only, via `ReadingPane`).
- Re-skinning other analysis widgets in `WorkflowPage` beyond the reasoning-wire swap (a future d-style pass; gate blocks regressions in cleaned files).
- Per-vote reasoning in the blotter (dropped by decision; it lives in the Discussion).

## Files

- **Create**: `src/components/common/ReasoningWire.tsx` (+ `ReasoningWire.test.tsx`).
- **Modify**: `src/components/agent-chat/ChatSessionViewer.tsx` (blotter + ticket + chrome), `src/components/terminal/panels/ReasoningPanel.tsx` (delegate to `ReasoningWire`), `src/pages/WorkflowPage.tsx` (inline wire, remove modal + toggle), `src/components/analysis/index.ts` (drop export), `frontend/scripts/check-trading-colors.mjs` (CLEAN_SET).
- **Delete**: `src/components/analysis/ReasoningSlidePanel.tsx`.
