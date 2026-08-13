"""F4b Task 5 (I5): post-approve notifications must be honest about
execution_status.

Defect: the approved branch's WS/Telegram notification for BUY/SELL always
called broadcast_trade_executed/send_trade_executed ("거래 체결"/"trade
executed" wording), even when the graph's execution node only placed an
order without a confirmed fill (execution_status=='placed_pending_fill') or
the order failed outright (execution_status=='failed'). The dead giveaway:
the pre-fix code branched on `"queued" in allocation_rationale.lower()`, but
allocation_rationale is always built as
f"{action} executed via trading graph ({exec_status})" -- which never
contains the substring "queued" -- so BUY/SELL unconditionally fell through
to the "executed" notification regardless of the real outcome.

Fix: branch on state["execution_status"] directly.
  - "completed" (or missing/None, defaulting per the pre-existing
    `state.get("execution_status", "completed")` convention) -> unchanged
    "executed" wording.
  - "placed_pending_fill" -> "접수, 체결 대기" wording (broadcast_trade_queued
    / telegram.send_trade_pending), carrying ord_no when available. Never
    claims a fill.
  - "failed" -> rejected/failed wording (broadcast_trade_rejected /
    telegram.send_trade_rejected) with the execution error as the reason.

P2-5 (session-SSOT): submit_decision now resolves the session and all its
state entirely off the SessionManager (SM) -- there is no legacy dict ("B")
lookup and no _adopt_session_from_manager fallback. This fixture's fake
SessionManager is the SOLE source of truth.
"""

from unittest.mock import AsyncMock

import pytest

from services.session_manager import AnalysisSession, MarketType, SessionStatus
import app.api.routes.approval as approval_module


def _sm_session(session_id: str) -> AnalysisSession:
    state = {
        "awaiting_approval": True,
        "approval_status": None,
        "trade_proposal": {
            "id": "prop-1", "action": "BUY", "quantity": 10,
            "entry_price": 70000,
        },
        "reasoning_log": [],
    }
    return AnalysisSession(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        status=SessionStatus.AWAITING_APPROVAL,
        state=state,
        ticker="005930",
        display_name="삼성전자",
        stk_cd="005930",
        stk_nm="삼성전자",
    )


class _FakeSessionManager:
    def __init__(self, session: AnalysisSession | None):
        self._session = session

    async def get_session(self, session_id: str):
        if self._session is not None and self._session.session_id == session_id:
            return self._session
        return None

    async def update_state(self, session_id: str, updates: dict, last_node=None):
        if self._session is None or self._session.session_id != session_id:
            raise KeyError(session_id)
        self._session.state.update(updates)
        if last_node:
            self._session.last_node = last_node


class _FakeGraph:
    """Resume that lands the execution node's output straight into state."""

    def __init__(self, resume_events):
        self._resume_events = resume_events
        self.aupdate_state = AsyncMock()

    def astream(self, _input, _config):
        events = list(self._resume_events)

        async def gen():
            for e in events:
                yield e

        return gen()


class _FakeTelegram:
    is_ready = True

    def __init__(self):
        self.executed_calls = []
        self.pending_calls = []
        self.rejected_calls = []

    async def send_trade_executed(self, **kwargs):
        self.executed_calls.append(kwargs)

    async def send_trade_pending(self, **kwargs):
        self.pending_calls.append(kwargs)

    async def send_trade_rejected(self, **kwargs):
        self.rejected_calls.append(kwargs)

    async def send_watch_list_added(self, **kwargs):
        pass


