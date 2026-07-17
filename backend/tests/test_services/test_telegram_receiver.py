"""TG-1: 수신 기반 (services/telegram/receiver.py).

Covers the 5 scenarios pinned by the task brief:

  1. `_authorized(update)` — matching / mismatched chat_id (2 tests).
  2. `/help` handler invoked directly on a mock Update (never a real
     polling loop) — asserts the reply call, mirroring the repo's
     `test_telegram_daily_summary.py` AsyncMock convention (PTB objects
     are frozen — can't set attributes on a real Update/Message, so the
     whole Update is built as a MagicMock/AsyncMock tree instead).
  3. `/help` from an unauthorized chat — silent (no reply) + a
     `telegram_unauthorized_chat` warning log (captured via
     `structlog.testing.capture_logs()`, the repo's established pattern
     for asserting structlog output, see test_coin_fill_slippage.py).
  4. `start_telegram_receiver()` when `Application.builder()` raises —
     best-effort: returns None, never raises.
  5. `stop_telegram_receiver()` when the receiver was never started —
     no-op, never raises.

No real network/polling/send anywhere — `Application.builder` itself is
monkeypatched to raise in the one test that touches it; every other test
only exercises `_authorized`/the wrapped `/help` handler directly.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing

from services.telegram import receiver
from services.telegram.config import TelegramConfig

pytestmark = pytest.mark.asyncio


def _config(chat_id="12345", enabled=True, token="test-token"):
    return TelegramConfig(
        TELEGRAM_ENABLED=enabled,
        TELEGRAM_BOT_TOKEN=token,
        TELEGRAM_CHAT_ID=chat_id,
    )


def _make_update(chat_id):
    """A MagicMock tree standing in for a PTB Update -- real Update/Message
    objects are frozen (can't assign .effective_chat etc after construction),
    so tests build the whole tree as mocks (repo AsyncMock convention)."""
    chat = MagicMock()
    chat.id = chat_id

    message = AsyncMock()

    update = MagicMock()
    update.effective_chat = chat
    update.effective_message = message
    update.message = message
    return update, message


@pytest.fixture(autouse=True)
def _reset_application_singleton(monkeypatch):
    """`_application` is a module-level singleton -- isolate tests from each
    other regardless of run order."""
    monkeypatch.setattr(receiver, "_application", None)


# -------------------------------------------
# 1. _authorized
# -------------------------------------------


async def test_authorized_matching_chat_id_returns_true(monkeypatch):
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config(chat_id="12345"))
    update, _ = _make_update(12345)  # int on the wire, str in config

    assert receiver._authorized(update) is True


async def test_authorized_mismatched_chat_id_returns_false(monkeypatch):
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config(chat_id="12345"))
    update, _ = _make_update(99999)

    assert receiver._authorized(update) is False


# -------------------------------------------
# 2. /help handler (direct await on a mock Update)
# -------------------------------------------


async def test_help_handler_replies_with_registered_commands(monkeypatch):
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config(chat_id="12345"))
    update, message = _make_update(12345)
    wrapped = receiver._wrap_command("help", receiver._COMMAND_REGISTRY["help"])

    await wrapped(update, MagicMock())

    message.reply_text.assert_awaited_once()
    sent_text = message.reply_text.await_args.args[0]
    assert "/help" in sent_text


# -------------------------------------------
# 3. /help from an unauthorized chat -> silent + warning log
# -------------------------------------------


async def test_help_handler_unauthorized_chat_silently_ignored_and_warns(monkeypatch):
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config(chat_id="12345"))
    update, message = _make_update(99999)
    wrapped = receiver._wrap_command("help", receiver._COMMAND_REGISTRY["help"])

    with structlog.testing.capture_logs() as logs:
        await wrapped(update, MagicMock())

    message.reply_text.assert_not_called()
    warnings = [log for log in logs if log.get("event") == "telegram_unauthorized_chat"]
    assert len(warnings) == 1
    assert warnings[0]["chat_id"] == 99999


# -------------------------------------------
# 4. start_telegram_receiver — builder failure is best-effort
# -------------------------------------------


async def test_start_receiver_builder_failure_returns_none_without_raising(monkeypatch):
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config())

    def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(receiver.Application, "builder", _raise)

    result = await receiver.start_telegram_receiver()

    assert result is None


# -------------------------------------------
# 5. stop_telegram_receiver — never started is a no-op
# -------------------------------------------


async def test_stop_receiver_never_started_is_noop():
    # _reset_application_singleton fixture already guarantees _application is None.
    await receiver.stop_telegram_receiver()  # must not raise
