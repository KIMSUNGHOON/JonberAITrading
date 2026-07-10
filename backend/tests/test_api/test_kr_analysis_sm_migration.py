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
    monkeypatch.setattr(ws_module, "PUSH_SAFETY_POLL_SECONDS", 30.0)
    monkeypatch.setattr(ws_module, "LEGACY_POLL_SECONDS", 30.0)
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
