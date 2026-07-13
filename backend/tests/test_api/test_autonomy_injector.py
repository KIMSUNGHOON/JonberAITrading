"""R3 t5: the auto-approve injector — 60s grace, manual-wins, fail-closed.

When a session reaches awaiting_approval and the autonomy gate allows, the
injector announces (auto_approve_at + reasoning + Telegram), waits the grace
period, RE-checks (session still awaiting + gate still green), then submits
the decision as actor='system' through the extracted submit_decision. Any
failure leaves the session awaiting (HITL fallback).
"""

import asyncio
import os

import pytest

import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager
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


def _awaiting_session(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "stk_cd": "005930",
        "status": "awaiting_approval",
        "state": {
            "awaiting_approval": True,
            "reasoning_log": ["[t] 분석 완료"],
            "trade_proposal": {
                "id": "p1",
                "action": "BUY",
                "quantity": 10,
                "entry_price": 50_000,
            },
        },
        "created_at": None,
        "error": None,
    }


async def _seed_sm(sm, session_id: str):
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        state={"reasoning_log": []},
    )


async def _wait_for(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met")


async def test_auto_approves_after_grace_as_system(sm, fast_grace, gate_allow, submit_recorder):
    session_id = "inj-1"
    session = _awaiting_session(session_id)
    await _seed_sm(sm, session_id)
    queue = await sm.subscribe(session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom", session)

    # Announcement written immediately: countdown field + reasoning entry
    assert "auto_approve_at" in session["state"]
    assert any("자율 승인 예정" in e for e in session["state"]["reasoning_log"])
    sm_session = await sm.get_session(session_id)
    assert sm_session.state.get("auto_approve_at") == session["state"]["auto_approve_at"]
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
    session = _awaiting_session(session_id)
    await _seed_sm(sm, session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom", session)
    # User decides during the grace window
    session["status"] = "completed"
    session["state"]["awaiting_approval"] = False

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
    session = _awaiting_session(session_id)
    await _seed_sm(sm, session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom", session)
    await asyncio.sleep(0.2)

    assert submit_recorder == []
    assert session["status"] == "awaiting_approval"  # stays HITL
    assert any("자율 승인 취소" in e for e in session["state"]["reasoning_log"])


async def test_pre_check_deny_writes_nothing(sm, fast_grace, monkeypatch, submit_recorder):
    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="AUTONOMY_ENABLED is off", check="master_gate")

    monkeypatch.setattr(injector_module, "check_autonomy", deny_gate)

    session_id = "inj-4"
    session = _awaiting_session(session_id)
    await _seed_sm(sm, session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom", session)
    await asyncio.sleep(0.15)

    assert "auto_approve_at" not in session["state"]
    assert submit_recorder == []
    assert session["status"] == "awaiting_approval"


async def test_submit_failure_leaves_session_awaiting(sm, fast_grace, gate_allow, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("resume blew up")

    monkeypatch.setattr("app.api.routes.approval.submit_decision", boom)

    session_id = "inj-5"
    session = _awaiting_session(session_id)
    await _seed_sm(sm, session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom", session)
    await asyncio.sleep(0.2)

    # Fail-closed: the normal HITL flow still owns the session
    assert session["status"] == "awaiting_approval"
    assert session["state"]["awaiting_approval"] is True


async def test_stale_timer_stands_down_when_proposal_changed(sm, fast_grace, gate_allow, submit_recorder):
    """SAFETY (review fix): a reject→re-analyze cycle mutates the SAME session
    dict and can re-arm awaiting with a NEW proposal — the stale timer must
    never approve a proposal it did not announce."""
    session_id = "inj-6"
    session = _awaiting_session(session_id)
    await _seed_sm(sm, session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom", session)
    # During the grace: re-analysis replaced the proposal (new id), awaiting re-armed.
    session["state"]["trade_proposal"] = {"id": "p2-NEW", "action": "BUY", "quantity": 1, "entry_price": 1000}

    await asyncio.sleep(0.2)
    assert submit_recorder == []
    assert "auto_approve_at" not in session["state"], "stale countdown must be cleared"


async def test_recorded_decision_blocks_stale_timer(sm, fast_grace, gate_allow, submit_recorder):
    """approval_status set (a decision was recorded) must stand the timer down
    even if awaiting flags look re-armed (mid-reject resume window)."""
    session_id = "inj-7"
    session = _awaiting_session(session_id)
    await _seed_sm(sm, session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom", session)
    session["state"]["approval_status"] = "rejected"  # decision recorded; flags still awaiting

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
    session = _awaiting_session(session_id)
    await _seed_sm(sm, session_id)

    await maybe_schedule_auto_approve(session_id, "kiwoom", session)
    await asyncio.sleep(0.2)

    assert "auto_approve_at" not in session["state"]
    sm_session = await sm.get_session(session_id)
    assert sm_session.state.get("auto_approve_at") is None


async def test_kr_producer_invokes_injector(sm, monkeypatch):
    """The KR analysis task must hand awaiting sessions to the injector."""
    from app.api.routes.kr_stocks.constants import kr_stock_sessions
    from app.api.routes.kr_stocks.analysis import run_kr_stock_analysis_task

    calls = []

    async def recorder(session_id, market, session):
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

    saved = dict(kr_stock_sessions)
    kr_stock_sessions.clear()
    try:
        kr_stock_sessions["inj-kr-1"] = _awaiting_session("inj-kr-1")
        kr_stock_sessions["inj-kr-1"]["status"] = "running"
        kr_stock_sessions["inj-kr-1"]["state"]["awaiting_approval"] = False
        await _seed_sm(sm, "inj-kr-1")

        await run_kr_stock_analysis_task("inj-kr-1")

        assert calls == [("inj-kr-1", "kiwoom")]
    finally:
        kr_stock_sessions.clear()
        kr_stock_sessions.update(saved)
