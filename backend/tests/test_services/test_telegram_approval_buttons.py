"""TG-3: 승인/거부 인라인 버튼 -- 원격 거부권.

Covers the task brief's Step 1 contract:

  1. approve callback success -- `approval.submit_decision` is called with
     actor="telegram" and the LIVE full proposal id pinned.
  2. reject callback -- same, decision="rejected".
  3. pid8 mismatch (stale button) -- submit_decision is NEVER called; the
     message is edited with the stale-proposal text.
  4. submit_decision raises HTTPException -- its `.detail` is edited into
     the message.
  5. unauthorized chat_id -- silent (no answer/edit/submit) + a
     `telegram_unauthorized_chat` warning log. Dispatched through the REAL
     `receiver._dispatch_callback` (not a hand-called handler) -- this is
     the first test in the repo to exercise the callback dispatch path
     end-to-end (TG-1 carryover note: "실배선은 TG-1 이후 미검증").
  6. producer wiring -- `_finalize_awaiting_transition`'s success path
     (kr_stocks/analysis.py, via `maybe_schedule_auto_approve`) sends
     exactly once; its fail-closed commit-failure path never calls
     `maybe_schedule_auto_approve` at all, so it never sends either.
  7. approval.py's actor-pin widening (`actor in ("system", "telegram")`)
     -- actor="telegram" with a stale `expected_proposal_id` now stands
     down exactly like actor="system" already did.
  8. injector `_notify_pending` replacement -- `maybe_schedule_auto_approve`
     now sends an approval-request button unconditionally: a plain-HITL
     (gate-denied) session gets one with `auto_approve_at=None`, and an
     autonomous (gate-allowed) session gets one with a non-None countdown
     -- proving the single dispatch point now covers both HITL and
     autonomous sessions (spec F1's "HITL/자율 양쪽 커버 지점").

Plus direct unit coverage of `TelegramNotifier.send_approval_request` /
`_send_message`'s new `reply_markup` passthrough (service.py).

No real network/polling/send anywhere: PTB Update/CallbackQuery trees are
built as MagicMock/AsyncMock (PTB objects are frozen -- can't assign
attributes after construction, repo convention, see
test_telegram_receiver.py), and every SessionManager /
`approval.submit_decision` / outbound `TelegramNotifier` touchpoint is
either monkeypatched or constructed directly with an explicit
`TelegramConfig` (mirrors test_telegram_daily_summary.py's
`_configured_notifier` helper) -- never the real `.env`-backed singleton.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing
from fastapi import HTTPException

import app.api.routes._autonomy_injector as injector_module
import services.session_manager as sm_module
from services.autonomy import GateDecision
from services.session_manager import MarketType, SessionManager, SessionStatus
from services.telegram import callbacks, receiver
from services.telegram.config import TelegramConfig
from services.telegram.service import TelegramNotifier

pytestmark = pytest.mark.asyncio

PROPOSAL_ID = "prop-abcdefgh-extra"
PID8 = PROPOSAL_ID[:8]  # "prop-abc"


# -------------------------------------------
# Shared helpers
# -------------------------------------------


def _config(chat_id: str = "12345") -> TelegramConfig:
    return TelegramConfig(
        TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="test-token", TELEGRAM_CHAT_ID=chat_id
    )


def _make_callback_update(chat_id, data: str):
    """A MagicMock tree standing in for a PTB callback-query Update -- real
    Update/CallbackQuery objects are frozen (test_telegram_receiver.py
    convention)."""
    chat = MagicMock()
    chat.id = chat_id

    query = AsyncMock()
    query.data = data

    update = MagicMock()
    update.effective_chat = chat
    update.callback_query = query
    return update, query


def _seed_live_session(monkeypatch, proposal_id: str = PROPOSAL_ID):
    """Stands in for `callbacks._fetch_live_session` -- the mock-injection
    seam for the callback handler's SessionManager lookup."""
    session = SimpleNamespace(state={"trade_proposal": {"id": proposal_id, "action": "BUY"}})

    async def fake_fetch(session_id):
        return session

    monkeypatch.setattr(callbacks, "_fetch_live_session", fake_fetch)
    return session


