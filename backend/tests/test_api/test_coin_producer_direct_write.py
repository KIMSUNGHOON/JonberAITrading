"""P2-4: coin producer SM 직접쓰기 전환 — characterization tests (목표 거동).

세션 SSOT 통합 P2-4. `coin/analysis.py`가 legacy dict(B, `coin_sessions`) +
SessionManager(SM) + `app.core.analysis_limiter.active_sessions`(4번째 사본)
로 이중/삼중쓰기하던 것을 SM 직접쓰기 단독으로 전환한다. P2-3(KR,
`e38a4ff`)과 동일 원칙, coin 코드에 적용한 것 — 이 파일은 REFACTOR 전
실패(RED)해야 하는, 목표 거동을 고정하는 특성화 테스트다:

  1) 동시 start 2건(asyncio.gather) — 원자 예약(`create_session_if_no_active`)
     이 dedup을 대체하므로 정확히 하나만 새 세션을 예약하고, 그래프는 정확히
     1회만 실행된다.
  2) awaiting_approval 세션이 3개의 읽기 표면(/approval/pending,
     GET /api/trading/operations, WS `_get_session_snapshot`)에서 동일하게
     보인다 — SM이 유일한 쓰기 대상이므로 셋 다 같은 진실을 읽는다.
  3) legacy dict(`coin_sessions`, B)는 start~cancel 전 생애주기 동안
     완전히 비어 있다 — B 쓰기가 하나도 남지 않았다는 핀.
  4) analysis_limiter의 `active_sessions` dict(4번째 사본)도 전 과정 빈
     상태 유지 — register_session/update_session_status 호출이 전부
     삭제됐다는 핀.

awaiting-commit 실패 시 fail-closed(2회 시도 후 ERROR + schedule 금지)는
`test_awaiting_writethrough.py`의 조정된 coin 테스트가 커버한다(새 시그니처
`_finalize_awaiting_transition(session_id)`).

Headless: 스텁 그래프 astream + 테스트 SQLite db 위의 실제 SessionManager
(test_kr_producer_direct_write.py / test_coin_analysis_sm_migration.py와
동일 관례).
"""

import asyncio
import os
from unittest.mock import MagicMock

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

TEST_DB_PATH = "data/test_coin_producer_direct_write.db"


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
def coin_sessions():
    """Isolated view of the legacy coin session dict (B) -- must stay empty."""
    from app.api.routes.coin.constants import coin_sessions as _coin_sessions

    saved = dict(_coin_sessions)
    _coin_sessions.clear()
    yield _coin_sessions
    _coin_sessions.clear()
    _coin_sessions.update(saved)


@pytest.fixture
def limiter_active_sessions():
    """Isolated view of analysis_limiter's legacy `active_sessions` dict (the
    4th copy) -- must stay empty across the whole lifecycle once
    register_session/update_session_status calls are removed from the coin
    producer."""
    from app.core.analysis_limiter import active_sessions

    saved = dict(active_sessions)
    active_sessions.clear()
    yield active_sessions
    active_sessions.clear()
    active_sessions.update(saved)


def _patch_graph(monkeypatch, graph):
    monkeypatch.setattr(
        "agents.graph.coin_trading_graph.get_coin_trading_graph", lambda: graph
    )


class _CountingCompletingGraph:
    """Yields one data_collection node then ends -- session goes COMPLETED."""

    def __init__(self):
        self.calls = 0

    async def astream(self, initial_state, config):
        self.calls += 1
        yield {"data_collection": {"reasoning_log": ["[t] 수집"], "current_stage": "done"}}


class _AwaitingGraph:
    """Reaches the approval interrupt on the first node."""

    async def astream(self, initial_state, config):
        yield {
            "strategic_decision": {
                "reasoning_log": ["[t] 결정"],
                "awaiting_approval": True,
                "trade_proposal": {
                    "id": "p1",
                    "market": "KRW-BTC",
                    "korean_name": "비트코인",
                    "action": "BUY",
                    "quantity": 1,
                    "entry_price": 70000000,
                    "risk_score": 0.4,
                    "rationale": "테스트",
                    "created_at": "2026-07-16T00:00:00+00:00",
                },
            }
        }


# -------------------------------------------
# 1) Concurrent starts for the same market -- atomic reservation replaces
#    the old find-then-write dedup sequence.
# -------------------------------------------


