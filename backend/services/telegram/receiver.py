"""
Telegram Receiver Service (TG-1)

Inbound PTB `Application` (long polling) for the two-way Telegram arc
(TG-1..TG-4, see docs/superpowers/specs/2026-07-17-telegram-twoway-design.md
S1). Runs as a SEPARATE Application instance alongside the existing
outbound `TelegramNotifier` (services/telegram/service.py) -- "공존 방식
A" in the spec: the notifier is untouched, and getUpdates has exactly one
consumer (this Application) so there is no polling conflict between the
two.

This module owns:

  - `start_telegram_receiver()` / `stop_telegram_receiver()`: FastAPI
    lifespan hooks. Both are best-effort and NEVER raise -- a receiver
    failure (missing config, bad token, 409 Conflict from a second
    poller, etc.) must never block server startup, outbound
    notifications, or the HITL approval pipeline.
  - `register_command(name, handler)` / `register_callback(pattern_prefix,
    handler)`: module-level registries populated at IMPORT time by later
    tasks (TG-2 approval buttons, TG-3 /halt+/auto, TG-4 read-only
    queries). `start_telegram_receiver()` wires every registered entry
    into a CommandHandler/CallbackQueryHandler and applies the shared
    security wrapper (`_wrap_command`/`_wrap_callback`) so no individual
    handler can forget the chat_id check or the never-raise contract --
    the security invariants live in exactly one place.
  - `_authorized(update)`: `effective_chat.id == TELEGRAM_CHAT_ID`
    (normalized to str on both sides -- the wire value is always an int,
    the configured value may be entered as either str or int).
  - A built-in `/help` command that lists every currently-registered
    command name (dynamic -- reflects whatever TG-2/3/4 have registered
    by the time it runs).

`run_polling()` is intentionally NOT used -- it drives its own event loop
and would collide with FastAPI's (see spec S1 / PTB 22.5
`Application.start` docstring). Instead this uses the official
non-blocking lifespan sequence:

    startup:  await application.initialize()
              await application.updater.start_polling()
              await application.start()

    teardown: await application.updater.stop()
              await application.stop()
              await application.shutdown()
"""

from __future__ import annotations

from typing import Awaitable, Callable, Dict, Optional

import structlog
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from services.telegram.config import get_telegram_config

logger = structlog.get_logger()

CommandHandlerFn = Callable[[Update, "ContextTypes.DEFAULT_TYPE"], Awaitable[None]]
CallbackHandlerFn = Callable[[Update, "ContextTypes.DEFAULT_TYPE"], Awaitable[None]]

# Populated at import time by this module (built-in /help) and by TG-2/3/4
# (their own commands/callbacks). Plain module-level dicts rather than class
# state so later tasks can `from services.telegram.receiver import
# register_command` and call it unconditionally at module load -- no
# Application instance needs to exist yet, and registration order across
# modules doesn't matter as long as it happens before start_telegram_receiver()
# runs (main.py imports every route module before the lifespan body executes).
_COMMAND_REGISTRY: Dict[str, CommandHandlerFn] = {}
_CALLBACK_REGISTRY: Dict[str, CallbackHandlerFn] = {}

# The single receiver Application, set by start_telegram_receiver() and
# cleared by stop_telegram_receiver(). None means "not currently running"
# (never started, start failed, or already stopped) -- stop is a no-op in
# that state.
_application: Optional[Application] = None


def register_command(name: str, handler: CommandHandlerFn) -> None:
    """Register a `/name` command handler.

    Call at import time so the handler is present by the time
    `start_telegram_receiver()` builds the Application. `name` excludes the
    leading slash (e.g. "status", not "/status"). The shared security
    wrapper (chat_id check + never-raise) is applied automatically at
    wiring time -- handlers registered here should NOT re-check chat_id
    themselves.
    """
    _COMMAND_REGISTRY[name] = handler


def register_callback(pattern_prefix: str, handler: CallbackHandlerFn) -> None:
    """Register a callback_data prefix handler (inline keyboard buttons).

    `pattern_prefix` is matched against the start of the incoming
    `callback_query.data` (e.g. "a:" for an approval button, "r:" for a
    rejection button -- see spec F1). Like `register_command`, the shared
    security wrapper is applied automatically at dispatch time.
    """
    _CALLBACK_REGISTRY[pattern_prefix] = handler


def _authorized(update: Update) -> bool:
    """True iff the update's chat matches the single configured
    TELEGRAM_CHAT_ID.

    Normalizes both sides to str: the wire value (`effective_chat.id`) is
    always an int, while the configured value may have been entered as
    either str or int. An unconfigured chat_id (None/empty) always fails
    closed (False) -- there is no "authorize everyone" fallback.
    """
    config = get_telegram_config()
    if not config.TELEGRAM_CHAT_ID:
        return False
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None) if chat is not None else None
    if chat_id is None:
        return False
    return str(chat_id) == str(config.TELEGRAM_CHAT_ID)


