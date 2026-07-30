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
  - A built-in `/help` command backed by `_COMMAND_META` (Task 5) -- the
    same registry entry `register_command()` fills is the single source
    for both `/help`'s grouped overview / per-command detail and
    `setMyCommands`'s autocomplete list, so a command registered without
    metadata can no longer silently vanish from one but not the other.

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

from dataclasses import dataclass
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

# 리뷰 픽스(Critical): 상태를 바꾸는 콜백 프리픽스 집합 -- CommandMeta.risk
# ("read"|"mutate")의 콜백판. /auto는 2단계라 실제 모드 플립은 명령이 아니라
# 확인 버튼 콜백
# (callbacks.py의 auto_confirm:)에서 일어나므로, _wrap_command만 막으면
# 그룹 안의 admin 아닌 사용자가 admin이 띄운 버튼을 눌러 우회할 수 있다.
# register_callback(..., mutate=True)로 등록 시점에 표시한다 -- 문자열
# 프리픽스를 receiver.py에 따로 하드코딩하면 commands.py/callbacks.py가
# 이미 단일 출처로 합의해둔 AUTO_CONFIRM_CALLBACK_PREFIX와 다시 갈라질
# 위험이 있고(callbacks.py 모듈독스트링 참고), receiver.py가 commands.py를
# 직접 import하면 순환 임포트가 된다.
#
# Task 5 note: 이 집합은 CommandMeta로 흡수하지 *않는다*. CommandMeta는
# /help·setMyCommands가 함께 쓰는 "명령어" 메타(summary/group/usage/detail/
# caution)인데, 콜백 프리픽스("a:", "r:", "auto_confirm:")는 슬래시 명령이
# 아니라서 /help에도 자동완성에도 실리지 않는다 -- 담을 곳 없는 필드를
# CommandMeta에 얹으면 오히려 "명령/콜백" 두 개념이 한 dataclass에 섞여
# 헷갈린다. register_callback(mutate=True) 배선은 그대로 두고, /help의
# 대상인 명령어 쪽만 레지스트리 메타로 옮긴다.
_MUTATE_CALLBACK_PREFIXES: set[str] = set()


@dataclass(frozen=True)
class CommandMeta:
    """/help와 setMyCommands가 함께 쓰는 명령어 설명.

    별도 설명 dict를 두면 '등록됐지만 /help에 없는 명령'이 반드시 생긴다 --
    레지스트리를 단일 출처로 삼는다.
    """

    summary: str = ""
    group: str = "기타"
    risk: str = "read"  # read | mutate
    usage: str = ""
    detail: str = ""
    caution: str = ""


_COMMAND_META: Dict[str, CommandMeta] = {}

# /help 섹션 순서. 미등록 그룹은 이 뒤에 붙고, mutate 섹션은 항상 맨 아래다.
_HELP_GROUP_ORDER = ["지금 상태", "종목 판단", "성과", "승인 대기"]
_MUTATE_GROUP = "상태를 바꿈"

# The single receiver Application, set by start_telegram_receiver() and
# cleared by stop_telegram_receiver(). None means "not currently running"
# (never started, start failed, or already stopped) -- stop is a no-op in
# that state.
_application: Optional[Application] = None


def register_command(
    name: str,
    handler: CommandHandlerFn,
    *,
    summary: str = "",
    group: str = "기타",
    risk: str = "read",
    usage: str = "",
    detail: str = "",
    caution: str = "",
) -> None:
    """`/name` 명령 핸들러를 등록한다.

    새 키워드 인자는 전부 optional이라 기존 호출부가 깨지지 않는다. 다만
    신규 명령은 summary/group/risk를 채워야 /help와 setMyCommands에 제대로
    실린다 -- 누락 시 기동 로그에 warning을 남기되 예외는 던지지 않는다
    (receiver의 never-raise 계약).

    import 시점에 호출한다. `name`은 슬래시를 뺀 이름이다("status", not
    "/status"). 공유 보안 래퍼(chat_id 검증 + never-raise)는 배선 시점에
    자동 적용되므로 핸들러가 직접 재검사하면 안 된다.
    """
    _COMMAND_REGISTRY[name] = handler
    _COMMAND_META[name] = CommandMeta(
        summary=summary, group=group, risk=risk,
        usage=usage or f"/{name}", detail=detail, caution=caution,
    )
    if not summary:
        logger.warning("telegram_command_meta_missing", command=name)


