"""P4 Task 1: ticker-level dedup for concurrent analysis sessions.

`POST /analysis/start` (KR + coin) used to mint a brand new session_id on
EVERY call, with no check for an existing in-progress session for the same
ticker — only `app/core/analysis_limiter.py`'s GLOBAL concurrent-count
semaphore limited anything, and that's a separate, complementary concern
(still untouched here). A user/scanner/basket could fire N redundant
analyses of the same stk_cd/market.

This ports the `ticker in self._active_rooms` guard pattern from
`services/agent_chat/coordinator.py` (coordinator.py:860-861) to the
analysis pipeline: if a RUNNING or AWAITING_APPROVAL session already exists
for the ticker, `/analysis/start` returns that EXISTING session
(`duplicate=True`) instead of spawning a second graph run. Completed,
cancelled, and errored sessions never block — re-analysis is always allowed
once the prior run finished.

Headless: stubbed graph astream + a real SessionManager on a test SQLite db,
following the conventions in test_kr_analysis_sm_migration.py /
test_coin_analysis_sm_migration.py.
"""

import asyncio
import os

import pytest
from fastapi import BackgroundTasks

import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager, SessionStatus

from app.api.schemas.kr_stocks import KRStockAnalysisRequest
from app.api.schemas.coin import CoinAnalysisRequest
from app.api.routes.kr_stocks.analysis import start_kr_stock_analysis
from app.api.routes.coin.analysis import start_coin_analysis
from app.api.routes.kr_stocks.helpers import find_active_kr_session
from app.api.routes.coin.helpers import find_active_coin_session

TEST_DB_PATH = "data/test_analysis_dedup.db"


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
def coin_sessions_fixture():
    from app.api.routes.coin.constants import coin_sessions

    saved = dict(coin_sessions)
    coin_sessions.clear()
    yield coin_sessions
    coin_sessions.clear()
    coin_sessions.update(saved)


class _FakeStockInfo:
    stk_nm = "삼성전자"


class _FakeKiwoomClient:
    async def get_stock_info(self, stk_cd):
        return _FakeStockInfo()


@pytest.fixture
def fake_kiwoom(monkeypatch):
    async def _fake_client():
        return _FakeKiwoomClient()

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.get_shared_kiwoom_client_async", _fake_client
    )


def _seed_kr_session(kr_sessions, session_id: str, status: str = "running") -> dict:
    record = {
        "session_id": session_id,
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "status": status,
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


def _seed_coin_session(coin_sessions, session_id: str, status: str = "running") -> dict:
    record = {
        "session_id": session_id,
        "market": "KRW-BTC",
        "korean_name": "비트코인",
        "status": status,
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


async def _seed_kr_sm_session(sm, session_id: str, status: SessionStatus = SessionStatus.RUNNING):
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        stk_cd="005930",
        stk_nm="삼성전자",
        state={"stk_cd": "005930", "reasoning_log": [], "current_stage": "data_collection"},
    )
    await sm.update_status(session_id, status)


async def _seed_coin_sm_session(sm, session_id: str, status: SessionStatus = SessionStatus.RUNNING):
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.COIN,
        ticker="KRW-BTC",
        display_name="비트코인",
        market="KRW-BTC",
        korean_name="비트코인",
        state={"market": "KRW-BTC", "reasoning_log": [], "current_stage": "data_collection"},
    )
    await sm.update_status(session_id, status)


# -------------------------------------------
# KR: an active session blocks a duplicate start
# -------------------------------------------


@pytest.mark.parametrize("blocking_status", ["running", "awaiting_approval"])
async def test_kr_start_dedup_returns_existing_session(
    sm, kr_sessions, fake_kiwoom, blocking_status
):
    existing_id = "kr-existing-1"
    _seed_kr_session(kr_sessions, existing_id, status=blocking_status)
    await _seed_kr_sm_session(
        sm,
        existing_id,
        status=SessionStatus.RUNNING
        if blocking_status == "running"
        else SessionStatus.AWAITING_APPROVAL,
    )

    bg = BackgroundTasks()
    response = await start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg)

    assert response.session_id == existing_id
    assert response.duplicate is True
    assert response.status == blocking_status
    # No second session was created, and no second graph run was queued.
    assert len(kr_sessions) == 1
    assert bg.tasks == []


async def test_kr_start_dedup_does_not_call_kiwoom_client(sm, kr_sessions, monkeypatch):
    """A dedup hit should short-circuit before the (network-bound) stock-name
    lookup — no reason to pay that cost for a session we're not creating."""
    existing_id = "kr-existing-nocall"
    _seed_kr_session(kr_sessions, existing_id, status="running")
    await _seed_kr_sm_session(sm, existing_id)

    called = {"n": 0}

    async def _boom():
        called["n"] += 1
        raise AssertionError("kiwoom client should not be called on a dedup hit")

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.get_shared_kiwoom_client_async", _boom
    )

    response = await start_kr_stock_analysis(
        KRStockAnalysisRequest(stk_cd="005930"), BackgroundTasks()
    )

    assert response.duplicate is True
    assert called["n"] == 0


