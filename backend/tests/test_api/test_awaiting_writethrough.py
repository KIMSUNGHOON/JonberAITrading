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


# -------------------------------------------
# KR (kiwoom) — brief 원문 테스트 2건
# -------------------------------------------


@pytest.mark.asyncio
async def test_awaiting_transition_failclosed_on_sm_failure(monkeypatch):
    """SM awaiting 기록이 계속 실패하면 세션은 error 가 되고 auto-approve 는 안 뜬다."""
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

    session = {"session_id": "wt-1", "status": "running", "error": None,
               "state": {"awaiting_approval": True,
                         "trade_proposal": {"action": "BUY"},
                         "reasoning_log": []}}

    await kr_analysis._finalize_awaiting_transition("wt-1", session)

    assert calls["n"] == 2                      # 1회 재시도 포함 2회 시도
    assert session["status"] == "error"          # fail-closed
    assert session["state"]["awaiting_approval"] is False
    assert scheduled == []                       # 보이지 않는 자동승인 금지
    # Best-effort ERROR mirror to the sm still attempted exactly once.
    assert len(mirrored) == 1
    assert mirrored[0][0] == "wt-1"


@pytest.mark.asyncio
async def test_awaiting_transition_success_path(monkeypatch):
    from app.api.routes.kr_stocks import analysis as kr_analysis

    committed = []

    async def ok_commit(session_id, status, **kw):
        committed.append((session_id, status))

    monkeypatch.setattr(kr_analysis, "commit_session_status", ok_commit)
    scheduled = []

    async def fake_schedule(session_id, market, session):
        scheduled.append(session_id)

    monkeypatch.setattr(kr_analysis, "maybe_schedule_auto_approve", fake_schedule)

    session = {"session_id": "wt-2", "status": "running", "error": None,
               "state": {"awaiting_approval": True,
                         "trade_proposal": {"action": "BUY"},
                         "reasoning_log": []}}
    await kr_analysis._finalize_awaiting_transition("wt-2", session)
    assert session["status"] == "awaiting_approval"
    assert scheduled == ["wt-2"]
    assert committed and committed[0][0] == "wt-2"


# -------------------------------------------
# coin — 동형 1건 (fail-closed)
# -------------------------------------------


@pytest.mark.asyncio
async def test_coin_awaiting_transition_failclosed_on_sm_failure(monkeypatch):
    """coin 쪽 _finalize_awaiting_transition 도 KR과 동일하게 1회 재시도 후
    fail-closed: 세션 error, awaiting_approval False, auto-approve 미호출.
    (update_session_status 는 legacy analysis_limiter.active_sessions 를 건드리는
    순수 no-op 라 이 테스트의 미등록 session_id 에 대해서는 페이크할 필요가 없다.)
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

    session = {"session_id": "wt-coin-1", "status": "running", "error": None,
               "state": {"awaiting_approval": True,
                         "trade_proposal": {"action": "BUY"},
                         "reasoning_log": []}}

    await coin_analysis._finalize_awaiting_transition("wt-coin-1", session)

    assert calls["n"] == 2
    assert session["status"] == "error"
    assert session["state"]["awaiting_approval"] is False
    assert scheduled == []
    assert len(mirrored) == 1


# -------------------------------------------
# approval.py — 결정 진입 write-through 503 경로 1건
# -------------------------------------------


@pytest.mark.asyncio
async def test_approval_decision_entry_503_when_sm_commit_fails(monkeypatch):
    """P1-5: 결정 진입 시점의 decision_updates 미러는 write-through다 -- SM
    커밋이 실패하면 그래프를 재개(=주문 실행 가능)하지 않고 503으로 fail-loud
    해야 한다. 결정이 SM에 반영되지 않은 채 200 을 돌려주는 것은 금지.
    """
    from app.api.routes import approval as approval_module
    from app.api.routes.kr_stocks.constants import kr_stock_sessions

    session_id = "wt-approval-1"
    saved = dict(kr_stock_sessions)
    kr_stock_sessions.clear()
    kr_stock_sessions[session_id] = {
        "session_id": session_id,
        "status": "awaiting_approval",
        "error": None,
        "state": {
            "awaiting_approval": True,
            "trade_proposal": {"id": "p1", "action": "BUY"},
            "reasoning_log": [],
        },
    }

    async def failing_commit_state(session_id, state_updates, **kw):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(approval_module, "commit_session_state", failing_commit_state)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await approval_module.submit_decision(session_id, "approved")

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "approval state could not be persisted — retry"
        # The decision must not have been applied as a silent success: the
        # graph resume (and any order it could place) never ran.
        assert kr_stock_sessions[session_id]["status"] == "awaiting_approval"
    finally:
        kr_stock_sessions.clear()
        kr_stock_sessions.update(saved)
