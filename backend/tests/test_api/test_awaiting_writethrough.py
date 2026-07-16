"""P1-5: awaiting-critical 전이는 write-through — SM 기록 실패 시 fail-closed ERROR.

세션 SSOT 통합 P1의 마지막 태스크. P1-1~P1-4로 읽기가 SessionManager(SM)
단독이 된 지금, awaiting_approval 전이가 SM에 기록되지 못하면 그 세션은
어느 read surface(상태 조회/승인 대기 목록/WebSocket)에서도 보이지 않는
"invisible interrupt"(파킹된 그래프)가 된다. 이 불변식을 지키는 것이
`_finalize_awaiting_transition` 헬퍼(kr_stocks/coin 공용 패턴)와
`services.session_manager.commit_session_status`/`commit_session_state`
(실패 시 raise하는 strict 변형, best-effort `mirror_*`와 대비)다.

격리 원칙(과제 지시): DB 격리·lru_cache 무력화 없이, SM 싱글턴을 절대
건드리지 않도록 대상 모듈이 import한 함수 이름만 monkeypatch로 페이크한다
(commit_session_status/commit_session_state/maybe_schedule_auto_approve/
mirror_session_status). 실패 경로가 best-effort로 mirror_session_status를
한 번 더 부르는 지점까지 전부 페이크하므로 실제 SessionManager
(get_session_manager()) 는 이 테스트에서 한 번도 호출되지 않는다.
"""
import pytest
from fastapi import HTTPException
from types import SimpleNamespace

from services.session_manager import AnalysisSession, MarketType, SessionStatus


# -------------------------------------------
# KR (kiwoom) — brief 원문 테스트 2건
# -------------------------------------------


@pytest.mark.asyncio
async def test_awaiting_transition_failclosed_on_sm_failure(monkeypatch):
    """SM awaiting 기록이 계속 실패하면 세션은 error 가 되고 auto-approve 는 안 뜬다.

    P2-3: `_finalize_awaiting_transition` no longer takes a legacy-dict
    `session` argument -- the KR producer writes to the SessionManager only,
    so the helper re-fetches the SM row itself. A minimal fake SessionManager
    (only `get_session`/`update_state`) stands in for the real singleton,
    following this file's isolation principle (only names the target module
    imported are faked).
    """
    from app.api.routes.kr_stocks import analysis as kr_analysis

    calls = {"n": 0}

    async def failing_commit(session_id, status, **kw):
        calls["n"] += 1
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(kr_analysis, "commit_session_status", failing_commit)

    scheduled = []

    async def fake_schedule(session_id, market, session):
        scheduled.append(session_id)

    monkeypatch.setattr(kr_analysis, "maybe_schedule_auto_approve", fake_schedule)

    # The fail-closed branch also best-effort mirrors ERROR to the sm --
    # faked too so this test never touches the real SessionManager singleton.
    mirrored = []

    async def fake_mirror_status(session_id, status, error=None):
        mirrored.append((session_id, status, error))

    monkeypatch.setattr(kr_analysis, "mirror_session_status", fake_mirror_status)

    fake_sm_session = SimpleNamespace(
        state={"awaiting_approval": True,
               "trade_proposal": {"action": "BUY"},
               "reasoning_log": []},
    )
    state_updates_seen = []

    class _FakeSM:
        async def get_session(self, session_id):
            return fake_sm_session

        async def update_state(self, session_id, updates, **kw):
            state_updates_seen.append(updates)
            fake_sm_session.state.update(updates)

    async def fake_get_session_manager():
        return _FakeSM()

    monkeypatch.setattr(kr_analysis, "get_session_manager", fake_get_session_manager)

    await kr_analysis._finalize_awaiting_transition("wt-1")

    assert calls["n"] == 2                      # 1회 재시도 포함 2회 시도
    assert scheduled == []                       # 보이지 않는 자동승인 금지
    # The reasoning-log/awaiting_approval cleanup landed directly on the sm.
    assert fake_sm_session.state["awaiting_approval"] is False
    assert "안전 종료" in fake_sm_session.state["reasoning_log"][-1]
    # Best-effort ERROR mirror to the sm still attempted exactly once.
    assert len(mirrored) == 1
    assert mirrored[0][0] == "wt-1"
    assert mirrored[0][1] == SessionStatus.ERROR


