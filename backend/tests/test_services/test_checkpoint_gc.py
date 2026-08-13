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

리뷰 픽스(락 밖 발화): 4사이트 전부 원래 `async with self._lock:` **안**에서
훅을 발화했다 -- SM 락은 앱 전역 SSOT 읽기/쓰기를 직렬화하는데, storage.db
DELETE가 라이브 그래프 체크포인트 쓰기와 SQLite busy-timeout 경합을 일으키면
그 대기 시간 동안 SM 전체가 동결될 위험이 있었다. 지금은 모두 락 해제 후
발화한다(세션은 이미 terminal/removed라 락 밖 발화에 레이스가 없다).
`reconcile_stranded_sessions`는 새 `fire_hooks` 파라미터(기본 True)로 이
경로를 지원한다: 직접 호출자(테스트 등, 락 미보유)는 기존과 동일하게 즉시
발화하고, `initialize()`는 자신이 락을 보유한 채로 reconcile을 호출하므로
`fire_hooks=False`로 억제한 뒤 락 해제 후 `ReconcileReport.errored`/
`.cancelled`를 직접 순회해 발화한다.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

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
    """Records delete_checkpoints(session_id) calls; can be told to raise.

    Also records whether `lock` (if given) was held at call time. This is
    what actually distinguishes the P5-1 review fix (fire the GC hook only
    AFTER releasing SessionManager._lock) from the pre-fix behavior (fired
    from inside the lock) -- both produce the identical final `calls` list
    either way, so a plain "was it called" assertion can't tell them apart;
    only observing lock state at the moment of the call can.
    """

    def __init__(self, fail: bool = False, lock: Optional[asyncio.Lock] = None):
        self.calls: list[str] = []
        self.fail = fail
        self.lock = lock
        self.locked_during_call: list[bool] = []

    async def delete_checkpoints(self, session_id: str) -> bool:
        if self.lock is not None:
            self.locked_during_call.append(self.lock.locked())
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
    # Review fix: wire the manager's own lock into the fake so
    # delete_checkpoints can record whether it was held at call time (see
    # _FakeStorage's docstring -- this is the only way to actually
    # distinguish the lock-safe fix from the pre-fix in-lock firing).
    fake_storage.lock = manager._lock
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
    # Review fix pin: fired AFTER self._lock was released, never while held.
    assert sm._fake_storage.locked_during_call == [False]


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
    # Direct call, fire_hooks defaults True, no lock held by this caller.
    assert sm._fake_storage.locked_during_call == [False]


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
    assert sm._fake_storage.locked_during_call == [False]


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
    assert sm._fake_storage.locked_during_call == [False]


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
    # Review fix pin: fired AFTER self._lock was released, never while held.
    assert sm._fake_storage.locked_during_call == [False]


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
    # Review fix pin: fired AFTER self._lock was released, never while held.
    assert sm._fake_storage.locked_during_call == [False]


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


async def test_delete_checkpoints_failure_does_not_break_update_status(sm, caplog):
    sm._fake_storage.fail = True
    await sm.create_session("t5", MarketType.KIWOOM, "005930", "삼성전자")
    with caplog.at_level(logging.WARNING, logger="services.session_manager"):
        await sm.update_status("t5", SessionStatus.COMPLETED)  # must not raise

    session = await sm.get_session("t5")
    assert session.status == SessionStatus.COMPLETED
    assert sm._fake_storage.calls == ["t5"]  # attempted; failure swallowed
    assert sm._fake_storage.locked_during_call == [False]
    # Not just "didn't raise" -- the failure must actually be surfaced
    # somewhere (P5-2's sweep is the recovery path, not silence).
    assert "checkpoint_gc_failed" in caplog.text


async def test_delete_checkpoints_failure_does_not_break_remove_session(sm, caplog):
    sm._fake_storage.fail = True
    await sm.create_session("t6", MarketType.KIWOOM, "005930", "삼성전자")
    with caplog.at_level(logging.WARNING, logger="services.session_manager"):
        removed = await sm.remove_session("t6")  # must not raise
    assert removed is True
    assert "checkpoint_gc_failed" in caplog.text


