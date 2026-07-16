"""P2-1: SM 원자 예약 API + fail-loud 갱신 + flush 디바운스.

Session SSOT 통합 Phase P2(쓰기 통일)의 첫 태스크. 이 파일은
`services.session_manager.SessionManager`에 추가된 3가지 계약을 검증한다:

1. `create_session_if_no_active` — 동시 호출에도 같은 (market_type, ticker)에
   대해 정확히 1건만 생성되는 원자적 예약.
2. fail-loud 갱신 — `update_state`/`update_status`가 추적되지 않는
   session_id에 대해 조용히 no-op 하는 대신 KeyError를 raise.
3. flush 디바운스 — `_CRITICAL_STATE_KEYS`와 교집합 없는 state_update는
   즉시 SQLite에 쓰지 않고 ~1s 후 배치로 flush(단, pub/sub 알림은 항상 즉시).

픽스처는 `tests/test_services/test_session_manager.py`의 tmp DB 패턴을
새 SessionManager 인스턴스로 복제한다(싱글턴 미오염).
"""

import asyncio
import os

import pytest

from services.session_manager import (
    SessionManager,
    MarketType,
    SessionStatus,
)

TEST_DB_PATH = "data/test_sessions_p2.db"


@pytest.fixture
def clean_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


async def _fake_get_storage_service():
    """P5-1: stand-in for services.storage_service.get_storage_service.

    update_status/remove_session/cleanup_expired_sessions now fire a
    checkpoint-GC hook that calls the REAL storage_service singleton unless
    patched -- that singleton points at the production
    backend/data/storage.db by default, which a live dev server may have
    open concurrently. Every fixture in this file patches it out.
    """
    class _NoopStorage:
        async def delete_checkpoints(self, session_id):
            return True
    return _NoopStorage()


@pytest.fixture
async def sm(clean_db, monkeypatch):
    """Fresh SessionManager on an isolated tmp DB — no singleton involved."""
    monkeypatch.setattr("services.session_manager.DB_PATH", TEST_DB_PATH)
    monkeypatch.setattr(
        "services.session_manager.get_storage_service", _fake_get_storage_service
    )
    manager = SessionManager()
    await manager.initialize()
    yield manager
    # Debounced flush tasks are allowed to be lost on process exit (by
    # design — see update_state's docstring), but leaving one pending past
    # the end of a test needlessly leaks a task into a closing event loop.
    # Cancel it defensively so teardown is clean regardless of which test
    # left one armed.
    task = manager._flush_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    manager._sessions.clear()


# -------------------------------------------
# 1) Atomic reservation
# -------------------------------------------


@pytest.mark.asyncio
async def test_atomic_reservation_single_winner(sm):
    results = await asyncio.gather(*[
        sm.create_session_if_no_active(f"p21-{i}", MarketType.KIWOOM, "005930", "삼성전자")
        for i in range(2)
    ])
    created = [r[0] for r in results if r[0] is not None]
    existing = [r[1] for r in results if r[1] is not None]
    assert len(created) == 1 and len(existing) == 1
    assert existing[0].session_id == created[0].session_id


@pytest.mark.asyncio
async def test_reservation_creates_when_no_active_session(sm):
    created, existing = await sm.create_session_if_no_active(
        "p21-solo", MarketType.KIWOOM, "005930", "삼성전자"
    )
    assert existing is None
    assert created is not None
    assert created.session_id == "p21-solo"
    assert created.status == SessionStatus.RUNNING

    # Actually persisted, not just held in memory.
    fetched = await sm.get_session("p21-solo")
    assert fetched is not None
    assert fetched.ticker == "005930"


@pytest.mark.asyncio
async def test_reservation_ignores_completed_sessions_for_same_ticker(sm):
    """A COMPLETED/ERROR/CANCELLED session for the same ticker must not
    block a new reservation — only RUNNING/AWAITING_APPROVAL are 'active'."""
    await sm.create_session(
        session_id="p21-done",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
    )
    await sm.update_status("p21-done", SessionStatus.COMPLETED)

    created, existing = await sm.create_session_if_no_active(
        "p21-new", MarketType.KIWOOM, "005930", "삼성전자"
    )
    assert existing is None
    assert created is not None
    assert created.session_id == "p21-new"


