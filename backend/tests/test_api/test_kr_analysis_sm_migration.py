"""P7 Phase 1 -> P2-3: KR (kiwoom) analysis producer migration to the
SessionManager, then to SM-only direct writes.

The KR analysis routes historically wrote ONLY a legacy in-process session
dict (P7 Phase 1 made it write BOTH -- legacy dict first, then the
SessionManager, so pub/sub could fire). P2-3 (session-SSOT) removed the
legacy-dict write entirely: the producer now writes the SessionManager
ONLY. P2-5 (session-SSOT) went further and deleted approval.py's own
legacy-dict-adoption restart fallback (`_adopt_session_from_manager`)
entirely: `/decide` now reads and writes the SessionManager exclusively.
P3-1 deleted the legacy in-memory dict itself, so every test below seeds
the SessionManager directly (`_seed_sm_session` / `_seed_awaiting_approval`)
and asserts only against the SM row.

Headless: stubbed graph astream + a real SessionManager on a test SQLite db.
"""

import asyncio
import os

import pytest
from fastapi import BackgroundTasks, HTTPException

import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager, SessionStatus

from app.api.schemas.kr_stocks import KRStockAnalysisRequest
from app.api.routes.kr_stocks.analysis import (
    cancel_kr_stock_analysis,
    run_kr_stock_analysis_task,
    start_kr_stock_analysis,
)

TEST_DB_PATH = "data/test_kr_sm_migration.db"


class FakeGraph:
    """Stub trading graph: yields pre-baked astream events (or raises)."""

    def __init__(self, events, raise_after: int | None = None):
        self._events = events
        self._raise_after = raise_after

    async def astream(self, initial_state, config):
        for i, event in enumerate(self._events):
            if self._raise_after is not None and i >= self._raise_after:
                raise RuntimeError("graph exploded")
            yield event
        if self._raise_after is not None and self._raise_after >= len(self._events):
            raise RuntimeError("graph exploded")


class _FakeStockInfo:
    stk_nm = "삼성전자"


class _FakeKiwoomClient:
    async def get_stock_info(self, stk_cd):
        return _FakeStockInfo()


@pytest.fixture
async def sm(monkeypatch):
    """Fresh SessionManager on a test db, installed as the process singleton."""
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    monkeypatch.setattr(sm_module, "DB_PATH", TEST_DB_PATH)
    manager = SessionManager()
    await manager.initialize()
    monkeypatch.setattr(sm_module, "_session_manager", manager)
    yield manager
    manager._sessions.clear()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture
def fake_kiwoom(monkeypatch):
    async def _fake_client():
        return _FakeKiwoomClient()

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.get_shared_kiwoom_client_async", _fake_client
    )


async def _seed_sm_session(sm, session_id: str):
    """Register the sm-side session the migrated start route creates."""
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        stk_cd="005930",
        stk_nm="삼성전자",
        state={
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "query": None,
            "reasoning_log": [],
            "current_stage": "data_collection",
        },
    )


def _patch_graph(monkeypatch, graph: FakeGraph):
    monkeypatch.setattr(
        "agents.graph.kr_stock_graph.get_kr_stock_trading_graph", lambda: graph
    )


# -------------------------------------------
# Start route registers the session in the SessionManager
# -------------------------------------------


async def test_start_route_registers_sm_session(sm, fake_kiwoom):
    response = await start_kr_stock_analysis(
        KRStockAnalysisRequest(stk_cd="005930"), BackgroundTasks()
    )

    session = await sm.get_session(response.session_id)
    assert session is not None, "start route must register the session in the SessionManager"
    assert session.market_type == MarketType.KIWOOM
    assert session.stk_cd == "005930"
    assert session.stk_nm == "삼성전자"
    assert session.state.get("reasoning_log") == []


# -------------------------------------------
# Background task mirrors node updates + final status to the SessionManager
# -------------------------------------------


