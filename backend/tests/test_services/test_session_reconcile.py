"""reconcile_stranded_sessions — shape별 정합화.

Real AnalysisSession fixtures (no MagicMock) seeded directly into
SessionManager._sessions, matching the existing test_session_manager.py
DB_PATH-patch convention (temp DB per test via monkeypatch).
"""
from datetime import datetime, timezone, timedelta

import pytest

from services.session_manager import (
    SessionManager, AnalysisSession, MarketType, SessionStatus,
)

NOW = datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc)


def _sess(sid, status, state, created=NOW, market=MarketType.KIWOOM, kind="analysis"):
    return AnalysisSession(
        session_id=sid, market_type=market, ticker="005930",
        display_name="삼성전자", status=status, state=state,
        created_at=created, stk_cd="005930", stk_nm="삼성전자", kind=kind,
    )


async def _mgr_with(sessions, tmp_path, monkeypatch):
    import services.session_manager as sm_mod
    monkeypatch.setattr(sm_mod, "DB_PATH", str(tmp_path / "s.db"))
    mgr = SessionManager()
    await mgr.initialize()  # reconcile 포함 — 빈 상태
    for s in sessions:
        mgr._sessions[s.session_id] = s
        await mgr._save_session(s)
    return mgr


async def test_r1_hold_running_awaiting_flips_to_awaiting(tmp_path, monkeypatch):
    s = _sess("r1", SessionStatus.RUNNING, {
        "awaiting_approval": True, "approval_status": "rejected",
        "trade_proposal": {"action": "HOLD", "created_at": NOW.isoformat()},
        "auto_approve_at": "2026-07-14T09:01:00+00:00"})
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r1" in rep.flipped
    assert mgr._sessions["r1"].status == SessionStatus.AWAITING_APPROVAL
    assert mgr._sessions["r1"].state.get("auto_approve_at") is None
    assert mgr._sessions["r1"].state.get("approval_status") in (None, "")
    # I7: the cleared countdown must be explained in the reasoning log, not
    # just silently vanish -- the FE countdown would otherwise disappear
    # with no indication a human now has to decide.
    assert any(
        "재시작으로 자율 승인 타이머 해제" in line
        for line in mgr._sessions["r1"].state.get("reasoning_log", [])
    )


async def test_i7_kept_session_still_clears_and_annotates_auto_approve_at(tmp_path, monkeypatch):
    """A session that falls through to the default 'kept' branch (no status
    change otherwise) must still have its stale auto_approve_at cleared AND
    annotated -- the common-path handling (I7) runs regardless of which
    branch a session ends up in below it."""
    s = _sess("r5b", SessionStatus.AWAITING_APPROVAL, {
        "awaiting_approval": True,
        "trade_proposal": {"action": "WATCH", "created_at": NOW.isoformat()},
        "auto_approve_at": "2026-07-14T09:01:00+00:00",
        "reasoning_log": ["[09:00:00] 기존 로그"],
    })
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r5b" in rep.kept
    assert mgr._sessions["r5b"].status == SessionStatus.AWAITING_APPROVAL
    assert mgr._sessions["r5b"].state.get("auto_approve_at") is None
    log = mgr._sessions["r5b"].state.get("reasoning_log", [])
    assert log[0] == "[09:00:00] 기존 로그"  # prior entries preserved, not clobbered
    assert any("재시작으로 자율 승인 타이머 해제" in line for line in log)


async def test_i7_no_auto_approve_at_leaves_reasoning_log_untouched(tmp_path, monkeypatch):
    """No stale deadline present -> nothing popped -> no annotation added
    (the line must be conditioned on an actual pop, not unconditional)."""
    s = _sess("r5c", SessionStatus.AWAITING_APPROVAL, {
        "awaiting_approval": True,
        "trade_proposal": {"action": "WATCH", "created_at": NOW.isoformat()},
    })
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r5c" in rep.kept
    assert mgr._sessions["r5c"].state.get("reasoning_log", []) == []


async def test_r1_buy_over_6h_errors(tmp_path, monkeypatch):
    old = NOW - timedelta(hours=7)
    s = _sess("r1b", SessionStatus.RUNNING, {
        "awaiting_approval": True,
        "trade_proposal": {"action": "BUY", "created_at": old.isoformat()}},
        created=old)
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r1b" in rep.errored
    assert mgr._sessions["r1b"].status == SessionStatus.ERROR