async def test_delete_checkpoints_failure_does_not_break_reconcile(sm, caplog):
    sm._fake_storage.fail = True
    s = _sess("r6", SessionStatus.RUNNING)
    sm._sessions["r6"] = s
    await sm._save_session(s)
    with caplog.at_level(logging.WARNING, logger="services.session_manager"):
        rep = await sm.reconcile_stranded_sessions(now=NOW)  # must not raise
    assert "r6" in rep.errored
    assert sm._sessions["r6"].status == SessionStatus.ERROR
    assert "checkpoint_gc_failed" in caplog.text


# -------------------------------------------
# 5) Idempotency: duplicate terminal calls for the same session are harmless
# -------------------------------------------


async def test_duplicate_terminal_calls_are_harmless(sm):
    await sm.create_session("t7", MarketType.KIWOOM, "005930", "삼성전자")
    await sm.update_status("t7", SessionStatus.COMPLETED)
    await sm.update_status("t7", SessionStatus.COMPLETED)  # re-fire, no error

    assert sm._fake_storage.calls == ["t7", "t7"]
    assert sm._fake_storage.locked_during_call == [False, False]
    session = await sm.get_session("t7")
    assert session.status == SessionStatus.COMPLETED


# -------------------------------------------
# 6) Review fix: hooks fire OUTSIDE self._lock (never while it's held)
# -------------------------------------------


async def test_reconcile_fire_hooks_false_suppresses_immediate_gc(sm):
    """`fire_hooks=False` is what initialize() passes because IT calls
    reconcile while holding self._lock -- this pins that the flag actually
    suppresses the per-branch firing (the other half of the contract,
    initialize() firing them itself after releasing the lock, is pinned by
    test_initialize_fires_gc_for_reconciled_terminal_sessions below)."""
    s = _sess("r7", SessionStatus.RUNNING)
    sm._sessions["r7"] = s
    await sm._save_session(s)
    rep = await sm.reconcile_stranded_sessions(now=NOW, fire_hooks=False)
    assert "r7" in rep.errored
    assert sm._fake_storage.calls == []


async def test_initialize_fires_gc_for_reconciled_terminal_sessions(tmp_path, monkeypatch):
    """End-to-end pin for the lock-safety review fix: SessionManager.
    initialize() must fire the checkpoint-GC hook for sessions that
    reconcile_stranded_sessions flips to a terminal status during startup
    -- AFTER releasing self._lock, never from inside reconcile itself
    (which initialize() calls with fire_hooks=False for exactly this
    reason). A dedicated tmp DB/manager pair is used here (not the `sm`
    fixture) because the behavior under test IS initialize()'s own
    reconcile pass, which the `sm` fixture already consumed on an empty
    DB during its own setup.
    """
    db_path = str(tmp_path / "init_gc.db")
    fake_storage = _FakeStorage()

    async def _fake_get_storage_service():
        return fake_storage

    monkeypatch.setattr("services.session_manager.DB_PATH", db_path)
    monkeypatch.setattr(
        "services.session_manager.get_storage_service", _fake_get_storage_service
    )

    # Phase 1: seed a RUNNING session (no awaiting/proposal -- reconcile's
    # "no live task behind it" branch) directly into SQLite, simulating
    # what a killed process would have left behind.
    seed_mgr = SessionManager()
    await seed_mgr.initialize()  # creates schema; no sessions yet -> no GC
    stranded = _sess("init-r1", SessionStatus.RUNNING)
    seed_mgr._sessions[stranded.session_id] = stranded
    await seed_mgr._save_session(stranded)
    fake_storage.calls.clear()  # ignore anything from seed_mgr's own init

    # Phase 2: a fresh manager loading that same DB simulates the restart.
    # Its initialize() runs reconcile_stranded_sessions (RUNNING -> ERROR,
    # fire_hooks=False) then must fire the GC hook for it itself, once
    # self._lock is released.
    restarted_mgr = SessionManager()
    # Wire the lock BEFORE initialize() runs -- this is the crux of the
    # whole review fix: pre-fix, this call recorded locked_during_call ==
    # [True] (fired from inside reconcile, which ran under initialize()'s
    # held lock); post-fix it must be [False].
    fake_storage.lock = restarted_mgr._lock
    await restarted_mgr.initialize()

    assert restarted_mgr._sessions["init-r1"].status == SessionStatus.ERROR
    assert fake_storage.calls == ["init-r1"]
    assert fake_storage.locked_during_call == [False]