async def test_analysis_task_mirrors_node_updates_and_notifies(sm, monkeypatch):
    session_id = "kr-mirror-1"
    await _seed_sm_session(sm, session_id)
    queue = await sm.subscribe(session_id)

    # Nodes return the FULL accumulated reasoning_log (add_kr_stock_reasoning_log semantics)
    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {
                "reasoning_log": ["[t] 데이터 수집"],
                "current_stage": "parallel_analysis",
            }},
            {"technical_analysis": {
                "reasoning_log": ["[t] 데이터 수집", "[t] 기술 분석"],
                "current_stage": "decision",
            }},
            {"strategic_decision": {
                "reasoning_log": ["[t] 데이터 수집", "[t] 기술 분석", "[t] 결정"],
                "awaiting_approval": True,
                "trade_proposal": {"id": "p1", "stk_cd": "005930", "action": "BUY"},
            }},
        ]),
    )

    await run_kr_stock_analysis_task(session_id)

    # sm updated per node: full state + last_node + status
    session = await sm.get_session(session_id)
    assert session.state.get("reasoning_log") == ["[t] 데이터 수집", "[t] 기술 분석", "[t] 결정"]
    assert session.state["reasoning_log"][-1] == "[t] 결정"
    assert session.last_node == "strategic_decision"
    assert session.status == SessionStatus.AWAITING_APPROVAL

    # And the pub/sub actually fired: state_update notifications carry the deltas
    notifications = []
    while not queue.empty():
        notifications.append(queue.get_nowait())
    state_updates = [n for n in notifications if n.get("type") == "state_update"]
    assert len(state_updates) == 3, f"one notify per node expected, got {notifications}"
    assert state_updates[0].get("reasoning_delta") == ["[t] 데이터 수집"]
    assert state_updates[1].get("reasoning_delta") == ["[t] 기술 분석"]
    status_updates = [n for n in notifications if n.get("type") == "status"]
    assert any(n.get("status") == "awaiting_approval" for n in status_updates)


async def test_analysis_task_mirrors_completed_status(sm, monkeypatch):
    session_id = "kr-mirror-2"
    await _seed_sm_session(sm, session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {
                "reasoning_log": ["[t] 수집"],
                "current_stage": "done",
            }},
        ]),
    )

    await run_kr_stock_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.COMPLETED


