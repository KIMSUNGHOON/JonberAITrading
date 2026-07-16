"""R3 t5: the auto-approve injector — 60s grace, manual-wins, fail-closed.

When a session reaches awaiting_approval and the autonomy gate allows, the
injector announces (auto_approve_at + reasoning + Telegram), waits the grace
period, RE-checks (session still awaiting + gate still green), then submits
the decision as actor='system' through the extracted submit_decision. Any
failure leaves the session awaiting (HITL fallback).

P2-6 (session-SSOT): maybe_schedule_auto_approve/rearm_awaiting_approvals no
longer take a session dict/snapshot at all -- every entry point resolves the
live AnalysisSession itself via sm.get_session(session_id), both at schedule
time and again inside the grace task's re-check. Every test below therefore
seeds ONLY the SessionManager (never a legacy dict, never a passed-in
snapshot) and asserts against a fresh `sm.get_session(...)` read -- there is
no local `session` object left to go stale relative to the SM.
"""

import asyncio
import os

import pytest

import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager, SessionStatus
from services.autonomy import GateDecision

import app.api.routes._autonomy_injector as injector_module
from app.api.routes._autonomy_injector import maybe_schedule_auto_approve

TEST_DB_PATH = "data/test_autonomy_injector.db"


@pytest.fixture
async def sm(monkeypatch):
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
def fast_grace(monkeypatch):
    monkeypatch.setattr(injector_module, "AUTONOMY_GRACE_SECONDS", 0.05)


@pytest.fixture
def gate_allow(monkeypatch):
    calls = []

    async def fake_gate(market, **kwargs):
        calls.append(kwargs)
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(injector_module, "check_autonomy", fake_gate)
    return calls


@pytest.fixture
def submit_recorder(monkeypatch):
    calls = []

    async def fake_submit(
        session_id,
        decision,
        feedback=None,
        modifications=None,
        actor="user",
        expected_proposal_id=None,
    ):
        calls.append({
            "session_id": session_id,
            "decision": decision,
            "actor": actor,
            "expected_proposal_id": expected_proposal_id,
        })

    monkeypatch.setattr("app.api.routes.approval.submit_decision", fake_submit)
    return calls


async def _seed_sm(sm, session_id: str):
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        state={"reasoning_log": []},
    )


async def _seed_awaiting_sm(
    sm,
    session_id: str,
    *,
    market_type: MarketType = MarketType.KIWOOM,
    auto_approve_at: str | None = None,
    proposal_id: str = "p-rearm-1",
) -> None:
    """Seed an AWAITING_APPROVAL session directly into the SessionManager,
    bypassing the legacy dicts entirely -- the only seeding path
    maybe_schedule_auto_approve/rearm can observe post-P2-6."""
    state = {
        "awaiting_approval": True,
        "approval_status": None,
        "trade_proposal": {
            "id": proposal_id,
            "action": "BUY",
            "quantity": 10,
            "entry_price": 50_000,
        },
        "reasoning_log": ["[t] 분석 완료"],
    }
    if auto_approve_at is not None:
        state["auto_approve_at"] = auto_approve_at
    ticker = "005930" if market_type == MarketType.KIWOOM else "KRW-BTC"
    await sm.create_session(
        session_id=session_id,
        market_type=market_type,
        ticker=ticker,
        display_name="테스트",
        state=state,
    )
    await sm.update_status(session_id, SessionStatus.AWAITING_APPROVAL)


