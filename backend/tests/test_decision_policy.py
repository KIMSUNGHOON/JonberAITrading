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
    result = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert result == (TradeAction.BUY, "r", "llm", None, None)


async def test_decide_action_guardrails_infeasible_to_rule():
    llm = _StubLLM(structured={"action": "SELL", "confidence": 0.9, "rationale": "r"})
    result = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.WATCH,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert result == (TradeAction.WATCH, "r", "rule_guardrail", None, None)


async def test_decide_action_falls_back_to_rule_on_structured_failure():
    llm = _StubLLM(structured_exc=ValueError("bad json"), text="fallback narrative")
    result = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert result == (TradeAction.HOLD, "fallback narrative", "rule_fallback", None, None)


async def test_decide_action_empty_rationale_when_both_calls_fail():
    llm = _StubLLM(structured_exc=ValueError("x"), text_exc=RuntimeError("down"))
    result = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert result == (TradeAction.HOLD, "", "rule_fallback", None, None)


async def test_decide_action_unknown_action_string_falls_back():
    # An action not in the enum (e.g. US/coin returning ADD) raises in the enum -> fallback.
    llm = _StubLLM(structured={"action": "NONSENSE", "confidence": 1.0, "rationale": "r"},
                   text="fb")
    result = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=POSITION_AGNOSTIC_ACTIONS, decision_schema={"required": []}, task="t",
    )
    assert (result[0], result[2]) == (TradeAction.HOLD, "rule_fallback")


async def test_decide_action_threads_structured_bull_bear():
    llm = _StubLLM(structured={"action": "buy", "confidence": 0.8, "rationale": "r",
                               "bull_case": ["up1"], "bear_case": ["down1"]})
    result = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    # Arrays are joined to strings (proposal models type these fields str).
    assert result == (TradeAction.BUY, "r", "llm", "up1", "down1")


async def test_decide_action_normalizes_structured_case_arrays_to_strings():
    """LIVE-VERIFICATION BUG (R3-P2, 2026-07-12): DECISION_SCHEMA declares
    bull_case/bear_case as ARRAYS of strings, but both proposal models type the
    fields as str — a real LLM returning arrays crashed the decision node with
    a pydantic ValidationError (analysis → error). decide_action must hand
    callers strings."""
    llm = _StubLLM(structured={
        "action": "hold", "confidence": 0.7, "rationale": "r",
        "bull_case": ["Neutral Fear & Greed", "no forced breakdown"],
        "bear_case": ["Price rejected three times"],
    })
    action, rationale, source, bull, bear = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert bull == "Neutral Fear & Greed\nno forced breakdown"
    assert bear == "Price rejected three times"


async def test_decide_action_passes_string_and_none_cases_through():
    llm = _StubLLM(structured={
        "action": "hold", "confidence": 0.7, "rationale": "r",
        "bull_case": "already a string",
    })
    *_, bull, bear = await decide_action(
        llm, [], trade_action_cls=TradeAction, rule_action=TradeAction.HOLD,
        feasible=FEASIBLE_WITHOUT_POSITION, decision_schema={"required": []}, task="t",
    )
    assert bull == "already a string"
    assert bear is None