async def test_analysis_task_mirrors_error_status(sm, monkeypatch):
    session_id = "kr-mirror-3"
    await _seed_sm_session(sm, session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph(
            [{"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}],
            raise_after=1,
        ),
    )

    await run_kr_stock_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.ERROR
    assert "graph exploded" in (session.error or "")


# -------------------------------------------
# Cancel route mirrors the cancelled status
# -------------------------------------------


async def test_cancel_route_mirrors_cancelled_status(sm):
    session_id = "kr-cancel-1"
    await _seed_sm_session(sm, session_id)
    queue = await sm.subscribe(session_id)

    await cancel_kr_stock_analysis(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED
    msg = await asyncio.wait_for(queue.get(), timeout=1)
    assert msg == {"type": "status", "status": "cancelled"}


# -------------------------------------------
# Zombie-resurrection guard: cancel must clear awaiting_approval on the sm
# row, and any sm write failure must be surfaced loudly instead of swallowed.
# -------------------------------------------


async def test_cancel_clears_awaiting_flag_on_sm(sm):
    """The zombie-resurrection guard this test pins applies to the SM's own
    state directly (a restart resurrects from SQLite)."""
    session_id = "kr-cancel-clear-1"
    await _seed_sm_session(sm, session_id)
    await sm.update_state(
        session_id,
        {"awaiting_approval": True, "trade_proposal": {"id": "p1", "action": "HOLD"}},
    )
    await sm.update_status(session_id, SessionStatus.AWAITING_APPROVAL)

    await cancel_kr_stock_analysis(session_id)

    # Without this, a restart resurrects the session as AWAITING_APPROVAL
    # with awaiting_approval still True (zombie).
    session = await sm.get_session(session_id)
    assert session.state.get("awaiting_approval") is False
    assert session.state.get("approval_status") == "cancelled"
    assert session.status == SessionStatus.CANCELLED


async def test_cancel_failure_is_surfaced_as_503_not_swallowed(sm, monkeypatch):
    """P2-3: with the SM as the sole store, a persistent write failure during
    cancel can no longer be treated as a best-effort 'mirror' -- there is no
    second store whose local success could paper over it. It now fails loud
    (503) after one retry instead of returning 200 with mirror_failed=True
    (the old dual-store semantics from test_cancel_mirror_failure_is_
    surfaced_not_swallowed). Without this, a silently-accepted cancel could
    leave the SM row stuck AWAITING_APPROVAL with awaiting_approval still
    True -- a restart-time zombie."""
    session_id = "kr-cancel-mirror-fail-1"
    await _seed_sm_session(sm, session_id)

    calls = {"n": 0}

    async def boom(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "update_status", boom)

    logged = {}

    def fake_error(event, **kwargs):
        logged["event"] = event
        logged["kwargs"] = kwargs

    from app.api.routes.kr_stocks import analysis as analysis_mod

    monkeypatch.setattr(analysis_mod.logger, "error", fake_error)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_kr_stock_analysis(session_id)

    assert exc_info.value.status_code == 503
    assert calls["n"] == 2  # one retry, then fail closed

    assert logged["event"] == "kr_stock_analysis_cancel_failed"
    assert logged["kwargs"]["session_id"] == session_id
    assert "sqlite down" in logged["kwargs"]["error"]

    # The sm row was never actually transitioned -- no zombie
    # AWAITING_APPROVAL-with-awaiting_approval=True shape was created.
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.RUNNING


async def test_cancel_mirror_success_reports_mirror_failed_false(sm):
    session_id = "kr-cancel-mirror-ok-1"
    await _seed_sm_session(sm, session_id)

    response = await cancel_kr_stock_analysis(session_id)

    assert response["mirror_failed"] is False


# -------------------------------------------
# (I3) Cancel route participates in the per-session decision lock
# -------------------------------------------


async def test_cancel_route_serializes_against_concurrent_decision_lock_holder(sm):
    """(I3) cancel must wait if another decision (e.g. an in-flight reject
    resume through /decide) currently holds the per-session decision lock for
    this session_id — otherwise the cancel races the resume directly against
    the sm, and whichever writes last silently wins even if it is the stale
    one.
    """
    import app.api.routes.approval as approval_module

    session_id = "kr-cancel-lock-1"
    await _seed_sm_session(sm, session_id)

    lock_acquired = asyncio.Event()
    release_lock = asyncio.Event()

    async def hold_lock():
        async with approval_module._session_decision_lock(session_id):
            lock_acquired.set()
            await release_lock.wait()

    holder = asyncio.create_task(hold_lock())
    await asyncio.wait_for(lock_acquired.wait(), timeout=5)

    cancel_task = asyncio.create_task(cancel_kr_stock_analysis(session_id))
    # Give the cancel ample scheduler turns: with the lock in place it must be
    # BLOCKED (pre-fix it ran immediately, concurrently with the lock holder).
    for _ in range(10):
        await asyncio.sleep(0)
    assert not cancel_task.done(), (
        "cancel ran while the decision lock was held elsewhere — routes not serialized"
    )

    release_lock.set()
    await holder
    result = await cancel_task

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED
    assert result["mirror_failed"] is False

    # Lock bookkeeping fully pruned afterwards.
    assert approval_module._decision_locks == {}
    assert approval_module._decision_lock_refs == {}


# -------------------------------------------
# (I4) Cancel route refuses an already-settled session with 409
# -------------------------------------------


async def test_cancel_route_refuses_completed_session_409(sm):
    session_id = "kr-cancel-done-1"
    await _seed_sm_session(sm, session_id)
    await sm.update_status(session_id, SessionStatus.COMPLETED)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_kr_stock_analysis(session_id)

    assert exc_info.value.status_code == 409
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.COMPLETED  # not flipped to cancelled


async def test_cancel_route_refuses_error_session_409(sm):
    session_id = "kr-cancel-err-1"
    await _seed_sm_session(sm, session_id)
    await sm.update_status(session_id, SessionStatus.ERROR)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_kr_stock_analysis(session_id)

    assert exc_info.value.status_code == 409
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.ERROR  # not flipped to cancelled


async def test_cancel_route_still_200s_for_awaiting_session(sm):
    """Normal case unchanged: an actively-running (not yet settled) session
    cancels cleanly with 200."""
    session_id = "kr-cancel-normal-1"
    await _seed_sm_session(sm, session_id)  # RUNNING by default

    response = await cancel_kr_stock_analysis(session_id)

    assert response["mirror_failed"] is False
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED


# -------------------------------------------
# Producer robustness: sm mirror failures must not affect the analysis
# -------------------------------------------


async def test_analysis_task_propagates_sm_write_failure_but_releases_slot(
    sm, monkeypatch
):
    """P2-3: with the SM as the SOLE write target (all mirror_* calls
    replaced by direct sm.update_state/update_status), a SessionManager
    write failure is a REAL failure now — it propagates instead of being
    silently swallowed the way the old best-effort mirror_session_state/
    mirror_session_status wrappers used to (superseding this test's old
    'a mirror failure must not abort a healthy run' premise, which no longer
    holds: there is no second store whose local success could paper over an
    SM outage). The analysis slot must still be released via `finally`, so a
    persistent SQLite outage doesn't also starve the concurrency semaphore
    for every other ticker."""
    session_id = "kr-guard-1"
    await _seed_sm_session(sm, session_id)

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "update_state", boom)
    monkeypatch.setattr(sm, "update_status", boom)

    released = {"n": 0}

    def counting_release():
        released["n"] += 1

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.release_analysis_slot", counting_release
    )

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "done"}},
        ]),
    )

    with pytest.raises(RuntimeError):
        await run_kr_stock_analysis_task(session_id)

    assert released["n"] == 1, "the analysis slot must still be released via finally"