async def _wait_for(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met")


async def test_auto_approves_after_grace_as_system(sm, fast_grace, gate_allow, submit_recorder):
    session_id = "inj-1"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")
    queue = await sm.subscribe(session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom")

    # Announcement written immediately: countdown field + reasoning entry,
    # both landed directly on the SM row via a single sm.update_state call.
    sm_session = await sm.get_session(session_id)
    assert sm_session.state.get("auto_approve_at") is not None
    assert any("자율 승인 예정" in e for e in sm_session.state["reasoning_log"])
    assert not queue.empty()  # notify fired → WS pushes the countdown

    await _wait_for(lambda: len(submit_recorder) == 1)
    assert submit_recorder[0] == {
        "session_id": session_id,
        "decision": "approved",
        "actor": "system",
        "expected_proposal_id": "p1",
    }
    # Gate ran twice: pre-check + re-check after the grace
    assert len(gate_allow) == 2


async def test_manual_decision_during_grace_wins(sm, fast_grace, gate_allow, submit_recorder):
    session_id = "inj-2"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")
    # User decides during the grace window -- mutate the LIVE SM row
    # directly (the injector re-reads sm.get_session() live, P2-6; there is
    # no separate snapshot for this mutation to fall out of sync with).
    await sm.update_status(session_id, SessionStatus.COMPLETED)
    sm_session = await sm.get_session(session_id)
    sm_session.state["awaiting_approval"] = False

    await asyncio.sleep(0.2)
    assert submit_recorder == []  # injector silently stood down


async def test_gate_deny_at_recheck_stays_hitl(sm, fast_grace, monkeypatch, submit_recorder):
    verdicts = [
        GateDecision(allowed=True, reason="ok", check="all"),
        GateDecision(allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode"),
    ]

    async def flip_gate(market, **kwargs):
        return verdicts.pop(0)

    monkeypatch.setattr(injector_module, "check_autonomy", flip_gate)

    session_id = "inj-3"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")
    await asyncio.sleep(0.2)

    assert submit_recorder == []
    sm_session = await sm.get_session(session_id)
    assert sm_session.status == SessionStatus.AWAITING_APPROVAL  # stays HITL
    assert any("자율 승인 취소" in e for e in sm_session.state["reasoning_log"])


async def test_pre_check_deny_writes_nothing(sm, fast_grace, monkeypatch, submit_recorder):
    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="AUTONOMY_ENABLED is off", check="master_gate")

    monkeypatch.setattr(injector_module, "check_autonomy", deny_gate)

    session_id = "inj-4"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")
    await asyncio.sleep(0.15)

    sm_session = await sm.get_session(session_id)
    assert "auto_approve_at" not in sm_session.state
    assert submit_recorder == []
    assert sm_session.status == SessionStatus.AWAITING_APPROVAL


async def test_submit_failure_leaves_session_awaiting(sm, fast_grace, gate_allow, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("resume blew up")

    monkeypatch.setattr("app.api.routes.approval.submit_decision", boom)

    session_id = "inj-5"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")
    await asyncio.sleep(0.2)

    # Fail-closed: the normal HITL flow still owns the session
    sm_session = await sm.get_session(session_id)
    assert sm_session.status == SessionStatus.AWAITING_APPROVAL
    assert sm_session.state["awaiting_approval"] is True


async def test_stale_timer_stands_down_when_proposal_changed(sm, fast_grace, gate_allow, submit_recorder):
    """SAFETY (review fix): a reject→re-analyze cycle mutates the SAME SM
    row and can re-arm awaiting with a NEW proposal — the stale timer must
    never approve a proposal it did not announce."""
    session_id = "inj-6"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")
    # During the grace: re-analysis replaced the proposal (new id), awaiting re-armed.
    sm_session = await sm.get_session(session_id)
    sm_session.state["trade_proposal"] = {"id": "p2-NEW", "action": "BUY", "quantity": 1, "entry_price": 1000}

    await asyncio.sleep(0.2)
    assert submit_recorder == []
    # _clear_countdown writes auto_approve_at=None via sm.update_state (a
    # dict merge, same convention submit_decision's decision_updates uses)
    # rather than popping the key -- there is only one state dict now.
    assert sm_session.state.get("auto_approve_at") is None, "stale countdown must be cleared"


async def test_recorded_decision_blocks_stale_timer(sm, fast_grace, gate_allow, submit_recorder):
    """approval_status set (a decision was recorded) must stand the timer down
    even if awaiting flags look re-armed (mid-reject resume window)."""
    session_id = "inj-7"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")
    sm_session = await sm.get_session(session_id)
    sm_session.state["approval_status"] = "rejected"  # decision recorded; flags still awaiting

    await asyncio.sleep(0.2)
    assert submit_recorder == []


async def test_recheck_deny_clears_countdown(sm, fast_grace, monkeypatch, submit_recorder):
    verdicts = [
        GateDecision(allowed=True, reason="ok", check="all"),
        GateDecision(allowed=False, reason="mode off", check="market_mode"),
    ]

    async def flip_gate(market, **kwargs):
        return verdicts.pop(0)

    monkeypatch.setattr(injector_module, "check_autonomy", flip_gate)

    session_id = "inj-8"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")
    await asyncio.sleep(0.2)

    sm_session = await sm.get_session(session_id)
    assert sm_session.state.get("auto_approve_at") is None


async def test_kr_producer_invokes_injector(sm, monkeypatch):
    """The KR analysis task must hand awaiting sessions to the injector."""
    from app.api.routes.kr_stocks.analysis import run_kr_stock_analysis_task

    calls = []

    async def recorder(session_id, market):
        calls.append((session_id, market))

    monkeypatch.setattr(
        "app.api.routes.kr_stocks.analysis.maybe_schedule_auto_approve", recorder
    )

    class FakeGraph:
        async def astream(self, initial_state, config):
            yield {"strategic_decision": {
                "reasoning_log": ["[t] 결정"],
                "awaiting_approval": True,
                "trade_proposal": {"id": "p1", "action": "BUY"},
            }}

    monkeypatch.setattr(
        "agents.graph.kr_stock_graph.get_kr_stock_trading_graph", lambda: FakeGraph()
    )

    await _seed_sm(sm, "inj-kr-1")

    await run_kr_stock_analysis_task("inj-kr-1")

    assert calls == [("inj-kr-1", "kiwoom")]


# -------------------------------------------
# P2-6 dedicated pins: no snapshot ever passed through the call chain, and
# the grace-window re-check is a LIVE SessionManager read (not a
# locally-cached flag).
# -------------------------------------------


async def test_full_cycle_no_snapshot_ever_touched_auto_approves(
    sm, fast_grace, gate_allow, submit_recorder
):
    """End-to-end with no snapshot/session argument passed anywhere in the
    call chain -- maybe_schedule_auto_approve's signature is (session_id,
    market) only, so this is structurally guaranteed rather than merely
    asserted."""
    session_id = "inj-b-free-1"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")

    await _wait_for(lambda: len(submit_recorder) == 1)
    assert submit_recorder[0] == {
        "session_id": session_id,
        "decision": "approved",
        "actor": "system",
        "expected_proposal_id": "p1",
    }


async def test_sm_cancel_during_grace_stands_down_via_live_status_check(
    sm, fast_grace, gate_allow, submit_recorder
):
    """P2-6: the manual-wins re-check reads sm_session.status LIVE, not a
    locally-cached flag -- flip ONLY the SM status to CANCELLED (leave
    state["awaiting_approval"]/["approval_status"] in their pre-cancel
    shape, mirroring how a status-only mutation could reach the SM from a
    concurrent route) and confirm the grace task still stands down. This
    isolates the live-status half of the guard from the state-flag half
    already covered by test_manual_decision_during_grace_wins."""
    session_id = "inj-cancel-live"
    await _seed_awaiting_sm(sm, session_id, proposal_id="p1")

    await maybe_schedule_auto_approve(session_id, "kiwoom")

    await sm.update_status(session_id, SessionStatus.CANCELLED)
    sm_session = await sm.get_session(session_id)
    assert sm_session.state["awaiting_approval"] is True  # deliberately untouched
    assert sm_session.state.get("approval_status") is None  # deliberately untouched

    await asyncio.sleep(0.2)
    assert submit_recorder == []  # live status re-check caught it regardless


# -------------------------------------------
# Startup re-arm pass: re-arm sessions that were ALREADY awaiting_approval
# when the gate turns on (or the process restarts) — not just sessions that
# transition to awaiting afterward.
# -------------------------------------------


async def test_rearm_schedules_for_sm_only_awaiting_session(
    sm, fast_grace, gate_allow, submit_recorder
):
    """A session that survived only in the SessionManager (legacy dict
    empty -- the restart shape) gets handed to maybe_schedule_auto_approve
    when the gate allows -- full rearm→schedule→auto-approve e2e."""
    session_id = "rearm-1"
    await _seed_awaiting_sm(sm, session_id)

    await injector_module.rearm_awaiting_approvals()

    sm_session = await sm.get_session(session_id)
    assert sm_session.state.get("auto_approve_at") is not None

    await _wait_for(lambda: len(submit_recorder) == 1)
    assert submit_recorder[0]["session_id"] == session_id
    assert submit_recorder[0]["actor"] == "system"


async def test_rearm_gate_deny_schedules_nothing(
    sm, fast_grace, monkeypatch, submit_recorder
):
    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="AUTONOMY_ENABLED is off", check="master_gate")

    monkeypatch.setattr(injector_module, "check_autonomy", deny_gate)

    session_id = "rearm-2"
    await _seed_awaiting_sm(sm, session_id)

    await injector_module.rearm_awaiting_approvals()
    await asyncio.sleep(0.1)

    sm_session = await sm.get_session(session_id)
    assert sm_session.state.get("auto_approve_at") is None
    assert submit_recorder == []


async def test_rearm_skips_session_with_live_future_countdown(
    sm, fast_grace, monkeypatch
):
    """A session that already carries a FUTURE auto_approve_at (a live grace
    task presumably already counting it down) must not be re-armed -- doing
    so would stack a duplicate timer."""
    from datetime import datetime, timedelta, timezone

    future = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
    session_id = "rearm-3"
    await _seed_awaiting_sm(sm, session_id, auto_approve_at=future)

    calls = []

    async def recorder(sid, market):
        calls.append(sid)

    monkeypatch.setattr(injector_module, "maybe_schedule_auto_approve", recorder)

    await injector_module.rearm_awaiting_approvals()

    assert calls == []
    sm_session = await sm.get_session(session_id)
    assert sm_session.state.get("auto_approve_at") == future  # left untouched


async def test_rearm_skips_non_awaiting_sessions(sm, monkeypatch):
    session_id = "rearm-4"
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="테스트",
        state={"reasoning_log": []},
    )
    # default status is RUNNING, not AWAITING_APPROVAL

    calls = []

    async def recorder(sid, market):
        calls.append(sid)

    monkeypatch.setattr(injector_module, "maybe_schedule_auto_approve", recorder)

    await injector_module.rearm_awaiting_approvals()

    assert calls == []


async def test_rearm_continues_after_one_session_errors(
    sm, fast_grace, gate_allow, submit_recorder, monkeypatch
):
    """A single session raising during scheduling must not stop the pass --
    the other awaiting sessions still get re-armed."""
    boom_id = "rearm-boom"
    ok_id = "rearm-ok"
    await _seed_awaiting_sm(sm, boom_id)
    await _seed_awaiting_sm(sm, ok_id)

    real = injector_module.maybe_schedule_auto_approve

    async def flaky(sid, market):
        if sid == boom_id:
            raise RuntimeError("boom")
        return await real(sid, market)

    monkeypatch.setattr(injector_module, "maybe_schedule_auto_approve", flaky)

    await injector_module.rearm_awaiting_approvals()  # must not raise

    await _wait_for(lambda: len(submit_recorder) == 1)
    assert submit_recorder[0]["session_id"] == ok_id


async def test_rearm_covers_both_markets_gate_can_deny_coin_only(
    sm, fast_grace, monkeypatch, submit_recorder
):
    """coin is HITL-only in this codebase's default posture -- the gate
    denies it, but the pass must still attempt it (not skip coin entirely),
    while kiwoom (allowed) gets scheduled normally."""
    calls = []

    async def per_market_gate(market, **kwargs):
        calls.append(market)
        if market == "coin":
            return GateDecision(allowed=False, reason="coin is hitl", check="market_mode")
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(injector_module, "check_autonomy", per_market_gate)

    kr_id = "rearm-kr-both"
    coin_id = "rearm-coin-both"
    await _seed_awaiting_sm(sm, kr_id, market_type=MarketType.KIWOOM)
    await _seed_awaiting_sm(sm, coin_id, market_type=MarketType.COIN)

    await injector_module.rearm_awaiting_approvals()
    await asyncio.sleep(0.1)

    assert "kiwoom" in calls and "coin" in calls
    coin_sm = await sm.get_session(coin_id)
    assert coin_sm.state.get("auto_approve_at") is None  # denied -> stays HITL

    await _wait_for(lambda: len(submit_recorder) == 1)
    assert submit_recorder[0]["session_id"] == kr_id


async def test_rearm_scans_sm_only(sm, monkeypatch):
    """P1-4/P3-1: rearm scans the SessionManager alone (legacy in-memory
    dicts have been retired) -- an awaiting SM session gets rearmed."""
    scheduled: list[str] = []

    async def fake_schedule(session_id, market):
        scheduled.append(session_id)

    monkeypatch.setattr(injector_module, "maybe_schedule_auto_approve", fake_schedule)

    session_id = "ssot-p14"
    await _seed_awaiting_sm(sm, session_id)

    await injector_module.rearm_awaiting_approvals()

    assert session_id in scheduled


async def test_rearm_excludes_non_analysis_kind_session(sm, monkeypatch):
    """P4-1: an AWAITING_APPROVAL session with kind='discussion' must never
    be picked up as a rearm candidate -- only kind='analysis' sessions are
    eligible for autonomous auto-approve scheduling. Pre-empts P4-2's future
    agent-chat discussion sessions from being auto-approved as if they were
    trade proposals."""
    scheduled: list[str] = []

    async def fake_schedule(session_id, market):
        scheduled.append(session_id)

    monkeypatch.setattr(injector_module, "maybe_schedule_auto_approve", fake_schedule)

    discussion_id = "rearm-discussion-1"
    await sm.create_session(
        session_id=discussion_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="테스트",
        kind="discussion",
        state={
            "awaiting_approval": True,
            "approval_status": None,
            "trade_proposal": {"id": "p-x", "action": "BUY", "quantity": 10},
            "reasoning_log": [],
        },
    )
    await sm.update_status(discussion_id, SessionStatus.AWAITING_APPROVAL)

    await injector_module.rearm_awaiting_approvals()

    assert scheduled == []

