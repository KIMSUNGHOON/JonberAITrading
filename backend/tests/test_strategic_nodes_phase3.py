"""Phase 3 wiring tests: each strategic node passes the correct feasible-set to
decide_action and threads its (action, rationale) into the proposal. decide_action's
own logic is covered in test_decision_policy.py."""
from unittest.mock import MagicMock


async def test_kr_node_passes_position_feasible_set_and_threads_result(monkeypatch):
    import agents.graph.kr_stock_nodes.decision_nodes as kr
    from agents.graph.decision_policy import position_feasible_set

    captured = {}

    async def fake_decide_action(llm, messages, **kwargs):
        captured.update(kwargs)
        return kr.TradeAction.HOLD, "LLM chose to hold", "llm", None, None

    monkeypatch.setattr(kr, "get_llm_provider", lambda: MagicMock())
    monkeypatch.setattr(kr, "decide_action", fake_decide_action)

    state = {"stk_cd": "005930", "stk_nm": "삼성전자", "market_data": {"cur_prc": 70000}}
    result = await kr.kr_stock_strategic_decision_node(state)

    # no existing_position -> has_position False
    assert captured["feasible"] == position_feasible_set(False)
    assert captured["trade_action_cls"] is kr.TradeAction
    assert result["trade_proposal"]["action"] == "HOLD"
    assert result["synthesis"]["decision_rationale"] == "LLM chose to hold"


async def test_coin_node_passes_agnostic_set_and_threads_result(monkeypatch):
    import agents.graph.coin_nodes as coin
    from agents.graph.decision_policy import POSITION_AGNOSTIC_ACTIONS

    captured = {}

    async def fake_decide_action(llm, messages, **kwargs):
        captured.update(kwargs)
        return coin.TradeAction.HOLD, "coin hold rationale", "llm", None, None

    monkeypatch.setattr(coin, "get_llm_provider", lambda: MagicMock())
    monkeypatch.setattr(coin, "decide_action", fake_decide_action)

    state = {"market": "KRW-BTC", "market_data": {"current_price": 90000000}}
    result = await coin.coin_strategic_decision_node(state)

    assert captured["feasible"] == POSITION_AGNOSTIC_ACTIONS
    assert captured["trade_action_cls"] is coin.TradeAction
    assert result["trade_proposal"]["action"] == "HOLD"