async def test_start_route_failfast_on_sm_registration_failure(sm, fake_kiwoom, monkeypatch):
    """P1-5: sm reservation failure must fail the start route loud (503), not
    silently degrade to poll-only -- with SM-only reads a session the SM
    never registered is invisible to every read surface, so a 200 "started"
    response here would be lying to the caller.

    P2-3: the atomic reservation (`create_session_if_no_active`) IS the
    registration call now -- there is no separate legacy-dict placeholder
    left behind to mark "error" on failure; the reservation itself simply
    never lands, so nothing is created anywhere.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "create_session_if_no_active", boom)

    with pytest.raises(HTTPException) as exc_info:
        await start_kr_stock_analysis(
            KRStockAnalysisRequest(stk_cd="005930"), BackgroundTasks()
        )

    assert exc_info.value.status_code == 503
    assert await sm.get_all_sessions(market_type=MarketType.KIWOOM) == {}


async def test_cancel_mid_run_is_not_overwritten_by_final_status(sm, monkeypatch):
    """User cancel during a run must stick — the task's final status write must not flap it."""
    session_id = "kr-cancelflap-1"
    await _seed_sm_session(sm, session_id)

    class CancellingGraph:
        async def astream(self, initial_state, config):
            yield {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}
            # User cancels while the graph is still streaming
            await cancel_kr_stock_analysis(session_id)
            yield {"technical_analysis": {"reasoning_log": ["[t] 수집", "[t] 기술"], "current_stage": "y"}}

    _patch_graph(monkeypatch, CancellingGraph())

    await run_kr_stock_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED


async def test_state_error_branch_mirrors_error(sm, monkeypatch):
    """A graph that finishes cleanly WITH state['error'] set must mirror ERROR."""
    session_id = "kr-stateerr-1"
    await _seed_sm_session(sm, session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {
                "reasoning_log": ["[t] 수집 실패"],
                "error": "키움 API 실패",
            }},
        ]),
    )

    await run_kr_stock_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.ERROR
    assert "키움" in (session.error or "")


async def test_slot_timeout_mirrors_error(sm, monkeypatch):
    session_id = "kr-slot-1"
    await _seed_sm_session(sm, session_id)

    async def no_slot(timeout=60.0):
        return False

    monkeypatch.setattr("app.api.routes.kr_stocks.analysis.acquire_analysis_slot", no_slot)

    await run_kr_stock_analysis_task(session_id)

    assert (await sm.get_session(session_id)).status == SessionStatus.ERROR


async def test_cancel_during_slot_wait_keeps_cancelled(sm, monkeypatch):
    session_id = "kr-cancelslot-1"
    await _seed_sm_session(sm, session_id)

    async def cancel_then_timeout(timeout=60.0):
        await cancel_kr_stock_analysis(session_id)
        return False

    monkeypatch.setattr("app.api.routes.kr_stocks.analysis.acquire_analysis_slot", cancel_then_timeout)

    await run_kr_stock_analysis_task(session_id)

    assert (await sm.get_session(session_id)).status == SessionStatus.CANCELLED


async def test_cancel_then_graph_exception_keeps_cancelled(sm, monkeypatch):
    """Terminal cancelled must survive the exception path too (same invariant
    as the normal-completion flap guard)."""
    session_id = "kr-cancelerr-1"
    await _seed_sm_session(sm, session_id)

    class CancelThenExplodeGraph:
        async def astream(self, initial_state, config):
            yield {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}
            await cancel_kr_stock_analysis(session_id)
            raise RuntimeError("LLM call failed")

    _patch_graph(monkeypatch, CancelThenExplodeGraph())

    await run_kr_stock_analysis_task(session_id)

    assert (await sm.get_session(session_id)).status == SessionStatus.CANCELLED


# -------------------------------------------
# Approval decisions must be mirrored to the SessionManager
# -------------------------------------------


class FakeApprovalGraph:
    """Stub for the graph resume in approval.py (aupdate_state + astream(None))."""

    def __init__(self, events):
        self._events = events
        self.state_update = None

    async def aupdate_state(self, config, update):
        self.state_update = update

    async def astream(self, inp, config):
        for event in self._events:
            yield event


async def _seed_awaiting_approval(sm, session_id: str) -> dict:
    proposal = {
        "id": "p1",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "action": "HOLD",
        "quantity": 0,
        "entry_price": 70000,
    }
    await _seed_sm_session(sm, session_id)
    await sm.update_state(
        session_id, {"awaiting_approval": True, "trade_proposal": dict(proposal)}
    )
    await sm.update_status(session_id, SessionStatus.AWAITING_APPROVAL)
    return proposal


async def test_approval_approved_mirrors_completed_to_sm(sm, monkeypatch):
    """Without a durable write, decided sessions stay AWAITING_APPROVAL in sm
    forever (never TTL-cleaned) and replay a stale proposal from the WS
    sm-fallback after a backend restart. P2-5: /decide resolves and writes
    the SessionManager exclusively; the "did approved durably land"
    assertions are all against the SM.
    """
    from app.api.routes.approval import submit_approval
    from app.api.schemas.approval import ApprovalRequest

    session_id = "kr-approve-1"
    await _seed_awaiting_approval(sm, session_id)

    graph = FakeApprovalGraph([
        {"kr_stock_execution": {
            "execution_status": "skipped",
            "reasoning_log": ["[t] 실행 스킵"],
        }},
    ])
    monkeypatch.setattr("app.api.routes.approval.get_kr_stock_trading_graph", lambda: graph)

    await submit_approval(ApprovalRequest(session_id=session_id, decision="approved"))

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.COMPLETED
    assert session.state.get("awaiting_approval") is False
    # resume-loop node outputs land in the SM directly (sm.update_state,
    # P2-5), keeping sm state fresh for restart recovery.
    assert session.state.get("execution_status") == "skipped"


