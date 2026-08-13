"""WATCH 결정의 워치리스트 자동 추가 (HITL C1 라이브에서 발견된 버그).

프로덕션 로그: `watch_list_addition_failed ... WatchedStock.session_id Input
should be a valid string [input_value=None]` — 분석 라우트가 그래프 초기
상태에 session_id를 넣지 않아 state["session_id"]=None이 되고, 노드의
`state.get("session_id", fallback)`은 키가 '없을 때만' 폴백이라 None이 그대로
WatchedStock 검증에 도달해 WATCH 결과가 워치리스트에 한 번도 못 들어갔다.

이 테스트는 실제 ExecutionCoordinator(진짜 pydantic 검증)를 물려 노드의
WATCH 분기를 통과시켜 회귀를 고정한다.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def watch_node_harness(monkeypatch):
    """WATCH를 강제한 strategic-decision 노드 + 실제 코디네이터."""
    import agents.graph.kr_stock_nodes.decision_nodes as kr
    import app.dependencies as deps
    import services.telegram as telegram_pkg
    from services.trading.coordinator import ExecutionCoordinator

    async def fake_decide_action(llm, messages, **kwargs):
        return kr.TradeAction.WATCH, "watch rationale", "llm", None, None

    monkeypatch.setattr(kr, "get_llm_provider", lambda: MagicMock())
    monkeypatch.setattr(kr, "decide_action", fake_decide_action)

    # 실제 코디네이터 → add_to_watch_list의 WatchedStock 검증이 실제로 돈다.
    coordinator = ExecutionCoordinator(kiwoom_client=None)
    monkeypatch.setattr(
        deps, "get_trading_coordinator", AsyncMock(return_value=coordinator)
    )

    # 텔레그램은 네트워크 차단 (is_ready=False → 전송 스킵).
    notifier = MagicMock(is_ready=False)
    monkeypatch.setattr(
        telegram_pkg, "get_telegram_notifier", AsyncMock(return_value=notifier)
    )

    return kr, coordinator


async def test_watch_adds_to_watch_list_when_state_session_id_is_none(
    watch_node_harness,
):
    """세션 ID가 None(프로덕션 트리거)이어도 WATCH는 워치리스트에 들어가야 한다."""
    kr, coordinator = watch_node_harness

    state = {
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "market_data": {"cur_prc": 70000},
        "session_id": None,  # 키는 있고 값이 None — dict.get 폴백이 안 먹는 케이스
    }
    await kr.kr_stock_strategic_decision_node(state)

    watch_list = coordinator.get_watch_list()
    assert len(watch_list) == 1, "WATCH 결정이 워치리스트에 추가되지 않았다"
    assert watch_list[0].ticker == "005930"
    assert isinstance(watch_list[0].session_id, str) and watch_list[0].session_id


async def test_watch_uses_real_session_id_when_present(watch_node_harness):
    """세션 ID가 있으면 폴백이 아니라 그 값이 워치 항목에 실린다."""
    kr, coordinator = watch_node_harness

    state = {
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "market_data": {"cur_prc": 70000},
        "session_id": "sess-real-123",
    }
    await kr.kr_stock_strategic_decision_node(state)

    watch_list = coordinator.get_watch_list()
    assert len(watch_list) == 1
    assert watch_list[0].session_id == "sess-real-123"
