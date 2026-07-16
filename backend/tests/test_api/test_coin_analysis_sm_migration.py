"""P7 Phase 2 -> P2-4: coin analysis producer migration to the
SessionManager, then to SM-only direct writes.

The coin analysis routes historically wrote ONLY a legacy in-process
session dict (P7 Phase 2 made it write BOTH -- legacy dict first, then
the SessionManager, so pub/sub could fire). P2-4 (session-SSOT) removed the
legacy-dict write entirely -- and dropped the 4th-copy analysis_limiter
sync writes (register_session/update_session_status) too: the producer now
writes the SessionManager ONLY (the legacy dict itself was fully deleted in
P3-1). Tests that need a "session that already exists" fixture seed the
SessionManager directly (`_seed_sm_session`).

Headless: stubbed graph astream + a real SessionManager on a test SQLite db.
"""

import asyncio
import os

import pytest
from fastapi import BackgroundTasks, HTTPException

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


async def _seed_sm_session(sm, session_id: str):
    """Register the sm-side session the migrated start route creates."""
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.COIN,
        ticker="KRW-BTC",
        display_name="비트코인",
        market="KRW-BTC",
        korean_name="비트코인",
        state={
            "market": "KRW-BTC",
            "korean_name": "비트코인",
            "query": None,
            "reasoning_log": [],
            "current_stage": "data_collection",
        },
    )


def _patch_graph(monkeypatch, graph: FakeGraph):
    monkeypatch.setattr(
        "agents.graph.coin_trading_graph.get_coin_trading_graph", lambda: graph
    )


# -------------------------------------------
# Start route registers the session in the SessionManager
# -------------------------------------------


async def test_start_route_registers_sm_session(sm):
    response = await start_coin_analysis(
        CoinAnalysisRequest(market="KRW-BTC"), BackgroundTasks()
    )

    session = await sm.get_session(response.session_id)
    assert session is not None, "start route must register the session in the SessionManager"
    assert session.market_type == MarketType.COIN
    assert session.market == "KRW-BTC"
    assert session.state.get("reasoning_log") == []


# -------------------------------------------
# Background task mirrors node updates + final status to the SessionManager
# -------------------------------------------


async def test_analysis_task_mirrors_node_updates_and_notifies(sm, monkeypatch):
    session_id = "coin-mirror-1"
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