async def _reply_error(update: Update, error: Exception) -> None:
    """Best-effort '오류: {message}' reply -- swallows its own failures so a
    broken reply path can never turn into a second unhandled exception."""
    try:
        message = getattr(update, "effective_message", None) or getattr(update, "message", None)
        if message is not None:
            await message.reply_text(f"오류: {error}")
    except Exception:
        pass


def _wrap_command(name: str, handler: CommandHandlerFn) -> CommandHandlerFn:
    """Shared security wrapper applied to every registered command handler
    at wiring time (spec S1 security invariants):

      - chat_id mismatch -> silent (no reply) + `telegram_unauthorized_chat`
        warning log (chat_id + command recorded).
      - any exception from the underlying handler -> "오류: {message}" reply
        + error log (never-raise -- PTB must never see an exception bubble
        out of a handler).
    """

    async def _wrapped(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not _authorized(update):
            chat = getattr(update, "effective_chat", None)
            logger.warning(
                "telegram_unauthorized_chat",
                chat_id=getattr(chat, "id", None),
                command=name,
            )
            return
        try:
            await handler(update, context)
        except Exception as e:
            logger.error("telegram_command_handler_failed", command=name, error=str(e))
            await _reply_error(update, e)

    return _wrapped


def _wrap_callback(prefix: str, handler: CallbackHandlerFn) -> CallbackHandlerFn:
    """Same contract as `_wrap_command`, for a single registered callback
    prefix handler (used by `_dispatch_callback` once it has matched
    `callback_query.data` against a registered prefix)."""

    async def _wrapped(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not _authorized(update):
            chat = getattr(update, "effective_chat", None)
            logger.warning(
                "telegram_unauthorized_chat",
                chat_id=getattr(chat, "id", None),
                command=prefix,
            )
            return
        try:
            await handler(update, context)
        except Exception as e:
            logger.error("telegram_callback_handler_failed", prefix=prefix, error=str(e))
            await _reply_error(update, e)

    return _wrapped


async def _dispatch_callback(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Single CallbackQueryHandler registered for every callback_query --
    looks up the matching registered prefix (longest match first, so a more
    specific prefix wins over a shorter one) and dispatches to it via
    `_wrap_callback`. Unregistered callback_data is silently ignored
    (fail-closed default, mirrors "미지 명령 = 무응답").
    """
    query = getattr(update, "callback_query", None)
    data = getattr(query, "data", None) if query is not None else None
    if not data:
        return

    matched_prefix = None
    for prefix in sorted(_CALLBACK_REGISTRY, key=len, reverse=True):
        if data.startswith(prefix):
            matched_prefix = prefix
            break
    if matched_prefix is None:
        return

    wrapped = _wrap_callback(matched_prefix, _CALLBACK_REGISTRY[matched_prefix])
    await wrapped(update, context)


async def _handle_help(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Built-in /help -- lists every currently-registered command name."""
    lines = ["*사용 가능한 명령어*", ""]
    for cmd_name in sorted(_COMMAND_REGISTRY):
        lines.append(f"/{cmd_name}")
    message = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if message is not None:
        await message.reply_text("\n".join(lines))


register_command("help", _handle_help)


async def start_telegram_receiver() -> Optional[Application]:
    """Build and start the inbound PTB Application (best-effort).

    Returns the running Application, or None if Telegram isn't configured
    (mirrors the existing `TelegramNotifier` enabled+token+chat_id gate) or
    if startup failed for any reason (bad token, 409 Conflict from a
    second poller, network error, ...). Never raises -- callers (FastAPI
    lifespan) can call this unconditionally without a try/except.
    """
    global _application

    config = get_telegram_config()
    if not config.is_configured:
        logger.info(
            "telegram_receiver_disabled",
            message="Telegram not configured - missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID/TELEGRAM_ENABLED",
        )
        return None

    try:
        application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

        for cmd_name, handler in _COMMAND_REGISTRY.items():
            application.add_handler(CommandHandler(cmd_name, _wrap_command(cmd_name, handler)))

        # Always wired, even if _CALLBACK_REGISTRY is empty right now -- TG-3/4
        # register their callback prefixes at import time, which already
        # happens before this function runs (main.py imports every route
        # module ahead of the lifespan body).
        application.add_handler(CallbackQueryHandler(_dispatch_callback))

        await application.initialize()
        await application.updater.start_polling()
        await application.start()

        _application = application
        logger.info("telegram_receiver_started", commands=sorted(_COMMAND_REGISTRY))
        return application
    except Exception as e:
        logger.error("telegram_receiver_start_failed", error=str(e))
        return None


async def stop_telegram_receiver() -> None:
    """Reverse-order teardown (updater.stop -> stop -> shutdown).

    No-op if the receiver was never started (or start failed) -- never
    raises, so FastAPI lifespan teardown can call this unconditionally.
    """
    global _application

    if _application is None:
        return

    application = _application
    _application = None

    try:
        if application.updater is not None:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("telegram_receiver_stopped")
    except Exception as e:
        logger.error("telegram_receiver_stop_failed", error=str(e))
