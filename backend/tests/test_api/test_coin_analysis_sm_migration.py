"""P7 Phase 2: coin analysis producer migration to the SessionManager.

Same pattern as the KR migration (P7 Phase 1 t2/t3): the producer writes the
legacy coin_sessions dict FIRST (still the read path), then mirrors to the
SessionManager via the guarded best-effort helpers so every graph node /
status transition fires a pub/sub notification for the session WebSocket.

Headless: stubbed graph astream + a real SessionManager on a test SQLite db.
"""

import os

import pytest
from fastapi import BackgroundTasks

import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager, SessionStatus

from app.api.schemas.coin import CoinAnalysisRequest
from app.api.routes.coin.analysis import (
    cancel_coin_analysis,
    run_coin_analysis_task,
    start_coin_analysis,
)

TEST_DB_PATH = "data/test_coin_sm_migration.db"


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
def coin_sessions_fixture():
    from app.api.routes.coin.constants import coin_sessions

    saved = dict(coin_sessions)
    coin_sessions.clear()
    yield coin_sessions
    coin_sessions.clear()
    coin_sessions.update(saved)


def _seed_session(coin_sessions, session_id: str) -> dict:
    """Seed the legacy dict exactly like the start route does."""
    record = {
        "session_id": session_id,
        "market": "KRW-BTC",
        "korean_name": "비트코인",
        "status": "running",
        "state": {
            "market": "KRW-BTC",
            "korean_name": "비트코인",
            "query": None,
            "reasoning_log": [],
            "current_stage": "data_collection",
        },
        "created_at": None,
        "error": None,
    }
    coin_sessions[session_id] = record
    return record


async def _seed_sm_session(sm, session_id: str):
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.COIN,
        ticker="KRW-BTC",
        display_name="비트코인",
        market="KRW-BTC",
        korean_name="비트코인",
        state={"market": "KRW-BTC", "reasoning_log": [], "current_stage": "data_collection"},
    )


def _patch_graph(monkeypatch, graph):
    monkeypatch.setattr(
        "agents.graph.coin_trading_graph.get_coin_trading_graph", lambda: graph
    )


async def test_start_route_registers_sm_session(sm, coin_sessions_fixture):
    response = await start_coin_analysis(
        CoinAnalysisRequest(market="KRW-BTC"), BackgroundTasks()
    )

    session = await sm.get_session(response.session_id)
    assert session is not None, "start route must register the session in the SessionManager"
    assert session.market_type == MarketType.COIN
    assert session.market == "KRW-BTC"
    assert session.state.get("reasoning_log") == []
    assert response.session_id in coin_sessions_fixture
    # sm state must be an independent copy of the legacy state
    assert session.state is not coin_sessions_fixture[response.session_id]["state"]
    assert (
        session.state["reasoning_log"]
        is not coin_sessions_fixture[response.session_id]["state"]["reasoning_log"]
    )


async def test_analysis_task_mirrors_node_updates_and_notifies(sm, coin_sessions_fixture, monkeypatch):
    session_id = "coin-mirror-1"
    record = _seed_session(coin_sessions_fixture, session_id)
    await _seed_sm_session(sm, session_id)
    queue = await sm.subscribe(session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {
                "reasoning_log": ["[t] 수집"],
                "current_stage": "analysis",
            }},
            {"strategic_decision": {
                "reasoning_log": ["[t] 수집", "[t] 결정"],
                "awaiting_approval": True,
                "trade_proposal": {"id": "p1", "market": "KRW-BTC", "action": "BUY"},
            }},
        ]),
    )

    await run_coin_analysis_task(session_id)

    assert record["status"] == "awaiting_approval"  # legacy unchanged
    session = await sm.get_session(session_id)
    assert session.state.get("reasoning_log") == ["[t] 수집", "[t] 결정"]
    assert session.last_node == "strategic_decision"
    assert session.status == SessionStatus.AWAITING_APPROVAL

    notifications = []
    while not queue.empty():
        notifications.append(queue.get_nowait())
    state_updates = [n for n in notifications if n.get("type") == "state_update"]
    assert len(state_updates) == 2, f"one notify per node expected, got {notifications}"
    assert state_updates[0].get("reasoning_delta") == ["[t] 수집"]
    assert state_updates[1].get("reasoning_delta") == ["[t] 결정"]
    assert any(
        n.get("type") == "status" and n.get("status") == "awaiting_approval"
        for n in notifications
    )


async def test_analysis_task_mirrors_completed_and_error(sm, coin_sessions_fixture, monkeypatch):
    # completed
    sid_ok = "coin-mirror-2"
    _seed_session(coin_sessions_fixture, sid_ok)
    await _seed_sm_session(sm, sid_ok)
    _patch_graph(
        monkeypatch,
        FakeGraph([{"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "done"}}]),
    )
    await run_coin_analysis_task(sid_ok)
    assert (await sm.get_session(sid_ok)).status == SessionStatus.COMPLETED

    # error (graph raises)
    sid_err = "coin-mirror-3"
    record = _seed_session(coin_sessions_fixture, sid_err)
    await _seed_sm_session(sm, sid_err)
    _patch_graph(monkeypatch, FakeGraph([], raise_after=0))
    await run_coin_analysis_task(sid_err)
    assert record["status"] == "error"
    session = await sm.get_session(sid_err)
    assert session.status == SessionStatus.ERROR
    assert "graph exploded" in (session.error or "")


async def test_cancel_route_mirrors_cancelled_status(sm, coin_sessions_fixture):
    session_id = "coin-cancel-1"
    _seed_session(coin_sessions_fixture, session_id)
    await _seed_sm_session(sm, session_id)

    await cancel_coin_analysis(session_id)

    assert coin_sessions_fixture[session_id]["status"] == "cancelled"
    assert (await sm.get_session(session_id)).status == SessionStatus.CANCELLED


async def test_cancel_mid_run_is_not_overwritten_by_final_status(sm, coin_sessions_fixture, monkeypatch):
    session_id = "coin-cancelflap-1"
    record = _seed_session(coin_sessions_fixture, session_id)
    await _seed_sm_session(sm, session_id)

    class CancellingGraph:
        async def astream(self, initial_state, config):
            yield {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}
            await cancel_coin_analysis(session_id)
            yield {"technical_analysis": {"reasoning_log": ["[t] 수집", "[t] 기술"], "current_stage": "y"}}

    _patch_graph(monkeypatch, CancellingGraph())

    await run_coin_analysis_task(session_id)

    assert record["status"] == "cancelled"
    assert (await sm.get_session(session_id)).status == SessionStatus.CANCELLED


async def test_analysis_task_survives_sm_mirror_failure(sm, coin_sessions_fixture, monkeypatch):
    session_id = "coin-guard-1"
    record = _seed_session(coin_sessions_fixture, session_id)
    await _seed_sm_session(sm, session_id)

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "update_state", boom)
    monkeypatch.setattr(sm, "update_status", boom)

    _patch_graph(
        monkeypatch,
        FakeGraph([{"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "done"}}]),
    )

    await run_coin_analysis_task(session_id)

    assert record["status"] == "completed", "mirror failure must not fail the analysis"
    assert record["error"] is None


async def test_start_route_survives_sm_registration_failure(sm, coin_sessions_fixture, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "create_session", boom)

    response = await start_coin_analysis(
        CoinAnalysisRequest(market="KRW-BTC"), BackgroundTasks()
    )

    assert response.status == "started"
    assert response.session_id in coin_sessions_fixture
