# Backend Phase 3 — Real AI Decisions at the Strategic Nodes — Design

> Restructure roadmap **Phase 3** ("make decisions real AI"). Phase 1 built the task-routed multi-backend router and **plumbed** `generate_structured` + `DECISION_SCHEMA` ("Phase 3 consumes it; Phase 1 only plumbs it" — `agents/llm/tasks.py:69`). This spec makes the three strategic decision nodes **consume** the structured LLM decision, so the AI actually chooses the trade action instead of the LLM output being discarded. **NOT** the frozen "P3 Live Trading" (`KIWOOM_IS_MOCK=false`) — this is decision LOGIC in paper mode; live trading stays frozen.

## The problem today

The marquee claim "agentic / autonomous AI trading" is **false in code**: the LLM writes narrative, then a rule overwrites the action. In the KR strategic node (`agents/graph/kr_stock_nodes/decision_nodes.py:181-188`):

```python
response = await llm.generate(messages)                        # free text → becomes rationale/bull/bear ONLY
action = _signal_to_action_with_position(consensus_signal, …)  # RULE decides the action ← the LLM never touches it
```

Same pattern in US (`agents/graph/nodes.py:411`, `action = _signal_to_action(consensus_signal)`) and coin (`agents/graph/coin_nodes.py:458,461`). The LLM's decision is thrown away; 0% of the action is the AI's.

Phase 1 already ships everything needed to fix this:
- `LLMProvider.generate_structured(messages, schema, *, task="strategic_decision") -> dict` (`agents/llm_provider.py:172`) — JSON-parses the backend output, checks the schema's `required` keys, **raises `ValueError`** on parse failure / missing keys.
- `DECISION_SCHEMA` (`agents/llm/tasks.py:70`) — `action` (enum of the 7 TradeActions), `confidence`, `summary`, `bull_case[]`, `bear_case[]`, `rationale`; `required = [action, confidence, rationale]`.
- Router routes `TaskType.STRATEGIC_DECISION`/`RISK` to the strongest Claude model (opus) with fallback chain.

## Design

### Authority model (user-approved)

**The LLM action is authoritative, guarded by a position-feasibility check, with a rule fallback.**

1. Call `generate_structured(messages, DECISION_SCHEMA, task=STRATEGIC_DECISION)`.
2. Convert `decision["action"]` to the node's `TradeAction`.
3. **Position-feasibility guardrail**: if the LLM action is feasible for the actual position, use it (`source="llm"`); else fall back to the node's existing rule action (`source="rule_guardrail"`).
4. **Failure fallback**: if `generate_structured` raises (`ValueError`: parse/missing-keys/backend-down) or the action string is not a valid `TradeAction` (`ValueError` from the enum), fall back to the rule action (`source="rule_fallback"`) and obtain the narrative via a plain `generate` (itself guarded — a static rationale if that also fails).
5. **Worst case = today's behavior.** When the LLM path never succeeds, the node produces exactly the current rule-based action + narrative. This makes Phase 3 strictly additive in risk terms.

Observability: every node logs `decision_source ∈ {llm, rule_guardrail, rule_fallback}` + `llm_action` + `final_action` + `has_position`, so we can measure how often the AI actually decides.

### Position-feasibility table

The 7 TradeActions split by position (KR semantics, `agents/graph/kr_stock_state.py:33`):

| has_position | feasible actions |
|---|---|
| **True** (holding) | `HOLD`, `ADD`, `REDUCE`, `SELL` |
| **False** (no position) | `BUY`, `WATCH`, `AVOID`, `HOLD` |

Infeasible ⇒ fall back to the rule (e.g. LLM says `SELL` with no position, or `BUY` while already holding → use the rule action instead).

### New shared module: `agents/graph/decision_policy.py`

Pure, enum-agnostic (works across all three per-market `TradeAction` enums by comparing the string `.value`), unit-tested:

```python
from enum import Enum

_FEASIBLE_WITH_POSITION = frozenset({"HOLD", "ADD", "REDUCE", "SELL"})
_FEASIBLE_WITHOUT_POSITION = frozenset({"BUY", "WATCH", "AVOID", "HOLD"})

def _value(action) -> str:
    return action.value if isinstance(action, Enum) else str(action)

def action_is_feasible(action, has_position: bool) -> bool:
    v = _value(action)
    return v in (_FEASIBLE_WITH_POSITION if has_position else _FEASIBLE_WITHOUT_POSITION)

def resolve_action(llm_action, fallback_action, has_position: bool) -> tuple:
    """Return (action, source). LLM action if feasible for the position; else the rule fallback.
    source ∈ {'llm', 'rule_guardrail'}."""
    if action_is_feasible(llm_action, has_position):
        return llm_action, "llm"
    return fallback_action, "rule_guardrail"
```

### Per-node change (KR canonical)

Replace `decision_nodes.py:181-188` with (pseudocode; exact code in the plan):

```python
from agents.graph.decision_policy import resolve_action
from agents.llm.tasks import DECISION_SCHEMA, TaskType

rule_action = _signal_to_action_with_position(consensus_signal, has_position, position_pnl_pct)
try:
    decision = await llm.generate_structured(messages, DECISION_SCHEMA, task=TaskType.STRATEGIC_DECISION)
    llm_action = TradeAction(str(decision["action"]).upper())
    action, decision_source = resolve_action(llm_action, rule_action, has_position)
    response = decision.get("rationale") or ""
    bull = decision.get("bull_case") or _extract_bull_case(response)
    bear = decision.get("bear_case") or _extract_bear_case(response)
except (ValueError, KeyError) as e:
    logger.warning("structured_decision_failed", stk_cd=stk_cd, error=str(e))
    action, decision_source = rule_action, "rule_fallback"
    try:
        response = await llm.generate(messages)
    except Exception:
        response = f"[룰 기반 결정] 컨센서스 {consensus_signal.value} → {action.value} (LLM 구조화/생성 실패)"
    bull, bear = _extract_bull_case(response), _extract_bear_case(response)

logger.info("kr_stock_decision_source", stk_cd=stk_cd, decision_source=decision_source,
            final_action=action.value, has_position=has_position)
```