@pytest.mark.asyncio
async def test_reservation_different_market_type_does_not_collide(sm):
    """Same ticker string, different market_type -- not a collision."""
    created1, existing1 = await sm.create_session_if_no_active(
        "p21-kiwoom", MarketType.KIWOOM, "AAA", "종목A"
    )
    created2, existing2 = await sm.create_session_if_no_active(
        "p21-coin", MarketType.COIN, "AAA", "코인A"
    )
    assert existing1 is None and existing2 is None
    assert created1 is not None and created2 is not None


# -------------------------------------------
# 2) fail-loud update_state / update_status
# -------------------------------------------


@pytest.mark.asyncio
async def test_update_state_raises_on_unknown_session(sm):
    with pytest.raises(KeyError):
        await sm.update_state("no-such-session", {"x": 1})


@pytest.mark.asyncio
async def test_update_status_raises_on_unknown_session(sm):
    with pytest.raises(KeyError):
        await sm.update_status("no-such-session", SessionStatus.COMPLETED)


# -------------------------------------------
# 3) flush debounce
# -------------------------------------------


async def _row_status_and_state(db_path: str, session_id: str):
    """Read the raw SQLite row directly (bypassing in-memory _sessions) so
    the assertions genuinely observe what has been persisted so far."""
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT status, state_json FROM analysis_sessions WHERE session_id = ?",
            (session_id,),
        ) as cursor:
            return await cursor.fetchone()


@pytest.mark.asyncio
async def test_reasoning_only_update_is_debounced_then_flushed(sm):
    await sm.create_session(
        session_id="p21-debounce",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
    )
    # The initial create_session save is synchronous, so wipe the row to
    # isolate what THIS non-critical update does to persistence.
    import aiosqlite

    async with aiosqlite.connect(TEST_DB_PATH) as db:
        await db.execute(
            "DELETE FROM analysis_sessions WHERE session_id = ?", ("p21-debounce",)
        )
        await db.commit()

    await sm.update_state("p21-debounce", {"reasoning_log": ["a"]})
    # Second non-critical update immediately after -- should coalesce onto
    # the same pending flush task rather than scheduling a second one.
    await sm.update_state("p21-debounce", {"reasoning_log": ["a", "b"]})

    row = await _row_status_and_state(TEST_DB_PATH, "p21-debounce")
    assert row is None  # not written yet -- debounced

    await asyncio.sleep(1.2)

    row = await _row_status_and_state(TEST_DB_PATH, "p21-debounce")
    assert row is not None
    assert "b" in row["state_json"]


@pytest.mark.asyncio
async def test_critical_key_update_flushes_immediately(sm):
    await sm.create_session(
        session_id="p21-critical",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
    )
    await sm.update_state(
        "p21-critical",
        {"trade_proposal": {"action": "BUY"}, "awaiting_approval": True},
    )

    row = await _row_status_and_state(TEST_DB_PATH, "p21-critical")
    assert row is not None
    assert "BUY" in row["state_json"]


@pytest.mark.asyncio
async def test_update_status_flushes_immediately(sm):
    await sm.create_session(
        session_id="p21-status",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
    )
    await sm.update_status("p21-status", SessionStatus.AWAITING_APPROVAL)

    row = await _row_status_and_state(TEST_DB_PATH, "p21-status")
    assert row is not None
    assert row["status"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_notify_is_immediate_regardless_of_debounce(sm):
    """A non-critical (debounced-for-SQLite) update must still wake WS
    subscribers immediately -- the debounce applies to the SQLite write
    only, never to pub/sub."""
    await sm.create_session(
        session_id="p21-notify",
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
    )
    queue = await sm.subscribe("p21-notify")

    await sm.update_state("p21-notify", {"reasoning_log": ["a"]})

    message = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert message["type"] == "state_update"
    assert message["reasoning_delta"] == ["a"]
