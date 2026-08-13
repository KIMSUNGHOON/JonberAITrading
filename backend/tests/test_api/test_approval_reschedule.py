"""Paper-Proof Phase B3: reject→재분석 후 injector 재암.

R3의 문서화된 한계: injector 호출 지점이 kr/coin analysis.py의 최초
awaiting_approval 도달 1곳뿐이라, reject 후 재분석이 만든 새 제안은 플레인
HITL로 남았다. submit_decision의 rejected 분기가 — 그래프 resume가 새
awaiting_approval + 새 제안으로 끝났으면 — status를 'awaiting_approval'로
정합시키고(injector 가드가 요구) maybe_schedule_auto_approve를 재호출해야
한다. 기존 제안 ID 피닝이 이중 승인을 방지한다.

P2-5 (session-SSOT): submit_decision now resolves the session and all its
state/status entirely off the SessionManager (SM) -- there is no legacy
dict ("B") lookup and no _adopt_session_from_manager fallback (the legacy
dicts themselves were fully retired in P3-1). This fixture's fake
SessionManager is the SOLE source of truth.
"""

from unittest.mock import AsyncMock

import pytest

from services.session_manager import AnalysisSession, MarketType, SessionStatus
import app.api.routes.approval as approval_module


def _sm_session(
    session_id: str,
    *,
    market_type: MarketType = MarketType.KIWOOM,
    status: SessionStatus = SessionStatus.AWAITING_APPROVAL,
) -> AnalysisSession:
    if market_type == MarketType.KIWOOM:
        kwargs = {"ticker": "005930", "display_name": "삼성전자",
                  "stk_cd": "005930", "stk_nm": "삼성전자"}
    else:
        kwargs = {"ticker": "KRW-BTC", "display_name": "비트코인",
                  "market": "KRW-BTC", "korean_name": "비트코인"}
    state = {
        "awaiting_approval": True,
        "approval_status": None,
        "trade_proposal": {"id": "prop-old", "action": "BUY", "quantity": 1,
                           "entry_price": 70000},
        "reasoning_log": [],
    }
    return AnalysisSession(
        session_id=session_id, market_type=market_type, status=status,
        state=state, **kwargs,
    )


class _FakeSessionManager:
    """Tracks ONE AnalysisSession; implements get_session + update_state
    (the resume loop's sole per-node write, P2-5)."""

    def __init__(self, session: AnalysisSession | None):
        self._session = session

    async def get_session(self, session_id: str):
        if self._session is not None and self._session.session_id == session_id:
            return self._session
        return None

    async def update_state(self, session_id: str, updates: dict, last_node=None):
        if self._session is None or self._session.session_id != session_id:
            raise KeyError(session_id)
        self._session.state.update(updates)
        if last_node:
            self._session.last_node = last_node


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
    """SM-only session + no-op notification side channels + reschedule spy."""
    reschedule_calls = []

    async def fake_reschedule(session_id, market):
        reschedule_calls.append((session_id, market))

    monkeypatch.setattr(
        approval_module, "maybe_schedule_auto_approve", fake_reschedule
    )

    async def noop(*a, **k):
        return None

    for name in (
        "broadcast_trade_rejected", "broadcast_trade_executed",
        "broadcast_trade_queued", "broadcast_watch_added",
    ):
        monkeypatch.setattr(approval_module, name, noop)

    class _Telegram:
        enabled = False

    monkeypatch.setattr(approval_module, "get_telegram_notifier", lambda: _Telegram())

    holder: dict = {"manager": _FakeSessionManager(None)}

    async def fake_get_session_manager():
        return holder["manager"]

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    def set_sm_session(sm_session):
        holder["manager"] = _FakeSessionManager(sm_session)

    # P2-5: commit_session_state/commit_session_status are the sole writers
    # of state/status now -- fakes write through to the SAME AnalysisSession
    # the fake manager tracks (services/session_manager.py's own module
    # globals are untouched by this fixture's approval_module patch, so
    # faking these names directly is this file's isolation principle).
    async def fake_commit_session_state(session_id, updates, **kw):
        session = holder["manager"]._session
        if session is None or session.session_id != session_id:
            raise KeyError(session_id)
        session.state.update(updates)

    async def fake_commit_session_status(session_id, new_status, **kw):
        session = holder["manager"]._session
        if session is None or session.session_id != session_id:
            raise KeyError(session_id)
        session.status = new_status

    async def fake_mirror_session_status(session_id, new_status, error=None):
        session = holder["manager"]._session
        if session is not None and session.session_id == session_id:
            session.status = new_status if isinstance(new_status, SessionStatus) else SessionStatus(new_status)

    monkeypatch.setattr(approval_module, "commit_session_state", fake_commit_session_state)
    monkeypatch.setattr(approval_module, "commit_session_status", fake_commit_session_status)
    monkeypatch.setattr(approval_module, "mirror_session_status", fake_mirror_session_status)

    def set_graph(graph):
        monkeypatch.setattr(
            approval_module, "get_kr_stock_trading_graph", lambda: graph
        )

    return {
        "holder": holder,
        "reschedule_calls": reschedule_calls,
        "set_sm_session": set_sm_session,
        "set_graph": set_graph,
    }


@pytest.mark.asyncio
async def test_reject_rearms_injector_when_new_proposal_awaits(wired):
    session_id = "s1"
    wired["set_sm_session"](_sm_session(session_id))
    # 재분석이 새 제안으로 다시 인터럽트에 도달
    wired["set_graph"](_FakeGraph([
        {"re_analyze": {"approval_status": None, "user_feedback": None}},
        {"decision": {
            "trade_proposal": {"id": "prop-new", "action": "BUY", "quantity": 1,
                               "entry_price": 69000},
            "awaiting_approval": True,
            "approval_status": None,
        }},
    ]))

    await approval_module.submit_decision(session_id, "rejected", feedback="너무 비쌈")

    assert wired["holder"]["manager"]._session.status == SessionStatus.AWAITING_APPROVAL
    assert wired["reschedule_calls"] == [(session_id, "kiwoom")]