async def test_r1_buy_within_6h_flips(tmp_path, monkeypatch):
    recent = NOW - timedelta(hours=2)
    s = _sess("r1c", SessionStatus.RUNNING, {
        "awaiting_approval": True,
        "trade_proposal": {"action": "BUY", "created_at": recent.isoformat()}},
        created=recent)
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r1c" in rep.flipped
    assert mgr._sessions["r1c"].status == SessionStatus.AWAITING_APPROVAL


async def test_r2_running_not_awaiting_errors(tmp_path, monkeypatch):
    s = _sess("r2", SessionStatus.RUNNING, {"awaiting_approval": False})
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r2" in rep.errored
    assert mgr._sessions["r2"].status == SessionStatus.ERROR
    assert "재시작" in (mgr._sessions["r2"].error or "")


async def test_r3_awaiting_approved_errors_execution_uncertain(tmp_path, monkeypatch):
    s = _sess("r3", SessionStatus.AWAITING_APPROVAL, {
        "awaiting_approval": False, "approval_status": "approved"})
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r3" in rep.errored
    assert "체결 확인" in (mgr._sessions["r3"].error or "")


async def test_r4_awaiting_cancelled_mirror_corrects(tmp_path, monkeypatch):
    s = _sess("r4", SessionStatus.AWAITING_APPROVAL, {
        "awaiting_approval": True, "approval_status": "cancelled",
        "trade_proposal": {"action": "WATCH", "created_at": NOW.isoformat()}})
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r4" in rep.cancelled
    assert mgr._sessions["r4"].status == SessionStatus.CANCELLED


async def test_r5_normal_awaiting_kept(tmp_path, monkeypatch):
    s = _sess("r5", SessionStatus.AWAITING_APPROVAL, {
        "awaiting_approval": True,
        "trade_proposal": {"action": "WATCH", "created_at": NOW.isoformat()}})
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "r5" in rep.kept
    assert mgr._sessions["r5"].status == SessionStatus.AWAITING_APPROVAL


async def test_r1_flip_denied_when_checkpoint_not_parked(tmp_path, monkeypatch):
    # 체크포인트가 approval에 없으면 flip 강등→ERROR
    s = _sess("r1d", SessionStatus.RUNNING, {
        "awaiting_approval": True,
        "trade_proposal": {"action": "HOLD", "created_at": NOW.isoformat()}})
    mgr = await _mgr_with([s], tmp_path, monkeypatch)

    async def _next(_sid):
        return ("decision",)  # not ('approval',)

    rep = await mgr.reconcile_stranded_sessions(now=NOW, checkpoint_next=_next)
    assert "r1d" in rep.errored


# -------------------------------------------
# P4-5 (session-ssot): kind="discussion" reconcile branch
# -------------------------------------------
# reconcile_stranded_sessions used to be kind-blind: a restart-orphaned
# discussion row (kind="discussion", left RUNNING when its ChatRoom died
# with the process) fell into the generic "RUNNING, no proposal" branch
# and was flipped to ERROR with an analysis-flavored reasoning ("서버
# 재시작으로 분석 중단") -- harmless (defense-in-depth filters everywhere
# else already exclude non-analysis kinds from every consumer) but
# semantically wrong. These pin the new kind-aware branch: discussions
# always resolve to CANCELLED with an explicit marker, never ERROR/
# AWAITING_APPROVAL, and the pre-existing analysis branches (awaiting-flip,
# 6h staleness, checkpoint verification, approved-mismatch) are untouched
# for kind="analysis" rows (the r1-r5 tests above are the byte-invariance
# pin -- they stay GREEN unmodified).


async def test_p45_discussion_running_reconciled_to_cancelled_with_marker(tmp_path, monkeypatch):
    """① RUNNING discussion 행 → reconcile 후 CANCELLED + state 마커."""
    s = _sess("d1", SessionStatus.RUNNING, {"sub_status": "discussing"}, kind="discussion")
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "d1" in rep.cancelled
    assert mgr._sessions["d1"].status == SessionStatus.CANCELLED
    assert mgr._sessions["d1"].state.get("cancelled_reason") == "재시작으로 토론 중단"
    assert mgr._sessions["d1"].state.get("sub_status") == "cancelled"
    # never mistaken for an analysis-flavored outcome
    assert mgr._sessions["d1"].error is None


