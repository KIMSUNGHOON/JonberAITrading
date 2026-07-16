"""P2-5: /decide 결정·resume는 SessionManager(SM) 단독 상태로 동작한다.

세션 SSOT 통합 P2-5의 신규 테스트: `_adopt_session_from_manager`는 삭제되고
`submit_decision`/`_submit_decision_locked`는 오직 `sm.get_session()`이
돌려주는 AnalysisSession 하나만 참조한다(레거시 dict 병합 조회 없음, B에
아무것도 쓰지 않음). 이 파일은 브리프가 요구한 4가지를 정확히 고정한다:

  1. B가 완전히 빈 상태에서 approve 전 사이클(그래프 페이크) 후 SM
     COMPLETED로 정상 귀결.
  2. reject -> 재분석이 새 awaiting을 SM에 직접 만든다(재-arm 포함).
  3. cancel 동시성 가드(진행 중인 decision과 겹치는 cancel 직렬화)가
     _adopt 제거 후에도 보존된다.
  4. `_adopt_session_from_manager` 심볼이 approval.py에서 완전히
     제거되었다(grep 0).
"""

import asyncio

import pytest

import app.api.routes.approval as approval_module
from services.session_manager import AnalysisSession, MarketType, SessionStatus


def _kr_sm_session(
    session_id: str,
    *,
    status: SessionStatus = SessionStatus.AWAITING_APPROVAL,
    awaiting_approval: bool = True,
    approval_status: str | None = None,
) -> AnalysisSession:
    return AnalysisSession(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        display_name="삼성전자",
        ticker="005930",
        stk_cd="005930",
        stk_nm="삼성전자",
        status=status,
        state={
            "awaiting_approval": awaiting_approval,
            "approval_status": approval_status,
            "trade_proposal": {
                "id": "prop-direct-1",
                "action": "BUY",
                "quantity": 1,
                "entry_price": 70000,
            },
            "reasoning_log": [],
        },
    )


class _FakeSessionManager:
    """B-free stand-in for SessionManager: tracks ONE AnalysisSession by id
    and implements exactly the two methods submit_decision now calls
    directly -- get_session (session acquisition) and update_state (the
    resume loop's sole per-node write, P2-5). Both operate on the SAME live
    AnalysisSession object, matching the real SessionManager's in-place
    mutation contract (no separate legacy-dict copy exists to fall out of
    sync)."""

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
    def __init__(self, resume_events):
        self._resume_events = resume_events
        self.aupdate_state_calls = []

    async def aupdate_state(self, config, update):
        self.aupdate_state_calls.append((config, update))

    def astream(self, _input, _config):
        events = list(self._resume_events)

        async def gen():
            for e in events:
                yield e

        return gen()