async def test_analysis_task_mirrors_completed_status(sm, monkeypatch):
    session_id = "coin-mirror-2"
    await _seed_sm_session(sm, session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph([{"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "done"}}]),
    )

    await run_coin_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.COMPLETED


async def test_analysis_task_mirrors_error_status(sm, monkeypatch):
    session_id = "coin-mirror-3"
    await _seed_sm_session(sm, session_id)

    _patch_graph(monkeypatch, FakeGraph([], raise_after=0))

    await run_coin_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.ERROR
    assert "graph exploded" in (session.error or "")


# -------------------------------------------
# Cancel route mirrors the cancelled status
# -------------------------------------------


async def test_cancel_route_mirrors_cancelled_status(sm):
    session_id = "coin-cancel-1"
    await _seed_sm_session(sm, session_id)

    await cancel_coin_analysis(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED


# -------------------------------------------
# F4b IMPORTANT-1: cancel must clear awaiting_approval/approval_status on the
# sm -- same zombie-resurrection / stale-auto-approve guard as the kr_stocks
# analog (test_kr_analysis_sm_migration.py::
# test_cancel_clears_awaiting_flag_on_legacy_and_sm). Pre-fix, this route
# only set session["status"] = "cancelled" and left state["awaiting_approval"]
# True / approval_status None behind -- a stale system auto-approve racing in
# through the injector's grace-window timer would then find the proposal-id
# pin unchanged (a cancel never replaces the proposal) and awaiting_approval
# still True, sail through submit_decision's stale-flag checks, place the
# order, and overwrite this cancelled status with "completed".
# -------------------------------------------


async def test_cancel_clears_awaiting_flag_on_sm(sm):
    """P2-4: there is no separate legacy-dict copy to desync from the sm
    anymore -- the zombie-resurrection guard this test pins now applies to
    the SM's own state directly (a restart resurrects from SQLite, not from
    an in-process dict)."""
    session_id = "coin-cancel-clear-1"
    await _seed_sm_session(sm, session_id)
    await sm.update_state(
        session_id,
        {"awaiting_approval": True, "trade_proposal": {"id": "p1", "action": "HOLD"}},
    )
    await sm.update_status(session_id, SessionStatus.AWAITING_APPROVAL)

    await cancel_coin_analysis(session_id)

    # sm cleared too -- without this, a restart resurrects the session as
    # AWAITING_APPROVAL with awaiting_approval still True (zombie), and a
    # live stale auto-approve would sail through the pin check unopposed.
    session = await sm.get_session(session_id)
    assert session.state.get("awaiting_approval") is False
    assert session.state.get("approval_status") == "cancelled"
    assert session.status == SessionStatus.CANCELLED


async def test_cancel_failure_is_surfaced_as_503_not_swallowed(sm, monkeypatch):
    """P2-4: with the SM as the sole store, a persistent write failure during
    cancel can no longer be treated as a best-effort 'mirror' -- there is no
    second store whose local success could paper over it. It now fails loud
    (503) after one retry instead of returning 200 with mirror_failed=True.
    Without this, a silently-accepted cancel could leave the SM row stuck
    AWAITING_APPROVAL with awaiting_approval still True -- a restart-time
    zombie."""
    session_id = "coin-cancel-mirror-fail-1"
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

    from app.api.routes.coin import analysis as analysis_mod

    monkeypatch.setattr(analysis_mod.logger, "error", fake_error)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_coin_analysis(session_id)

    assert exc_info.value.status_code == 503
    assert calls["n"] == 2  # one retry, then fail closed

    assert logged["event"] == "coin_analysis_cancel_failed"
    assert logged["kwargs"]["session_id"] == session_id
    assert "sqlite down" in logged["kwargs"]["error"]

    # The sm row was never actually transitioned -- no zombie
    # AWAITING_APPROVAL-with-awaiting_approval=True shape was created.
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.RUNNING


async def test_cancel_mirror_success_reports_mirror_failed_false(sm):
    session_id = "coin-cancel-mirror-ok-1"
    await _seed_sm_session(sm, session_id)

    response = await cancel_coin_analysis(session_id)

    assert response["mirror_failed"] is False


# -------------------------------------------
# (I3) Cancel route participates in the per-session decision lock
# -------------------------------------------


async def test_cancel_route_serializes_against_concurrent_decision_lock_holder(sm):
    """(I3) cancel must wait if another decision (e.g. an in-flight reject
    resume through /decide) currently holds the per-session decision lock for
    this session_id — otherwise the cancel races the resume directly against
    the sm, and whichever writes last silently wins even if it is the stale
    one."""
    import app.api.routes.approval as approval_module

    session_id = "coin-cancel-lock-1"
    await _seed_sm_session(sm, session_id)

    lock_acquired = asyncio.Event()
    release_lock = asyncio.Event()

    async def hold_lock():
        async with approval_module._session_decision_lock(session_id):
            lock_acquired.set()
            await release_lock.wait()

    holder = asyncio.create_task(hold_lock())
    await asyncio.wait_for(lock_acquired.wait(), timeout=5)

    cancel_task = asyncio.create_task(cancel_coin_analysis(session_id))
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

    assert approval_module._decision_locks == {}
    assert approval_module._decision_lock_refs == {}


# -------------------------------------------
# (I4) Cancel route refuses an already-settled session with 409
# -------------------------------------------


async def test_cancel_route_refuses_completed_session_409(sm):
    session_id = "coin-cancel-done-1"
    await _seed_sm_session(sm, session_id)
    await sm.update_status(session_id, SessionStatus.COMPLETED)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_coin_analysis(session_id)

    assert exc_info.value.status_code == 409
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.COMPLETED


async def test_cancel_route_refuses_error_session_409(sm):
    session_id = "coin-cancel-err-1"
    await _seed_sm_session(sm, session_id)
    await sm.update_status(session_id, SessionStatus.ERROR)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_coin_analysis(session_id)

    assert exc_info.value.status_code == 409
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.ERROR


async def test_cancel_route_still_200s_for_awaiting_session(sm):
    """Normal case unchanged: an actively-running (not yet settled) session
    cancels cleanly with 200."""
    session_id = "coin-cancel-normal-1"
    await _seed_sm_session(sm, session_id)  # RUNNING by default

    response = await cancel_coin_analysis(session_id)

    assert response["mirror_failed"] is False
    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED


# -------------------------------------------
# Producer robustness: sm write failures must propagate (SM is the sole store)
# -------------------------------------------


async def test_analysis_task_propagates_sm_write_failure_but_releases_slot(
    sm, monkeypatch
):
    """P2-4: with the SM as the SOLE write target (all mirror_* calls
    replaced by direct sm.update_state/update_status), a SessionManager
    write failure is a REAL failure now — it propagates instead of being
    silently swallowed the way the old best-effort mirror_session_state/
    mirror_session_status wrappers used to (superseding this test's old
    'a mirror failure must not abort a healthy run' premise, which no longer
    holds: there is no second store whose local success could paper over an
    SM outage). The analysis slot must still be released via `finally`, so a
    persistent SQLite outage doesn't also starve the concurrency semaphore
    for every other market."""
    session_id = "coin-guard-1"
    await _seed_sm_session(sm, session_id)

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "update_state", boom)
    monkeypatch.setattr(sm, "update_status", boom)

    released = {"n": 0}

    def counting_release():
        released["n"] += 1

    monkeypatch.setattr(
        "app.api.routes.coin.analysis.release_analysis_slot", counting_release
    )

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "done"}},
        ]),
    )

    with pytest.raises(RuntimeError):
        await run_coin_analysis_task(session_id)

    assert released["n"] == 1, "the analysis slot must still be released via finally"