@pytest.mark.asyncio
async def test_reject_without_new_awaiting_does_not_rearm(wired):
    session_id = "s2"
    wired["set_sm_session"](_sm_session(session_id))
    # 재분석이 제안 없이 종료 (awaiting 재진입 없음)
    wired["set_graph"](_FakeGraph([
        {"re_analyze": {"approval_status": None}},
        {"finalize": {"awaiting_approval": False}},
    ]))

    await approval_module.submit_decision(session_id, "rejected")

    assert wired["holder"]["manager"]._session.status == SessionStatus.RUNNING
    assert wired["reschedule_calls"] == []


@pytest.mark.asyncio
async def test_approved_never_rearms(wired):
    session_id = "s3"
    wired["set_sm_session"](_sm_session(session_id))
    wired["set_graph"](_FakeGraph([
        {"execution": {"execution_status": "completed", "awaiting_approval": False}},
    ]))

    await approval_module.submit_decision(session_id, "approved", actor="system")

    assert wired["holder"]["manager"]._session.status == SessionStatus.COMPLETED
    assert wired["reschedule_calls"] == []


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
    session_id = "s4"
    sm_session = _sm_session(session_id)
    sm_session.state["trade_proposal"]["id"] = "P2"  # replaced while stale timer waited
    wired["set_sm_session"](sm_session)
    graph = _FakeGraph([])
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(
        session_id, "approved", actor="system", expected_proposal_id="P1"
    )

    assert result == {"status": "stood_down", "reason": "proposal_changed"}
    graph.aupdate_state.assert_not_awaited()
    assert sm_session.status == SessionStatus.AWAITING_APPROVAL
    assert sm_session.state["approval_status"] is None
    assert sm_session.state["awaiting_approval"] is True
    assert wired["reschedule_calls"] == []


@pytest.mark.asyncio
async def test_system_approve_proceeds_when_id_matches(wired):
    """The pinned id still matches what's live -> normal approval proceeds."""
    session_id = "s5"
    sm_session = _sm_session(session_id)
    sm_session.state["trade_proposal"]["id"] = "P1"
    wired["set_sm_session"](sm_session)
    graph = _FakeGraph([
        {"execution": {"execution_status": "completed", "awaiting_approval": False}},
    ])
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(
        session_id, "approved", actor="system", expected_proposal_id="P1"
    )

    assert result.status == "completed"
    assert result.decision == "approved"
    graph.aupdate_state.assert_awaited_once()
    assert sm_session.state["approval_status"] == "approved"


# --- Task 2 (F4b, IMPORTANT-1): inside-lock guard on sm_session.status ------
#
# The proposal-id pin only catches a REPLACED proposal (reject -> re-analysis).
# A cancel never replaces the proposal, so on the coin market (whose cancel
# route did not clear awaiting_approval/approval_status) a stale system
# auto-approve raced straight through the pin check and the
# `not state.get("awaiting_approval")` check into the live approve path —
# executing the trade and overwriting the cancelled status. The inside-lock
# guard must also stand down whenever sm_session.status is no longer
# AWAITING_APPROVAL, regardless of which market or which route caused the
# mutation.

@pytest.mark.asyncio
async def test_system_approve_stands_down_when_status_not_awaiting(wired):
    """cancel already flipped sm_session.status away from AWAITING_APPROVAL
    while awaiting_approval/approval_status remained in their pre-cancel
    shape — the pin still matches (cancel didn't touch the proposal), so
    only the status guard can catch this. No resume, no state mutation
    beyond what cancel already did, no order.

    코인 스택 제거(2026-08-01) 이전에는 이 테스트가 COIN 시장으로 이 가드를
    검증했다 — 이제 KIWOOM만 남아 시장을 바꿔 동일 가드를 그대로 핀한다."""
    session_id = "c1"
    sm_session = _sm_session(session_id, status=SessionStatus.CANCELLED)
    sm_session.state["trade_proposal"]["id"] = "P1"
    wired["set_sm_session"](sm_session)

    graph = _FakeGraph([])
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(
        session_id, "approved", actor="system", expected_proposal_id="P1"
    )

    assert result == {"status": "stood_down", "reason": "not_awaiting"}
    graph.aupdate_state.assert_not_awaited()
    assert sm_session.status == SessionStatus.CANCELLED
    assert sm_session.state["approval_status"] is None
    assert sm_session.state["awaiting_approval"] is True
    assert wired["reschedule_calls"] == []


async def test_user_decision_ignores_expected_id(wired):
    """actor='user' must never be stood down by the pin check -- it is scoped
    to actor=='system' only. Defense-in-depth: even a mismatched
    expected_proposal_id (never sent by the real user-facing route) must not
    change user-decision behavior."""
    session_id = "s6"
    sm_session = _sm_session(session_id)
    sm_session.state["trade_proposal"]["id"] = "P1"
    wired["set_sm_session"](sm_session)
    graph = _FakeGraph([
        {"execution": {"execution_status": "completed", "awaiting_approval": False}},
    ])
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(
        session_id, "approved", actor="user", expected_proposal_id="MISMATCH"
    )

    assert result.status == "completed"
    graph.aupdate_state.assert_awaited_once()
    assert sm_session.state["approval_status"] == "approved"