async def test_p45_mixed_pass_analysis_branch_unaffected_by_discussion_branch(tmp_path, monkeypatch):
    """② 동일 reconcile pass에 analysis + discussion 행이 섞여도 kind 분기가
    서로 오염되지 않음 -- 기존 analysis flip 로직(awaiting+HOLD→AWAITING_APPROVAL)
    그대로."""
    analysis = _sess("a1", SessionStatus.RUNNING, {
        "awaiting_approval": True,
        "trade_proposal": {"action": "HOLD", "created_at": NOW.isoformat()},
    })
    discussion = _sess("d2", SessionStatus.RUNNING, {"sub_status": "voting"}, kind="discussion")
    mgr = await _mgr_with([analysis, discussion], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)

    assert "a1" in rep.flipped
    assert mgr._sessions["a1"].status == SessionStatus.AWAITING_APPROVAL

    assert "d2" in rep.cancelled
    assert mgr._sessions["d2"].status == SessionStatus.CANCELLED
    assert mgr._sessions["d2"].state.get("cancelled_reason") == "재시작으로 토론 중단"


async def test_p45_discussion_awaiting_approval_failsafe_cancelled(tmp_path, monkeypatch):
    """③ 정상적으론 불가능한 discussion AWAITING_APPROVAL 행도 fail-safe로
    동일하게 CANCELLED (ERROR/AWAITING_APPROVAL로 남기지 않음)."""
    s = _sess("d3", SessionStatus.AWAITING_APPROVAL, {"sub_status": "discussing"}, kind="discussion")
    mgr = await _mgr_with([s], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "d3" in rep.cancelled
    assert mgr._sessions["d3"].status == SessionStatus.CANCELLED
    assert mgr._sessions["d3"].state.get("cancelled_reason") == "재시작으로 토론 중단"


async def test_p45_discussion_terminal_states_left_alone(tmp_path, monkeypatch):
    """터미널 discussion 행(COMPLETED/CANCELLED/ERROR)은 stranded가 아니므로
    reconcile이 건드리지 않고 kept로 분류."""
    done = _sess("d4", SessionStatus.COMPLETED, {"sub_status": "decided"}, kind="discussion")
    already_cancelled = _sess("d5", SessionStatus.CANCELLED, {"sub_status": "cancelled"}, kind="discussion")
    mgr = await _mgr_with([done, already_cancelled], tmp_path, monkeypatch)
    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert "d4" in rep.kept
    assert "d5" in rep.kept
    assert mgr._sessions["d4"].status == SessionStatus.COMPLETED
    assert mgr._sessions["d5"].status == SessionStatus.CANCELLED


async def test_p45_discussion_reconcile_visible_as_cancelled_in_history(tmp_path, monkeypatch):
    """④ 통합: 재시작 시뮬 — RUNNING discussion 행 로드 → reconcile →
    P4-4의 ChatCoordinator.get_session_history()에서 'cancelled'로 노출.
    P4-2(SM mirror 계약: state["chat_snapshot"]/state["sub_status"]) +
    P4-4(read merge: sub_status가 있으면 그 값을 그대로 status로 노출) +
    본 태스크(kind-aware reconcile이 sub_status="cancelled"를 씀)를 잇는
    end-to-end 증거."""
    from unittest.mock import AsyncMock

    import services.session_manager as sm_module
    from services.agent_chat.coordinator import ChatCoordinator
    from services.agent_chat.models import ChatSession, MarketContext
    from services.storage_service import StorageService

    context = MarketContext(
        ticker="005930", stock_name="삼성전자",
        current_price=72500.0, price_change_pct=0.5,
    )
    chat_session = ChatSession(ticker="005930", stock_name="삼성전자", context=context)
    chat_session.started_at = NOW

    row = AnalysisSession(
        session_id=chat_session.id, market_type=MarketType.KIWOOM, ticker="005930",
        display_name="삼성전자", kind="discussion", status=SessionStatus.RUNNING,
        state={
            "sub_status": "discussing",
            "chat_snapshot": chat_session.model_dump(mode="json"),
        },
        created_at=NOW, stk_cd="005930", stk_nm="삼성전자",
    )
    mgr = await _mgr_with([row], tmp_path, monkeypatch)
    monkeypatch.setattr(sm_module, "_session_manager", mgr)

    rep = await mgr.reconcile_stranded_sessions(now=NOW)
    assert chat_session.id in rep.cancelled

    storage = StorageService(db_path=str(tmp_path / "ledger.db"))
    await storage.initialize()
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_storage_service",
        AsyncMock(return_value=storage),
    )

    coordinator = ChatCoordinator()
    history = await coordinator.get_session_history()
    found = next((entry for entry in history if entry["id"] == chat_session.id), None)
    assert found is not None, "reconciled discussion must still surface in history"
    assert found["status"] == "cancelled"
