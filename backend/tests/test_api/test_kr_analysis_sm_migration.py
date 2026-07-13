"""P7 Phase 1: KR (kiwoom) analysis producer migration to the SessionManager.

The KR analysis routes historically wrote ONLY the legacy in-process
kr_stock_sessions dict, so the SessionManager pub/sub never fired and the
session WebSocket could only poll. After the migration the producer writes
BOTH — legacy dict first (still the read path), then the SessionManager —
so every graph node / status transition fires a subscriber notification.

Headless: stubbed graph astream + a real SessionManager on a test SQLite db.
"""

import asyncio
import os

import pytest
from fastapi import BackgroundTasks

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
def kr_sessions():
    from app.api.routes.kr_stocks.constants import kr_stock_sessions

    saved = dict(kr_stock_sessions)
    kr_stock_sessions.clear()
    yield kr_stock_sessions
    kr_stock_sessions.clear()
    kr_stock_sessions.update(saved)


@pytest.fixture
def fake_kiwoom(monkeypatch):
    async def _fake_client():
        return _FakeKiwoomClient()

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.get_shared_kiwoom_client_async", _fake_client
    )


def _seed_session(kr_sessions, session_id: str, sm_manager=None) -> dict:
    """Seed the legacy dict exactly like the start route does."""
    record = {
        "session_id": session_id,
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "status": "running",
        "state": {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "query": None,
            "reasoning_log": [],
            "current_stage": "data_collection",
        },
        "created_at": None,
        "error": None,
    }
    kr_sessions[session_id] = record
    return record


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


async def test_start_route_registers_sm_session(sm, kr_sessions, fake_kiwoom):
    response = await start_kr_stock_analysis(
        KRStockAnalysisRequest(stk_cd="005930"), BackgroundTasks()
    )

    session = await sm.get_session(response.session_id)
    assert session is not None, "start route must register the session in the SessionManager"
    assert session.market_type == MarketType.KIWOOM
    assert session.stk_cd == "005930"
    assert session.stk_nm == "삼성전자"
    assert session.state.get("reasoning_log") == []
    # Legacy record still created (read path unchanged)
    assert response.session_id in kr_sessions
    # sm state must be an independent copy, not the legacy dict's objects
    assert session.state is not kr_sessions[response.session_id]["state"]
    assert (
        session.state["reasoning_log"]
        is not kr_sessions[response.session_id]["state"]["reasoning_log"]
    )


# -------------------------------------------
# Background task mirrors node updates + final status to the SessionManager
# -------------------------------------------


async def test_analysis_task_mirrors_node_updates_and_notifies(sm, kr_sessions, monkeypatch):
    session_id = "kr-mirror-1"
    record = _seed_session(kr_sessions, session_id)
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

    # Legacy behavior unchanged
    assert record["status"] == "awaiting_approval"
    assert record["state"]["reasoning_log"][-1] == "[t] 결정"

    # sm mirrored per node: full state + last_node + status
    session = await sm.get_session(session_id)
    assert session.state.get("reasoning_log") == ["[t] 데이터 수집", "[t] 기술 분석", "[t] 결정"]
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


async def test_analysis_task_mirrors_completed_status(sm, kr_sessions, monkeypatch):
    session_id = "kr-mirror-2"
    record = _seed_session(kr_sessions, session_id)
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

    assert record["status"] == "completed"
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.COMPLETED


async def test_analysis_task_mirrors_error_status(sm, kr_sessions, monkeypatch):
    session_id = "kr-mirror-3"
    record = _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph(
            [{"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}],
            raise_after=1,
        ),
    )

    await run_kr_stock_analysis_task(session_id)

    assert record["status"] == "error"
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.ERROR
    assert "graph exploded" in (session.error or "")


# -------------------------------------------
# Cancel route mirrors the cancelled status
# -------------------------------------------


async def test_cancel_route_mirrors_cancelled_status(sm, kr_sessions):
    session_id = "kr-cancel-1"
    _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)
    queue = await sm.subscribe(session_id)

    await cancel_kr_stock_analysis(session_id)

    assert kr_sessions[session_id]["status"] == "cancelled"
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED
    msg = await asyncio.wait_for(queue.get(), timeout=1)
    assert msg == {"type": "status", "status": "cancelled"}


# -------------------------------------------
# Zombie-resurrection guard: cancel must clear awaiting_approval on BOTH the
# legacy dict AND the sm mirror (they are independent dicts — sm gets a copy
# at registration, see test_start_route_registers_sm_session above), and any
# sm-mirror failure must be surfaced loudly instead of swallowed.
# -------------------------------------------


