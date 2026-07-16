"""Approval decisions must resolve entirely off the SessionManager (SM).

P2-5 (session-SSOT): submit_decision now looks up sessions in the
SessionManager ONLY -- there is no legacy in-memory dict ("B") lookup and no
_adopt_session_from_manager restart fallback (that function was deleted by
this task). This file used to pin the restart-recovery FALLBACK behavior
(legacy dict miss -> adopt from sm -> re-register into the legacy dict); it
now pins the SM-direct behavior that fallback was migrated into: every
/decide call -- restart-recovered or not -- resolves the session, its state,
its market_type and its final status entirely off the AnalysisSession object
sm.get_session() returns (a live reference, not a to_legacy_dict()
snapshot). The legacy dicts (get_coin_sessions()/get_kr_stock_sessions())
play no role in /decide at all anymore; they stay empty throughout every
test in this file and are asserted to remain so.

Hardening carried over from the original adoption-era tests: a CANCELLED (or
otherwise settled) sm_session.status must never be resumed just because
state["awaiting_approval"] is stale-True (mirror lag, or some other route
mutating status without clearing state) -- a decision "found" that way must
404, exactly as the pre-P2-5 adoption gate refused to adopt it.
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
    auto_approve_at: str | None = None,
    approval_status: str | None = None,
) -> AnalysisSession:
    if market_type == MarketType.KIWOOM:
        kwargs = {"ticker": "005930", "display_name": "삼성전자",
                  "stk_cd": "005930", "stk_nm": "삼성전자"}
    elif market_type == MarketType.COIN:
        kwargs = {"ticker": "KRW-BTC", "display_name": "비트코인",
                  "market": "KRW-BTC", "korean_name": "비트코인"}
    else:
        kwargs = {"ticker": "AAPL", "display_name": "Apple Inc"}
    state = {
        "awaiting_approval": awaiting_approval,
        "approval_status": approval_status,
        "trade_proposal": {
            "id": "prop-restart-1",
            "action": "BUY",
            "quantity": 1,
            "entry_price": 70000,
        },
        "reasoning_log": [],
    }
    if auto_approve_at is not None:
        state["auto_approve_at"] = auto_approve_at
    return AnalysisSession(
        session_id=session_id,
        market_type=market_type,
        status=status,
        state=state,
        **kwargs,
    )


class _FakeSessionManager:
    """Stand-in for SessionManager: tracks ONE AnalysisSession by id.

    Implements the subset of the real SessionManager API submit_decision now
    calls directly: get_session (session acquisition) and update_state (the
    resume loop's sole per-node write, P2-5). Both mutate the SAME live
    AnalysisSession object get_session() returns, matching the real
    SessionManager's own in-place-mutation contract.
    """

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
    """Empty legacy dicts (asserted to stay empty) + no-op notification side
    channels + a live-mutating fake SessionManager.

    Mirrors the mocking approach in tests/test_api/test_approval_reschedule.py.
    """
    coin_sessions: dict = {}
    kr_stock_sessions: dict = {}
    monkeypatch.setattr(approval_module, "get_coin_sessions", lambda: coin_sessions)
    monkeypatch.setattr(approval_module, "get_kr_stock_sessions", lambda: kr_stock_sessions)

    async def noop(*a, **k):
        return None

    for name in (
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

    holder: dict = {"manager": _FakeSessionManager(None)}

    async def fake_get_session_manager():
        return holder["manager"]

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    def set_sm_session(sm_session):
        holder["manager"] = _FakeSessionManager(sm_session)

    # P1-5's write-through commit_session_state/commit_session_status are
    # the SOLE writers of session state/status now (P2-5 removed the old
    # local "B" re-application block) -- these fakes simulate the real
    # write-through by mutating the SAME AnalysisSession object the fake
    # SessionManager tracks, exactly like the real SessionManager.update_
    # state/update_status would (services/session_manager.py's own
    # module-global get_session_manager() is untouched by this fixture's
    # approval_module patch, so faking these names directly -- rather than
    # trying to route them through the fake manager -- is this file's
    # isolation principle; see test_awaiting_writethrough.py for the same
    # rationale).
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
        "holder": holder,
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
    # Decision applied directly to the SM row's own state (no B involved).
    sm_session = wired["holder"]["manager"]._session
    assert sm_session.state["approval_status"] == "approved"
    assert sm_session.state["awaiting_approval"] is False
    assert sm_session.status == SessionStatus.COMPLETED
    # Resume machinery was actually invoked (not a fork / no-op).
    graph.aupdate_state.assert_awaited_once()
    resume_config, resume_update = graph.aupdate_state.await_args.args
    assert resume_config == {"configurable": {"thread_id": session_id}}
    assert resume_update["approval_status"] == "approved"
    # B genuinely never participates -- stays empty throughout.
    assert session_id not in wired["kr_stock_sessions"]
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
    sm_session = wired["holder"]["manager"]._session
    assert sm_session.status == SessionStatus.RUNNING
    assert session_id not in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_coin_session_resolves_coin_graph(wired):
    """COIN market happy path: SM row alone selects the coin graph, and B is
    never touched (no "adoption" into a legacy dict happens anymore)."""
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
    # Never registered into either legacy dict.
    assert session_id not in wired["coin_sessions"]
    assert session_id not in wired["kr_stock_sessions"]
    # The COIN graph's resume machinery ran.
    coin_graph.aupdate_state.assert_awaited_once()
    resume_config, resume_update = coin_graph.aupdate_state.await_args.args
    assert resume_config == {"configurable": {"thread_id": session_id}}
    assert resume_update["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_unknown_session_still_404s(wired):
    """Miss in the session_manager -> 404 preserved."""
    from fastapi import HTTPException

    wired["set_sm_session"](None)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision("does-not-exist", "approved")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_sm_session_not_awaiting_approval_400s(wired):
    """sm status row says awaiting but state says settled (mirror lag) -> 400, not 404."""
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
async def test_cancelled_sm_session_with_stale_awaiting_flag_404s(wired):
    """status=CANCELLED but state.awaiting_approval=True (failed mirror write, or
    some other route flipping status without clearing state) -> 404.

    Pre-P2-5 this was _adopt_session_from_manager's own refusal-to-adopt
    gate; P2-5 deleted that function but the general (actor-agnostic) guard
    it provided is still needed -- resuming a graph off a stale True flag
    here would let an approve run against a proposal the SM already
    considers settled/dead. Must not register anything into a legacy dict
    either (there is nothing left to register into).
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
async def test_cancel_of_cancelled_sm_session_with_stale_awaiting_flag_also_404s(wired):
    """Same pathological shape as above, but decision='cancelled' -- the
    general guard runs BEFORE the `not state.get("awaiting_approval")`
    branch (which is unreachable here since the flag is stale-True), so even
    a cancel of an already-cancelled-per-SM session in this exact shape
    fails closed instead of silently no-op'ing as a "harmless" cancel.
    """
    from fastapi import HTTPException

    session_id = "restart-cancelled-cancel-1"
    wired["set_sm_session"](
        _sm_session(session_id, status=SessionStatus.CANCELLED, awaiting_approval=True)
    )

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "cancelled")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_market_type_fails_closed_400(wired):
    """market_type=STOCK (US stack removed) -> 400 at graph selection, never resumed."""
    from fastapi import HTTPException

    session_id = "restart-stock-1"
    wired["set_sm_session"](
        _sm_session(session_id, market_type=MarketType.STOCK)
    )

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 400
    assert "unknown session market" in exc_info.value.detail
    assert session_id not in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_concurrent_cancel_during_slow_reject_is_serialized(wired, monkeypatch):
    """A cancel fired mid-flight during a slow reject must NOT interleave.

    RACE (pre-fix, historical): state["awaiting_approval"] clears at
    submit_decision START but the SM status commit only flips at the END.
    During a long reject-triggered re-analysis the session still lists as
    awaiting on the operations board, so a second decision (e.g. 취소 from a
    reloaded tab) used to run concurrently: it took the zombie-cancel
    branch, returned 200 "cancelled" and mirrored CANCELLED — then the
    ORIGINAL in-flight reject finished and unconditionally mirrored
    "running", silently overwriting the user's cancel (mirror order:
    cancelled -> running).

    Serialized semantics (post-fix, asserted here): the cancel WAITS on the
    per-session lock until the reject completes. The reject's resume leaves
    awaiting_approval=False with no new proposal -> it commits "running";
    the cancel then observes the settled state, takes the zombie-cancel
    branch, and mirrors CANCELLED LAST (status order: running -> cancelled).
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

    status_history = []
    sm_session = wired["holder"]["manager"]._session

    # Wrap the wired fixture's own fakes (which already write through to the
    # tracked AnalysisSession) to additionally record transition ORDER --
    # the whole point of this test.
    orig_commit_status = approval_module.commit_session_status

    async def tracking_commit_status(sid, new_status, **kw):
        status_history.append(new_status)
        await orig_commit_status(sid, new_status, **kw)

    monkeypatch.setattr(approval_module, "commit_session_status", tracking_commit_status)

    orig_mirror_status = approval_module.mirror_session_status

    async def tracking_mirror_status(sid, new_status, error=None):
        status_history.append(new_status)
        await orig_mirror_status(sid, new_status, error=error)

    monkeypatch.setattr(approval_module, "mirror_session_status", tracking_mirror_status)

    reject_task = asyncio.create_task(
        approval_module.submit_decision(session_id, "rejected", feedback="retry")
    )
    # Deterministic: wait until the reject is INSIDE its resume (holding
    # the per-session lock, blocked on the gate).
    await asyncio.wait_for(resume_started.wait(), timeout=5)

    cancel_task = asyncio.create_task(
        approval_module.submit_decision(session_id, "cancelled")
    )
    # Give the cancel ample scheduler turns: with the lock it must be
    # BLOCKED (pre-fix it completed right here, mid-reject, and
    # returned 200).
    for _ in range(10):
        await asyncio.sleep(0)
    assert not cancel_task.done(), (
        "cancel ran concurrently with the in-flight reject (per-session lock missing)"
    )
    assert status_history == []  # nothing committed while the reject is in flight

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

    # THE defect assertion: the final SM status is the cancel — never a
    # "running" overwrite landing after a "cancelled".
    assert status_history == [SessionStatus.RUNNING, SessionStatus.CANCELLED]

    # Session ends terminally cancelled; only the reject resumed the graph.
    assert sm_session.status == SessionStatus.CANCELLED
    assert sm_session.state["approval_status"] == "cancelled"
    graph.aupdate_state.assert_awaited_once()

    # Lock bookkeeping fully pruned (bounded by in-flight sessions).
    assert approval_module._decision_locks == {}
    assert approval_module._decision_lock_refs == {}


@pytest.mark.asyncio
async def test_cancel_of_approved_session_is_rejected_409(wired):
    """awaiting_approval=False + approval_status='approved' + cancel -> 409.

    DEFECT this guards (P0-4): if approve resumed the graph and the
    execution node placed a broker order, but the process died (or a
    concurrent cancel raced in) before the final status commit at the end of
    the resume ran, the session is left with awaiting_approval=False and
    approval_status='approved' — the exact shape the zombie-cancel branch
    otherwise treats as "safe to terminate". A broker position may actually
    exist here, so cancel must be refused (409), not silently marked
    cancelled. No state mutation, no status mirror.
    """
    from fastapi import HTTPException

    session_id = "approved-zombie-cancel-1"
    wired["set_sm_session"](
        _sm_session(
            session_id,
            status=SessionStatus.COMPLETED,
            awaiting_approval=False,
            approval_status="approved",
        )
    )
    graph = _FakeGraph([])
    wired["set_graph"](graph)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "cancelled")

    assert exc_info.value.status_code == 409
    assert "체결 확인" in exc_info.value.detail

    sm_session = wired["holder"]["manager"]._session
    assert sm_session.state["approval_status"] == "approved"  # not overwritten
    assert sm_session.status == SessionStatus.COMPLETED  # unchanged
    graph.aupdate_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_of_non_approved_settled_session_still_200s(wired):
    """awaiting_approval=False + approval_status='rejected' (NOT 'approved') +
    status=RUNNING (not yet terminal) + cancel -> 200.

    Pins that the 409 masquerade guard is scoped ONLY to approval_status ==
    'approved' — every other settled/stale shape keeps the pre-existing
    zombie-cancel tolerance unchanged.
    """
    session_id = "non-approved-zombie-cancel-1"
    wired["set_sm_session"](
        _sm_session(
            session_id,
            status=SessionStatus.RUNNING,
            awaiting_approval=False,
            approval_status="rejected",
        )
    )
    graph = _FakeGraph([])
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(session_id, "cancelled")

    assert result.status == "cancelled"
    assert result.execution_status == "cancelled"
    sm_session = wired["holder"]["manager"]._session
    assert sm_session.state["approval_status"] == "cancelled"
    assert sm_session.status == SessionStatus.CANCELLED
    graph.aupdate_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_preserves_cancel_marked_during_resume(wired):
    """approval_status flipped to "cancelled" DURING the resume -> preserved.

    Belt-and-braces on top of the lock: the lock serializes decisions within
    this process, but the state dict is shared by reference (sm row,
    position manager, another worker) — if approval_status mutates to
    "cancelled" underneath the resume, the completion branch must NOT
    overwrite it with running/completed. Here the mutation is delivered
    in-band via a resume event (sm.update_state(node_output)), same effect
    as a direct mutation.
    """
    session_id = "resume-mutated-cancel-1"
    wired["set_sm_session"](_sm_session(session_id))
    graph = _FakeGraph(
        [{"re_analyze": {"approval_status": "cancelled", "awaiting_approval": False}}]
    )
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(session_id, "rejected", feedback="x")

    # Pre-fix: new_proposal_awaiting=False -> else-branch unconditionally set
    # "running" and mirrored it, orphaning the concurrent cancel.
    assert result.status == "cancelled"
    assert result.execution_status == "cancelled"
    sm_session = wired["holder"]["manager"]._session
    assert sm_session.status == SessionStatus.CANCELLED
    # And the cancel-preserving path must never rearm the autonomy injector.
    assert wired["reschedule_calls"] == []


@pytest.mark.asyncio
async def test_cancel_of_completed_session_is_rejected_409(wired):
    """(I4) awaiting_approval=False + status=COMPLETED (via 'modified') + cancel -> 409.

    DEFECT this guards: the F4a T4 guard only checked approval_status ==
    'approved', but a session can reach status=COMPLETED via decision=
    'modified' too. A late cancel targeting that session must not fall into
    the zombie-cancel tolerance branch (only approval_status is inspected
    there) and flip a real, already-executed outcome back to CANCELLED.
    """
    from fastapi import HTTPException

    session_id = "completed-zombie-cancel-1"
    wired["set_sm_session"](
        _sm_session(
            session_id,
            status=SessionStatus.COMPLETED,
            awaiting_approval=False,
            approval_status="modified",
        )
    )
    graph = _FakeGraph([])
    wired["set_graph"](graph)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "cancelled")

    assert exc_info.value.status_code == 409
    assert "이미 처리됨" in exc_info.value.detail

    sm_session = wired["holder"]["manager"]._session
    assert sm_session.state["approval_status"] == "modified"  # not overwritten
    assert sm_session.status == SessionStatus.COMPLETED  # unchanged
    graph.aupdate_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_of_error_session_is_rejected_409(wired):
    """(I4) awaiting_approval=False + status=ERROR + cancel -> 409, stays error.

    DEFECT this guards: a re-analysis (reject -> resume) that blew up leaves
    status=ERROR with approval_status still whatever the prior decision was
    (e.g. 'rejected', never 'approved'). A late cancel used to sail through
    the zombie-cancel branch and overwrite ERROR with CANCELLED, erasing the
    failure record.
    """
    from fastapi import HTTPException

    session_id = "error-zombie-cancel-1"
    wired["set_sm_session"](
        _sm_session(
            session_id,
            status=SessionStatus.ERROR,
            awaiting_approval=False,
            approval_status="rejected",
        )
    )
    graph = _FakeGraph([])
    wired["set_graph"](graph)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "cancelled")

    assert exc_info.value.status_code == 409
    assert "이미 처리됨" in exc_info.value.detail

    sm_session = wired["holder"]["manager"]._session
    assert sm_session.state["approval_status"] == "rejected"  # not overwritten
    assert sm_session.status == SessionStatus.ERROR  # unchanged, not cancelled
    graph.aupdate_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_while_genuinely_awaiting_still_200s(wired):
    """Regression pin: a normal cancel of a session truly awaiting approval
    (awaiting_approval=True, status=AWAITING_APPROVAL, not the stale-flag
    zombie shape) must still succeed and go through the full resume
    machinery unchanged by I3/I4 — those only touch the
    `not awaiting_approval` zombie-cancel branch.
    """
    session_id = "genuine-awaiting-cancel-1"
    wired["set_sm_session"](_sm_session(session_id))
    graph = _FakeGraph([{"finalize": {"awaiting_approval": False}}])
    wired["set_graph"](graph)

    result = await approval_module.submit_decision(session_id, "cancelled")

    assert result.session_id == session_id
    assert result.decision == "cancelled"
    assert result.status == "cancelled"
    assert result.execution_status == "cancelled"

    graph.aupdate_state.assert_awaited_once()
    resume_config, resume_update = graph.aupdate_state.await_args.args
    assert resume_config == {"configurable": {"thread_id": session_id}}
    assert resume_update["approval_status"] == "cancelled"
    sm_session = wired["holder"]["manager"]._session
    assert sm_session.status == SessionStatus.CANCELLED