def _record_submit_decision(monkeypatch, return_value=None, side_effect=None):
    """Patches the REAL `approval.submit_decision` target `callbacks._submit`
    lazily imports -- mirrors test_autonomy_injector.py's `submit_recorder`
    fixture so the exact (actor, expected_proposal_id) pin is verifiable."""
    calls = []

    async def fake_submit(
        session_id, decision, feedback=None, modifications=None,
        actor="user", expected_proposal_id=None,
    ):
        calls.append({
            "session_id": session_id, "decision": decision,
            "actor": actor, "expected_proposal_id": expected_proposal_id,
        })
        if side_effect is not None:
            raise side_effect
        return return_value

    monkeypatch.setattr("app.api.routes.approval.submit_decision", fake_submit)
    return calls


# -------------------------------------------
# 1-4: callback handler unit tests
# -------------------------------------------


async def test_approve_callback_success_pins_actor_telegram_and_live_proposal_id(monkeypatch):
    _seed_live_session(monkeypatch)
    calls = _record_submit_decision(monkeypatch)

    update, query = _make_callback_update(12345, f"a:sess-1:{PID8}")
    await callbacks.handle_approve_callback(update, MagicMock())

    query.answer.assert_awaited_once()
    assert calls == [{
        "session_id": "sess-1", "decision": "approved",
        "actor": "telegram", "expected_proposal_id": PROPOSAL_ID,
    }]
    query.edit_message_text.assert_awaited_once()
    args, kwargs = query.edit_message_text.await_args
    assert "승인" in args[0]
    assert kwargs["reply_markup"] is None


async def test_reject_callback_success_pins_actor_telegram_and_live_proposal_id(monkeypatch):
    _seed_live_session(monkeypatch)
    calls = _record_submit_decision(monkeypatch)

    update, query = _make_callback_update(12345, f"r:sess-2:{PID8}")
    await callbacks.handle_reject_callback(update, MagicMock())

    query.answer.assert_awaited_once()
    assert calls == [{
        "session_id": "sess-2", "decision": "rejected",
        "actor": "telegram", "expected_proposal_id": PROPOSAL_ID,
    }]
    args, kwargs = query.edit_message_text.await_args
    assert "거부" in args[0]
    assert kwargs["reply_markup"] is None


async def test_pid8_mismatch_never_calls_submit_and_edits_stale_text(monkeypatch):
    _seed_live_session(monkeypatch, proposal_id=PROPOSAL_ID)  # live id starts with PID8
    calls = _record_submit_decision(monkeypatch)

    update, query = _make_callback_update(12345, "a:sess-3:zzzzzzzz")  # wrong pid8
    await callbacks.handle_approve_callback(update, MagicMock())

    query.answer.assert_awaited_once()
    assert calls == []  # submit_decision NEVER called
    args, kwargs = query.edit_message_text.await_args
    assert "제안이 변경되어 처리할 수 없습니다" in args[0]
    assert kwargs["reply_markup"] is None


async def test_session_vanished_never_calls_submit_and_edits_stale_text(monkeypatch):
    async def fake_fetch(session_id):
        return None

    monkeypatch.setattr(callbacks, "_fetch_live_session", fake_fetch)
    calls = _record_submit_decision(monkeypatch)

    update, query = _make_callback_update(12345, f"a:sess-gone:{PID8}")
    await callbacks.handle_approve_callback(update, MagicMock())

    assert calls == []
    args, _ = query.edit_message_text.await_args
    assert "제안이 변경되어 처리할 수 없습니다" in args[0]


async def test_httpexception_from_submit_decision_edits_detail_into_message(monkeypatch):
    _seed_live_session(monkeypatch)
    _record_submit_decision(
        monkeypatch, side_effect=HTTPException(status_code=409, detail="이미 처리됨 — 취소 불가")
    )

    update, query = _make_callback_update(12345, f"a:sess-4:{PID8}")
    await callbacks.handle_approve_callback(update, MagicMock())

    args, kwargs = query.edit_message_text.await_args
    assert args[0] == "오류: 이미 처리됨 — 취소 불가"
    assert kwargs["reply_markup"] is None


async def test_stood_down_result_edits_stale_text(monkeypatch):
    """submit_decision's F4b stand-down shape ({"status": "stood_down", ...})
    -- the TOCTOU-closing re-check inside the lock -- must read the same as
    an outside-the-lock pid8 mismatch to the Telegram user."""
    _seed_live_session(monkeypatch)
    _record_submit_decision(monkeypatch, return_value={"status": "stood_down", "reason": "proposal_changed"})

    update, query = _make_callback_update(12345, f"a:sess-5:{PID8}")
    await callbacks.handle_approve_callback(update, MagicMock())

    args, _ = query.edit_message_text.await_args
    assert "제안이 변경되어 처리할 수 없습니다" in args[0]