async def test_concurrent_starts_same_market_reserve_exactly_once(
    sm, coin_sessions, limiter_active_sessions, monkeypatch
):
    graph = _CountingCompletingGraph()
    _patch_graph(monkeypatch, graph)

    bg_a = BackgroundTasks()
    bg_b = BackgroundTasks()

    response_a, response_b = await asyncio.gather(
        start_coin_analysis(CoinAnalysisRequest(market="KRW-BTC"), bg_a),
        start_coin_analysis(CoinAnalysisRequest(market="KRW-BTC"), bg_b),
    )

    responses = [response_a, response_b]
    winners = [r for r in responses if not r.duplicate]
    duplicates = [r for r in responses if r.duplicate]

    assert len(winners) == 1, "exactly one of the two concurrent starts must win the reservation"
    assert len(duplicates) == 1
    assert duplicates[0].session_id == winners[0].session_id

    # Exactly one graph run was queued across BOTH start calls.
    assert len(bg_a.tasks) + len(bg_b.tasks) == 1

    # Exactly one SM session exists for this market -- no second row created
    # by the "loser" of the race.
    all_sessions = await sm.get_all_sessions(market_type=MarketType.COIN)
    assert len(all_sessions) == 1
    assert next(iter(all_sessions)) == winners[0].session_id

    # Running the single winning session's analysis invokes the graph exactly
    # once -- the loser never queued a second run to invoke.
    await run_coin_analysis_task(winners[0].session_id)
    assert graph.calls == 1

    session = await sm.get_session(winners[0].session_id)
    assert session.status == SessionStatus.COMPLETED


# -------------------------------------------
# 2) An awaiting_approval session is visible, identically, on all three read
#    surfaces -- SM is the sole write target so all three read the same truth.
# -------------------------------------------


async def test_awaiting_session_visible_on_pending_operations_and_ws_snapshot(
    sm, coin_sessions, limiter_active_sessions, monkeypatch
):
    _patch_graph(monkeypatch, _AwaitingGraph())

    bg = BackgroundTasks()
    response = await start_coin_analysis(CoinAnalysisRequest(market="KRW-BTC"), bg)
    session_id = response.session_id

    await run_coin_analysis_task(session_id)

    session = await sm.get_session(session_id)
    assert session.status == SessionStatus.AWAITING_APPROVAL
    assert session.state.get("awaiting_approval") is True

    # Surface 1: GET /approval/pending
    from app.api.routes.approval import list_pending_approvals

    pending = await list_pending_approvals()
    pending_ids = {p.session_id for p in pending.pending_approvals}
    assert session_id in pending_ids

    # Surface 2: GET /api/trading/operations
    from app.api.routes import trading as trading_mod

    coordinator = MagicMock()
    coordinator.get_watch_list.return_value = []
    coordinator.get_trade_queue.return_value = []
    coordinator.state.positions = []
    ops = await trading_mod.get_operations(market="coin", coordinator=coordinator)
    awaiting_ids = {a.session_id for a in (ops.awaiting or [])}
    assert session_id in awaiting_ids

    # Surface 3: the session WebSocket's snapshot read
    from app.api.routes.websocket import _get_session_snapshot

    snap = await _get_session_snapshot(session_id)
    assert snap is not None
    assert snap["session_id"] == session_id
    assert snap["state"].get("awaiting_approval") is True


# -------------------------------------------
# 3) The legacy dict (B) AND the limiter's active_sessions dict (the 4th
#    copy) stay empty across the ENTIRE lifecycle -- start, run-to-completion,
#    run-to-awaiting, and cancel never write either.
# -------------------------------------------


async def test_b_dict_stays_empty_through_completed_lifecycle(
    sm, coin_sessions, limiter_active_sessions, monkeypatch
):
    _patch_graph(monkeypatch, _CountingCompletingGraph())

    bg = BackgroundTasks()
    response = await start_coin_analysis(CoinAnalysisRequest(market="KRW-BTC"), bg)
    assert coin_sessions == {}, "start must never write the legacy dict"
    assert limiter_active_sessions == {}, "start must never write the limiter's active_sessions dict"

    await run_coin_analysis_task(response.session_id)
    assert coin_sessions == {}, "the background task must never write the legacy dict"
    assert limiter_active_sessions == {}, (
        "the background task must never write the limiter's active_sessions dict"
    )

    session = await sm.get_session(response.session_id)
    assert session.status == SessionStatus.COMPLETED


async def test_b_dict_stays_empty_through_awaiting_and_cancel_lifecycle(
    sm, coin_sessions, limiter_active_sessions, monkeypatch
):
    _patch_graph(monkeypatch, _AwaitingGraph())

    bg = BackgroundTasks()
    response = await start_coin_analysis(CoinAnalysisRequest(market="KRW-BTC"), bg)
    assert coin_sessions == {}
    assert limiter_active_sessions == {}

    await run_coin_analysis_task(response.session_id)
    assert coin_sessions == {}, "reaching the approval interrupt must never write the legacy dict"
    assert limiter_active_sessions == {}

    session = await sm.get_session(response.session_id)
    assert session.status == SessionStatus.AWAITING_APPROVAL

    result = await cancel_coin_analysis(response.session_id)
    assert coin_sessions == {}, "cancel must never write the legacy dict"
    assert limiter_active_sessions == {}
    assert result["mirror_failed"] is False

    session = await sm.get_session(response.session_id)
    assert session.status == SessionStatus.CANCELLED
    assert session.state.get("awaiting_approval") is False