@pytest.mark.asyncio
async def test_awaiting_transition_success_path(monkeypatch):
    from app.api.routes.kr_stocks import analysis as kr_analysis

    committed = []

    async def ok_commit(session_id, status, **kw):
        committed.append((session_id, status))

    monkeypatch.setattr(kr_analysis, "commit_session_status", ok_commit)
    scheduled = []

    async def fake_schedule(session_id, market, session):
        scheduled.append((session_id, market, session))

    monkeypatch.setattr(kr_analysis, "maybe_schedule_auto_approve", fake_schedule)

    fake_sm_session = SimpleNamespace(
        session_id="wt-2",
        status="awaiting_approval",
        error=None,
        last_node=None,
        stk_cd="005930",
        stk_nm="삼성전자",
        state={"awaiting_approval": True,
               "trade_proposal": {"action": "BUY"},
               "reasoning_log": []},
    )

    def to_legacy_dict():
        return {
            "session_id": fake_sm_session.session_id,
            "status": fake_sm_session.status,
            "state": fake_sm_session.state,
            "stk_cd": fake_sm_session.stk_cd,
            "stk_nm": fake_sm_session.stk_nm,
        }

    fake_sm_session.to_legacy_dict = to_legacy_dict

    class _FakeSM:
        async def get_session(self, session_id):
            return fake_sm_session

    async def fake_get_session_manager():
        return _FakeSM()

    monkeypatch.setattr(kr_analysis, "get_session_manager", fake_get_session_manager)

    await kr_analysis._finalize_awaiting_transition("wt-2")

    assert scheduled and scheduled[0][0] == "wt-2"
    assert scheduled[0][1] == "kiwoom"
    assert scheduled[0][2]["state"] is fake_sm_session.state
    assert committed and committed[0][0] == "wt-2"
    assert committed[0][1] == SessionStatus.AWAITING_APPROVAL


# -------------------------------------------
# coin — 동형 1건 (fail-closed)
# -------------------------------------------


@pytest.mark.asyncio
async def test_coin_awaiting_transition_failclosed_on_sm_failure(monkeypatch):
    """coin 쪽 _finalize_awaiting_transition 도 KR과 동일하게 1회 재시도 후
    fail-closed: 세션 error, awaiting_approval False, auto-approve 미호출.

    P2-4: `_finalize_awaiting_transition` no longer takes a legacy-dict
    `session` argument -- the coin producer writes to the SessionManager
    only, so the helper re-fetches the SM row itself. A minimal fake
    SessionManager (only `get_session`/`update_state`) stands in for the
    real singleton, following this file's isolation principle (only names
    the target module imported are faked).
    """
    from app.api.routes.coin import analysis as coin_analysis

    calls = {"n": 0}

    async def failing_commit(session_id, status, **kw):
        calls["n"] += 1
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(coin_analysis, "commit_session_status", failing_commit)

    scheduled = []

    async def fake_schedule(session_id, market, session):
        scheduled.append(session_id)

    monkeypatch.setattr(coin_analysis, "maybe_schedule_auto_approve", fake_schedule)

    mirrored = []

    async def fake_mirror_status(session_id, status, error=None):
        mirrored.append((session_id, status, error))

    monkeypatch.setattr(coin_analysis, "mirror_session_status", fake_mirror_status)

    fake_sm_session = SimpleNamespace(
        state={"awaiting_approval": True,
               "trade_proposal": {"action": "BUY"},
               "reasoning_log": []},
    )
    state_updates_seen = []

    class _FakeSM:
        async def get_session(self, session_id):
            return fake_sm_session

        async def update_state(self, session_id, updates, **kw):
            state_updates_seen.append(updates)
            fake_sm_session.state.update(updates)

    async def fake_get_session_manager():
        return _FakeSM()

    monkeypatch.setattr(coin_analysis, "get_session_manager", fake_get_session_manager)

    await coin_analysis._finalize_awaiting_transition("wt-coin-1")

    assert calls["n"] == 2                      # 1회 재시도 포함 2회 시도
    assert scheduled == []                       # 보이지 않는 자동승인 금지
    # The reasoning-log/awaiting_approval cleanup landed directly on the sm.
    assert fake_sm_session.state["awaiting_approval"] is False
    assert "safely terminated" in fake_sm_session.state["reasoning_log"][-1]
    # Best-effort ERROR mirror to the sm still attempted exactly once.
    assert len(mirrored) == 1
    assert mirrored[0][0] == "wt-coin-1"
    assert mirrored[0][1] == SessionStatus.ERROR


