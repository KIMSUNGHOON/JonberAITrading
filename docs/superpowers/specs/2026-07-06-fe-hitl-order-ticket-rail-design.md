# FE feature e2 — HITL Docked Order-Ticket Rail — Design

> Part of the frontend redesign's **Phase 3 "AI 레인"** (`docs/superpowers/specs/2026-07-05-frontend-redesign-design.md` §5, §7). This spec covers ONLY the docked HITL order-ticket (e2). The sibling Phase-3 piece — **agent-lane dual-mode (e1)** — is deferred to its own later spec/cycle.

## Goal

Promote the human-in-the-loop trade-approval UI from a **modal that pops over every view** (`components/approval/ApprovalDialog.tsx`) to a **persistent docked order-ticket rail** on the right edge of the terminal shell — always visible, dense, keyboard-confirmable, so a time-sensitive approval is never missed and never blocks content. This is a **frontend presentation change**: it re-homes and re-skins the existing approval UI and reuses the existing decision-submission flow verbatim. It does NOT build or modify any trade-execution pipeline.

## Hard constraints (safety / honesty)

- **Live trading is FROZEN; the approval→execute backend path is known-broken** (`approval.py` `astream(None)` without `update_state`; `order_agent` calls a nonexistent `place_order`). This feature therefore MUST NOT build, fix, or imply live execution.
- Approve/Reject/Cancel call the **existing** `submitApproval({ session_id, decision, feedback })` endpoint exactly as the current modal does — same optimistic close, same system chat message, same error handling. The ticket reports "decision submitted", never "trade executed".
- **No fabricated data.** Idle/unknown fields render honest empty states (`—`, "NO PENDING ORDER"), never invented numbers.

## Approach (chosen)

**TerminalShell owns a persistent right-rail region** (like it already owns the command bar, nav rail, and status line). Rejected alternatives: a react-mosaic tile (dashboard-route only — the rail must show on every route), and a `position: fixed` overlay (reserves no space, overlaps content).

## Layout — TerminalShell

- Body becomes a 3-column row under the command bar: `[ nav rail | <Outlet/> | order-ticket rail ]`. The bottom status line stays full-width below.
- The order-ticket rail is slim on desktop (target `w-64`, ~256px) and always present.
- **Desktop-only.** The rail renders only at desktop widths. The `ApprovalDialog` modal is **retired entirely** — there is no mobile HITL fallback. This is an accepted scope cut: at mobile widths a pending approval has no UI. (Documented limitation; a mobile HITL treatment is a future follow-up if needed.)

## Component — `OrderTicketRail`

A single component subscribing to the store, with two visual states:

**Idle** (no proposal awaiting): slim header `ORDER` + `NO PENDING ORDER` (`text-dim`) + one honest status line showing the active market's current session stage / last decision (from `selectStatus` / current-stage / last-decision state; `—` when none). No fabrication.

**Active** (`awaitingApproval && tradeProposal` for the active market): a dense key-value ticket built from the existing proposal fields (the same set the modal shows):
- ACTION badge — `pnlColor`-driven, **text-only** chip (BUY/ADD → up/green, SELL/REDUCE → down/red, HOLD → muted), matching the app-wide convention already unified in d/d-follow/d2.
- SYMBOL, QTY (`tabular-nums`).
- ENTRY / current price, STOP-LOSS (`text-down`), TAKE-PROFIT (`text-up`) — all `tabular-nums`, currency via the existing `formatCurrency(value, marketType)`.
- Risk gauge — bar + label colored **green→amber→red = `up`→`warn`→`down` tokens (NOT brand `accent`)**, reusing the existing `getRiskLevel(risk_score)` helper (re-pointed to the semantic tokens).
- KR market-close warning — preserved from the current dialog.
- Feedback `textarea` (used on Reject).
- Large labeled **[REJECT]** and **[APPROVE]** buttons — no `[y/N]` trap.

Active proposal = the **active market's** `tradeProposal` (the store is already per-market: stock/coin/kiwoom). Multiple simultaneous pending proposals across markets are out of scope for v1 (the rail shows the active market's; an optional small count indicator may hint at others — not required).

## Data & behavior

- Store wiring: the rail reads `awaitingApproval` + `tradeProposal` (+ status/stage/last-decision for the idle line) for the active market, via existing selectors. On decision it calls the existing `submitApproval` action path and preserves the existing optimistic-close + `addChatMessage` + `setError` behavior.
- The store's `showApprovalDialog` flag and its open-on-proposal logic (`store/index.ts` ~562) are removed or reduced to what the rail needs — the rail is driven by `awaitingApproval && tradeProposal`, not by a separate "dialog open" boolean. Any now-dead `showApprovalDialog` state/setters are deleted (tsc `noUnusedLocals` will surface leftovers).

## Keyboard model (safe — no accidental approve)

- **No single-keystroke approve.** The Approve/Reject buttons are focusable. A shortcut (e.g. `⌘⏎`, or focusing the rail then Tab) moves focus to the Approve button; the user then presses Enter/Space to activate it. Approving is always a **deliberate two-step** action. This satisfies the spec's "키보드 확정" while avoiding the `[y/N]` hazard.

## Styling / cleanup

- Full dense-terminal token pass (the current `ApprovalDialog` still uses old `text-white`/gray tokens — part of the raw-color debt). All directional/P&L color routes through `@/utils/pnl`; risk gauge uses `up`/`warn`/`down`; surfaces → `card`/`elevated`, borders → `hairline`.
- Add `OrderTicketRail`'s file(s) to the `CLEAN_SET` in `frontend/scripts/check-trading-colors.mjs`; `npm run lint:colors` must stay green.
- Delete `components/approval/ApprovalDialog.tsx` (and its App.tsx mount) once the rail replaces it; salvage `getRiskLevel`, `formatCurrency` usage, and the KR-close-warning logic into the rail or a shared helper.

## Out of scope (YAGNI — explicitly deferred)

- Agent-lane dual-mode (e1) — separate cycle.
- HITL light-theme inversion (meaningless while live trading is frozen).
- Useful idle-rail content (mini positions/portfolio) — duplicates existing tiles.
- Multi-market pending-proposal queue.
- Any backend / execution-pipeline change.
- Mobile HITL UI.

## Testing

- vitest component tests: idle↔active state transition; `submitApproval` called with the right `{session_id, decision, feedback}` on Approve/Reject/Cancel; risk gauge maps score→`up`/`warn`/`down`; the keyboard two-step focuses Approve without activating it on a stray key.
- Gates: `npm run build` PASS, `npm run test:run` green (except the 1 known pre-existing `navigation-bug.test.ts` failure), `npm run lint:colors` exit 0.
- Browser verify (if the Chrome extension connects): idle rail on `/`, and — if a proposal can be produced — the active ticket; else code+build.

## Files (anticipated)

- Modify: `components/terminal/TerminalShell.tsx` (add the right-rail region).
- Add: `components/terminal/OrderTicketRail.tsx` (+ possibly a small `orderTicket` helper for `getRiskLevel`/KR-close if extracted).
- Modify: `store/index.ts` (drop `showApprovalDialog` open-logic; expose whatever selector the rail needs).
- Modify: `App.tsx` (remove the `ApprovalDialog` mount).
- Delete: `components/approval/ApprovalDialog.tsx`.
- Modify: `frontend/scripts/check-trading-colors.mjs` (CLEAN_SET).
