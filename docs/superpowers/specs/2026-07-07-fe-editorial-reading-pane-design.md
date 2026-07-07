# FE feature e1 (core) — Editorial Reading Pane for Agent-Lane & Report Bodies — Design

> Part of the frontend redesign's **Phase 3 "AI 레인"** / the "Dense Terminal Shell, **Editorial Agent Lane**" direction (`docs/superpowers/specs/2026-07-05-frontend-redesign-design.md` §5). This spec covers the DEFINING core of e1 — the editorial treatment of agent-message and report prose bodies. The rest of e1 — vote-blotter table, consensus ticket, and the always-on `tail -f` reasoning wire — is DEFERRED to its own later cycle.

## Goal

Give the "agent lane" its dual-mode identity: everything stays dense monospace EXCEPT the **prose bodies** (agent chat messages, analysis report/summary text), which become an **editorial reading pane** — system proportional font, a measured ~65ch line length, generous leading, and real (already-rendered) markdown. Korean analysis prose is unreadable in a cramped monospace column; this is where it gets a proper reading home.

## The problem today

- `ChatSessionViewer`'s `MessageBubble` renders the message body as `text-sm text-ink whitespace-pre-wrap` (`components/agent-chat/ChatSessionViewer.tsx:116`) — plain text that **inherits the shell's `font-mono`** and does NOT render markdown. LLM analysis prose (Korean, with headers/bold/lists) reads as a cramped mono wall.
- `MarkdownRenderer` (`components/common/MarkdownRenderer.tsx`) is a hand-rolled regex renderer that (a) sets **no body font**, so it inherits `font-mono`, (b) applies **no measure / leading**, and (c) still uses old debt tokens (`text-white`, `text-gray-300`, `bg-surface`, `text-blue-400`, `border-gray-700` — ~15 raw-color lines, part of the 186-line debt).
- `AnalysisDetailPage` renders its report/summary + trade-proposal rationale through `MarkdownRenderer` — same cramped-mono result.

## Design

### 1. `ReadingPane` — shared editorial typography container

New component `src/components/common/ReadingPane.tsx`. Single responsibility: wrap prose content in the editorial register.

- `font-sans` (system proportional stack — no web font loaded; system Korean font renders Korean prose correctly). **This is the ONLY place `font-sans` appears** in the app — it is the visual boundary of "dual-mode": mono everywhere, proportional only inside a reading pane.
- `max-w-[65ch]` measure (in the spec's ~64–68ch band) so lines don't run too long.
- `leading-relaxed` generous line-height + `text-ink` base color + a modest base size (`text-sm`/`text-[13px]`, tuned for reading, not marketing).
- Renders `children` (the markdown output). Optional `className` passthrough for per-call tweaks (e.g. a message bubble vs a full report).

Interface: `function ReadingPane({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element`.

### 2. `MarkdownRenderer` token re-skin (it is the reading pane's renderer)

Re-skin `MarkdownRenderer.tsx`'s output classes to dense-terminal tokens so the editorial bodies are clean and to drain its ~15 debt lines:
- `text-white`/`text-gray-300` → `text-ink`; secondary → `text-muted`; list bullet `text-gray-500` → `text-dim`.
- code block `bg-surface border-gray-700 text-gray-300` → `bg-elevated border-hairline text-ink` (keep `font-mono` on code — code stays monospace inside the proportional pane).
- inline code `bg-surface text-blue-400` → `bg-elevated text-accent` (or `text-ink`).
- Keep the existing regex logic + the `compact` prop behavior; ONLY the class strings change. Add `MarkdownRenderer.tsx` to the color-lint `CLEAN_SET` in `frontend/scripts/check-trading-colors.mjs`.
- Do NOT convert to `react-markdown` (out of scope — the regex renderer works; a rewrite is a separate risk).

### 3. Apply the reading pane — agent lane

`ChatSessionViewer.tsx` `MessageBubble`: replace the plain body
`<div className="text-sm text-ink whitespace-pre-wrap">{message.content}</div>`
with
`<ReadingPane><MarkdownRenderer content={message.content} /></ReadingPane>`.
Everything else in the bubble — the agent handle/name, timestamp, avatar, the per-agent identity color (`agentConfig`, already present) — stays dense mono. That contrast IS the dual mode.

### 4. Apply the reading pane — report bodies

`AnalysisDetailPage.tsx`: wrap its `MarkdownRenderer` usages (the analysis summary/report body and the trade-proposal rationale) in `ReadingPane` so the report reads editorial. Keep the surrounding dense KV/metric/table structure (from d2 T5) unchanged — only the prose bodies get the reading pane.

### 5. Dual-mode principle (the invariant)

Only message/report **prose bodies** are editorial (proportional, measured, leaded). Everything else — shell chrome, tables, vote rows, KV tickets, agent handles, timestamps, status — stays dense monospace. `font-sans` appears ONLY via `ReadingPane`. A reviewer can grep `font-sans` and expect it only in `ReadingPane`.

## Out of scope (YAGNI — deferred)

- Vote-blotter table (AGENT·VOTE·CONF·WGT·SCORE), consensus ticket restructure, always-on `tail -f` reasoning wire (`ReasoningSlidePanel` promotion) — the rest of e1, next cycle.
- Web-font loading (system `font-sans` only).
- Converting `MarkdownRenderer` to `react-markdown`.
- Any backend / data change. No new markdown features.

## Testing

- `ReadingPane.test.tsx` (vitest + @testing-library/react): renders `children` and applies the editorial classes (`font-sans`, a `max-w-*` measure, `leading-relaxed`); passes through `className`.
- `MarkdownRenderer` re-skin: a focused test (or extend an existing render check) that it still renders markdown (bold/header/list/code) and emits token classes, not raw `text-white`/`bg-surface`. (If no existing MarkdownRenderer test, a small render-and-assert-on-output test.)
- Gates: `npm run build` PASS; `npm run test:run` green except the 1 known pre-existing `navigation-bug.test.ts`; `npm run lint:colors` exit 0 (MarkdownRenderer + ReadingPane in CLEAN_SET).
- Browser (if the Chrome extension connects): a ChatSessionViewer with messages reads editorial (proportional, measured, markdown), while handles/timestamps stay mono; AnalysisDetailPage report body reads editorial. Else code+build.

## Files (anticipated)

- Create: `src/components/common/ReadingPane.tsx` (+ `ReadingPane.test.tsx`).
- Modify: `src/components/common/MarkdownRenderer.tsx` (token re-skin) (+ a render/token test).
- Modify: `src/components/agent-chat/ChatSessionViewer.tsx` (MessageBubble body → ReadingPane).
- Modify: `src/pages/AnalysisDetailPage.tsx` (report/rationale MarkdownRenderer → wrapped in ReadingPane).
- Modify: `frontend/scripts/check-trading-colors.mjs` (CLEAN_SET: MarkdownRenderer, ReadingPane).