@pytest.mark.parametrize("settled_status", ["completed", "error", "cancelled"])
async def test_kr_start_allows_new_analysis_after_settled_session(
    sm, kr_sessions, fake_kiwoom, settled_status
):
    prior_id = "kr-settled-1"
    _seed_kr_session(kr_sessions, prior_id, status=settled_status)
    await _seed_kr_sm_session(sm, prior_id, status=SessionStatus.RUNNING)
    await sm.update_status(
        prior_id,
        {
            "completed": SessionStatus.COMPLETED,
            "error": SessionStatus.ERROR,
            "cancelled": SessionStatus.CANCELLED,
        }[settled_status],
    )

    bg = BackgroundTasks()
    response = await start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg)

    assert response.session_id != prior_id
    assert response.duplicate is False
    # P2-3: the producer writes the SM only -- `kr_sessions` here still has
    # its ONE fixture-seeded entry (the settled prior session, planted
    # directly by this test's own setup, not by the route) and gains no
    # second entry from the fresh start.
    assert len(kr_sessions) == 1
    all_sessions = await sm.get_all_sessions(market_type=MarketType.KIWOOM)
    assert len(all_sessions) == 2  # the settled one + the freshly-started one
    assert len(bg.tasks) == 1  # a new graph run WAS queued


async def test_kr_start_dedup_falls_back_to_sm_when_legacy_dict_misses(sm, kr_sessions):
    """Post-restart shape: kr_stock_sessions (plain in-process dict) is wiped,
    but SessionManager reloaded/reconciled the session as still
    AWAITING_APPROVAL from SQLite. The dedup guard must still catch it."""
    existing_id = "kr-restart-active-1"
    await _seed_kr_sm_session(sm, existing_id, status=SessionStatus.AWAITING_APPROVAL)
    assert existing_id not in kr_sessions

    found = await find_active_kr_session("005930")

    assert found is not None
    assert found["session_id"] == existing_id


async def test_kr_start_ticker_isolation_different_stk_cd_not_blocked(
    sm, kr_sessions, fake_kiwoom
):
    """An active session for one stk_cd must not block a different stk_cd."""
    existing_id = "kr-other-ticker-1"
    record = _seed_kr_session(kr_sessions, existing_id, status="running")
    record["stk_cd"] = "000660"
    record["state"]["stk_cd"] = "000660"

    bg = BackgroundTasks()
    response = await start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg)

    assert response.duplicate is False
    assert response.session_id != existing_id
    assert len(bg.tasks) == 1


# -------------------------------------------
# KR: P4-T1-review TOCTOU fix — the check-then-record window itself
# -------------------------------------------
#
# The tests above all seed the "existing session" synchronously before
# calling start_kr_stock_analysis, so they never exercise the actual race:
# find_active_kr_session (~line 68) returning None for BOTH of two
# near-simultaneous same-stk_cd requests because neither had recorded a
# session yet, with the awaited kiwoom name lookup (get_shared_kiwoom_client_
# async + client.get_stock_info) sitting in the gap. These tests drive that
# window directly with a controllable asyncio.Event.


async def test_kr_start_concurrent_same_ticker_only_one_session_created(
    sm, kr_sessions, monkeypatch
):
    """Two near-simultaneous starts for the SAME stk_cd, with NO prior
    session: task A is parked mid-lookup (blocked inside `get_stock_info` on
    `gate`) — by the time it parks there, `sm.create_session_if_no_active`
    must already have reserved A's session in the SessionManager (P2-3: the
    atomic reservation happens entirely BEFORE any kiwoom await, replacing
    the old synchronous-B-placeholder-before-awaits ordering trick). Task
    B's start, arriving while A is still parked, must then see that
    reservation and dedup onto it instead of minting a second session + a
    second graph run."""
    gate = asyncio.Event()

    class _BlockingClient:
        async def get_stock_info(self, stk_cd):
            await gate.wait()
            return _FakeStockInfo()

        async def get_account_balance(self):
            return None  # unused here; exercised by test_analysis_position_exists.py

    async def _fake_client():
        return _BlockingClient()

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.get_shared_kiwoom_client_async", _fake_client
    )

    bg_a = BackgroundTasks()
    task_a = asyncio.create_task(
        start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg_a)
    )

    # Let task A run up to (and park inside) the gated get_stock_info call —
    # by construction of the fix this is AFTER the atomic sm reservation and
    # BEFORE the kiwoom name lookup resolves.
    for _ in range(50):
        await asyncio.sleep(0)
        if sm._sessions:
            break
    assert len(sm._sessions) == 1, "A's sm reservation must already be recorded"
    existing_id = next(iter(sm._sessions))
    assert sm._sessions[existing_id].status == SessionStatus.RUNNING
    assert kr_sessions == {}, "P2-3: the legacy dict is never written"

    # Task B "arrives" while A is still parked — same stk_cd, no gating on
    # its own client lookup needed since it must dedup before reaching it.
    bg_b = BackgroundTasks()
    response_b = await start_kr_stock_analysis(
        KRStockAnalysisRequest(stk_cd="005930"), bg_b
    )

    assert response_b.duplicate is True
    assert response_b.session_id == existing_id
    assert bg_b.tasks == []  # no second graph run queued for B
    assert len(sm._sessions) == 1  # still exactly one session record

    # Release A and let it finish.
    gate.set()
    response_a = await task_a

    assert response_a.duplicate is False
    assert response_a.session_id == existing_id
    assert len(bg_a.tasks) == 1  # exactly one graph run total, from A
    assert len(sm._sessions) == 1  # B never created a second entry
    assert sm._sessions[existing_id].stk_nm == "삼성전자"  # finalized after the lookup
    assert kr_sessions == {}