async def test_cancel_clears_awaiting_flag_on_legacy_and_sm(sm, kr_sessions):
    session_id = "kr-cancel-clear-1"
    record = _seed_session(kr_sessions, session_id)
    record["status"] = "awaiting_approval"
    record["state"]["awaiting_approval"] = True
    record["state"]["trade_proposal"] = {"id": "p1", "action": "HOLD"}
    await _seed_sm_session(sm, session_id)
    await sm.update_state(session_id, {"awaiting_approval": True})
    await sm.update_status(session_id, SessionStatus.AWAITING_APPROVAL)

    await cancel_kr_stock_analysis(session_id)

    # Legacy dict cleared (pinned)
    assert record["state"]["awaiting_approval"] is False
    assert record["state"]["approval_status"] == "cancelled"

    # sm mirror cleared too — without this, a restart resurrects the session
    # as AWAITING_APPROVAL with awaiting_approval still True (zombie).
    session = await sm.get_session(session_id)
    assert session.state.get("awaiting_approval") is False
    assert session.state.get("approval_status") == "cancelled"
    assert session.status == SessionStatus.CANCELLED


async def test_cancel_mirror_failure_is_surfaced_not_swallowed(sm, kr_sessions, monkeypatch):
    """A failing sm mirror during cancel must not silently plant a zombie —
    the local cancel still succeeds, but the response says mirror_failed=True
    and the failure is logged at error (not warning) level."""
    session_id = "kr-cancel-mirror-fail-1"
    _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "update_status", boom)

    logged = {}

    def fake_error(event, **kwargs):
        logged["event"] = event
        logged["kwargs"] = kwargs

    from app.api.routes.kr_stocks import analysis as analysis_mod

    monkeypatch.setattr(analysis_mod.logger, "error", fake_error)

    response = await cancel_kr_stock_analysis(session_id)

    # Local cancel still succeeds despite the mirror failure
    assert kr_sessions[session_id]["status"] == "cancelled"
    assert kr_sessions[session_id]["state"]["awaiting_approval"] is False

    assert response["mirror_failed"] is True
    assert logged["event"] == "kr_stock_analysis_cancel_mirror_failed"
    assert logged["kwargs"]["session_id"] == session_id
    assert "sqlite down" in logged["kwargs"]["error"]


async def test_cancel_mirror_success_reports_mirror_failed_false(sm, kr_sessions):
    session_id = "kr-cancel-mirror-ok-1"
    _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    response = await cancel_kr_stock_analysis(session_id)

    assert response["mirror_failed"] is False


# -------------------------------------------
# Producer robustness: sm mirror failures must not affect the analysis
# -------------------------------------------


async def test_analysis_task_survives_sm_mirror_failure(sm, kr_sessions, monkeypatch):
    """A SessionManager hiccup (e.g. SQLite lock) must not abort a healthy run."""
    session_id = "kr-guard-1"
    record = _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "update_state", boom)
    monkeypatch.setattr(sm, "update_status", boom)

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "done"}},
        ]),
    )

    await run_kr_stock_analysis_task(session_id)

    assert record["status"] == "completed", "mirror failure must not fail the analysis"
    assert record["error"] is None


async def test_start_route_survives_sm_registration_failure(sm, kr_sessions, fake_kiwoom, monkeypatch):
    """sm registration failure must degrade to poll-only, not 500 the start route."""

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "create_session", boom)

    response = await start_kr_stock_analysis(
        KRStockAnalysisRequest(stk_cd="005930"), BackgroundTasks()
    )

    assert response.status == "started"
    assert response.session_id in kr_sessions


async def test_cancel_mid_run_is_not_overwritten_by_final_status(sm, kr_sessions, monkeypatch):
    """User cancel during a run must stick — the task's final status write must not flap it."""
    session_id = "kr-cancelflap-1"
    record = _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    class CancellingGraph:
        async def astream(self, initial_state, config):
            yield {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}
            # User cancels while the graph is still streaming
            await cancel_kr_stock_analysis(session_id)
            yield {"technical_analysis": {"reasoning_log": ["[t] 수집", "[t] 기술"], "current_stage": "y"}}

    _patch_graph(monkeypatch, CancellingGraph())

    await run_kr_stock_analysis_task(session_id)

    assert record["status"] == "cancelled"
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED


async def test_state_error_branch_mirrors_error(sm, kr_sessions, monkeypatch):
    """A graph that finishes cleanly WITH state['error'] set must mirror ERROR."""
    session_id = "kr-stateerr-1"
    record = _seed_session(kr_sessions, session_id)
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

    assert record["status"] == "error"
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.ERROR
    assert "키움" in (session.error or "")


async def test_slot_timeout_mirrors_error(sm, kr_sessions, monkeypatch):
    session_id = "kr-slot-1"
    record = _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    async def no_slot(timeout=60.0):
        return False

    monkeypatch.setattr("app.api.routes.kr_stocks.analysis.acquire_analysis_slot", no_slot)

    await run_kr_stock_analysis_task(session_id)

    assert record["status"] == "error"
    assert (await sm.get_session(session_id)).status == SessionStatus.ERROR


async def test_cancel_during_slot_wait_keeps_cancelled(sm, kr_sessions, monkeypatch):
    session_id = "kr-cancelslot-1"
    record = _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    async def cancel_then_timeout(timeout=60.0):
        await cancel_kr_stock_analysis(session_id)
        return False

    monkeypatch.setattr("app.api.routes.kr_stocks.analysis.acquire_analysis_slot", cancel_then_timeout)

    await run_kr_stock_analysis_task(session_id)

    assert record["status"] == "cancelled"
    assert (await sm.get_session(session_id)).status == SessionStatus.CANCELLED


