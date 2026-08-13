"""P2-3: KR producer SM 직접쓰기 전환 — characterization tests (목표 거동).

세션 SSOT 통합 P2-3. `kr_stocks/analysis.py`가 legacy dict(B)와
SessionManager(SM)에 이중쓰기하던 것을 SM 직접쓰기 단독으로 전환한다
(legacy dict는 P3-1에서 완전 삭제됨). 이 파일은 REFACTOR 전 실패(RED)해야
하는, 목표 거동을 고정하는 특성화 테스트다:

  1) 동시 start 2건(asyncio.gather) — 원자 예약(`create_session_if_no_active`)
     이 dedup을 대체하므로 정확히 하나만 새 세션을 예약하고, 그래프는 정확히
     1회만 실행된다.
  2) awaiting_approval 세션이 3개의 읽기 표면(/approval/pending,
     GET /api/trading/operations, WS `_get_session_snapshot`)에서 동일하게
     보인다 — SM이 유일한 쓰기 대상이므로 셋 다 같은 진실을 읽는다.

awaiting-commit 실패 시 fail-closed(2회 시도 후 ERROR + schedule 금지)는
`test_awaiting_writethrough.py`의 조정된 KR 테스트가 커버한다(새 시그니처
`_finalize_awaiting_transition(session_id)`).

Headless: 스텁 그래프 astream + 테스트 SQLite db 위의 실제 SessionManager
(test_kr_analysis_sm_migration.py / test_analysis_dedup.py와 동일 관례).
"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks

import app.api.routes._autonomy_injector as injector_module
import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager, SessionStatus

from app.api.schemas.kr_stocks import KRStockAnalysisRequest
from app.api.routes.kr_stocks.analysis import (
    cancel_kr_stock_analysis,
    run_kr_stock_analysis_task,
    start_kr_stock_analysis,
)

TEST_DB_PATH = "data/test_kr_producer_direct_write.db"


@pytest.fixture(autouse=True)
def no_real_telegram(monkeypatch):
    """TG-3 review fix (Critical-1): the awaiting-approval graph path in this
    file (`_AwaitingGraph`, used by test 2/3 below) runs all the way through
    `_finalize_awaiting_transition` -> `maybe_schedule_auto_approve`, which
    always attempts a best-effort Telegram send (TG-3). Without this,
    running this file with a real `.env` (TELEGRAM_ENABLED=true) sends a
    real Telegram message on every awaiting-approval test (실증됨:
    `telegram_send_failed ... Event loop is closed` in this file's own
    output) -- constraint: 실 네트워크 금지. Mirrors the identical fixture
    in test_autonomy_injector.py / test_telegram_approval_buttons.py; a fake
    notifier with is_ready=False is sufficient since the send call always
    checks that first."""
    fake_notifier = SimpleNamespace(is_ready=False)

    async def fake_get_notifier():
        return fake_notifier

    monkeypatch.setattr(injector_module, "get_telegram_notifier", fake_get_notifier)


class _FakeStockInfo:
    stk_nm = "삼성전자"


class _FakeKiwoomClient:
    async def get_stock_info(self, stk_cd):
        return _FakeStockInfo()

    async def get_account_balance(self):
        return None


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


def _patch_graph(monkeypatch, graph):
    monkeypatch.setattr(
        "agents.graph.kr_stock_graph.get_kr_stock_trading_graph", lambda: graph
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
                    "stk_cd": "005930",
                    "stk_nm": "삼성전자",
                    "action": "BUY",
                    "quantity": 1,
                    "entry_price": 70000,
                    "risk_score": 0.4,
                    "rationale": "테스트",
                    "created_at": "2026-07-16T00:00:00+00:00",
                },
            }
        }


# -------------------------------------------
# 1) Concurrent starts for the same ticker -- atomic reservation replaces
#    the old find-then-write dedup sequence.
# -------------------------------------------


async def test_concurrent_starts_same_ticker_reserve_exactly_once(
    sm, fake_kiwoom, monkeypatch
):
    graph = _CountingCompletingGraph()
    _patch_graph(monkeypatch, graph)

    bg_a = BackgroundTasks()
    bg_b = BackgroundTasks()

    response_a, response_b = await asyncio.gather(
        start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg_a),
        start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg_b),
    )

    responses = [response_a, response_b]
    winners = [r for r in responses if not r.duplicate]
    duplicates = [r for r in responses if r.duplicate]

    assert len(winners) == 1, "exactly one of the two concurrent starts must win the reservation"
    assert len(duplicates) == 1
    assert duplicates[0].session_id == winners[0].session_id

    # Exactly one graph run was queued across BOTH start calls.
    assert len(bg_a.tasks) + len(bg_b.tasks) == 1

    # Exactly one SM session exists for this ticker -- no second row created
    # by the "loser" of the race.
    all_sessions = await sm.get_all_sessions(market_type=MarketType.KIWOOM)
    assert len(all_sessions) == 1
    assert next(iter(all_sessions)) == winners[0].session_id

    # Running the single winning session's analysis invokes the graph exactly
    # once -- the loser never queued a second run to invoke.
    await run_kr_stock_analysis_task(winners[0].session_id)
    assert graph.calls == 1

    session = await sm.get_session(winners[0].session_id)
    assert session.status == SessionStatus.COMPLETED


# -------------------------------------------
# 2) An awaiting_approval session is visible, identically, on all three read
#    surfaces -- SM is the sole write target so all three read the same truth.
# -------------------------------------------


async def test_awaiting_session_visible_on_pending_operations_and_ws_snapshot(
    sm, fake_kiwoom, monkeypatch
):
    _patch_graph(monkeypatch, _AwaitingGraph())

    bg = BackgroundTasks()
    response = await start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg)
    session_id = response.session_id

    await run_kr_stock_analysis_task(session_id)

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
    ops = await trading_mod.get_operations(market="kiwoom", coordinator=coordinator)
    awaiting_ids = {a.session_id for a in (ops.awaiting or [])}
    assert session_id in awaiting_ids

    # Surface 3: the session WebSocket's snapshot read
    from app.api.routes.websocket import _get_session_snapshot

    snap = await _get_session_snapshot(session_id)
    assert snap is not None
    assert snap["session_id"] == session_id
    assert snap["state"].get("awaiting_approval") is True


# -------------------------------------------
# 3) Cancel-after-awaiting lifecycle transitions correctly through the SM
#    alone (legacy dict writes were retired in P3-1).
# -------------------------------------------


async def test_awaiting_and_cancel_lifecycle(sm, fake_kiwoom, monkeypatch):
    _patch_graph(monkeypatch, _AwaitingGraph())

    bg = BackgroundTasks()
    response = await start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg)

    await run_kr_stock_analysis_task(response.session_id)

    session = await sm.get_session(response.session_id)
    assert session.status == SessionStatus.AWAITING_APPROVAL

    result = await cancel_kr_stock_analysis(response.session_id)
    assert result["mirror_failed"] is False

    session = await sm.get_session(response.session_id)
    assert session.status == SessionStatus.CANCELLED
    assert session.state.get("awaiting_approval") is False