async def test_kr_start_cleans_up_placeholder_on_kiwoom_client_failure(
    sm, kr_sessions, monkeypatch
):
    """If resolving the kiwoom client itself blows up (distinct from the
    already-guarded, best-effort inner get_stock_info/get_account_balance
    calls), the just-reserved sm session must be removed (P2-3:
    `session_manager.remove_session`). Otherwise a stranded "running" session
    would permanently dedup-block all future analysis of this ticker."""

    async def _boom_client():
        raise RuntimeError("kiwoom client unavailable")

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.get_shared_kiwoom_client_async", _boom_client
    )

    with pytest.raises(RuntimeError):
        await start_kr_stock_analysis(
            KRStockAnalysisRequest(stk_cd="005930"), BackgroundTasks()
        )

    assert len(sm._sessions) == 0  # no stranded reservation left behind
    assert kr_sessions == {}

    # A subsequent analysis for the SAME ticker must not be blocked by
    # anything left over from the failed attempt.
    async def _fake_client():
        return _FakeKiwoomClient()

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.get_shared_kiwoom_client_async", _fake_client
    )

    bg = BackgroundTasks()
    response = await start_kr_stock_analysis(KRStockAnalysisRequest(stk_cd="005930"), bg)

    assert response.duplicate is False
    assert len(bg.tasks) == 1
    assert len(sm._sessions) == 1
    assert kr_sessions == {}


# -------------------------------------------
# Coin: same guarantees
# -------------------------------------------


@pytest.mark.parametrize("blocking_status", ["running", "awaiting_approval"])
async def test_coin_start_dedup_returns_existing_session(
    sm, coin_sessions_fixture, blocking_status
):
    existing_id = "coin-existing-1"
    _seed_coin_session(coin_sessions_fixture, existing_id, status=blocking_status)
    await _seed_coin_sm_session(
        sm,
        existing_id,
        status=SessionStatus.RUNNING
        if blocking_status == "running"
        else SessionStatus.AWAITING_APPROVAL,
    )

    bg = BackgroundTasks()
    response = await start_coin_analysis(CoinAnalysisRequest(market="KRW-BTC"), bg)

    assert response.session_id == existing_id
    assert response.duplicate is True
    assert response.status == blocking_status
    assert len(coin_sessions_fixture) == 1
    assert bg.tasks == []


@pytest.mark.parametrize("settled_status", ["completed", "error", "cancelled"])
async def test_coin_start_allows_new_analysis_after_settled_session(
    sm, coin_sessions_fixture, settled_status
):
    prior_id = "coin-settled-1"
    _seed_coin_session(coin_sessions_fixture, prior_id, status=settled_status)
    await _seed_coin_sm_session(sm, prior_id, status=SessionStatus.RUNNING)
    await sm.update_status(
        prior_id,
        {
            "completed": SessionStatus.COMPLETED,
            "error": SessionStatus.ERROR,
            "cancelled": SessionStatus.CANCELLED,
        }[settled_status],
    )

    bg = BackgroundTasks()
    response = await start_coin_analysis(CoinAnalysisRequest(market="KRW-BTC"), bg)

    assert response.session_id != prior_id
    assert response.duplicate is False
    assert len(coin_sessions_fixture) == 2
    assert len(bg.tasks) == 1


async def test_coin_start_dedup_falls_back_to_sm_when_legacy_dict_misses(
    sm, coin_sessions_fixture
):
    existing_id = "coin-restart-active-1"
    await _seed_coin_sm_session(sm, existing_id, status=SessionStatus.AWAITING_APPROVAL)
    assert existing_id not in coin_sessions_fixture

    found = await find_active_coin_session("KRW-BTC")

    assert found is not None
    assert found["session_id"] == existing_id


async def test_coin_start_ticker_isolation_different_market_not_blocked(
    sm, coin_sessions_fixture
):
    existing_id = "coin-other-market-1"
    record = _seed_coin_session(coin_sessions_fixture, existing_id, status="running")
    record["market"] = "KRW-ETH"
    record["state"]["market"] = "KRW-ETH"

    bg = BackgroundTasks()
    response = await start_coin_analysis(CoinAnalysisRequest(market="KRW-BTC"), bg)

    assert response.duplicate is False
    assert response.session_id != existing_id
    assert len(bg.tasks) == 1
