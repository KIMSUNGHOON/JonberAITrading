from agents.graph.decision_policy import (
    FEASIBLE_WITH_POSITION,
    FEASIBLE_WITHOUT_POSITION,
    POSITION_AGNOSTIC_ACTIONS,
    action_is_feasible,
    position_feasible_set,
    resolve_action,
    decide_action,
)
from agents.graph.kr_stock_state import TradeAction  # has all 7 values


def test_position_feasible_set_selects_by_position():
    assert position_feasible_set(True) is FEASIBLE_WITH_POSITION
    assert position_feasible_set(False) is FEASIBLE_WITHOUT_POSITION


def test_action_is_feasible_respects_the_set():
    assert action_is_feasible(TradeAction.SELL, FEASIBLE_WITH_POSITION) is True
    assert action_is_feasible(TradeAction.SELL, FEASIBLE_WITHOUT_POSITION) is False
    assert action_is_feasible(TradeAction.BUY, FEASIBLE_WITHOUT_POSITION) is True
    assert action_is_feasible(TradeAction.BUY, FEASIBLE_WITH_POSITION) is False
    assert action_is_feasible("HOLD", POSITION_AGNOSTIC_ACTIONS) is True
    assert action_is_feasible(TradeAction.WATCH, POSITION_AGNOSTIC_ACTIONS) is False


def test_resolve_action_uses_llm_when_feasible_else_rule():
    a, src = resolve_action(TradeAction.BUY, TradeAction.HOLD, FEASIBLE_WITHOUT_POSITION)
    assert (a, src) == (TradeAction.BUY, "llm")
    a, src = resolve_action(TradeAction.SELL, TradeAction.WATCH, FEASIBLE_WITHOUT_POSITION)
    assert (a, src) == (TradeAction.WATCH, "rule_guardrail")


class _StubLLM:
    def __init__(self, *, structured=None, structured_exc=None, text="narrative", text_exc=None):
        self._structured, self._structured_exc = structured, structured_exc
        self._text, self._text_exc = text, text_exc

    async def generate_structured(self, messages, schema, *, task=None):
        if self._structured_exc:
            raise self._structured_exc
        return self._structured

    async def generate(self, messages):
        if self._text_exc:
            raise self._text_exc
        return self._text


async def test_decide_action_consumes_feasible_llm_action():
    llm = _StubLLM(structured={"action": "buy", "confidence": 0.8, "rationale": "r"})
    action, rationale, source = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert (action, rationale, source) == (TradeAction.BUY, "r", "llm")


async def test_decide_action_guardrails_infeasible_to_rule():
    llm = _StubLLM(structured={"action": "SELL", "confidence": 0.9, "rationale": "r"})
    action, rationale, source = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.WATCH,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert (action, rationale, source) == (TradeAction.WATCH, "r", "rule_guardrail")


async def test_decide_action_falls_back_to_rule_on_structured_failure():
    llm = _StubLLM(structured_exc=ValueError("bad json"), text="fallback narrative")
    action, rationale, source = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert (action, rationale, source) == (TradeAction.HOLD, "fallback narrative", "rule_fallback")


async def test_decide_action_empty_rationale_when_both_calls_fail():
    llm = _StubLLM(structured_exc=ValueError("x"), text_exc=RuntimeError("down"))
    action, rationale, source = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert (action, rationale, source) == (TradeAction.HOLD, "", "rule_fallback")


async def test_decide_action_unknown_action_string_falls_back():
    # An action not in the enum (e.g. US/coin returning ADD) raises in the enum -> fallback.
    llm = _StubLLM(structured={"action": "NONSENSE", "confidence": 1.0, "rationale": "r"},
                   text="fb")
    action, rationale, source = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=POSITION_AGNOSTIC_ACTIONS, decision_schema={"required": []}, task="t",
    )
    assert (action, source) == (TradeAction.HOLD, "rule_fallback")