def register_callback(
    pattern_prefix: str, handler: CallbackHandlerFn, mutate: bool = False
) -> None:
    """Register a callback_data prefix handler (inline keyboard buttons).

    `pattern_prefix` is matched against the start of the incoming
    `callback_query.data` (e.g. "a:" for an approval button, "r:" for a
    rejection button -- see spec F1). Like `register_command`, the shared
    security wrapper is applied automatically at dispatch time.

    `mutate=True` marks a prefix as state-changing (리뷰 픽스: "auto_confirm:",
    /auto step-2's confirm button, which actually flips `trading_mode:kiwoom`
    to autonomous; and Task 5's extension to "a:"/"r:", the approve/reject
    buttons -- `expected_proposal_id` pins WHICH proposal a tap decides, not
    WHO may decide it, so under a group `TELEGRAM_CHAT_ID` any member could
    otherwise approve/reject a proposal that isn't theirs to decide -- see
    `_MUTATE_CALLBACK_PREFIXES`). Such prefixes get the same extra per-user
    gate as a command registered with `risk="mutate"`
    (`_user_allowed_for_mutate`) on top of the ordinary chat_id check --
    necessary because `_authorized` only verifies the chat, and a group
    member other than the admin who typed `/auto` (or who wasn't even
    consulted on an approve/reject decision) could otherwise tap the button
    posted into that shared chat.
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
        if _COMMAND_META.get(name, CommandMeta()).risk == "mutate" and not _user_allowed_for_mutate(update):
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


def _help_overview() -> str:
    """그룹별 1행 요약. 평문 -- 현행 `*사용 가능한 명령어*`는 parse_mode가
    없어 별표가 리터럴로 노출되는 버그다."""
    reads = [n for n, m in _COMMAND_META.items() if m.risk != "mutate"]
    mutates = [n for n, m in _COMMAND_META.items() if m.risk == "mutate"]
    lines = [f"[명령어] 조회 {len(reads)} · 실행 {len(mutates)}"]

    groups = list(_HELP_GROUP_ORDER)
    for name in sorted(reads):
        g = _COMMAND_META[name].group
        if g not in groups:
            groups.append(g)

    for g in groups:
        members = sorted(n for n in reads if _COMMAND_META[n].group == g)
        if not members:
            continue
        lines.append(f"── {g}")
        for n in members:
            lines.append(f"/{n}  {_COMMAND_META[n].summary}")

    if mutates:
        lines.append(f"── ⚠️ {_MUTATE_GROUP}")
        for n in sorted(mutates):
            lines.append(f"/{n}  {_COMMAND_META[n].summary}")

    lines.append("")
    lines.append("상세는 /help positions 처럼")
    return "\n".join(lines)


def _help_detail(name: str) -> str:
    meta = _COMMAND_META.get(name)
    if meta is None:
        candidates = sorted(
            _COMMAND_META, key=lambda n: (0 if n.startswith(name[:3]) else 1, n)
        )[:3]
        hint = " ".join(f"/{c}" for c in candidates)
        return f"'{name}' 명령이 없습니다.\n비슷한 것: {hint}"
    risk_ko = "⚠️ 상태를 바꿈" if meta.risk == "mutate" else "읽기 전용 (아무것도 바꾸지 않음)"
    lines = [f"[/{name}] {meta.summary}"]
    if meta.detail:
        lines.append(meta.detail)
    lines.append(f"인자: {meta.usage}")
    lines.append(f"위험도: {risk_ko}")
    if meta.caution:
        lines.append(f"주의: {meta.caution}")
    return "\n".join(lines)


async def _handle_help(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    """내장 /help -- 2단 구조.

    `/help`는 그룹별 1행 요약, `/help <명령>`은 상세. 명령어가 6→14개가 되면
    상세를 한 통에 담을 수 없다(4,096자).
    """
    args = list(getattr(context, "args", None) or [])
    text = _help_detail(args[0].lstrip("/")) if args else _help_overview()
    message = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if message is not None:
        await message.reply_text(text)


register_command(
    "help", _handle_help,
    summary="명령어 목록과 사용법",
    group="지금 상태",
    risk="read",
    usage="/help 또는 /help <명령>",
    detail="목적: 어떤 명령이 있고 무엇을 하는지",
)


def _build_bot_commands() -> list:
    """setMyCommands에 보낼 목록. 설명이 비면 Telegram이 거부하므로 폴백을 둔다."""
    from telegram import BotCommand

    return [
        BotCommand(name, (_COMMAND_META.get(name, CommandMeta()).summary or name)[:256])
        for name in sorted(_COMMAND_REGISTRY)
    ]


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

        # 폰에서 `/`를 쳤을 때 뜨는 자동완성. 코드베이스에 set_my_commands가
        # 0건이라 지금은 목록이 비어 있고 /help가 그 역할을 100% 혼자 진다.
        # 실패는 로그만 -- 자동완성이 없다고 수신이 죽어선 안 된다.
        #
        # Minor 6 (최종 전체 브랜치 리뷰): scope를 명시하지 않으면 기본
        # scope(BotCommandScopeDefault)로 등록되는데, 이건 "이 봇을 연 모든
        # 텔레그램 사용자"에게 전체 명령 표면과 한국어 설명이 자동완성으로
        # 노출된다는 뜻이다. 실행 자체는 `_authorized`(receiver.py)가
        # fail-closed로 막으므로 이건 접근이 아니라 노출(disclosure) 문제지만,
        # 스펙이 요구한 BotCommandScopeChat(운영자 채팅으로만 한정)과는
        # 다르다. TELEGRAM_CHAT_ID가 이미 `_authorized`가 비교하는 그
        # 채팅이므로 그대로 재사용한다.
        try:
            from telegram import BotCommandScopeChat

            await application.bot.set_my_commands(
                _build_bot_commands(),
                scope=BotCommandScopeChat(chat_id=config.TELEGRAM_CHAT_ID),
            )
            logger.info("telegram_set_my_commands_ok", count=len(_COMMAND_REGISTRY))
        except Exception as e:
            logger.warning("telegram_set_my_commands_failed", error=str(e))

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