async def test_invalid_callback_data_shows_generic_error_without_touching_sm(monkeypatch):
    fetch_calls = []

    async def fake_fetch(session_id):
        fetch_calls.append(session_id)
        return None

    monkeypatch.setattr(callbacks, "_fetch_live_session", fake_fetch)
    calls = _record_submit_decision(monkeypatch)

    update, query = _make_callback_update(12345, "a:sess-6:")  # empty pid8
    await callbacks.handle_approve_callback(update, MagicMock())

    query.answer.assert_awaited_once()
    assert fetch_calls == []
    assert calls == []
    args, _ = query.edit_message_text.await_args
    assert "잘못된 요청입니다" in args[0]


# -------------------------------------------
# 5: unauthorized chat -- real dispatch path (chat_id security wrapper)
# -------------------------------------------


async def test_unauthorized_chat_is_silent_and_never_reaches_the_handler(monkeypatch):
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config(chat_id="12345"))
    _seed_live_session(monkeypatch)
    calls = _record_submit_decision(monkeypatch)

    update, query = _make_callback_update(99999, f"a:sess-7:{PID8}")

    with structlog.testing.capture_logs() as logs:
        await receiver._dispatch_callback(update, MagicMock())

    query.answer.assert_not_awaited()
    query.edit_message_text.assert_not_awaited()
    assert calls == []
    warnings = [log for log in logs if log.get("event") == "telegram_unauthorized_chat"]
    assert len(warnings) == 1
    assert warnings[0]["chat_id"] == 99999


async def test_authorized_chat_reaches_the_handler_via_real_dispatch(monkeypatch):
    """Positive counterpart -- proves the registry/prefix-match/wrapper
    chain actually reaches callbacks.handle_approve_callback for a matching
    chat_id (not just that unauthorized is silent)."""
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config(chat_id="12345"))
    _seed_live_session(monkeypatch)
    calls = _record_submit_decision(monkeypatch)

    update, query = _make_callback_update(12345, f"a:sess-8:{PID8}")

    await receiver._dispatch_callback(update, MagicMock())

    query.answer.assert_awaited_once()
    assert calls == [{
        "session_id": "sess-8", "decision": "approved",
        "actor": "telegram", "expected_proposal_id": PROPOSAL_ID,
    }]


# -------------------------------------------
# SessionManager test-isolation fixture (mirrors test_autonomy_injector.py)
# -------------------------------------------

TEST_DB_PATH = "data/test_telegram_approval_buttons.db"


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


def _fake_notifier_recorder():
    return SimpleNamespace(is_ready=True, send_approval_request=AsyncMock(return_value=True))


# -------------------------------------------
# 6: producer wiring (kr_stocks/analysis.py's _finalize_awaiting_transition)
# -------------------------------------------


async def test_producer_success_path_sends_approval_button_exactly_once(sm, monkeypatch):
    from app.api.routes.kr_stocks import analysis as kr_analysis

    session_id = "prod-wire-1"
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        state={
            "trade_proposal": {"id": "p1", "action": "BUY", "quantity": 10, "entry_price": 50000},
            "reasoning_log": [],
        },
    )

    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="hitl mode", check="market_mode")

    monkeypatch.setattr(injector_module, "check_autonomy", deny_gate)

    fake_notifier = _fake_notifier_recorder()

    async def fake_get_notifier():
        return fake_notifier

    monkeypatch.setattr(injector_module, "get_telegram_notifier", fake_get_notifier)

    await kr_analysis._finalize_awaiting_transition(session_id)

    fake_notifier.send_approval_request.assert_awaited_once()
    args = fake_notifier.send_approval_request.await_args.args
    assert args[0] == session_id
    assert args[1] == "kiwoom"
    assert args[2]["id"] == "p1"
    assert args[3] is None  # plain HITL -- no countdown


async def test_producer_failclosed_path_never_sends_approval_button(sm, monkeypatch):
    from app.api.routes.kr_stocks import analysis as kr_analysis

    session_id = "prod-wire-2"
    await sm.create_session(
        session_id=session_id,
        market_type=MarketType.KIWOOM,
        ticker="005930",
        display_name="삼성전자",
        state={"trade_proposal": {"id": "p1", "action": "BUY"}, "reasoning_log": []},
    )

    async def failing_commit(session_id, status, **kw):
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(kr_analysis, "commit_session_status", failing_commit)

    fake_notifier = _fake_notifier_recorder()

    async def fake_get_notifier():
        return fake_notifier

    monkeypatch.setattr(injector_module, "get_telegram_notifier", fake_get_notifier)

    await kr_analysis._finalize_awaiting_transition(session_id)

    fake_notifier.send_approval_request.assert_not_awaited()


