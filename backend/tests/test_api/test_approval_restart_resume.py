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

Hardening (adversarial review): adoption is gated on sm status ==
AWAITING_APPROVAL and validated BEFORE registration — a CANCELLED row whose
state dict still says awaiting_approval=True (cancel clears status, not
state; a silently-failed CANCELLED mirror could leave such a row surviving
the restart load filter) must NOT be adoptable, or an approve would resume a
proposal the user already vetoed.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

import app.api.routes.approval as approval_module
from services.session_manager import AnalysisSession, MarketType, SessionStatus


def _sm_session(
    session_id: str,
    *,
    market_type: MarketType = MarketType.KIWOOM,
    status: SessionStatus = SessionStatus.AWAITING_APPROVAL,
    awaiting_approval: bool = True,
) -> AnalysisSession:
    if market_type == MarketType.KIWOOM:
        kwargs = {"ticker": "005930", "display_name": "삼성전자",
                  "stk_cd": "005930", "stk_nm": "삼성전자"}
    elif market_type == MarketType.COIN:
        kwargs = {"ticker": "KRW-BTC", "display_name": "비트코인",
                  "market": "KRW-BTC", "korean_name": "비트코인"}
    else:
        kwargs = {"ticker": "AAPL", "display_name": "Apple Inc"}
    return AnalysisSession(
        session_id=session_id,
        market_type=market_type,
        status=status,
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
        **kwargs,
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

    def set_coin_graph(graph):
        monkeypatch.setattr(approval_module, "get_coin_trading_graph", lambda: graph)

    return {
        "coin_sessions": coin_sessions,
        "kr_stock_sessions": kr_stock_sessions,
        "reschedule_calls": reschedule_calls,
        "set_sm_session": set_sm_session,
        "set_graph": set_graph,
        "set_coin_graph": set_coin_graph,
    }


@pytest.mark.asyncio
async def test_approve_after_restart_falls_back_to_session_manager(wired):
    """Legacy dicts empty; sm has an AWAITING_APPROVAL kiwoom session -> no 404."""
    session_id = "restart-approve-1"
    wired["set_sm_session"](_sm_session(session_id))
    graph = _FakeGraph(
        [{"execution": {"execution_status": "completed", "awaiting_approval": False}}]
    )
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(session_id, "approved")

    assert result.session_id == session_id
    assert result.status == "completed"
    # Decision applied to the (adopted) session state.
    assert wired["kr_stock_sessions"][session_id]["state"]["approval_status"] == "approved"
    assert wired["kr_stock_sessions"][session_id]["state"]["awaiting_approval"] is False
    # Resume machinery was actually invoked (not a fork / no-op).
    graph.aupdate_state.assert_awaited_once()
    resume_config, resume_update = graph.aupdate_state.await_args.args
    assert resume_config == {"configurable": {"thread_id": session_id}}
    assert resume_update["approval_status"] == "approved"
    # Re-adopted into the legacy dict so subsequent lookups hit it directly.
    assert session_id in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_reject_after_restart_falls_back_to_session_manager(wired):
    """Same restart scenario, decision='rejected' -> no 404, rejection path runs."""
    session_id = "restart-reject-1"
    wired["set_sm_session"](_sm_session(session_id))
    graph = _FakeGraph(
        [{"re_analyze": {"approval_status": None}}, {"finalize": {"awaiting_approval": False}}]
    )
    wired["set_graph"](graph)

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
    assert wired["kr_stock_sessions"][session_id]["status"] == "running"
    assert session_id in wired["kr_stock_sessions"]


@pytest.mark.asyncio
async def test_coin_session_adopted_into_coin_dict_and_coin_graph_resumed(wired):
    """COIN market adoption happy path: registered into coin_sessions, coin resume invoked."""
    session_id = "restart-coin-1"
    wired["set_sm_session"](_sm_session(session_id, market_type=MarketType.COIN))
    coin_graph = _FakeGraph(
        [{"execution": {"execution_status": "completed", "awaiting_approval": False}}]
    )
    wired["set_coin_graph"](coin_graph)
    # If the kr graph were (wrongly) selected, this sentinel would blow up.
    wired["set_graph"](None)

    result = await approval_module.submit_decision(session_id, "approved")

    assert result.session_id == session_id
    assert result.status == "completed"
    # Registered into the COIN dict, not the KR one.
    assert session_id in wired["coin_sessions"]
    assert session_id not in wired["kr_stock_sessions"]
    assert wired["coin_sessions"][session_id]["market"] == "KRW-BTC"
    # The COIN graph's resume machinery ran.
    coin_graph.aupdate_state.assert_awaited_once()
    resume_config, resume_update = coin_graph.aupdate_state.await_args.args
    assert resume_config == {"configurable": {"thread_id": session_id}}
    assert resume_update["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_unknown_session_still_404s(wired):
    """Miss in both legacy dicts AND session_manager -> 404 preserved."""
    from fastapi import HTTPException

    wired["set_sm_session"](None)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision("does-not-exist", "approved")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_sm_session_not_awaiting_approval_400s(wired):
    """sm status row says awaiting but state says settled (mirror lag) -> 400, not 404.

    Also: the failed probe must NOT leave a zombie entry in the legacy dicts.
    """
    from fastapi import HTTPException

    session_id = "restart-settled-1"
    wired["set_sm_session"](
        _sm_session(session_id, status=SessionStatus.AWAITING_APPROVAL, awaiting_approval=False)
    )

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 400
    assert "not awaiting approval" in exc_info.value.detail
    assert session_id not in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_cancelled_sm_session_is_never_adopted(wired):
    """status=CANCELLED but state.awaiting_approval=True (failed mirror write) -> 404.

    The cancel path clears the sm STATUS but not state["awaiting_approval"];
    if the CANCELLED mirror write failed silently, the row could survive the
    restart load filter with a stale awaiting state. Adopting it would let an
    approve resume a proposal the user already vetoed — the status gate must
    refuse (404) and must not register anything.
    """
    from fastapi import HTTPException

    session_id = "restart-cancelled-1"
    wired["set_sm_session"](
        _sm_session(session_id, status=SessionStatus.CANCELLED, awaiting_approval=True)
    )

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 404
    assert session_id not in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_cancel_tolerates_stale_state_flag_on_legacy_session(wired, monkeypatch):
    """Legacy dict hit, state["awaiting_approval"]=False (stale), decision='cancelled'.

    Live defect (2026-07-13): reject -> re-analysis cycles and mirror races can
    leave state["awaiting_approval"] False while the session_manager row (and
    hence the ops board) still lists the session as AWAITING_APPROVAL. Cancel
    must succeed anyway — it executes nothing, so there is no unsafe resume to
    guard against. This is a pure termination mark: no graph resume.
    """
    session_id = "legacy-stale-cancel-1"
    wired["kr_stock_sessions"][session_id] = {
        "session_id": session_id,
        "status": "awaiting_approval",
        "state": {
            "awaiting_approval": False,
            "approval_status": None,
            "trade_proposal": {"id": "prop-1", "action": "BUY", "quantity": 1, "entry_price": 70000},
            "reasoning_log": [],
        },
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
    }
    graph = _FakeGraph([])
    wired["set_graph"](graph)

    mirrored_statuses = []

    async def capture_mirror_status(sid, st, error=None):
        mirrored_statuses.append((sid, st))

    monkeypatch.setattr(approval_module, "mirror_session_status", capture_mirror_status)

    result = await approval_module.submit_decision(session_id, "cancelled")

    assert result.session_id == session_id
    assert result.decision == "cancelled"
    assert result.status == "cancelled"
    assert result.execution_status == "cancelled"

    state = wired["kr_stock_sessions"][session_id]["state"]
    assert state["approval_status"] == "cancelled"
    assert state["awaiting_approval"] is False
    assert wired["kr_stock_sessions"][session_id]["status"] == "cancelled"

    assert mirrored_statuses == [(session_id, SessionStatus.CANCELLED)]

    # Graph resume machinery was NOT invoked — nothing to safely resume.
    graph.aupdate_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_still_400s_on_stale_state_flag_legacy_session(wired):
    """Same stale-flag session as above, decision='approved' -> still 400.

    Pins that the cancel tolerance is scoped ONLY to decision='cancelled' —
    approve/reject/modified keep the exact fail-closed 400 behavior.
    """
    from fastapi import HTTPException

    session_id = "legacy-stale-approve-1"
    wired["kr_stock_sessions"][session_id] = {
        "session_id": session_id,
        "status": "awaiting_approval",
        "state": {
            "awaiting_approval": False,
            "approval_status": None,
            "trade_proposal": {"id": "prop-1", "action": "BUY", "quantity": 1, "entry_price": 70000},
            "reasoning_log": [],
        },
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
    }

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 400
    assert "not awaiting approval" in exc_info.value.detail


@pytest.mark.asyncio
async def test_cancel_tolerates_stale_state_flag_on_sm_only_session(wired, monkeypatch):
    """sm row status=AWAITING_APPROVAL, state flag False, decision='cancelled' -> 200.

    Exercises the _adopt_session_from_manager path: the sm-status gate lets the
    row through as "found", but its own state-level awaiting check (mirror lag)
    normally returns the session UNREGISTERED so approve/reject 400 without
    leaving a zombie legacy-dict entry. Cancel must still succeed here too, and
    must NOT register the session into the legacy dict as an awaiting session.
    """
    session_id = "sm-stale-cancel-1"
    wired["set_sm_session"](
        _sm_session(session_id, status=SessionStatus.AWAITING_APPROVAL, awaiting_approval=False)
    )

    mirrored_statuses = []

    async def capture_mirror_status(sid, st, error=None):
        mirrored_statuses.append((sid, st))

    monkeypatch.setattr(approval_module, "mirror_session_status", capture_mirror_status)

    result = await approval_module.submit_decision(session_id, "cancelled")

    assert result.session_id == session_id
    assert result.decision == "cancelled"
    assert result.status == "cancelled"
    assert result.execution_status == "cancelled"

    assert mirrored_statuses == [(session_id, SessionStatus.CANCELLED)]

    # Not (re-)registered into the legacy dict as an awaiting session.
    assert session_id not in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_unknown_session_cancel_still_404s(wired):
    """Miss in both legacy dicts AND session_manager, decision='cancelled' -> 404 unchanged.

    The cancel tolerance only kicks in once a session is FOUND (by either
    truth) but its state flag is stale — it must never mask a genuine 404.
    """
    from fastapi import HTTPException

    wired["set_sm_session"](None)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision("does-not-exist-cancel", "cancelled")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_market_type_fails_closed_404(wired):
    """market_type=STOCK (US stack removed) -> 404, never adopted."""
    from fastapi import HTTPException

    session_id = "restart-stock-1"
    wired["set_sm_session"](
        _sm_session(session_id, market_type=MarketType.STOCK)
    )

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 404
    assert session_id not in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_concurrent_cancel_during_slow_reject_is_serialized(wired, monkeypatch):
    """A cancel fired mid-flight during a slow reject must NOT interleave.

    RACE (pre-fix): state["awaiting_approval"] clears at submit_decision START
    but the SM status mirror only flips at the END. During a long
    reject-triggered re-analysis the session still lists as awaiting on the
    operations board, so a second decision (e.g. 취소 from a reloaded tab)
    used to run concurrently: it took the zombie-cancel branch, returned 200
    "cancelled" and mirrored CANCELLED — then the ORIGINAL in-flight reject
    finished and unconditionally mirrored "running", silently overwriting the
    user's cancel (mirror order: cancelled -> running).

    Serialized semantics (post-fix, asserted here): the cancel WAITS on the
    per-session lock until the reject completes. The reject's resume leaves
    awaiting_approval=False with no new proposal -> it mirrors "running";
    the cancel then observes the settled state, takes the zombie-cancel
    branch, and mirrors CANCELLED LAST (mirror order: running -> cancelled).
    The user's cancel is the final word.
    """
    session_id = "concurrent-reject-cancel-1"
    wired["set_sm_session"](_sm_session(session_id))

    resume_started = asyncio.Event()
    resume_gate = asyncio.Event()

    class _SlowGraph:
        """Resume blocks on resume_gate so the reject holds the lock mid-flight."""

        def __init__(self):
            self.aupdate_state = AsyncMock()

        def astream(self, _input, _config):
            async def gen():
                resume_started.set()
                await resume_gate.wait()
                yield {"finalize": {"awaiting_approval": False}}

            return gen()

    graph = _SlowGraph()
    wired["set_graph"](graph)

    mirrored_statuses = []

    async def capture_mirror_status(sid, st, error=None):
        mirrored_statuses.append(st)

    monkeypatch.setattr(approval_module, "mirror_session_status", capture_mirror_status)

    reject_task = asyncio.create_task(
        approval_module.submit_decision(session_id, "rejected", feedback="retry")
    )
    # Deterministic: wait until the reject is INSIDE its resume (holding the
    # per-session lock, blocked on the gate).
    await asyncio.wait_for(resume_started.wait(), timeout=5)

    cancel_task = asyncio.create_task(
        approval_module.submit_decision(session_id, "cancelled")
    )
    # Give the cancel ample scheduler turns: with the lock it must be BLOCKED
    # (pre-fix it completed right here, mid-reject, and returned 200).
    for _ in range(10):
        await asyncio.sleep(0)
    assert not cancel_task.done(), (
        "cancel ran concurrently with the in-flight reject (per-session lock missing)"
    )
    assert mirrored_statuses == []  # nothing mirrored while the reject is in flight

    resume_gate.set()
    reject_result = await reject_task
    cancel_result = await cancel_task

    # Serialized outcome: reject settled first ("running" — re-analysis ran to
    # end, no new proposal), THEN the cancel landed as the final word.
    assert reject_result.decision == "rejected"
    assert reject_result.status == "running"
    assert cancel_result.decision == "cancelled"
    assert cancel_result.status == "cancelled"
    assert cancel_result.execution_status == "cancelled"

    # THE defect assertion: the final SM mirror is the cancel — never a
    # "running" overwrite landing after a "cancelled".
    # (SessionStatus is a str-Enum, so members compare equal to raw strings.)
    assert mirrored_statuses == ["running", SessionStatus.CANCELLED]

    # Session ends terminally cancelled; only the reject resumed the graph.
    assert wired["kr_stock_sessions"][session_id]["status"] == "cancelled"
    assert wired["kr_stock_sessions"][session_id]["state"]["approval_status"] == "cancelled"
    graph.aupdate_state.assert_awaited_once()

    # Lock bookkeeping fully pruned (bounded by in-flight sessions).
    assert approval_module._decision_locks == {}
    assert approval_module._decision_lock_refs == {}


@pytest.mark.asyncio
async def test_cancel_of_approved_session_is_rejected_409(wired, monkeypatch):
    """awaiting_approval=False + approval_status='approved' + cancel -> 409.

    DEFECT this guards (P0-4): if approve resumed the graph and the execution
    node placed a broker order, but the process died (or a concurrent cancel
    raced in) before the final status mirror at the end of the resume ran,
    the session is left with awaiting_approval=False and
    approval_status='approved' — the exact shape the zombie-cancel branch
    otherwise treats as "safe to terminate". A broker position may actually
    exist here, so cancel must be refused (409), not silently marked
    cancelled. No state mutation, no status mirror.
    """
    from fastapi import HTTPException

    session_id = "approved-zombie-cancel-1"
    wired["kr_stock_sessions"][session_id] = {
        "session_id": session_id,
        "status": "completed",
        "state": {
            "awaiting_approval": False,
            "approval_status": "approved",
            "trade_proposal": {"id": "prop-1", "action": "BUY", "quantity": 1, "entry_price": 70000},
            "reasoning_log": [],
        },
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
    }
    graph = _FakeGraph([])
    wired["set_graph"](graph)

    mirrored_statuses = []

    async def capture_mirror_status(sid, st, error=None):
        mirrored_statuses.append(st)

    monkeypatch.setattr(approval_module, "mirror_session_status", capture_mirror_status)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "cancelled")

    assert exc_info.value.status_code == 409
    assert "체결 확인" in exc_info.value.detail

    state = wired["kr_stock_sessions"][session_id]["state"]
    assert state["approval_status"] == "approved"  # not overwritten to cancelled
    assert wired["kr_stock_sessions"][session_id]["status"] == "completed"  # unchanged
    assert mirrored_statuses == []  # no status mirror performed
    graph.aupdate_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_of_non_approved_settled_session_still_200s(wired, monkeypatch):
    """awaiting_approval=False + approval_status='rejected' (NOT 'approved') + cancel -> 200.

    Pins that the 409 masquerade guard is scoped ONLY to approval_status ==
    'approved' — every other settled/stale shape keeps the pre-existing
    zombie-cancel tolerance from 9c57fca unchanged.
    """
    session_id = "non-approved-zombie-cancel-1"
    wired["kr_stock_sessions"][session_id] = {
        "session_id": session_id,
        "status": "running",
        "state": {
            "awaiting_approval": False,
            "approval_status": "rejected",
            "trade_proposal": {"id": "prop-1", "action": "BUY", "quantity": 1, "entry_price": 70000},
            "reasoning_log": [],
        },
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
    }
    graph = _FakeGraph([])
    wired["set_graph"](graph)

    mirrored_statuses = []

    async def capture_mirror_status(sid, st, error=None):
        mirrored_statuses.append(st)

    monkeypatch.setattr(approval_module, "mirror_session_status", capture_mirror_status)

    result = await approval_module.submit_decision(session_id, "cancelled")

    assert result.status == "cancelled"
    assert result.execution_status == "cancelled"
    state = wired["kr_stock_sessions"][session_id]["state"]
    assert state["approval_status"] == "cancelled"
    assert mirrored_statuses == [SessionStatus.CANCELLED]
    graph.aupdate_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_preserves_cancel_marked_during_resume(wired, monkeypatch):
    """approval_status flipped to "cancelled" DURING the resume -> preserved.

    Belt-and-braces on top of the lock: the lock serializes decisions within
    this process, but the state dict is shared by reference (sm row, position
    manager, another worker) — if approval_status mutates to "cancelled"
    underneath the resume, the completion branch must NOT overwrite it with
    running/completed. Here the mutation is delivered in-band via a resume
    event (state.update(node_output)), same effect as a direct mutation.
    """
    session_id = "resume-mutated-cancel-1"
    wired["set_sm_session"](_sm_session(session_id))
    graph = _FakeGraph(
        [{"re_analyze": {"approval_status": "cancelled", "awaiting_approval": False}}]
    )
    wired["set_graph"](graph)

    mirrored_statuses = []

    async def capture_mirror_status(sid, st, error=None):
        mirrored_statuses.append(st)

    monkeypatch.setattr(approval_module, "mirror_session_status", capture_mirror_status)

    result = await approval_module.submit_decision(session_id, "rejected", feedback="x")

    # Pre-fix: new_proposal_awaiting=False -> else-branch unconditionally set
    # "running" and mirrored it, orphaning the concurrent cancel.
    assert result.status == "cancelled"
    assert result.execution_status == "cancelled"
    assert wired["kr_stock_sessions"][session_id]["status"] == "cancelled"
    assert mirrored_statuses == ["cancelled"]
    # And the cancel-preserving path must never rearm the autonomy injector.
    assert wired["reschedule_calls"] == []
