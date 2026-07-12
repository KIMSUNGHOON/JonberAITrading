"""Paper-Proof Phase B3: reject→재분석 후 injector 재암.

R3의 문서화된 한계: injector 호출 지점이 kr/coin analysis.py의 최초
awaiting_approval 도달 1곳뿐이라, reject 후 재분석이 만든 새 제안은 플레인
HITL로 남았다. submit_decision의 rejected 분기가 — 그래프 resume가 새
awaiting_approval + 새 제안으로 끝났으면 — status를 'awaiting_approval'로
정합시키고(injector 가드가 요구) maybe_schedule_auto_approve를 재호출해야
한다. 기존 제안 ID 피닝이 이중 승인을 방지한다.
"""

from unittest.mock import AsyncMock

import pytest

import app.api.routes.approval as approval_module


def _kr_session(session_id: str) -> dict:
    return {
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "status": "awaiting_approval",
        "state": {
            "awaiting_approval": True,
            "approval_status": None,
            "trade_proposal": {"id": "prop-old", "action": "BUY", "quantity": 1,
                               "entry_price": 70000},
            "reasoning_log": [],
        },
    }


class _FakeGraph:
    """rejected resume가 재분석을 돌아 다시 approval 인터럽트에 멈춘 상황."""

    def __init__(self, resume_events):
        self._resume_events = resume_events
        self.aupdate_state = AsyncMock()

    def astream(self, _input, _config):
        events = list(self._resume_events)

        async def gen():
            for e in events:
                yield e

        return gen()


@pytest.fixture
def wired(monkeypatch):
    """세션/그래프/알림/미러/재암 스파이 배선."""
    sessions = {}
    monkeypatch.setattr(approval_module, "get_kr_stock_sessions", lambda: sessions)
    monkeypatch.setattr(approval_module, "get_coin_sessions", lambda: {})

    reschedule_calls = []

    async def fake_reschedule(session_id, market, session):
        reschedule_calls.append((session_id, market))

    monkeypatch.setattr(
        approval_module, "maybe_schedule_auto_approve", fake_reschedule
    )

    async def noop(*a, **k):
        return None

    for name in (
        "mirror_session_state", "mirror_session_status",
        "broadcast_trade_rejected", "broadcast_trade_executed",
        "broadcast_trade_queued", "broadcast_watch_added",
    ):
        monkeypatch.setattr(approval_module, name, noop)

    class _Telegram:
        enabled = False

    monkeypatch.setattr(approval_module, "get_telegram_notifier", lambda: _Telegram())

    def set_graph(graph):
        monkeypatch.setattr(
            approval_module, "get_kr_stock_trading_graph", lambda: graph
        )

    return sessions, reschedule_calls, set_graph


@pytest.mark.asyncio
async def test_reject_rearms_injector_when_new_proposal_awaits(wired):
    sessions, reschedule_calls, set_graph = wired
    sessions["s1"] = _kr_session("s1")
    # 재분석이 새 제안으로 다시 인터럽트에 도달
    set_graph(_FakeGraph([
        {"re_analyze": {"approval_status": None, "user_feedback": None}},
        {"decision": {
            "trade_proposal": {"id": "prop-new", "action": "BUY", "quantity": 1,
                               "entry_price": 69000},
            "awaiting_approval": True,
            "approval_status": None,
        }},
    ]))

    await approval_module.submit_decision("s1", "rejected", feedback="너무 비쌈")

    assert sessions["s1"]["status"] == "awaiting_approval"  # injector 가드 정합
    assert reschedule_calls == [("s1", "kiwoom")]


@pytest.mark.asyncio
async def test_reject_without_new_awaiting_does_not_rearm(wired):
    sessions, reschedule_calls, set_graph = wired
    sessions["s2"] = _kr_session("s2")
    # 재분석이 제안 없이 종료 (awaiting 재진입 없음)
    set_graph(_FakeGraph([
        {"re_analyze": {"approval_status": None}},
        {"finalize": {"awaiting_approval": False}},
    ]))

    await approval_module.submit_decision("s2", "rejected")

    assert sessions["s2"]["status"] == "running"
    assert reschedule_calls == []


@pytest.mark.asyncio
async def test_approved_never_rearms(wired):
    sessions, reschedule_calls, set_graph = wired
    sessions["s3"] = _kr_session("s3")
    set_graph(_FakeGraph([
        {"execution": {"execution_status": "completed", "awaiting_approval": False}},
    ]))

    await approval_module.submit_decision("s3", "approved", actor="system")

    assert sessions["s3"]["status"] == "completed"
    assert reschedule_calls == []
