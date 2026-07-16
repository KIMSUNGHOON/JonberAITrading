"""P5-1: terminal 전이 시 체크포인트 삭제 훅.

Session SSOT 통합 Phase P5(retention/GC)의 첫 태스크. LangGraph 체크포인트
(storage.db의 `checkpoints` 테이블)는 그래프 resume의 실행 진실인데, 이를
지우는 호출자가 하나도 없어 무한정 자란다
(`storage_service.delete_checkpoints(session_id)`는 정의만 있었다).

이 파일은 `SessionManager._on_terminal_transition`이 spec §P5가 요구하는
모든 terminal 전이 사이트에서 정확히 호출되는지 -- 그리고 awaiting/running
전이·유지에는 오발하지 않는지 -- 검증한다:
  - update_status가 COMPLETED/ERROR/CANCELLED로 전이할 때
  - reconcile_stranded_sessions의 직접 대입 분기(analysis ERROR/CANCELLED
    플립 + P4-5의 discussion CANCELLED 분기) -- AWAITING_APPROVAL로 플립되는
    분기(부활 가능, 체크포인트 필요)와 무변화 kept 분기는 제외.
  - remove_session / cleanup_expired_sessions (행 삭제 시)

storage_service는 실제 SQLite를 건드리지 않는 페이크로 교체한다 -- 여기서는
SM의 호출 계약만 검증하면 충분하다(delete_checkpoints 자체의 SQL 정확성은
storage_service 자신의 테스트 몫).
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

from services.session_manager import (
    AnalysisSession,
    KIND_DISCUSSION,
    MarketType,
    SessionManager,
    SessionStatus,
)

TEST_DB_PATH = "data/test_checkpoint_gc.db"
NOW = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)


class _FakeStorage:
    """Records delete_checkpoints(session_id) calls; can be told to raise."""

    def __init__(self, fail: bool = False):
        self.calls: list[str] = []
        self.fail = fail

    async def delete_checkpoints(self, session_id: str) -> bool:
        self.calls.append(session_id)
        if self.fail:
            raise RuntimeError("boom: simulated delete_checkpoints failure")
        return True


@pytest.fixture
def clean_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture
async def sm(clean_db, monkeypatch):
    """Fresh SessionManager on an isolated tmp DB, with a fake storage
    service standing in for get_storage_service.

    services/session_manager.py does `from services.storage_service import
    get_storage_service` at module scope, so the name lives in
    services.session_manager's own namespace -- patching it THERE (not on
    services.storage_service) is what _on_terminal_transition actually
    resolves at call time.
    """
    monkeypatch.setattr("services.session_manager.DB_PATH", TEST_DB_PATH)
    fake_storage = _FakeStorage()

    async def _fake_get_storage_service():
        return fake_storage

    monkeypatch.setattr(
        "services.session_manager.get_storage_service", _fake_get_storage_service
    )

    manager = SessionManager()
    await manager.initialize()
    manager._fake_storage = fake_storage  # test-only handle
    yield manager

    # Same defensive flush-task cleanup as the other SM test files -- a
    # debounced flush left pending past teardown leaks a task into a
    # closing event loop.
    task = manager._flush_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    manager._sessions.clear()


def _sess(sid, status, kind="analysis", created=NOW, state=None):
    return AnalysisSession(
        session_id=sid,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        status=status,
        state=state or {},
        created_at=created,
        stk_cd="005930",
        stk_nm="삼성전자",
        kind=kind,
    )


# -------------------------------------------
# 1) update_status
# -------------------------------------------


@pytest.mark.parametrize(
    "status", [SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.CANCELLED]
)
async def test_update_status_terminal_calls_delete_checkpoints(sm, status):
    await sm.create_session("t1", MarketType.KIWOOM, "005930", "삼성전자")
    await sm.update_status("t1", status)
    assert sm._fake_storage.calls == ["t1"]


@pytest.mark.parametrize(
    "status", [SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL]
)
async def test_update_status_non_terminal_does_not_call(sm, status):
    await sm.create_session("t2", MarketType.KIWOOM, "005930", "삼성전자")
    await sm.update_status("t2", status)
    assert sm._fake_storage.calls == []


# -------------------------------------------
# 2) reconcile_stranded_sessions direct-assignment branches
# -------------------------------------------


async def test_reconcile_running_no_proposal_errors_and_gcs(sm):
    """RUNNING with no awaiting/proposal -> ERROR (no live task could ever
    move it forward again) -- must GC."""
    s = _sess("r1", SessionStatus.RUNNING)
    sm._sessions["r1"] = s
    await sm._save_session(s)
    rep = await sm.reconcile_stranded_sessions(now=NOW)
    assert "r1" in rep.errored
    assert sm._fake_storage.calls == ["r1"]


async def test_reconcile_awaiting_cancelled_appr_flip_gcs(sm):
    """AWAITING_APPROVAL with approval_status == 'cancelled' -> CANCELLED
    (shape correction) -- must GC."""
    s = _sess(
        "r2", SessionStatus.AWAITING_APPROVAL, state={"approval_status": "cancelled"}
    )
    sm._sessions["r2"] = s
    await sm._save_session(s)
    rep = await sm.reconcile_stranded_sessions(now=NOW)
    assert "r2" in rep.cancelled
    assert sm._fake_storage.calls == ["r2"]


async def test_reconcile_discussion_cancelled_gcs(sm):
    """P4-5's discussion-kind branch: any non-terminal row -> CANCELLED
    unconditionally -- must GC too (delete_checkpoints is a harmless 0-row
    no-op for discussion sessions, which never had checkpoint rows)."""
    s = _sess("r3", SessionStatus.RUNNING, kind=KIND_DISCUSSION)
    sm._sessions["r3"] = s
    await sm._save_session(s)
    rep = await sm.reconcile_stranded_sessions(now=NOW)
    assert "r3" in rep.cancelled
    assert sm._fake_storage.calls == ["r3"]


async def test_reconcile_flip_to_awaiting_does_not_gc(sm):
    """The AWAITING_APPROVAL flip branch (a graph parked at/near the HITL
    interrupt) must NOT fire the GC hook -- a resume still needs its
    checkpoint. This is the mis-fire guard for the whole task."""
    s = _sess(
        "r4",
        SessionStatus.RUNNING,
        state={
            "awaiting_approval": True,
            "trade_proposal": {"action": "HOLD", "created_at": NOW.isoformat()},
        },
    )
    sm._sessions["r4"] = s
    await sm._save_session(s)
    rep = await sm.reconcile_stranded_sessions(now=NOW)
    assert "r4" in rep.flipped
    assert sm._fake_storage.calls == []


async def test_reconcile_kept_session_does_not_gc(sm):
    """A normal, still-pending AWAITING_APPROVAL session falls through to
    'kept' -- no status change, no GC."""
    s = _sess(
        "r5",
        SessionStatus.AWAITING_APPROVAL,
        state={
            "awaiting_approval": True,
            "trade_proposal": {"action": "WATCH", "created_at": NOW.isoformat()},
        },
    )
    sm._sessions["r5"] = s
    await sm._save_session(s)
    rep = await sm.reconcile_stranded_sessions(now=NOW)
    assert "r5" in rep.kept
    assert sm._fake_storage.calls == []


# -------------------------------------------
# 3) remove_session / cleanup_expired_sessions
# -------------------------------------------


async def test_remove_session_gcs(sm):
    await sm.create_session("t3", MarketType.KIWOOM, "005930", "삼성전자")
    removed = await sm.remove_session("t3")
    assert removed is True
    assert sm._fake_storage.calls == ["t3"]


async def test_cleanup_expired_sessions_gcs(sm):
    # cleanup_expired_sessions reads real wall-clock time internally (not
    # injectable like reconcile's `now`), so the TTL boundary must be
    # relative to actual now, not the fixed NOW constant used elsewhere.
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    s = _sess("t4", SessionStatus.COMPLETED, created=old)
    sm._sessions["t4"] = s
    await sm._save_session(s)

    removed_count = await sm.cleanup_expired_sessions()
    assert removed_count == 1
    assert sm._fake_storage.calls == ["t4"]


async def test_cleanup_expired_sessions_no_expired_does_not_gc(sm):
    await sm.create_session("t4b", MarketType.KIWOOM, "005930", "삼성전자")
    await sm.update_status("t4b", SessionStatus.COMPLETED)
    sm._fake_storage.calls.clear()  # drop the update_status call from setup

    removed_count = await sm.cleanup_expired_sessions()
    assert removed_count == 0
    assert sm._fake_storage.calls == []


# -------------------------------------------
# 4) Best-effort: delete_checkpoints failure never breaks the transition
# -------------------------------------------


async def test_delete_checkpoints_failure_does_not_break_update_status(sm):
    sm._fake_storage.fail = True
    await sm.create_session("t5", MarketType.KIWOOM, "005930", "삼성전자")
    await sm.update_status("t5", SessionStatus.COMPLETED)  # must not raise

    session = await sm.get_session("t5")
    assert session.status == SessionStatus.COMPLETED
    assert sm._fake_storage.calls == ["t5"]  # attempted; failure swallowed


async def test_delete_checkpoints_failure_does_not_break_remove_session(sm):
    sm._fake_storage.fail = True
    await sm.create_session("t6", MarketType.KIWOOM, "005930", "삼성전자")
    removed = await sm.remove_session("t6")  # must not raise
    assert removed is True


async def test_delete_checkpoints_failure_does_not_break_reconcile(sm):
    sm._fake_storage.fail = True
    s = _sess("r6", SessionStatus.RUNNING)
    sm._sessions["r6"] = s
    await sm._save_session(s)
    rep = await sm.reconcile_stranded_sessions(now=NOW)  # must not raise
    assert "r6" in rep.errored
    assert sm._sessions["r6"].status == SessionStatus.ERROR


# -------------------------------------------
# 5) Idempotency: duplicate terminal calls for the same session are harmless
# -------------------------------------------


async def test_duplicate_terminal_calls_are_harmless(sm):
    await sm.create_session("t7", MarketType.KIWOOM, "005930", "삼성전자")
    await sm.update_status("t7", SessionStatus.COMPLETED)
    await sm.update_status("t7", SessionStatus.COMPLETED)  # re-fire, no error

    assert sm._fake_storage.calls == ["t7", "t7"]
    session = await sm.get_session("t7")
    assert session.status == SessionStatus.COMPLETED