async def test_start_route_failfast_on_sm_registration_failure(sm, monkeypatch):
    """P1-5: sm reservation failure must fail the start route loud (503), not
    silently degrade to poll-only -- with SM-only reads a session the SM
    never registered is invisible to every read surface, so a 200 "started"
    response here would be lying to the caller.

    P2-4: the atomic reservation (`create_session_if_no_active`) IS the
    registration call now -- there is no separate legacy-dict placeholder
    left behind to mark "error" on failure; the reservation itself simply
    never lands, so nothing is created anywhere.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(sm, "create_session_if_no_active", boom)

    with pytest.raises(HTTPException) as exc_info:
        await start_coin_analysis(
            CoinAnalysisRequest(market="KRW-BTC"), BackgroundTasks()
        )

    assert exc_info.value.status_code == 503
    assert await sm.get_all_sessions(market_type=MarketType.COIN) == {}


async def test_cancel_mid_run_is_not_overwritten_by_final_status(sm, monkeypatch):
    """User cancel during a run must stick — the task's final status write must not flap it."""
    session_id = "coin-cancelflap-1"
    await _seed_sm_session(sm, session_id)

    class CancellingGraph:
        async def astream(self, initial_state, config):
            yield {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}
            await cancel_coin_analysis(session_id)
            yield {"technical_analysis": {"reasoning_log": ["[t] 수집", "[t] 기술"], "current_stage": "y"}}

    _patch_graph(monkeypatch, CancellingGraph())

    await run_coin_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.CANCELLED


async def test_state_error_branch_mirrors_error(sm, monkeypatch):
    """A graph that finishes cleanly WITH state['error'] set (e.g. Upbit fetch
    failure) must mirror ERROR — else sm keeps a never-TTL-cleaned RUNNING row."""
    session_id = "coin-stateerr-1"
    await _seed_sm_session(sm, session_id)

    _patch_graph(
        monkeypatch,
        FakeGraph([
            {"data_collection": {
                "reasoning_log": ["[t] 수집 실패"],
                "error": "업비트 API 실패",
            }},
        ]),
    )

    await run_coin_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.ERROR
    assert "업비트" in (session.error or "")


async def test_slot_timeout_mirrors_error(sm, monkeypatch):
    session_id = "coin-slot-1"
    await _seed_sm_session(sm, session_id)

    async def no_slot(timeout=60.0):
        return False

    monkeypatch.setattr("app.api.routes.coin.analysis.acquire_analysis_slot", no_slot)

    await run_coin_analysis_task(session_id)

    assert (await sm.get_session(session_id)).status == SessionStatus.ERROR


async def test_cancel_during_slot_wait_keeps_cancelled(sm, monkeypatch):
    """Cancel while waiting for an analysis slot must not be overwritten by the
    slot-timeout error write."""
    session_id = "coin-cancelslot-1"
    await _seed_sm_session(sm, session_id)

    async def cancel_then_timeout(timeout=60.0):
        await cancel_coin_analysis(session_id)
        return False

    monkeypatch.setattr("app.api.routes.coin.analysis.acquire_analysis_slot", cancel_then_timeout)

    await run_coin_analysis_task(session_id)

    assert (await sm.get_session(session_id)).status == SessionStatus.CANCELLED


async def test_cancel_then_graph_exception_keeps_cancelled(sm, monkeypatch):
    """The diff's own invariant — terminal cancelled must not be overwritten —
    must hold on the exception path too, not just the normal-completion write."""
    session_id = "coin-cancelerr-1"
    await _seed_sm_session(sm, session_id)

    class CancelThenExplodeGraph:
        async def astream(self, initial_state, config):
            yield {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "x"}}
            await cancel_coin_analysis(session_id)
            raise RuntimeError("LLM call failed")

    _patch_graph(monkeypatch, CancelThenExplodeGraph())

    await run_coin_analysis_task(session_id)

    assert (await sm.get_session(session_id)).status == SessionStatus.CANCELLED