# -------------------------------------------
# approval.py — 결정 진입 write-through 503 경로 1건
# -------------------------------------------
#
# P2-5 (session-SSOT): submit_decision now resolves the session, its state
# and its status entirely off the SessionManager (SM) -- there is no legacy
# dict ("B") lookup and no _adopt_session_from_manager fallback, and the old
# "apply decision_updates to local state AFTER the commit succeeds" block is
# gone (state IS sm_session.state, a live reference -- commit_session_state
# is the ONLY writer). The fakes below simulate that write-through contract
# directly: on a successful (fake) commit they mutate the SAME AnalysisSession
# object get_session_manager() hands back, exactly like the real
# SessionManager.update_state/update_status would.


def _wt_sm_session(session_id: str) -> AnalysisSession:
    return AnalysisSession(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        display_name="삼성전자",
        ticker="005930",
        stk_cd="005930",
        stk_nm="삼성전자",
        status=SessionStatus.AWAITING_APPROVAL,
        state={
            "awaiting_approval": True,
            "trade_proposal": {"id": "p1", "action": "BUY"},
            "reasoning_log": [],
        },
    )


@pytest.mark.asyncio
async def test_approval_decision_entry_503_when_sm_commit_fails(monkeypatch):
    """P1-5: 결정 진입 시점의 decision_updates 커밋은 write-through다 -- SM
    커밋이 실패하면 그래프를 재개(=주문 실행 가능)하지 않고 503으로 fail-loud
    해야 한다. 결정이 SM에 반영되지 않은 채 200 을 돌려주는 것은 금지.
    """
    from app.api.routes import approval as approval_module

    session_id = "wt-approval-1"
    sm_session = _wt_sm_session(session_id)

    class _FakeSM:
        async def get_session(self, sid):
            return sm_session if sid == session_id else None

    async def fake_get_session_manager():
        return _FakeSM()

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    async def failing_commit_state(session_id, state_updates, **kw):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(approval_module, "commit_session_state", failing_commit_state)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "approval state could not be persisted — retry"
    # The decision must not have been applied as a silent success: the
    # graph resume (and any order it could place) never ran.
    assert sm_session.status == SessionStatus.AWAITING_APPROVAL
    # P1-5 review fix (Important A) pin, P2-5-adapted: since state IS
    # sm_session.state (no separate local copy to race ahead of a failed
    # commit), state["awaiting_approval"] simply never gets touched here --
    # a retry of the same decision is not wedged behind a false "already
    # decided" flag. See test_approval_decision_entry_retry_succeeds_
    # after_503 below for the full retry-recovers assertion.
    assert sm_session.state["awaiting_approval"] is True


