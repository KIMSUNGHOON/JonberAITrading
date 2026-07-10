"""P7 Phase 2: US (stock) analysis producer migration to the SessionManager.

Same pattern as the KR/coin migrations: legacy active_sessions dict FIRST
(still the read path), then guarded best-effort mirrors to the SessionManager
so graph nodes / status transitions fire pub/sub notifications for the session
WebSocket. The US DELETE /sessions/{id} route additionally mirrors the removal
so sm cannot keep serving a deleted session via the WS fallback.

Headless: stubbed graph astream + a real SessionManager on a test SQLite db.
"""

import os

import pytest
from fastapi import BackgroundTasks

import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager, SessionStatus

from app.api.schemas.analysis import AnalysisRequest
from app.api.routes.analysis import (
    delete_session,
    run_analysis_task,
    start_analysis,
)

TEST_DB_PATH = "data/test_us_sm_migration.db"


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
def us_sessions():
    from app.api.routes.analysis import active_sessions

    saved = dict(active_sessions)
    active_sessions.clear()
    yield active_sessions
    active_sessions.clear()
    active_sessions.update(saved)


def _seed_session(us_sessions, session_id: str) -> dict:
    record = {
        "session_id": session_id,
        "ticker": "AAPL",
        "status": "running",
        "state": {
            "ticker": "AAPL",
            "reasoning_log": [],
            "current_stage": "data_collection",
        },
        "created_at": None,
        "error": None,
    }
    us_sessions[session_id] = record
    return record


async def _seed_sm_session(sm, session_id: str):
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.STOCK,
        ticker="AAPL",
        display_name="AAPL",
        state={"ticker": "AAPL", "reasoning_log": [], "current_stage": "data_collection"},
    )


def _patch_graph(monkeypatch, graph):
    monkeypatch.setattr("app.api.routes.analysis.get_trading_graph", lambda: graph)


async def test_start_route_registers_sm_session(sm, us_sessions):
    response = await start_analysis(AnalysisRequest(ticker="AAPL"), BackgroundTasks())

    session = await sm.get_session(response.session_id)
    assert session is not None, "start route must register the session in the SessionManager"
    assert session.market_type == MarketType.STOCK
    assert session.ticker == "AAPL"
    assert session.state.get("reasoning_log") == []
    assert response.session_id in us_sessions
    # sm state must be an independent copy of the legacy state
    assert session.state is not us_sessions[response.session_id]["state"]
    assert (
        session.state["reasoning_log"]
        is not us_sessions[response.session_id]["state"]["reasoning_log"]
    )


async def test_analysis_task_mirrors_node_updates_and_notifies(sm, us_sessions, monkeypatch):
    session_id = "us-mirror-1"
    record = _seed_session(us_sessions, session_id)
    await _seed_sm_session(sm, session_id)
    queue = await sm.subscribe(session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {
                "reasoning_log": ["[t] collect"],
                "current_stage": "analysis",
            }},
            {"strategic_decision": {
                "reasoning_log": ["[t] collect", "[t] decide"],
                "awaiting_approval": True,
                "trade_proposal": {"id": "p1", "ticker": "AAPL", "action": "BUY"},
            }},
        ]),
    )

    await run_analysis_task(session_id, dict(record["state"]))

    assert record["status"] == "awaiting_approval"  # legacy unchanged
    session = await sm.get_session(session_id)
    assert session.state.get("reasoning_log") == ["[t] collect", "[t] decide"]
    assert session.last_node == "strategic_decision"
    assert session.status == SessionStatus.AWAITING_APPROVAL

    notifications = []
    while not queue.empty():
        notifications.append(queue.get_nowait())
    state_updates = [n for n in notifications if n.get("type") == "state_update"]
    assert len(state_updates) == 2, f"one notify per node expected, got {notifications}"
    assert state_updates[0].get("reasoning_delta") == ["[t] collect"]
    assert state_updates[1].get("reasoning_delta") == ["[t] decide"]
    assert any(
        n.get("type") == "status" and n.get("status") == "awaiting_approval"
        for n in notifications
    )


async def test_analysis_task_mirrors_completed_and_error(sm, us_sessions, monkeypatch):
    # completed
    sid_ok = "us-mirror-2"
    record_ok = _seed_session(us_sessions, sid_ok)
    await _seed_sm_session(sm, sid_ok)
    _patch_graph(
        monkeypatch,
        FakeGraph([{"data_collection": {"reasoning_log": ["[t] collect"], "current_stage": "done"}}]),
    )
    await run_analysis_task(sid_ok, dict(record_ok["state"]))
    assert (await sm.get_session(sid_ok)).status == SessionStatus.COMPLETED

    # error (graph raises)
    sid_err = "us-mirror-3"
    record_err = _seed_session(us_sessions, sid_err)
    await _seed_sm_session(sm, sid_err)
    _patch_graph(monkeypatch, FakeGraph([], raise_after=0))
    await run_analysis_task(sid_err, dict(record_err["state"]))
    assert record_err["status"] == "error"
    session = await sm.get_session(sid_err)
    assert session.status == SessionStatus.ERROR
    assert "graph exploded" in (session.error or "")


async def test_delete_route_removes_sm_session(sm, us_sessions):
    session_id = "us-delete-1"
    _seed_session(us_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    await delete_session(session_id)

    assert session_id not in us_sessions
    assert await sm.get_session(session_id) is None, (
        "deleted sessions must not survive in sm (the WS fallback would keep serving them)"
    )


async def test_analysis_task_survives_sm_mirror_failure(sm, us_sessions, monkeypatch):
    session_id = "us-guard-1"
    record = _seed_session(us_sessions, session_id)
    await _seed_sm_session(sm, session_id)

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "update_state", boom)
    monkeypatch.setattr(sm, "update_status", boom)

    _patch_graph(
        monkeypatch,
        FakeGraph([{"data_collection": {"reasoning_log": ["[t] collect"], "current_stage": "done"}}]),
    )

    await run_analysis_task(session_id, dict(record["state"]))

    assert record["status"] == "completed", "mirror failure must not fail the analysis"
    assert record["error"] is None


async def test_start_route_survives_sm_registration_failure(sm, us_sessions, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "create_session", boom)

    response = await start_analysis(AnalysisRequest(ticker="AAPL"), BackgroundTasks())

    assert response.status == "started"
    assert response.session_id in us_sessions
