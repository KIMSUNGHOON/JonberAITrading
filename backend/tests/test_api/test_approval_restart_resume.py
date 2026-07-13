"""Approval decisions must survive a backend restart.

Defect (live-confirmed 2026-07-13): submit_decision only looked up sessions in
the process-local legacy dicts (get_coin_sessions()/get_kr_stock_sessions()).
Those dicts are empty after a restart, so every approve/reject on a session
created before the restart 404'd — even though the session_manager SQLite row
and the LangGraph checkpoint (keyed by thread_id=session_id) both survive a
restart (that was the whole point of the P6 durable-persistence arc).

Fix: on a legacy-dict miss, fall back to session_manager.get_session() and
re-adopt a legacy-compatible dict into the correct dict (kr vs coin, chosen
by market_type) so the rest of submit_decision (state mutation, graph resume,
WS mirrors) runs unchanged, and subsequent lookups hit the legacy dict
directly.
"""

from unittest.mock import AsyncMock

import pytest

import app.api.routes.approval as approval_module
from services.session_manager import AnalysisSession, MarketType, SessionStatus


def _sm_kiwoom_session(session_id: str, *, awaiting_approval: bool = True) -> AnalysisSession:
    return AnalysisSession(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        status=SessionStatus.AWAITING_APPROVAL if awaiting_approval else SessionStatus.COMPLETED,
        stk_cd="005930",
        stk_nm="삼성전자",
        state={
            "awaiting_approval": awaiting_approval,
            "approval_status": None,
            "trade_proposal": {
                "id": "prop-restart-1",
                "action": "BUY",
                "quantity": 1,
                "entry_price": 70000,
            },
            "reasoning_log": [],
        },
    )


class _FakeSessionManager:
    def __init__(self, session: AnalysisSession | None):
        self._session = session

    async def get_session(self, session_id: str):
        if self._session is not None and self._session.session_id == session_id:
            return self._session
        return None


class _FakeGraph:
    """Mirrors the resume-events pattern used by test_approval_reschedule.py."""

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
    """Empty legacy dicts + no-op notification/mirror side channels.

    Mirrors the mocking approach in tests/test_api/test_approval_reschedule.py.
    """
    coin_sessions: dict = {}
    kr_stock_sessions: dict = {}
    monkeypatch.setattr(approval_module, "get_coin_sessions", lambda: coin_sessions)
    monkeypatch.setattr(approval_module, "get_kr_stock_sessions", lambda: kr_stock_sessions)

    async def noop(*a, **k):
        return None

    for name in (
        "mirror_session_state",
        "mirror_session_status",
        "broadcast_trade_rejected",
        "broadcast_trade_executed",
        "broadcast_trade_queued",
        "broadcast_watch_added",
    ):
        monkeypatch.setattr(approval_module, name, noop)

    class _Telegram:
        enabled = False
        is_ready = False

    async def fake_get_telegram_notifier():
        return _Telegram()

    monkeypatch.setattr(approval_module, "get_telegram_notifier", fake_get_telegram_notifier)

    reschedule_calls = []

    async def fake_reschedule(session_id, market, session):
        reschedule_calls.append((session_id, market))

    monkeypatch.setattr(approval_module, "maybe_schedule_auto_approve", fake_reschedule)

    async def fake_get_trading_coordinator():
        raise RuntimeError("no coordinator in unit test")

    monkeypatch.setattr(approval_module, "get_trading_coordinator", fake_get_trading_coordinator)

    def set_sm_session(sm_session):
        fake_manager = _FakeSessionManager(sm_session)

        async def fake_get_session_manager():
            return fake_manager

        monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    def set_graph(graph):
        monkeypatch.setattr(approval_module, "get_kr_stock_trading_graph", lambda: graph)

    return coin_sessions, kr_stock_sessions, reschedule_calls, set_sm_session, set_graph


@pytest.mark.asyncio
async def test_approve_after_restart_falls_back_to_session_manager(wired):
    """Legacy dicts empty; sm has an AWAITING_APPROVAL kiwoom session -> no 404."""
    coin_sessions, kr_stock_sessions, _reschedule_calls, set_sm_session, set_graph = wired
    session_id = "restart-approve-1"
    set_sm_session(_sm_kiwoom_session(session_id))
    graph = _FakeGraph(
        [{"execution": {"execution_status": "completed", "awaiting_approval": False}}]
    )
    set_graph(graph)

    result = await approval_module.submit_decision(session_id, "approved")

    assert result.session_id == session_id
    assert result.status == "completed"
    # Decision applied to the (adopted) session state.
    assert kr_stock_sessions[session_id]["state"]["approval_status"] == "approved"
    assert kr_stock_sessions[session_id]["state"]["awaiting_approval"] is False
    # Resume machinery was actually invoked (not a fork / no-op).
    graph.aupdate_state.assert_awaited_once()
    resume_config, resume_update = graph.aupdate_state.await_args.args
    assert resume_config == {"configurable": {"thread_id": session_id}}
    assert resume_update["approval_status"] == "approved"
    # Re-adopted into the legacy dict so subsequent lookups hit it directly.
    assert session_id in kr_stock_sessions
    assert session_id not in coin_sessions


@pytest.mark.asyncio
async def test_reject_after_restart_falls_back_to_session_manager(wired):
    """Same restart scenario, decision='rejected' -> no 404, rejection path runs."""
    coin_sessions, kr_stock_sessions, _reschedule_calls, set_sm_session, set_graph = wired
    session_id = "restart-reject-1"
    set_sm_session(_sm_kiwoom_session(session_id))
    graph = _FakeGraph(
        [{"re_analyze": {"approval_status": None}}, {"finalize": {"awaiting_approval": False}}]
    )
    set_graph(graph)

    result = await approval_module.submit_decision(session_id, "rejected", feedback="too pricey")

    assert result.session_id == session_id
    assert result.decision == "rejected"
    # The rejection decision was injected into the graph checkpoint and the
    # resume machinery actually ran (not a fork/no-op) — the fake graph's
    # events then re-run re-analysis, which is why the *post-resume* state
    # ends up with approval_status back at None (new proposal awaiting a
    # fresh decision), same semantics as test_approval_reschedule.py.
    graph.aupdate_state.assert_awaited_once()
    resume_config, resume_update = graph.aupdate_state.await_args.args
    assert resume_config == {"configurable": {"thread_id": session_id}}
    assert resume_update["approval_status"] == "rejected"
    assert kr_stock_sessions[session_id]["status"] == "running"
    assert session_id in kr_stock_sessions


@pytest.mark.asyncio
async def test_unknown_session_still_404s(wired):
    """Miss in both legacy dicts AND session_manager -> 404 preserved."""
    from fastapi import HTTPException

    _coin_sessions, _kr_stock_sessions, _reschedule_calls, set_sm_session, _set_graph = wired
    set_sm_session(None)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision("does-not-exist", "approved")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_sm_session_not_awaiting_approval_400s(wired):
    """sm session exists but is already settled -> 400, not 404."""
    from fastapi import HTTPException

    _coin_sessions, _kr_stock_sessions, _reschedule_calls, set_sm_session, _set_graph = wired
    session_id = "restart-settled-1"
    set_sm_session(_sm_kiwoom_session(session_id, awaiting_approval=False))

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 400
    assert "not awaiting approval" in exc_info.value.detail
