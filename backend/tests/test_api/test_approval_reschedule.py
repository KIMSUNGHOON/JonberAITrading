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


# --- Task 1 (F4b, CRITICAL): atomic proposal-ID pin -------------------------
#
# The autonomy injector's grace-window timer checks the proposal id BEFORE
# calling submit_decision (see _autonomy_injector._auto_approve_after_grace).
# But that check happens OUTSIDE the per-session decision lock: a reject ->
# re-analysis can replace state["trade_proposal"] with a NEW id in the window
# between that outside check and the timer actually acquiring the lock inside
# submit_decision. Without a check taken INSIDE the lock, the stale timer can
# still approve a proposal the user never saw. These tests pin the fix.

@pytest.mark.asyncio
async def test_system_approve_stands_down_when_proposal_replaced(wired):
    """TOCTOU: proposal replaced ("P1" -> "P2") between the injector's outside
    pin check and the lock being acquired -> stand down silently. No resume,
    no state mutation, no status change."""
    sessions, reschedule_calls, set_graph = wired
    sessions["s4"] = _kr_session("s4")
    sessions["s4"]["state"]["trade_proposal"]["id"] = "P2"  # replaced while stale timer waited
    graph = _FakeGraph([])
    set_graph(graph)

    result = await approval_module.submit_decision(
        "s4", "approved", actor="system", expected_proposal_id="P1"
    )

    assert result == {"status": "stood_down", "reason": "proposal_changed"}
    graph.aupdate_state.assert_not_awaited()
    assert sessions["s4"]["status"] == "awaiting_approval"
    assert sessions["s4"]["state"]["approval_status"] is None
    assert sessions["s4"]["state"]["awaiting_approval"] is True
    assert reschedule_calls == []


@pytest.mark.asyncio
async def test_system_approve_proceeds_when_id_matches(wired):
    """The pinned id still matches what's live -> normal approval proceeds."""
    sessions, reschedule_calls, set_graph = wired
    sessions["s5"] = _kr_session("s5")
    sessions["s5"]["state"]["trade_proposal"]["id"] = "P1"
    graph = _FakeGraph([
        {"execution": {"execution_status": "completed", "awaiting_approval": False}},
    ])
    set_graph(graph)

    result = await approval_module.submit_decision(
        "s5", "approved", actor="system", expected_proposal_id="P1"
    )

    assert result.status == "completed"
    assert result.decision == "approved"
    graph.aupdate_state.assert_awaited_once()
    assert sessions["s5"]["state"]["approval_status"] == "approved"


def _coin_session(session_id: str) -> dict:
    """A coin session where the user's cancel already landed (route sets
    session["status"] = "cancelled") but — pre-fix — left
    state["awaiting_approval"] True and approval_status None behind, exactly
    the shape the buggy coin cancel route used to produce (see coin/analysis.py
    cancel route + F4b IMPORTANT-1)."""
    return {
        "market": "KRW-BTC",
        "korean_name": "비트코인",
        "status": "cancelled",
        "state": {
            "awaiting_approval": True,
            "approval_status": None,
            "trade_proposal": {"id": "P1", "action": "BUY", "quantity": 1,
                               "entry_price": 50_000_000},
            "reasoning_log": [],
        },
    }


# --- Task 2 (F4b, IMPORTANT-1): inside-lock guard on session["status"] ------
#
# The proposal-id pin only catches a REPLACED proposal (reject -> re-analysis).
# A cancel never replaces the proposal, so on the coin market (whose cancel
# route did not clear awaiting_approval/approval_status) a stale system
# auto-approve raced straight through the pin check and the
# `not state.get("awaiting_approval")` check into the live approve path —
# executing the trade and overwriting the cancelled status. The inside-lock
# guard must also stand down whenever session["status"] is no longer
# "awaiting_approval", regardless of which market or which route caused the
# mutation.

@pytest.mark.asyncio
async def test_coin_system_approve_stands_down_when_status_not_awaiting(wired, monkeypatch):
    """Coin analog of the stale-approve stand-down: cancel already flipped
    session["status"] away from "awaiting_approval" while awaiting_approval/
    approval_status remained in their pre-cancel shape (the coin route bug
    this arc fixes) — the pin still matches (cancel didn't touch the
    proposal), so only the session-status guard can catch this. No resume,
    no state mutation beyond what cancel already did, no order."""
    _sessions, reschedule_calls, _set_graph = wired
    coin_sessions = {"c1": _coin_session("c1")}
    monkeypatch.setattr(approval_module, "get_coin_sessions", lambda: coin_sessions)
    monkeypatch.setattr(approval_module, "get_kr_stock_sessions", lambda: {})

    graph = _FakeGraph([])
    monkeypatch.setattr(approval_module, "get_coin_trading_graph", lambda: graph)

    result = await approval_module.submit_decision(
        "c1", "approved", actor="system", expected_proposal_id="P1"
    )

    assert result == {"status": "stood_down", "reason": "not_awaiting"}
    graph.aupdate_state.assert_not_awaited()
    assert coin_sessions["c1"]["status"] == "cancelled"
    assert coin_sessions["c1"]["state"]["approval_status"] is None
    assert coin_sessions["c1"]["state"]["awaiting_approval"] is True
    assert reschedule_calls == []


async def test_user_decision_ignores_expected_id(wired):
    """actor='user' must never be stood down by the pin check -- it is scoped
    to actor=='system' only. Defense-in-depth: even a mismatched
    expected_proposal_id (never sent by the real user-facing route) must not
    change user-decision behavior."""
    sessions, reschedule_calls, set_graph = wired
    sessions["s6"] = _kr_session("s6")
    sessions["s6"]["state"]["trade_proposal"]["id"] = "P1"
    graph = _FakeGraph([
        {"execution": {"execution_status": "completed", "awaiting_approval": False}},
    ])
    set_graph(graph)

    result = await approval_module.submit_decision(
        "s6", "approved", actor="user", expected_proposal_id="MISMATCH"
    )

    assert result.status == "completed"
    graph.aupdate_state.assert_awaited_once()
    assert sessions["s6"]["state"]["approval_status"] == "approved"
