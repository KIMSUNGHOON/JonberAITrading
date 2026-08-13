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

Pure, enum-agnostic (works across all three per-market `TradeAction` enums by comparing the string `.value`), unit-tested. The guardrail is expressed as an explicit **feasible-set** (not a hardcoded position boolean) so each node passes the set appropriate to what it models and its pipeline can handle:

```python
from enum import Enum

# All 7 actions split by position (KR position-aware semantics).
FEASIBLE_WITH_POSITION = frozenset({"HOLD", "ADD", "REDUCE", "SELL"})
FEASIBLE_WITHOUT_POSITION = frozenset({"BUY", "WATCH", "AVOID", "HOLD"})
# Position-unaware markets (US/coin) whose node + execution pipeline only
# handle these three (their _signal_to_action range); ADD/REDUCE need a
# position the node doesn't model, and WATCH/AVOID are mishandled downstream
# (e.g. coin_nodes side = "bid" if BUY else "ask" would turn WATCH into a
# sell order) — so those fall back to the rule.
POSITION_AGNOSTIC_ACTIONS = frozenset({"BUY", "SELL", "HOLD"})

def _value(action) -> str:
    return action.value if isinstance(action, Enum) else str(action)

def action_is_feasible(action, feasible: frozenset) -> bool:
    return _value(action) in feasible

def position_feasible_set(has_position: bool) -> frozenset:
    return FEASIBLE_WITH_POSITION if has_position else FEASIBLE_WITHOUT_POSITION

def resolve_action(llm_action, fallback_action, feasible: frozenset) -> tuple:
    """Return (action, source). LLM action if in `feasible`; else the rule fallback.
    source ∈ {'llm', 'rule_guardrail'}."""
    if action_is_feasible(llm_action, feasible):
        return llm_action, "llm"
    return fallback_action, "rule_guardrail"
```

- **KR** passes `position_feasible_set(has_position)` — full position-aware 7-action feasibility.
- **US/coin** pass `POSITION_AGNOSTIC_ACTIONS` (`{BUY, SELL, HOLD}`) — the LLM genuinely decides among the actions their pipeline handles (incl. SELL), and any position-requiring or watch/avoid action falls back to the rule, avoiding downstream mishandling.

### The async orchestrator: `decide_action` (the test seam)

The strategic nodes call kiwoom/upbit (quantity), telegram, and the coordinator (watch-list) — so testing the decision *through* the whole node is heavy and brittle. Extract the LLM-consumption + guardrail + fallback flow into a small async orchestrator in the same module, so it is testable with only a mocked `llm` (no side-effect mocking):

```python
async def decide_action(llm, messages, *, trade_action_cls, rule_action, feasible,
                        decision_schema, task):
    """LLM structured decision, guarded by `feasible`, with the rule as fallback.
    Returns (action, rationale, source). source ∈ {'llm','rule_guardrail','rule_fallback'}.
    On the fallback path `rationale` may be '' — the caller supplies a node-specific
    fallback string. `llm` is duck-typed (has async generate/generate_structured), so
    this module needs no LLM/provider import and stays unit-testable."""
    try:
        decision = await llm.generate_structured(messages, decision_schema, task=task)
        llm_action = trade_action_cls(str(decision["action"]).upper())
        action, source = resolve_action(llm_action, rule_action, feasible)
        return action, (decision.get("rationale") or ""), source
    except (ValueError, KeyError):
        try:
            return rule_action, (await llm.generate(messages)), "rule_fallback"
        except Exception:
            return rule_action, "", "rule_fallback"
```

Each node becomes thin wiring: compute `rule_action`, call `decide_action`, backfill an empty rationale, log `decision_source`, then build the proposal exactly as today.

### Per-node change (KR canonical)

Replace `decision_nodes.py:181-197` (the `response = await llm.generate(...)` + `action = _signal_to_action_with_position(...)` + the `kr_stock_action_determined` log) with (pseudocode; exact code in the plan):

```python
from agents.graph.decision_policy import decide_action, position_feasible_set
from agents.llm.tasks import DECISION_SCHEMA, TaskType

rule_action = _signal_to_action_with_position(consensus_signal, has_position, position_pnl_pct)
action, response, decision_source = await decide_action(
    llm, messages, trade_action_cls=TradeAction, rule_action=rule_action,
    feasible=position_feasible_set(has_position),
    decision_schema=DECISION_SCHEMA, task=TaskType.STRATEGIC_DECISION,
)
if not response:  # both structured and plain generate failed
    response = f"[룰 기반 결정] 컨센서스 {consensus_signal.value} → {action.value} (LLM 실패)"

logger.info("kr_stock_action_determined", stk_cd=stk_cd, consensus_signal=consensus_signal.value,
            has_position=has_position, position_pnl_pct=position_pnl_pct,
            action=action.value, decision_source=decision_source)
```

Everything downstream of `action`/`response` (quantity calc, `KRStockTradeProposal`, `_extract_bull_case(response)`/`_extract_bear_case(response)`, Telegram, `synthesis`) stays byte-identical — only the *provenance* of `action` and the rationale text changes. `avg_confidence` (rule consensus confidence) keeps feeding notifications/synthesis unchanged (lowest-risk; the LLM `confidence` is recorded in the log, not rewired — a later pass can promote it).

### Per-market specifics (verified)