Everything downstream of `action`/`response` (quantity calc, `KRStockTradeProposal`, Telegram, `synthesis`, `bull_case`/`bear_case`) stays as-is — only the *provenance* of `action` and the rationale text changes. `avg_confidence` (rule consensus confidence) keeps feeding notifications/synthesis unchanged (lowest-risk; the LLM `confidence` is recorded in the log, not rewired — a later pass can promote it).

### Per-market specifics (verified)

- **KR** (`kr_stock_nodes/decision_nodes.py`): position-aware. `has_position` = real (from `existing_position`); rule fallback = `_signal_to_action_with_position(consensus_signal, has_position, position_pnl_pct)`.
- **US** (`nodes.py:411`) and **coin** (`coin_nodes.py:431`): the strategic node does **not** model position (`grep` for `existing_position`/`has_position` = 0 hits). Pass `has_position=False` (honest to what the node knows) and rule fallback = `_signal_to_action(consensus_signal)`. Consequence: the guardrail limits the LLM to the no-position set `{BUY, WATCH, AVOID, HOLD}`; if the LLM picks a position-requiring action (`SELL`/`REDUCE`/`ADD`) it falls back to the rule (which still yields the existing signal-based action). Loading US/coin positions is **out of scope**.
- Per-market `TradeAction` enums (`kr_stock_state`/`coin_state`/`state`) may not all define `WATCH`/`AVOID`; `TradeAction(...)` raising on an unknown value is caught by the `except` and falls back — verify each enum's coverage in the plan.

### Prompt updates

The three strategic prompts (`agents/prompts.py`: `STRATEGIC_DECISION_PROMPT:123` US, `COIN_STRATEGIC_DECISION_PROMPT:239`, `KR_STOCK_STRATEGIC_DECISION_PROMPT:370`) get a concise **structured-decision instruction**: "Return your decision as JSON matching the schema — choose exactly one `action` from BUY/SELL/HOLD/ADD/REDUCE/WATCH/AVOID considering the current position, a `confidence` 0-1, a `rationale`, and `bull_case`/`bear_case` arrays." The schema constrains shape; the prompt supplies the semantics (which action, position-aware). Keep each prompt's existing analysis guidance.

### Deterministic test seam (folds roadmap P2)

`tests/conftest.py` has no LLM mock (only data fixtures). Add a reusable fixture that patches `get_llm_provider()` so `generate_structured` returns a fixed dict and `generate` returns fixed text. Tests then verify, deterministically:
- `decision_policy` pure unit tests: the full feasibility table (both position states × 7 actions) + `resolve_action` returns `("llm"|"rule_guardrail")` correctly.
- Node tests (per node): (a) feasible LLM action is consumed (`source=llm`, proposal `action` = LLM's); (b) infeasible LLM action → rule action (`source=rule_guardrail`); (c) `generate_structured` raising `ValueError` → rule action (`source=rule_fallback`) with a narrative.

This gives the decision nodes their first deterministic tests (the current path hits the real router) — the roadmap's P2 intent, scoped to what P3 needs.

## Out of scope (YAGNI — deferred)

- Group-chat weighted-vote consensus enforcement (`services/agent_chat`) — separate subsystem, later.
- Promoting the ~6 analyst rule-signals to structured LLM outputs.
- Loading US/coin positions into their strategic nodes (position-awareness for those markets).
- Rewiring `avg_confidence` → LLM `confidence` in notifications/proposal (recorded in logs only for now).
- Any live-trading change (`KIWOOM_IS_MOCK` stays; execution path untouched); streaming.

## Testing / gates

- `cd backend && /Users/sunghoonk/anaconda3/envs/agentic-trading/bin/python -m pytest <targeted files> --no-cov -o addopts="" -q` FOREGROUND (the full suite + coverage stalls; `import app.main` needs cwd=backend).
- New tests: `tests/test_decision_policy.py` (pure), plus node tests using the new provider-mock fixture. All new tests pass; no pre-existing passing test regresses.
- Manual/log check: with a mocked feasible decision, the KR node's `synthesis.decision_rationale` reflects the LLM rationale and the log shows `decision_source=llm`. (No live LLM call in tests.)

## Files

- **Create**: `agents/graph/decision_policy.py`; `tests/test_decision_policy.py`; per-node test file(s) (e.g. `tests/test_strategic_decision_nodes.py`).
- **Modify**: `agents/graph/kr_stock_nodes/decision_nodes.py`, `agents/graph/nodes.py` (US strategic node), `agents/graph/coin_nodes.py` (coin strategic node), `agents/prompts.py` (3 strategic prompts), `tests/conftest.py` (provider-mock fixture).

## SDD task breakdown (4 tasks)

- **T1** — `decision_policy.py` pure module (`action_is_feasible`, `resolve_action`) + `tests/test_decision_policy.py` (full feasibility table + resolve source).
- **T2** — KR node: consume `generate_structured` + guardrail + fallback + `decision_source` log + KR strategic prompt structured-instruction + add the `conftest` provider-mock fixture + KR node tests (llm / rule_guardrail / rule_fallback paths).
- **T3** — US node (`nodes.py`): same pattern (`has_position=False`, `_signal_to_action` fallback) + US prompt + node tests (reuse fixture).
- **T4** — coin node (`coin_nodes.py`): same pattern + coin prompt + node tests (reuse fixture).