# -------------------------------------------
# 7: approval.py actor-pin widening (system -> system+telegram)
# -------------------------------------------


async def test_approval_pin_widened_to_telegram_actor_stale_proposal_stands_down(monkeypatch):
    from app.api.routes import approval as approval_module

    session_id = "wt-telegram-pin-1"
    sm_session = SimpleNamespace(
        status=SessionStatus.AWAITING_APPROVAL,
        state={"awaiting_approval": True, "trade_proposal": {"id": "p2-NEW", "action": "BUY"}},
    )

    class _FakeSM:
        async def get_session(self, sid):
            return sm_session if sid == session_id else None

    async def fake_get_session_manager():
        return _FakeSM()

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    result = await approval_module.submit_decision(
        session_id, "approved", actor="telegram", expected_proposal_id="p1-STALE",
    )

    assert result == {"status": "stood_down", "reason": "proposal_changed"}


async def test_approval_pin_system_actor_behavior_unchanged_by_widening(monkeypatch):
    """Regression pin: actor='system' must still stand down on a stale id
    exactly as before -- the tuple widening must not have altered its own
    branch (system stays in the tuple)."""
    from app.api.routes import approval as approval_module

    session_id = "wt-system-pin-1"
    sm_session = SimpleNamespace(
        status=SessionStatus.AWAITING_APPROVAL,
        state={"awaiting_approval": True, "trade_proposal": {"id": "p2-NEW", "action": "BUY"}},
    )

    class _FakeSM:
        async def get_session(self, sid):
            return sm_session if sid == session_id else None

    async def fake_get_session_manager():
        return _FakeSM()

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    result = await approval_module.submit_decision(
        session_id, "approved", actor="system", expected_proposal_id="p1-STALE",
    )

    assert result == {"status": "stood_down", "reason": "proposal_changed"}


# -------------------------------------------
# 8: injector _notify_pending replacement -- covers HITL AND autonomous
# -------------------------------------------


async def test_maybe_schedule_auto_approve_sends_button_without_countdown_when_gate_denies(
    sm, monkeypatch
):
    session_id = "inj-tg3-deny"
    await sm.create_session(
        session_id=session_id, market_type=MarketType.KIWOOM, ticker="005930",
        display_name="삼성전자",
        state={"trade_proposal": {"id": "p1", "action": "BUY", "quantity": 10, "entry_price": 50000},
               "reasoning_log": []},
    )

    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="AUTONOMY_ENABLED is off", check="master_gate")

    monkeypatch.setattr(injector_module, "check_autonomy", deny_gate)

    fake_notifier = _fake_notifier_recorder()

    async def fake_get_notifier():
        return fake_notifier

    monkeypatch.setattr(injector_module, "get_telegram_notifier", fake_get_notifier)

    await injector_module.maybe_schedule_auto_approve(session_id, "kiwoom")

    fake_notifier.send_approval_request.assert_awaited_once()
    args = fake_notifier.send_approval_request.await_args.args
    assert args[3] is None  # HITL: no auto-approve countdown


async def test_maybe_schedule_auto_approve_sends_button_with_countdown_when_gate_allows(
    sm, monkeypatch, fast_grace
):
    session_id = "inj-tg3-allow"
    await sm.create_session(
        session_id=session_id, market_type=MarketType.KIWOOM, ticker="005930",
        display_name="삼성전자",
        state={"trade_proposal": {"id": "p1", "action": "BUY", "quantity": 10, "entry_price": 50000},
               "reasoning_log": []},
    )
    await sm.update_status(session_id, SessionStatus.AWAITING_APPROVAL)

    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(injector_module, "check_autonomy", allow_gate)

    async def noop_submit(*a, **k):
        return None

    monkeypatch.setattr("app.api.routes.approval.submit_decision", noop_submit)

    fake_notifier = _fake_notifier_recorder()

    async def fake_get_notifier():
        return fake_notifier

    monkeypatch.setattr(injector_module, "get_telegram_notifier", fake_get_notifier)

    await injector_module.maybe_schedule_auto_approve(session_id, "kiwoom")

    fake_notifier.send_approval_request.assert_awaited_once()
    args = fake_notifier.send_approval_request.await_args.args
    assert args[0] == session_id
    assert args[1] == "kiwoom"
    assert args[2]["id"] == "p1"
    assert args[3] is not None  # autonomous: countdown present (ISO string)

    await asyncio.sleep(0.1)  # let the fast-grace background task settle