async def test_cancel_then_graph_exception_keeps_cancelled(sm, kr_sessions, monkeypatch):
    """Terminal cancelled must survive the exception path too (same invariant
    as the normal-completion flap guard)."""
    session_id = "kr-cancelerr-1"
    record = _seed_session(kr_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    class CancelThenExplodeGraph:
        async def astream(self, initial_state, config):
            yield {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}
            await cancel_kr_stock_analysis(session_id)
            raise RuntimeError("LLM call failed")

    _patch_graph(monkeypatch, CancelThenExplodeGraph())

    await run_kr_stock_analysis_task(session_id)

    assert record["status"] == "cancelled"
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


async def _seed_awaiting_approval(sm, kr_sessions, session_id: str) -> dict:
    record = _seed_session(kr_sessions, session_id)
    proposal = {
        "id": "p1",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "action": "HOLD",
        "quantity": 0,
        "entry_price": 70000,
    }
    record["status"] = "awaiting_approval"
    record["state"]["awaiting_approval"] = True
    record["state"]["trade_proposal"] = proposal
    await _seed_sm_session(sm, session_id)
    await sm.update_state(
        session_id, {"awaiting_approval": True, "trade_proposal": dict(proposal)}
    )
    await sm.update_status(session_id, SessionStatus.AWAITING_APPROVAL)
    return record


async def test_approval_approved_mirrors_completed_to_sm(sm, kr_sessions, monkeypatch):
    """Without the mirror, decided sessions stay AWAITING_APPROVAL in sm forever
    (never TTL-cleaned) and replay a stale proposal from the WS sm-fallback after
    a backend restart."""
    from app.api.routes.approval import submit_approval
    from app.api.schemas.approval import ApprovalRequest

    session_id = "kr-approve-1"
    record = await _seed_awaiting_approval(sm, kr_sessions, session_id)

    graph = FakeApprovalGraph([
        {"kr_stock_execution": {
            "execution_status": "skipped",
            "reasoning_log": ["[t] 실행 스킵"],
        }},
    ])
    monkeypatch.setattr("app.api.routes.approval.get_kr_stock_trading_graph", lambda: graph)

    await submit_approval(ApprovalRequest(session_id=session_id, decision="approved"))

    assert record["status"] == "completed"  # legacy behavior unchanged
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.COMPLETED
    assert session.state.get("awaiting_approval") is False
    # resume-loop node outputs mirrored too (keeps sm state fresh for restart recovery)
    assert session.state.get("execution_status") == "skipped"


async def test_approval_records_actor(sm, kr_sessions, monkeypatch):
    """R3: every decision records WHO decided — 'user' via the route, 'system'
    via the extracted submit_decision (the autonomy injector's entry point)."""
    from app.api.routes.approval import submit_decision

    session_id = "kr-actor-1"
    await _seed_awaiting_approval(sm, kr_sessions, session_id)
    graph = FakeApprovalGraph([])
    monkeypatch.setattr("app.api.routes.approval.get_kr_stock_trading_graph", lambda: graph)

    # A pending autonomous countdown must be voided by any decision
    kr_sessions[session_id]["state"]["auto_approve_at"] = "2026-07-12T10:00:00+00:00"

    await submit_decision(session_id, "approved", actor="system")

    session = await sm.get_session(session_id)
    assert session.state.get("approval_actor") == "system"
    assert graph.state_update.get("approval_actor") == "system"  # audit trail in the checkpoint
    assert "auto_approve_at" not in kr_sessions[session_id]["state"]
    assert session.state.get("auto_approve_at") is None

    # The route path records 'user'
    session_id2 = "kr-actor-2"
    record2 = await _seed_awaiting_approval(sm, kr_sessions, session_id2)
    from app.api.routes.approval import submit_approval
    from app.api.schemas.approval import ApprovalRequest

    await submit_approval(ApprovalRequest(session_id=session_id2, decision="approved"))
    assert record2["state"].get("approval_actor") == "user"


async def test_approval_rejected_mirrors_running_to_sm(sm, kr_sessions, monkeypatch):
    from app.api.routes.approval import submit_approval
    from app.api.schemas.approval import ApprovalRequest

    session_id = "kr-reject-1"
    record = await _seed_awaiting_approval(sm, kr_sessions, session_id)

    graph = FakeApprovalGraph([])
    monkeypatch.setattr("app.api.routes.approval.get_kr_stock_trading_graph", lambda: graph)

    await submit_approval(
        ApprovalRequest(session_id=session_id, decision="rejected", feedback="재분석")
    )

    assert record["status"] == "running"
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.RUNNING
    assert session.state.get("awaiting_approval") is False


# -------------------------------------------
# End-to-end: producer push reaches the session WebSocket without polling
# -------------------------------------------


async def test_ws_streams_kr_analysis_via_push_end_to_end(sm, kr_sessions, monkeypatch):
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
    _seed_session(kr_sessions, session_id)
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