@pytest.fixture
def wired(monkeypatch):
    """No legacy dicts at all are ever populated by this fixture -- B is
    asserted to remain completely untouched by every test in this file
    (see get_coin_sessions/get_kr_stock_sessions patched to always-empty
    dicts, and the explicit "B never touched" assertions below)."""
    coin_sessions: dict = {}
    kr_stock_sessions: dict = {}
    monkeypatch.setattr(approval_module, "get_coin_sessions", lambda: coin_sessions)
    monkeypatch.setattr(approval_module, "get_kr_stock_sessions", lambda: kr_stock_sessions)

    holder: dict = {"manager": _FakeSessionManager(None)}

    async def fake_get_session_manager():
        return holder["manager"]

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    def set_sm_session(sm_session):
        holder["manager"] = _FakeSessionManager(sm_session)

    # P2-5: commit_session_state/commit_session_status are the SOLE writers
    # of state/status -- fakes write through to the SAME AnalysisSession the
    # fake manager tracks, exactly like the real SessionManager.update_
    # state/update_status would. Faked directly (rather than routed through
    # the fake manager) per this suite's isolation principle: services/
    # session_manager.py's own module globals are untouched by patching
    # approval_module's name binding.
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
            if error:
                session.error = error

    monkeypatch.setattr(approval_module, "commit_session_state", fake_commit_session_state)
    monkeypatch.setattr(approval_module, "commit_session_status", fake_commit_session_status)
    monkeypatch.setattr(approval_module, "mirror_session_status", fake_mirror_session_status)

    async def noop(*a, **k):
        return None

    for name in (
        "broadcast_trade_rejected", "broadcast_trade_executed",
        "broadcast_trade_queued", "broadcast_watch_added",
    ):
        monkeypatch.setattr(approval_module, name, noop)

    class _Telegram:
        enabled = False
        is_ready = False

    async def fake_get_telegram_notifier():
        return _Telegram()

    monkeypatch.setattr(approval_module, "get_telegram_notifier", fake_get_telegram_notifier)

    async def fake_get_trading_coordinator():
        raise RuntimeError("no coordinator in unit test")

    monkeypatch.setattr(approval_module, "get_trading_coordinator", fake_get_trading_coordinator)

    reschedule_calls = []

    async def fake_reschedule(session_id, market, session):
        reschedule_calls.append((session_id, market, session))

    monkeypatch.setattr(approval_module, "maybe_schedule_auto_approve", fake_reschedule)

    def set_graph(graph):
        monkeypatch.setattr(approval_module, "get_kr_stock_trading_graph", lambda: graph)

    return {
        "holder": holder,
        "coin_sessions": coin_sessions,
        "kr_stock_sessions": kr_stock_sessions,
        "set_sm_session": set_sm_session,
        "set_graph": set_graph,
        "reschedule_calls": reschedule_calls,
    }


# --- 1. B completely empty, full approve cycle -> SM COMPLETED --------------


@pytest.mark.asyncio
async def test_approve_cycle_with_b_fully_empty_lands_sm_completed(wired):
    """B (legacy dicts) is never populated anywhere in this test -- the
    session exists ONLY in the fake SessionManager. A full approve cycle
    (fake graph resume through to an execution node) must land the session
    COMPLETED in the SM, with B still completely empty afterward."""
    session_id = "direct-approve-1"
    wired["set_sm_session"](_kr_sm_session(session_id))
    graph = _FakeGraph([
        {"execution": {"execution_status": "completed", "awaiting_approval": False}},
    ])
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(session_id, "approved")

    assert result.session_id == session_id
    assert result.decision == "approved"
    assert result.status == "completed"

    sm_session = wired["holder"]["manager"]._session
    assert sm_session.status == SessionStatus.COMPLETED
    assert sm_session.state["approval_status"] == "approved"
    assert sm_session.state["awaiting_approval"] is False
    assert sm_session.state["execution_status"] == "completed"

    # The graph's own resume machinery actually ran (not a fork/no-op).
    assert len(graph.aupdate_state_calls) == 1
    resume_config, resume_update = graph.aupdate_state_calls[0]
    assert resume_config == {"configurable": {"thread_id": session_id}}
    assert resume_update["approval_status"] == "approved"

    # B never participated at any point.
    assert wired["kr_stock_sessions"] == {}
    assert wired["coin_sessions"] == {}


# --- 2. reject -> re-analysis makes a NEW awaiting directly in the SM -------


