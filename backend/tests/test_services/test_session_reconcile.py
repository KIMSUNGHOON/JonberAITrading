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


def _sess(sid, status, state, created=NOW, market=MarketType.KIWOOM):
    return AnalysisSession(
        session_id=sid, market_type=market, ticker="005930",
        display_name="삼성전자", status=status, state=state,
        created_at=created, stk_cd="005930", stk_nm="삼성전자",
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
