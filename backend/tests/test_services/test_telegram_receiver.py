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


# -------------------------------------------
# 6. start_telegram_receiver — polling error_callback observability
#    (TG-1 리뷰픽스 Finding 1)
# -------------------------------------------


async def test_start_receiver_wires_error_callback_that_logs_polling_errors(monkeypatch):
    """`updater.start_polling()` returns before the first get_updates completes
    (PTB 22.5), so a 409 Conflict from a second poller never reaches the
    try/except around start_telegram_receiver -- it can only be observed via
    `error_callback`. Assert the callback is actually wired and that invoking
    it (as PTB would on a polling error) logs `telegram_receiver_polling_error`."""
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config())

    mock_updater = MagicMock()
    mock_updater.start_polling = AsyncMock(return_value=None)
    mock_updater.stop = AsyncMock(return_value=None)

    mock_application = MagicMock()
    mock_application.updater = mock_updater
    mock_application.initialize = AsyncMock(return_value=None)
    mock_application.start = AsyncMock(return_value=None)
    mock_application.add_handler = MagicMock()

    mock_builder = MagicMock()
    mock_builder.token.return_value.build.return_value = mock_application
    monkeypatch.setattr(receiver.Application, "builder", lambda: mock_builder)

    result = await receiver.start_telegram_receiver()

    assert result is mock_application
    mock_updater.start_polling.assert_awaited_once()
    _, kwargs = mock_updater.start_polling.await_args
    assert "error_callback" in kwargs
    error_callback = kwargs["error_callback"]

    with structlog.testing.capture_logs() as logs:
        error_callback(RuntimeError("Conflict: terminated by other getUpdates request"))

    events = [log for log in logs if log.get("event") == "telegram_receiver_polling_error"]
    assert len(events) == 1
    assert "Conflict" in events[0]["error"]


# -------------------------------------------
# 7. start_telegram_receiver — start failure shuts down a partially-initialized
#    Application (TG-1 리뷰픽스 Finding 2)
# -------------------------------------------


async def test_start_receiver_initialize_failure_shuts_down_application(monkeypatch):
    """`Bot.initialize()` opens the httpx connection pool BEFORE token
    validation (get_me()) -- on InvalidToken (or any initialize failure) the
    Application must be shut down (best-effort) rather than abandoned, or the
    pool leaks. Returns None either way (never-raise contract preserved)."""
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config())

    mock_application = MagicMock()
    mock_application.initialize = AsyncMock(side_effect=RuntimeError("invalid token"))
    mock_application.shutdown = AsyncMock(return_value=None)
    mock_application.add_handler = MagicMock()

    mock_builder = MagicMock()
    mock_builder.token.return_value.build.return_value = mock_application
    monkeypatch.setattr(receiver.Application, "builder", lambda: mock_builder)

    result = await receiver.start_telegram_receiver()

    assert result is None
    mock_application.shutdown.assert_awaited_once()


async def test_start_receiver_shutdown_failure_after_initialize_failure_still_returns_none(
    monkeypatch,
):
    """Even if the best-effort shutdown() itself raises, start_telegram_receiver
    must still return None without propagating (never-raise contract)."""
    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config())

    mock_application = MagicMock()
    mock_application.initialize = AsyncMock(side_effect=RuntimeError("invalid token"))
    mock_application.shutdown = AsyncMock(side_effect=RuntimeError("shutdown also failed"))
    mock_application.add_handler = MagicMock()

    mock_builder = MagicMock()
    mock_builder.token.return_value.build.return_value = mock_application
    monkeypatch.setattr(receiver.Application, "builder", lambda: mock_builder)

    result = await receiver.start_telegram_receiver()

    assert result is None
    mock_application.shutdown.assert_awaited_once()


# -------------------------------------------
# 8. start_telegram_receiver — explicitly imports commands.py so TG-2's
#    /status /positions /pending /report register even if nothing else in
#    the import graph happened to import services.telegram.commands first
#    (TG-1 carryover finding: register_command is an import-time side
#    effect -- a module that never gets imported never registers).
# -------------------------------------------


async def test_start_receiver_wires_tg2_commands_via_explicit_import(monkeypatch):
    import sys

    monkeypatch.setattr(receiver, "get_telegram_config", lambda: _config())

    # Force a REAL re-import: drop the cached module AND the attribute the
    # import system stashed on the parent package (services.telegram) --
    # `from . import commands` resolves via `hasattr(package, "commands")`
    # BEFORE consulting sys.modules, so removing it from sys.modules alone
    # is not enough to force re-execution of commands.py's top-level
    # register_command(...) calls. Then reset the registry to only the
    # built-in "help", simulating a process where commands.py was never
    # imported by anything else. If the explicit `from . import commands`
    # inside start_telegram_receiver were ever removed, this would fail
    # (_COMMAND_REGISTRY would stay help-only).
    import services.telegram as telegram_pkg

    monkeypatch.delitem(sys.modules, "services.telegram.commands", raising=False)
    monkeypatch.delattr(telegram_pkg, "commands", raising=False)
    monkeypatch.setattr(receiver, "_COMMAND_REGISTRY", {"help": receiver._COMMAND_REGISTRY["help"]})

    mock_updater = MagicMock()
    mock_updater.start_polling = AsyncMock(return_value=None)
    mock_updater.stop = AsyncMock(return_value=None)

    mock_application = MagicMock()
    mock_application.updater = mock_updater
    mock_application.initialize = AsyncMock(return_value=None)
    mock_application.start = AsyncMock(return_value=None)
    mock_application.add_handler = MagicMock()

    mock_builder = MagicMock()
    mock_builder.token.return_value.build.return_value = mock_application
    monkeypatch.setattr(receiver.Application, "builder", lambda: mock_builder)

    result = await receiver.start_telegram_receiver()

    assert result is mock_application
    for name in ("status", "positions", "pending", "report"):
        assert name in receiver._COMMAND_REGISTRY