@pytest.mark.asyncio
async def test_reject_reanalysis_creates_new_awaiting_directly_in_sm(wired):
    """A rejected decision whose resume lands back at a fresh approval
    interrupt (new proposal) must commit AWAITING_APPROVAL straight to the
    SM and re-arm the autonomy injector -- entirely through sm.update_state
    in the resume loop, no B involved."""
    session_id = "direct-reject-1"
    wired["set_sm_session"](_kr_sm_session(session_id))
    graph = _FakeGraph([
        {"re_analyze": {"approval_status": None, "user_feedback": None}},
        {"decision": {
            "trade_proposal": {"id": "prop-direct-2", "action": "BUY",
                               "quantity": 1, "entry_price": 68000},
            "awaiting_approval": True,
            "approval_status": None,
        }},
    ])
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(session_id, "rejected", feedback="too pricey")

    assert result.decision == "rejected"
    assert result.status == "awaiting_approval"
    assert result.execution_status == "awaiting_approval"

    sm_session = wired["holder"]["manager"]._session
    assert sm_session.status == SessionStatus.AWAITING_APPROVAL
    # The new proposal from the resume event landed directly in the SM's
    # own state dict via sm.update_state -- no separate B copy to reconcile.
    assert sm_session.state["trade_proposal"]["id"] == "prop-direct-2"
    assert sm_session.state["awaiting_approval"] is True

    # Injector re-armed exactly once, for this session/market.
    assert len(wired["reschedule_calls"]) == 1
    resched_session_id, resched_market, resched_session_arg = wired["reschedule_calls"][0]
    assert resched_session_id == session_id
    assert resched_market == "kiwoom"
    # The injector arg is a live view over the SAME sm_session (P2-5's
    # _SmSessionView), not a to_legacy_dict() snapshot -- state["state"]/
    # ["status"] read through to the live object.
    assert resched_session_arg["state"] is sm_session.state
    assert resched_session_arg["status"] == "awaiting_approval"

    assert wired["kr_stock_sessions"] == {}
    assert wired["coin_sessions"] == {}


# --- 3. cancel concurrency guard preserved without _adopt --------------------


@pytest.mark.asyncio
async def test_cancel_concurrency_guard_preserved_without_adopt(wired):
    """The per-session decision lock (_session_decision_lock) must still
    serialize a cancel against an in-flight decision on the SAME session,
    exactly as before _adopt_session_from_manager was deleted -- the lock
    lives in approval.py itself and never depended on the adoption
    machinery, but this pins that removing B/adoption didn't accidentally
    also remove or bypass the lock."""
    session_id = "direct-concurrent-1"
    wired["set_sm_session"](_kr_sm_session(session_id))

    resume_started = asyncio.Event()
    resume_gate = asyncio.Event()

    class _SlowGraph:
        def __init__(self):
            self.aupdate_state_calls = []

        async def aupdate_state(self, config, update):
            self.aupdate_state_calls.append((config, update))

        def astream(self, _input, _config):
            async def gen():
                resume_started.set()
                await resume_gate.wait()
                yield {"finalize": {"awaiting_approval": False}}

            return gen()

    graph = _SlowGraph()
    wired["set_graph"](graph)

    reject_task = asyncio.create_task(
        approval_module.submit_decision(session_id, "rejected", feedback="slow")
    )
    await asyncio.wait_for(resume_started.wait(), timeout=5)

    cancel_task = asyncio.create_task(
        approval_module.submit_decision(session_id, "cancelled")
    )
    for _ in range(10):
        await asyncio.sleep(0)
    assert not cancel_task.done(), "cancel must block on the per-session lock"

    resume_gate.set()
    reject_result = await reject_task
    cancel_result = await cancel_task

    assert reject_result.decision == "rejected"
    assert reject_result.status == "running"
    assert cancel_result.decision == "cancelled"
    assert cancel_result.status == "cancelled"

    sm_session = wired["holder"]["manager"]._session
    assert sm_session.status == SessionStatus.CANCELLED  # cancel is the final word

    assert approval_module._decision_locks == {}
    assert approval_module._decision_lock_refs == {}


# --- 4. _adopt_session_from_manager symbol fully removed --------------------


def test_adopt_session_from_manager_symbol_fully_removed():
    """Grep-equivalent pin: _adopt_session_from_manager must not exist as an
    attribute of the approval module, nor appear in its source at all."""
    import inspect

    assert not hasattr(approval_module, "_adopt_session_from_manager")

    source = inspect.getsource(approval_module)
    assert "_adopt_session_from_manager" not in source