async def test_approval_records_actor(sm, monkeypatch):
    """R3: every decision records WHO decided — 'user' via the route, 'system'
    via the extracted submit_decision (the autonomy injector's entry point).

    P2-5: the audit trail (approval_actor) and the auto_approve_at void are
    both SM-only -- state IS sm_session.state (a live reference), so the
    countdown is seeded directly on the SM row.
    """
    from app.api.routes.approval import submit_decision

    session_id = "kr-actor-1"
    await _seed_awaiting_approval(sm, session_id)
    graph = FakeApprovalGraph([])
    monkeypatch.setattr("app.api.routes.approval.get_kr_stock_trading_graph", lambda: graph)

    # A pending autonomous countdown must be voided by any decision -- seeded
    # on the SM row directly (the only place /decide reads state from).
    await sm.update_state(session_id, {"auto_approve_at": "2026-07-12T10:00:00+00:00"})

    await submit_decision(session_id, "approved", actor="system")

    session = await sm.get_session(session_id)
    assert session.state.get("approval_actor") == "system"
    assert graph.state_update.get("approval_actor") == "system"  # audit trail in the checkpoint
    assert session.state.get("auto_approve_at") is None

    # The route path records 'user'
    session_id2 = "kr-actor-2"
    await _seed_awaiting_approval(sm, session_id2)
    from app.api.routes.approval import submit_approval
    from app.api.schemas.approval import ApprovalRequest

    await submit_approval(ApprovalRequest(session_id=session_id2, decision="approved"))
    session2 = await sm.get_session(session_id2)
    assert session2.state.get("approval_actor") == "user"


async def test_approval_rejected_mirrors_running_to_sm(sm, monkeypatch):
    """P2-5: the rejected -> RUNNING transition lands in the SM directly
    (commit_session_status)."""
    from app.api.routes.approval import submit_approval
    from app.api.schemas.approval import ApprovalRequest

    session_id = "kr-reject-1"
    await _seed_awaiting_approval(sm, session_id)

    graph = FakeApprovalGraph([])
    monkeypatch.setattr("app.api.routes.approval.get_kr_stock_trading_graph", lambda: graph)

    await submit_approval(
        ApprovalRequest(session_id=session_id, decision="rejected", feedback="재분석")
    )

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.RUNNING
    assert session.state.get("awaiting_approval") is False


# -------------------------------------------
# End-to-end: producer push reaches the session WebSocket without polling
# -------------------------------------------


async def test_ws_streams_kr_analysis_via_push_end_to_end(sm, monkeypatch):
    from tests.test_api.test_websocket_session import (
        FakeWebSocket,
        running_ws,
        wait_for_frame,
    )
    import app.api.routes.websocket as ws_module

    # Polls so slow that only pub/sub push can deliver frames in time.
    monkeypatch.setattr(ws_module, "SAFETY_POLL_SECONDS", 30.0)
    monkeypatch.setattr(ws_module, "COMPLETE_LINGER_SECONDS", 0.0)

    session_id = "kr-e2e-1"
    await _seed_sm_session(sm, session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {
                "reasoning_log": ["[t] 수집"],
                "current_stage": "analysis",
            }},
            {"technical_analysis": {
                "reasoning_log": ["[t] 수집", "[t] 기술"],
                "current_stage": "done",
            }},
        ]),
    )

    ws = FakeWebSocket()
    async with running_ws(ws, session_id) as task:
        await wait_for_frame(ws, lambda f: f.get("type") == "status", timeout=1.0)

        await run_kr_stock_analysis_task(session_id)

        await wait_for_frame(
            ws, lambda f: f.get("type") == "reasoning" and f.get("data") == "[t] 기술", timeout=1.0
        )
        complete = await wait_for_frame(ws, lambda f: f.get("type") == "complete", timeout=1.0)
        assert complete["data"]["status"] == "completed"
        await asyncio.wait_for(task, timeout=2.0)

    reasoning = [f["data"] for f in ws.sent if f.get("type") == "reasoning"]
    assert reasoning == ["[t] 수집", "[t] 기술"]
    # Inter-frame ordering: every reasoning frame precedes the complete frame.
    types = [f["type"] for f in ws.sent]
    assert max(i for i, t in enumerate(types) if t == "reasoning") < types.index("complete")


