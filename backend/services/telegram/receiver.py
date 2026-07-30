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
    failure (missing config, bad token, etc.) must never block server
    startup, outbound notifications, or the HITL approval pipeline. Note
    the failure modes are asymmetric: SYNCHRONOUS failures during startup
    (builder/`initialize()`, e.g. InvalidToken) surface here as `None`.
    PTB 22.5's `updater.start_polling()` returns as soon as the background
    polling task is *scheduled*, without waiting for the first
    `get_updates` to complete -- so a 409 Conflict (a second poller already
    running) happens AFTER `start_telegram_receiver()` has already returned
    a live Application. That class of error can only be observed via the
    `error_callback` passed to `start_polling()` (logged as
    `telegram_receiver_polling_error`), never via this function's return
    value.
  - `register_command(name, handler)` / `register_callback(pattern_prefix,
    handler)`: module-level registries populated at IMPORT time by later
    tasks (TG-2 read-only queries, TG-3 approval buttons, TG-4 /halt+/auto).
    `start_telegram_receiver()` explicitly imports each task's module (see
    the `from . import commands` line inside it) so registration is
    structurally guaranteed rather than depending on some other module
    having imported it first -- see `commands.py`'s module docstring for
    the TG-1 carryover finding this fixes -- and then wires every
    registered entry into a CommandHandler/CallbackQueryHandler, applying
    the shared security wrapper (`_wrap_command`/`_wrap_callback`) so no
    individual handler can forget the chat_id check or the never-raise
    contract -- the security invariants live in exactly one place.
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

# 리뷰 픽스(Critical): 상태를 바꾸는 콜백 프리픽스 집합 -- _MUTATE_COMMANDS의
# 콜백판. /auto는 2단계라 실제 모드 플립은 명령이 아니라 확인 버튼 콜백
# (callbacks.py의 auto_confirm:)에서 일어나므로, _wrap_command만 막으면
# 그룹 안의 admin 아닌 사용자가 admin이 띄운 버튼을 눌러 우회할 수 있다.
# register_callback(..., mutate=True)로 등록 시점에 표시한다 -- 문자열
# 프리픽스를 receiver.py에 따로 하드코딩하면 commands.py/callbacks.py가
# 이미 단일 출처로 합의해둔 AUTO_CONFIRM_CALLBACK_PREFIX와 다시 갈라질
# 위험이 있고(callbacks.py 모듈독스트링 참고), receiver.py가 commands.py를
# 직접 import하면 순환 임포트가 된다. Task 5에서 레지스트리 메타로 옮긴다.
_MUTATE_CALLBACK_PREFIXES: set[str] = set()

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


def register_callback(
    pattern_prefix: str, handler: CallbackHandlerFn, mutate: bool = False
) -> None:
    """Register a callback_data prefix handler (inline keyboard buttons).

    `pattern_prefix` is matched against the start of the incoming
    `callback_query.data` (e.g. "a:" for an approval button, "r:" for a
    rejection button -- see spec F1). Like `register_command`, the shared
    security wrapper is applied automatically at dispatch time.

    `mutate=True` marks a prefix as state-changing (리뷰 픽스: currently only
    "auto_confirm:", /auto step-2's confirm button, which actually flips
    `trading_mode:kiwoom` to autonomous -- see `_MUTATE_CALLBACK_PREFIXES`).
    Such prefixes get the same extra per-user gate as `_MUTATE_COMMANDS`
    (`_user_allowed_for_mutate`) on top of the ordinary chat_id check --
    necessary because `_authorized` only verifies the chat, and a group
    member other than the admin who typed `/auto` could otherwise tap the
    button the admin's message posted into that shared chat.
    """
    _CALLBACK_REGISTRY[pattern_prefix] = handler
    if mutate:
        _MUTATE_CALLBACK_PREFIXES.add(pattern_prefix)


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


# 상태를 바꾸는 명령. Task 5에서 레지스트리 메타(risk="mutate")로 옮긴다.
_MUTATE_COMMANDS = {"halt", "auto"}