async def test_maybe_schedule_auto_approve_never_sends_when_session_missing(sm, monkeypatch):
    fake_notifier = _fake_notifier_recorder()

    async def fake_get_notifier():
        return fake_notifier

    monkeypatch.setattr(injector_module, "get_telegram_notifier", fake_get_notifier)

    await injector_module.maybe_schedule_auto_approve("does-not-exist", "kiwoom")

    fake_notifier.send_approval_request.assert_not_awaited()


# -------------------------------------------
# service.py: TelegramNotifier.send_approval_request unit coverage
# -------------------------------------------


def _configured_notifier(notify_trade_alerts: bool = True) -> TelegramNotifier:
    """A notifier that is 'ready' without touching the network -- mirrors
    test_telegram_daily_summary.py's `_configured_notifier` helper."""
    config = TelegramConfig(
        TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN="test-token", TELEGRAM_CHAT_ID="12345",
        TELEGRAM_NOTIFY_TRADE_ALERTS=notify_trade_alerts,
    )
    notifier = TelegramNotifier(config=config)
    notifier._initialized = True
    notifier._bot = AsyncMock()
    return notifier


async def test_send_approval_request_builds_inline_keyboard_with_pid8_callback_data():
    notifier = _configured_notifier()
    proposal = {"id": PROPOSAL_ID, "action": "BUY", "quantity": 10, "entry_price": 71000}

    result = await notifier.send_approval_request("sess-123", "kiwoom", proposal, None)

    assert result is True
    notifier._bot.send_message.assert_awaited_once()
    kwargs = notifier._bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == "12345"
    keyboard = kwargs["reply_markup"]
    approve_btn, reject_btn = keyboard.inline_keyboard[0]
    assert approve_btn.callback_data == f"a:sess-123:{PID8}"
    assert reject_btn.callback_data == f"r:sess-123:{PID8}"
    assert len(approve_btn.callback_data.encode("utf-8")) <= 64
    assert "BUY" in kwargs["text"]


async def test_send_approval_request_includes_countdown_line_when_auto_approve_at_given():
    notifier = _configured_notifier()
    future = (datetime.now(timezone.utc) + timedelta(seconds=42)).isoformat()

    await notifier.send_approval_request("sess-1", "kiwoom", {"id": "p1", "action": "BUY"}, future)

    text = notifier._bot.send_message.await_args.kwargs["text"]
    assert "자동승인" in text


async def test_send_approval_request_omits_countdown_when_auto_approve_at_none():
    notifier = _configured_notifier()

    await notifier.send_approval_request("sess-1", "kiwoom", {"id": "p1", "action": "BUY"}, None)

    text = notifier._bot.send_message.await_args.kwargs["text"]
    assert "자동승인" not in text


async def test_send_approval_request_returns_false_when_trade_alerts_disabled():
    notifier = _configured_notifier(notify_trade_alerts=False)

    result = await notifier.send_approval_request("sess-1", "kiwoom", {"id": "p1", "action": "BUY"}, None)

    assert result is False
    notifier._bot.send_message.assert_not_awaited()


async def test_send_approval_request_returns_false_when_not_initialized():
    notifier = TelegramNotifier(
        config=TelegramConfig(TELEGRAM_ENABLED=False, TELEGRAM_BOT_TOKEN=None, TELEGRAM_CHAT_ID=None)
    )

    result = await notifier.send_approval_request("sess-1", "kiwoom", {"id": "p1", "action": "BUY"}, None)

    assert result is False


async def test_send_message_reply_markup_defaults_to_none_for_existing_callers():
    """Byte-invariant pin: every pre-TG-3 send_* call path goes through
    `_send_message` without a `reply_markup` argument -- confirm the default
    still produces `reply_markup=None` on the underlying bot call (identical
    to PTB's own default)."""
    notifier = _configured_notifier()

    await notifier.send_message("hello")

    kwargs = notifier._bot.send_message.await_args.kwargs
    assert kwargs["reply_markup"] is None