@pytest.mark.asyncio
async def test_approval_decision_entry_retry_succeeds_after_503(monkeypatch):
    """P1-5 review fix (Important A): a 503 from a failed decision-entry
    commit must not wedge the session. Because state IS sm_session.state (a
    live reference committed to only via commit_session_state -- P2-5
    removed the old local-B reapplication block), state["awaiting_approval"]
    stays True across the failed attempt -- so retrying the exact same
    decision on the exact same session lands normally instead of 400ing
    as "Session is not awaiting approval".
    """
    from app.api.routes import approval as approval_module

    session_id = "wt-approval-retry-1"
    sm_session = _wt_sm_session(session_id)

    class _FakeSM:
        async def get_session(self, sid):
            return sm_session if sid == session_id else None

    async def fake_get_session_manager():
        return _FakeSM()

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    calls = {"n": 0}

    async def flaky_commit_state(sid, state_updates, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("sqlite down")
        # P2-5: commit_session_state is the SOLE writer now -- the fake must
        # actually apply the update for the "retry succeeds" assertions
        # below to mean anything (pre-P2-5 this was done by a separate local
        # "B" reapplication block that no longer exists).
        sm_session.state.update(state_updates)

    async def ok_commit_status(sid, new_status, **kw):
        sm_session.status = new_status

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(approval_module, "commit_session_state", flaky_commit_state)
    monkeypatch.setattr(approval_module, "commit_session_status", ok_commit_status)
    monkeypatch.setattr(approval_module, "broadcast_trade_executed", noop)
    monkeypatch.setattr(approval_module, "broadcast_trade_queued", noop)
    monkeypatch.setattr(approval_module, "broadcast_trade_rejected", noop)
    monkeypatch.setattr(approval_module, "broadcast_watch_added", noop)

    async def fake_get_trading_coordinator():
        raise RuntimeError("no coordinator in unit test")

    monkeypatch.setattr(approval_module, "get_trading_coordinator", fake_get_trading_coordinator)

    class _Telegram:
        enabled = False
        is_ready = False

    async def fake_get_telegram_notifier():
        return _Telegram()

    monkeypatch.setattr(approval_module, "get_telegram_notifier", fake_get_telegram_notifier)

    class _FakeGraph:
        async def aupdate_state(self, config, update):
            return None

        def astream(self, _input, _config):
            async def gen():
                return
                yield  # pragma: no cover -- makes this an async generator

            return gen()

    monkeypatch.setattr(approval_module, "get_kr_stock_trading_graph", lambda: _FakeGraph())

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")
    assert exc_info.value.status_code == 503

    # Not wedged: still awaiting, so the exact same decision is retryable.
    assert sm_session.state["awaiting_approval"] is True
    assert sm_session.status == SessionStatus.AWAITING_APPROVAL

    result = await approval_module.submit_decision(session_id, "approved")

    assert result.session_id == session_id
    assert result.decision == "approved"
    assert sm_session.state["awaiting_approval"] is False
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_approval_rejected_rearm_failed_commit_never_schedules(monkeypatch):
    """P1-5 review fix (Important B): if the SM commit for the re-armed
    AWAITING_APPROVAL transition fails, the 60s auto-approve timer must
    NEVER be scheduled against a transition the SM never recorded -- fail
    closed (503), mirroring _finalize_awaiting_transition's own invariant.
    """
    from app.api.routes import approval as approval_module

    session_id = "wt-approval-rearm-1"
    sm_session = _wt_sm_session(session_id)

    class _FakeSM:
        async def get_session(self, sid):
            return sm_session if sid == session_id else None

        async def update_state(self, sid, updates, last_node=None):
            # The resume loop below actually yields one node event (this is
            # the only test in this file whose fake graph does), so the sm
            # local variable's update_state gets a real call -- P2-5 made it
            # the resume loop's sole per-node write.
            if sid != session_id:
                raise KeyError(sid)
            sm_session.state.update(updates)
            if last_node:
                sm_session.last_node = last_node

    async def fake_get_session_manager():
        return _FakeSM()

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    async def commit_state_ok(sid, state_updates, **kw):
        sm_session.state.update(state_updates)

    calls = {"n": 0}

    async def commit_status_fails(sid, new_status, **kw):
        calls["n"] += 1
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(approval_module, "commit_session_state", commit_state_ok)
    monkeypatch.setattr(approval_module, "commit_session_status", commit_status_fails)

    scheduled = []

    async def fake_schedule(sid, market, session):
        scheduled.append(sid)

    monkeypatch.setattr(approval_module, "maybe_schedule_auto_approve", fake_schedule)

    class _FakeGraph:
        async def aupdate_state(self, config, update):
            return None

        def astream(self, _input, _config):
            async def gen():
                # Resume lands back at a NEW awaiting-approval interrupt with
                # a fresh proposal -- new_proposal_awaiting == True.
                yield {"re_analyze": {
                    "awaiting_approval": True,
                    "approval_status": None,
                    "trade_proposal": {"id": "p2", "action": "BUY"},
                }}

            return gen()

    monkeypatch.setattr(approval_module, "get_kr_stock_trading_graph", lambda: _FakeGraph())

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "rejected", feedback="try again")

    assert exc_info.value.status_code == 503
    # The 1-retry loop attempted the commit twice, then gave up.
    assert calls["n"] == 2
    # Never armed against an SM row that doesn't know about this
    # transition -- the core invariant this whole task exists to guard.
    assert scheduled == []