@pytest.fixture
def wired(monkeypatch):
    holder: dict = {"manager": _FakeSessionManager(None)}

    async def fake_get_session_manager():
        return holder["manager"]

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    def set_sm_session(sm_session):
        holder["manager"] = _FakeSessionManager(sm_session)

    async def fake_commit_session_state(session_id, updates, **kw):
        session = holder["manager"]._session
        if session is None or session.session_id != session_id:
            raise KeyError(session_id)
        session.state.update(updates)

    async def fake_commit_session_status(session_id, new_status, **kw):
        session = holder["manager"]._session
        if session is None or session.session_id != session_id:
            raise KeyError(session_id)
        session.status = new_status

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(approval_module, "commit_session_state", fake_commit_session_state)
    monkeypatch.setattr(approval_module, "commit_session_status", fake_commit_session_status)
    monkeypatch.setattr(approval_module, "mirror_session_status", noop)
    monkeypatch.setattr(approval_module, "broadcast_watch_added", noop)

    ws_calls = {"executed": [], "queued": [], "rejected": []}

    async def fake_broadcast_trade_executed(**kwargs):
        ws_calls["executed"].append(kwargs)

    async def fake_broadcast_trade_queued(**kwargs):
        ws_calls["queued"].append(kwargs)

    async def fake_broadcast_trade_rejected(**kwargs):
        ws_calls["rejected"].append(kwargs)

    monkeypatch.setattr(approval_module, "broadcast_trade_executed", fake_broadcast_trade_executed)
    monkeypatch.setattr(approval_module, "broadcast_trade_queued", fake_broadcast_trade_queued)
    monkeypatch.setattr(approval_module, "broadcast_trade_rejected", fake_broadcast_trade_rejected)

    telegram = _FakeTelegram()

    async def fake_get_telegram_notifier():
        return telegram

    monkeypatch.setattr(approval_module, "get_telegram_notifier", fake_get_telegram_notifier)

    async def fake_get_trading_coordinator():
        raise RuntimeError("no coordinator in unit test")

    monkeypatch.setattr(approval_module, "get_trading_coordinator", fake_get_trading_coordinator)

    def set_graph(graph):
        monkeypatch.setattr(approval_module, "get_kr_stock_trading_graph", lambda: graph)

    return holder, ws_calls, telegram, set_sm_session, set_graph


@pytest.mark.asyncio
async def test_completed_fill_keeps_executed_wording(wired):
    """execution_status=='completed' -> unchanged 'executed' notification."""
    holder, ws_calls, telegram, set_sm_session, set_graph = wired
    set_sm_session(_sm_session("s1"))
    set_graph(_FakeGraph([
        {"execution": {
            "execution_status": "completed",
            "awaiting_approval": False,
            "order_response": {"ord_no": "ORD-1", "return_code": 0, "return_msg": "ok"},
        }},
    ]))

    result = await approval_module.submit_decision("s1", "approved", actor="system")

    assert len(ws_calls["executed"]) == 1
    assert ws_calls["queued"] == []
    assert ws_calls["rejected"] == []
    assert len(telegram.executed_calls) == 1
    assert telegram.pending_calls == []
    assert telegram.rejected_calls == []
    assert result.execution_status == "completed"
    assert "executed successfully" in result.message.lower()


@pytest.mark.asyncio
async def test_placed_pending_fill_sends_honest_pending_wording(wired):
    """execution_status=='placed_pending_fill' -> pending/queued wording,
    never the 'executed' notification, carrying ord_no through."""
    holder, ws_calls, telegram, set_sm_session, set_graph = wired
    set_sm_session(_sm_session("s2"))
    set_graph(_FakeGraph([
        {"execution": {
            "execution_status": "placed_pending_fill",
            "awaiting_approval": False,
            "order_response": {"ord_no": "ORD-2", "return_code": 0, "return_msg": "ok"},
        }},
    ]))

    result = await approval_module.submit_decision("s2", "approved", actor="system")

    # Never claims a fill.
    assert ws_calls["executed"] == []
    assert telegram.executed_calls == []

    assert len(ws_calls["queued"]) == 1
    queued = ws_calls["queued"][0]
    assert "체결 대기" in queued["expected_execution"]
    assert "ORD-2" in queued["expected_execution"]

    assert len(telegram.pending_calls) == 1
    assert telegram.pending_calls[0]["ord_no"] == "ORD-2"

    assert result.execution_status == "placed_pending_fill"
    assert "executed successfully" not in result.message.lower()
    assert "pending" in result.message.lower()


@pytest.mark.asyncio
async def test_failed_execution_sends_honest_failure_wording(wired):
    """execution_status=='failed' -> rejected/failed wording, never claims
    an execution."""
    holder, ws_calls, telegram, set_sm_session, set_graph = wired
    set_sm_session(_sm_session("s3"))
    set_graph(_FakeGraph([
        {"execution": {
            "execution_status": "failed",
            "awaiting_approval": False,
            "error": "주문 거부: 잔고 부족",
        }},
    ]))

    result = await approval_module.submit_decision("s3", "approved", actor="system")

    assert ws_calls["executed"] == []
    assert ws_calls["queued"] == []
    assert telegram.executed_calls == []
    assert telegram.pending_calls == []

    assert len(ws_calls["rejected"]) == 1
    assert "잔고 부족" in ws_calls["rejected"][0]["reason"]

    assert len(telegram.rejected_calls) == 1
    assert "잔고 부족" in telegram.rejected_calls[0]["reason"]

    assert result.execution_status == "failed"
    assert "executed successfully" not in result.message.lower()
    assert "failed" in result.message.lower()