- **KR** (`kr_stock_nodes/decision_nodes.py`): position-aware. `has_position` = real (from `existing_position`); rule fallback = `_signal_to_action_with_position(consensus_signal, has_position, position_pnl_pct)`.
- **US** (`nodes.py:411`, `_signal_to_action` at `nodes.py:811`) and **coin** (`coin_nodes.py:431`, `_signal_to_action` at `coin_nodes.py:1078`): the strategic node does **not** model position (`grep` for `existing_position`/`has_position` = 0 hits), and both `_signal_to_action` return only `BUY`/`SELL`/`HOLD`; their proposal/execution pipeline handles only those three (e.g. `coin_nodes` computes `side = "bid" if BUY else "ask"`). So they pass the feasible-set `POSITION_AGNOSTIC_ACTIONS` (`{BUY, SELL, HOLD}`), rule fallback = `_signal_to_action(consensus_signal)`. The LLM genuinely decides among BUY/SELL/HOLD (including SELL); `ADD`/`REDUCE`/`WATCH`/`AVOID` fall back to the rule — this avoids the downstream hazard where an unmodelled action (e.g. `WATCH`) would be mis-executed as a sell. Loading US/coin positions to enable the full position-aware set is **out of scope**.
- **Design refinement note**: an earlier draft passed `has_position=False` for US/coin (position-based table), which both *allowed* `WATCH`/`AVOID` (unsafe downstream) and *blocked* `SELL` (a valid AI decision). The feasible-set approach above supersedes it — strictly safer and within the approved "guardrail + rule fallback" intent.
- Per-market `TradeAction` enums (`kr_stock_state`/`coin_state`/`state`) may not all define `WATCH`/`AVOID`; `TradeAction(...)` raising on an unknown value is caught by the `except` and falls back — verify each enum's coverage in the plan.

### Prompt updates

The three strategic prompts (`agents/prompts.py`: `STRATEGIC_DECISION_PROMPT:123` US, `COIN_STRATEGIC_DECISION_PROMPT:239`, `KR_STOCK_STRATEGIC_DECISION_PROMPT:370`) get a concise **structured-decision instruction** telling the model to return JSON matching the schema (`action`, `confidence` 0-1, `rationale`, `bull_case[]`, `bear_case[]`). The **allowed action list matches each node's feasible-set**, so the prompt and the guardrail agree:
- **KR** (position-aware): "choose one `action` from BUY / SELL / HOLD / ADD / REDUCE / WATCH / AVOID considering the current position" (in Korean — the KR prompt mandates Korean output).
- **US / coin**: "choose one `action` from BUY / SELL / HOLD".
The schema constrains shape; the prompt supplies the semantics. Keep each prompt's existing analysis guidance.

### Deterministic test seam (folds roadmap P2)

`tests/conftest.py` has no LLM mock (only data fixtures). The decision logic lives in the dependency-light `decide_action` (duck-typed `llm`), so the core tests need only an `AsyncMock` llm — no kiwoom/telegram/coordinator mocking:
- `decision_policy` **pure** unit tests (`test_decision_policy.py`): `action_is_feasible` over each set; `resolve_action` returns `("llm"|"rule_guardrail")` for feasible/infeasible; `position_feasible_set(True/False)`.
- `decide_action` unit tests (same file, `AsyncMock` llm): (a) feasible structured action → `(llm_action, rationale, "llm")`; (b) infeasible structured action → `(rule_action, rationale, "rule_guardrail")`; (c) `generate_structured` raises → `(rule_action, generate_text, "rule_fallback")`; (d) both raise → `(rule_action, "", "rule_fallback")`.
- Per-node **wiring** test (one each, T2–T4): a small `mock_llm_provider` conftest fixture patches each node module's `get_llm_provider` to an `AsyncMock` whose `generate_structured` returns `{"action":"HOLD",...}` (HOLD triggers **no** kiwoom/telegram/coordinator side-effects in any node), plus a telegram-notifier guard (`is_ready=False`); the test calls the node with a minimal state and asserts `trade_proposal["action"] == "HOLD"` and the proposal `rationale`/`synthesis` carry the LLM rationale — proving the node threads `decide_action`'s output into the proposal.

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

- **T1** — `decision_policy.py`: the sets (`FEASIBLE_WITH/WITHOUT_POSITION`, `POSITION_AGNOSTIC_ACTIONS`) + pure `action_is_feasible`, `resolve_action`, `position_feasible_set` + async `decide_action` + `tests/test_decision_policy.py` (feasibility per set, resolve source, and `decide_action`'s 4 paths via an `AsyncMock` llm). This is the deterministic decision seam.
- **T2** — KR node (`kr_stock_nodes/decision_nodes.py`): wire `decide_action` with `position_feasible_set(has_position)` + empty-rationale backfill + `decision_source` log; KR strategic prompt structured-instruction (all 7 actions, Korean); add the `mock_llm_provider` conftest fixture; KR node HOLD wiring test.
- **T3** — US node (`nodes.py:411`): wire `decide_action` with `POSITION_AGNOSTIC_ACTIONS` + `_signal_to_action` fallback; US prompt (BUY/SELL/HOLD); US node HOLD wiring test (reuse fixture).
- **T4** — coin node (`coin_nodes.py:431`): same as US; coin prompt (BUY/SELL/HOLD); coin node HOLD wiring test (reuse fixture).