def _user_allowed_for_mutate(update: Update) -> bool:
    """상태 변경 명령의 추가 관문 — 발신 '사용자'까지 확인한다.

    _authorized는 chat만 본다. TELEGRAM_CHAT_ID를 그룹(음수 id)으로 바꾸면
    그룹원 전원이 /halt를 칠 수 있는데, /halt는 신규 매수 차단이 아니라
    자동 손절 무장해제라(gate.py:279 + position_manager.py:1255) 오조작
    비용이 비대칭이다.

    TELEGRAM_ADMIN_USER_ID 미설정이면 True — 새 설정을 강제해 기존 운용을
    갑자기 막지 않는다. 설정돼 있는데 발신자를 알 수 없으면 fail-closed.
    """
    config = get_telegram_config()
    admin = getattr(config, "TELEGRAM_ADMIN_USER_ID", None)
    if not admin:
        return True
    user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", None) if user is not None else None
    if user_id is None:
        return False
    return str(user_id) == str(admin)


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
        if name in _MUTATE_COMMANDS and not _user_allowed_for_mutate(update):
            user = getattr(update, "effective_user", None)
            logger.warning(
                "telegram_mutate_denied",
                command=name,
                user_id=getattr(user, "id", None),
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
    `callback_query.data` against a registered prefix).

    리뷰 픽스(Critical): `prefix`가 `_MUTATE_CALLBACK_PREFIXES`에 있으면
    `_wrap_command`와 동일한 추가 관문(`_user_allowed_for_mutate`)을 chat_id
    검사 직후에 적용한다. /auto의 실제 상태 변경(모드 플립)은 명령이 아니라
    확인 버튼 콜백에서 일어나므로, 이 관문이 없으면 그룹 안에서 admin이
    아닌 사용자도 admin이 띄운 버튼을 눌러 자율 모드를 재무장시킬 수 있다.
    """

    async def _wrapped(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not _authorized(update):
            chat = getattr(update, "effective_chat", None)
            logger.warning(
                "telegram_unauthorized_chat",
                chat_id=getattr(chat, "id", None),
                command=prefix,
            )
            return
        if prefix in _MUTATE_CALLBACK_PREFIXES and not _user_allowed_for_mutate(update):
            user = getattr(update, "effective_user", None)
            logger.warning(
                "telegram_mutate_denied",
                command=prefix,
                user_id=getattr(user, "id", None),
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


def _on_polling_error(error: Exception) -> None:
    """`error_callback` passed to `updater.start_polling()`.

    PTB 22.5's `start_polling()` schedules the polling loop as a background
    task and returns immediately -- it does NOT await the first
    `get_updates` call. Any error surfacing after that point (most notably
    409 Conflict from a second consumer of getUpdates) therefore never
    reaches the try/except in `start_telegram_receiver()`; PTB calls this
    callback instead (synchronously, on every polling-loop exception) and
    then retries on its own. This is a pure observability hook -- it must
    never raise, and it does not stop or restart anything itself.
    """
    logger.error("telegram_receiver_polling_error", error=str(error))


async def start_telegram_receiver() -> Optional[Application]:
    """Build and start the inbound PTB Application (best-effort).

    Returns the running Application, or None if Telegram isn't configured
    (mirrors the existing `TelegramNotifier` enabled+token+chat_id gate) or
    if a SYNCHRONOUS startup step failed (bad token / InvalidToken during
    `initialize()`, network error building the Application, ...). A 409
    Conflict from a second poller happens *after* `start_polling()` returns
    (PTB schedules the polling loop as a background task and does not await
    its first iteration) -- it is never raised here and never turns this
    function's result into None. It is instead observed via the
    `error_callback` wired into `start_polling()` below, which logs
    `telegram_receiver_polling_error` and lets PTB's own retry loop keep
    running. Never raises -- callers (FastAPI lifespan) can call this
    unconditionally without a try/except.
    """
    global _application

    config = get_telegram_config()
    if not config.is_configured:
        logger.info(
            "telegram_receiver_disabled",
            message="Telegram not configured - missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID/TELEGRAM_ENABLED",
        )
        return None

    application: Optional[Application] = None
    try:
        # TG-2 carryover fix: `register_command` populates _COMMAND_REGISTRY
        # as an IMPORT-TIME side effect (see commands.py's module docstring)
        # -- relying on "main.py imports every route module before this
        # runs" to guarantee that side effect fired is fragile (a module
        # that never gets imported never registers). Explicitly importing
        # each task's command module here, right before the registry is
        # drained, makes the guarantee structural instead of incidental.
        # Idempotent/cheap if already imported (Python caches in
        # sys.modules) and safe to extend as TG-3/TG-4 add their own
        # modules.
        from . import commands  # noqa: F401 -- import for registration side effect
        from . import callbacks  # noqa: F401 -- TG-3: registers "a:"/"r:" callback prefixes

        application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

        for cmd_name, handler in _COMMAND_REGISTRY.items():
            application.add_handler(CommandHandler(cmd_name, _wrap_command(cmd_name, handler)))

        # Always wired, even if _CALLBACK_REGISTRY is empty right now -- TG-3/4
        # register their callback prefixes at import time, which already
        # happens before this function runs (main.py imports every route
        # module ahead of the lifespan body).
        application.add_handler(CallbackQueryHandler(_dispatch_callback))

        await application.initialize()
        await application.updater.start_polling(error_callback=_on_polling_error)
        await application.start()

        _application = application
        logger.info("telegram_receiver_started", commands=sorted(_COMMAND_REGISTRY))
        return application
    except Exception as e:
        logger.error("telegram_receiver_start_failed", error=str(e))
        if application is not None:
            try:
                await application.shutdown()
            except Exception:
                pass
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