# -------------------------------------------
# P1-6: status endpoint serves a session's detail from the SessionManager
# after a restart (SQLite-persisted state_json), e.g. a session that was
# running/awaiting_approval at shutdown and reloaded by
# SessionManager._load_active_sessions.
# -------------------------------------------


async def test_status_endpoint_serves_from_sm_after_restart(sm):
    """A session that was running/awaiting_approval at shutdown is reloaded
    into the SessionManager (see SessionManager._load_active_sessions) and
    may since have completed via the resume/approval flow. The status
    endpoint must still serve its analyses/trade_proposal from the
    sm-persisted state instead of 404ing."""
    from app.api.routes.kr_stocks.analysis import get_kr_stock_analysis_status

    session_id = "kr-restart-detail-1"
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        stk_cd="005930",
        stk_nm="삼성전자",
        state={
            "reasoning_log": ["[t] 완료"],
            "current_stage": "done",
            "awaiting_approval": False,
            "technical_analysis": {
                "agent_type": "technical",
                "signal": "buy",
                "confidence": 0.8,
                "summary": "상승 추세",
                "key_factors": ["golden cross"],
            },
            "trade_proposal": {
                "id": "p1",
                "stk_cd": "005930",
                "stk_nm": "삼성전자",
                "action": "BUY",
                "quantity": 10,
                "created_at": "2026-07-13T10:00:00+00:00",
            },
        },
    )
    await sm.update_status(session_id, SessionStatus.COMPLETED)

    response = await get_kr_stock_analysis_status(session_id)

    assert response.status == "completed"
    assert response.stk_cd == "005930"
    assert response.stk_nm == "삼성전자"
    assert len(response.analyses) == 1
    assert response.analyses[0].signal == "buy"
    assert response.analyses[0].summary == "상승 추세"
    assert response.trade_proposal is not None
    assert response.trade_proposal.action == "BUY"
    assert response.trade_proposal.quantity == 10


async def test_status_endpoint_serves_completed_session_from_sm(sm):
    """The status route reads the SessionManager exclusively; a session with
    an empty state (no analyses/proposal yet) still serves correctly.
    Direct-seed variant of test_status_endpoint_serves_from_sm_after_restart
    above (seeds the sm directly instead of driving the full
    run_kr_stock_analysis_task pipeline)."""
    from app.api.routes.kr_stocks.analysis import get_kr_stock_analysis_status

    session_id = "kr-sm-only-empty-1"
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        stk_cd="005930",
        stk_nm="삼성전자",
        state={"reasoning_log": [], "current_stage": "data_collection"},
    )
    await sm.update_status(session_id, SessionStatus.COMPLETED)

    response = await get_kr_stock_analysis_status(session_id)

    assert response.status == "completed"
    assert response.analyses == []


async def test_status_endpoint_404s_when_sm_session_missing(sm):
    from fastapi import HTTPException

    from app.api.routes.kr_stocks.analysis import get_kr_stock_analysis_status

    with pytest.raises(HTTPException) as exc_info:
        await get_kr_stock_analysis_status("kr-nonexistent-session")

    assert exc_info.value.status_code == 404
