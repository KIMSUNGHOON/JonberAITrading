"""
Decision policy for the strategic nodes (Phase 3).

`decide_action` runs the LLM's structured decision, guards it against a
node-supplied feasible-set, and falls back to the node's existing rule action on
infeasibility or any failure. Pure helpers (`action_is_feasible`,
`resolve_action`, `position_feasible_set`) are unit-tested independently; the
module is dependency-light (the `llm` and `TradeAction` class are passed in) so
it needs no LLM/graph imports and stays testable with a stub llm.
"""
from enum import Enum

# The 7 TradeActions split by position (KR position-aware semantics).
FEASIBLE_WITH_POSITION = frozenset({"HOLD", "ADD", "REDUCE", "SELL"})
FEASIBLE_WITHOUT_POSITION = frozenset({"BUY", "WATCH", "AVOID", "HOLD"})
# Position-unaware markets (US/coin): their node + execution pipeline handle only
# these three (their _signal_to_action range and TradeAction enum).
POSITION_AGNOSTIC_ACTIONS = frozenset({"BUY", "SELL", "HOLD"})


def _value(action) -> str:
    return action.value if isinstance(action, Enum) else str(action)


def action_is_feasible(action, feasible: frozenset) -> bool:
    return _value(action) in feasible


def position_feasible_set(has_position: bool) -> frozenset:
    return FEASIBLE_WITH_POSITION if has_position else FEASIBLE_WITHOUT_POSITION


def resolve_action(llm_action, fallback_action, feasible: frozenset):
    """Return (action, source). LLM action if in `feasible`, else the rule fallback.
    source in {'llm', 'rule_guardrail'}."""
    if action_is_feasible(llm_action, feasible):
        return llm_action, "llm"
    return fallback_action, "rule_guardrail"


async def decide_action(llm, messages, *, trade_action_cls, rule_action, feasible,
                        decision_schema, task):
    """LLM structured decision, guarded by `feasible`, with the rule as fallback.

    Returns (action, rationale, source); source in {'llm','rule_guardrail','rule_fallback'}.
    On the fallback path `rationale` may be '' — the caller supplies a fallback string.
    """
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
