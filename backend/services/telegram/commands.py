"""
Telegram Read-Only Query Commands (TG-2) + /halt·/auto Emergency Mode
Switches (TG-4)

Implements the four read-only commands of the two-way Telegram arc (see
docs/superpowers/specs/2026-07-17-telegram-twoway-design.md F3):

  /status    — trading mode + coordinator status + KRX market session +
               agent-chat heartbeat
  /positions — current KR holdings (reuses /operations' holdings collection)
  /pending   — sessions awaiting HITL approval (reuses /operations' awaiting
               collection; each item is re-sent as an F1 approve/reject
               inline-keyboard message via `TelegramNotifier.
               send_approval_request` — TG-3 upgrade, see
               `_send_pending_button` below — falling back to the plain-text
               `_format_pending_line` caption only if that send fails)
  /report    — most recent EOD review row, reusing TelegramNotifier's
               existing daily-summary formatting (never its send path)

Registered into services.telegram.receiver's command registry at IMPORT
TIME via `register_command(name, handler)`. `receiver.start_telegram_
receiver()` explicitly does `from . import commands` right before it drains
the registry into the PTB Application, so this module's registration is
structurally guaranteed to have run by then regardless of whether any other
module happened to import it first (TG-1 carryover finding — import-time
side-effect registration is otherwise silently skippable).

All data sources are called DIRECTLY as plain async functions — never HTTP
loopback. FastAPI route functions in this repo are ordinary async
functions; `@router.get(...)` only registers them, it does not wrap or
alter the function object, so calling one directly (with any `Depends(...)`
default resolved by hand, e.g. `coordinator=await get_trading_coordinator()`)
is the established pattern (see app/api/routes/_autonomy_injector.py:233's
direct call to `approval.submit_decision`, and settings.py's
`_trading_mode_response` — an undecorated helper shared by the route and,
now, this module).

Route/dependency modules are imported LAZILY inside each `_fetch_*` helper
(not at this module's top level). This mirrors the repo's established
avoid-import-cycle convention (see _autonomy_injector.py's own comment on
why it lazy-imports `approval`): services/telegram is imported early by
app/main.py's lifespan, while app/api/routes/* modules stay telegram-free at
their own import time. The `_fetch_*` functions are also the deliberate
mock-injection seam for tests (each is monkeypatchable independently of the
others, matching the task brief's "명령별 목 소스 주입" requirement).

Security (chat_id check + never-raise) is applied once, uniformly, by
receiver._wrap_command at wiring time — handlers here must NOT re-check
chat_id. Every handler still independently degrades EACH data source to a
plain "데이터 없음" fallback via `_safe()` rather than letting one dead
source blank out (or exception out) the whole reply — mirrors /operations'
own per-section degrade-not-fail contract. Replies are plain text with no
`parse_mode` set, so a stray Markdown special character anywhere in
upstream data (ticker names, rationale text, ...) can never trigger a
Telegram parse error — this holds even for /report, whose reused format
strings contain literal `*bold*` markers: without `parse_mode`, Telegram
sends them back verbatim rather than parsing (and failing on) them.

TG-4 adds two mode-switch commands at the bottom of this module (see the
"/halt and /auto" section below for the full contract): `/halt` is a
one-step fail-safe emergency stop (kiwoom autonomous -> hitl, no
confirmation); `/auto` is the 2-step reverse (hitl -> autonomous) whose
step-2 confirm button is handled in `services/telegram/callbacks.py`
(`AUTO_CONFIRM_CALLBACK_PREFIX` / `handle_auto_confirm_callback`) rather
than here, mirroring how F1's approve/reject buttons live in callbacks.py
while their originating notification lives elsewhere.

TG-4 review fix (Important): /auto's confirm button used to carry a FIXED
callback_data literal with no TTL/one-time-use, so a stale never-tapped
button stayed valid forever -- including across an intervening `/halt`
emergency stop, which could then be silently undone by a late tap. The
button now carries a fresh single-use nonce with a 5-minute TTL
(`AUTO_CONFIRM_CALLBACK_PREFIX` / `_issue_auto_confirm_nonce` /
`consume_auto_confirm_nonce` below), and `/halt` explicitly invalidates any
outstanding nonce (`invalidate_auto_confirm_nonce`) so that exact scenario
now replies "만료" instead of re-arming autonomous mode.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Optional, TypeVar

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.telegram.receiver import register_command

logger = structlog.get_logger()

T = TypeVar("T")

_NO_DATA = "데이터 없음"


async def _safe(label: str, coro: Awaitable[T]) -> Optional[T]:
    """Await `coro`, logging+swallowing any failure -- returns None so the
    caller can degrade just that one section to `_NO_DATA` instead of
    losing (or exception-ing out of) the rest of the reply."""
    try:
        return await coro
    except Exception as e:  # noqa: BLE001 -- per-source independent degrade
        logger.warning("telegram_command_source_failed", source=label, error=str(e))
        return None


# Telegram 한 메시지 상한은 4,096자다. 3,900에서 자르는 이유는 절단 꼬리와
# 멀티바이트 여유를 남기기 위해서다. 분할하지 않는 것은 의도다 — 폰에서
# 3연속 메시지는 읽히지 않고, 청크 연속 발송이 동일 채팅 초당 1건 권고를
# 넘겨 429를 유발하며 그 429는 _send_message가 조용히 삼킨다. 게다가 분할은
# 기존 테스트 약 20곳의 assert_awaited_once 계약을 깬다.
_REPLY_LIMIT = 3900
_TRUNCATE_TAIL = "\n…이하 생략 (웹에서 확인)"


def _truncate(text: str) -> str:
    """줄 경계에서 자른다 — 현재 300자 하드컷이 '...breadth br'처럼 단어
    중간을 자른다."""
    if len(text) <= _REPLY_LIMIT:
        return text
    budget = _REPLY_LIMIT - len(_TRUNCATE_TAIL)
    head = text[:budget]
    cut = head.rfind("\n")
    if cut > budget // 2:
        head = head[:cut]
    return head + _TRUNCATE_TAIL


async def _reply(update: Update, text: str) -> None:
    message = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if message is not None:
        await message.reply_text(_truncate(text))


def source_status(value, error: Optional[str] = None, *, unconfigured: bool = False) -> str:
    """빈값 / 조회 실패 / 미설정 세 상태를 서로 겹치지 않게 구별한다.

    `데이터 없음` 단일 문자열을 쓰면 안 된다 — 현재 `_format_positions(None)`
    (API 예외)과 `holding=null`(정상 빈값)이 바이트 동일해서 운영자가
    "시스템이 죽었나 데이터가 없나"를 구별할 수 없다.

    리뷰 Important 1: 애초 이 함수는 '미설정'을 자체 상태로 내지 않고
    `error="미설정"`을 통해 `조회 실패(미설정)`로만 냈다 — "조회를
    시도했는데 실패했다: 설정 안 됨"으로 읽혀 자기모순이고, 조회를 시도한
    적도 없는데 시도했다고 운영자에게 알리는 셈이었다. 호출자가 소스가
    애초에 설정되지 않았음을 알고 있다면(예: TELEGRAM_BOT_TOKEN 미설정)
    조회를 시도했다는 신호(`error=`) 없이 `unconfigured=True`로 이 상태를
    직접 알린다 — `조회 실패(...)` 안에 절대 중첩되지 않는다.
    """
    if unconfigured:
        return "미설정"
    if value is None:
        return f"조회 실패({error})" if error else "조회 실패"
    try:
        return f"{len(value)}건"
    except TypeError:
        return "1건"


# -------------------------------------------
# /status
# -------------------------------------------


async def _fetch_trading_mode():
    """settings.py:125-133 -- per-market Autonomous|HITL mode + master gate."""
    from app.api.routes.settings import _trading_mode_response

    return await _trading_mode_response()


async def _fetch_trading_status():
    """trading.py:229 get_trading_status -- coordinator active/daily_trades."""
    from app.api.routes.trading import get_trading_status
    from app.dependencies import get_trading_coordinator

    coordinator = await get_trading_coordinator()
    return await get_trading_status(coordinator=coordinator)


async def _fetch_market_status(market: str = "krx"):
    """trading.py:517 get_market_status -- KRX session open/close state."""
    from app.api.routes.trading import get_market_status

    return await get_market_status(market=market)


async def _fetch_chat_heartbeat():
    """agent_chat.py:216 get_coordinator_status -- agent-chat discussion loop."""
    from app.api.routes.agent_chat import get_coordinator_status

    return await get_coordinator_status()


def _format_status(mode, trading_status, market_status, heartbeat) -> str:
    lines = ["[시스템 상태]"]

    if mode is not None:
        master = "ON" if mode.master_enabled else "OFF"
        lines.append(f"모드: 키움={mode.kiwoom} (마스터 {master})")
    else:
        lines.append(f"모드: {_NO_DATA}")

    if trading_status is not None:
        active = "활성" if trading_status.is_active else "비활성"
        lines.append(
            f"트레이딩: {active} (일일 거래 {trading_status.daily_trades}/"
            f"{trading_status.max_daily_trades}, 대기 알림 {trading_status.pending_alerts_count}건)"
        )
    else:
        lines.append(f"트레이딩: {_NO_DATA}")

    if market_status is not None:
        open_state = "개장" if market_status.is_open else "휴장"
        lines.append(f"장(KRX): {open_state} — {market_status.message}")
    else:
        lines.append(f"장(KRX): {_NO_DATA}")

    if heartbeat is not None:
        running = "가동중" if heartbeat.is_running else "정지"
        lines.append(
            f"에이전트 협의: {running} (진행 {heartbeat.active_discussions}건, "
            f"마지막 점검 {heartbeat.last_check_at or '-'})"
        )
    else:
        lines.append(f"에이전트 협의: {_NO_DATA}")

    return "\n".join(lines)


async def handle_status(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    mode = await _safe("trading_mode", _fetch_trading_mode())
    trading_status = await _safe("trading_status", _fetch_trading_status())
    market_status = await _safe("market_status", _fetch_market_status())
    heartbeat = await _safe("chat_heartbeat", _fetch_chat_heartbeat())

    await _reply(update, _format_status(mode, trading_status, market_status, heartbeat))


# -------------------------------------------
# /positions and /pending -- both read /operations
# -------------------------------------------


async def _fetch_operations(market: str = "kiwoom"):
    """trading.py:1563 get_operations -- holdings (:positions) + awaiting
    approval sessions (:pending) in one snapshot, exactly what the FE
    Operations board reads."""
    from app.api.routes.trading import get_operations
    from app.dependencies import get_trading_coordinator

    coordinator = await get_trading_coordinator()
    return await get_operations(market=market, coordinator=coordinator)


def _format_position_line(holding) -> str:
    name = holding.name or holding.ticker
    sign = "+" if holding.pnl >= 0 else ""
    return (
        f"• {name}({holding.ticker}) {holding.quantity:g}주 "
        f"평단 {holding.avg_price:,.0f} 현재 {holding.current_price:,.0f} "
        f"손익 {sign}{holding.pnl:,.0f} ({sign}{holding.pnl_pct:.2f}%)"
    )


def _format_positions(operations) -> str:
    holdings = operations.holding if operations is not None else None
    if holdings is None:
        return f"[보유 포지션]\n{_NO_DATA}"
    if not holdings:
        return "[보유 포지션] 0건 (보유 종목 없음)"
    lines = [f"[보유 포지션] {len(holdings)}건"]
    lines.extend(_format_position_line(h) for h in holdings)
    return "\n".join(lines)


async def handle_positions(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    operations = await _safe("operations_positions", _fetch_operations())
    await _reply(update, _format_positions(operations))


def _format_pending_line(item) -> str:
    """Text-only formatting for one awaiting-approval item.

    Deliberately factored out as its own function so `_send_pending_button`
    (TG-3, spec F3: "각 항목에 F1과 동일한 승인/거부 버튼 재발송") can reuse it
    verbatim as the plain-text fallback caption when the button send itself
    fails -- the item-line text is the caption either way, only the primary
    delivery mechanism (inline-keyboard message vs. plain reply_text)
    differs.
    """
    short_id = (item.session_id or "")[:8]
    name = item.name or item.ticker
    proposal = item.proposal or {}
    action = proposal.get("action") or "-"
    auto_at = item.auto_approve_at or "-"
    return f"• [{short_id}] {name}({item.ticker}) {action} 자동승인예정 {auto_at}"


async def _fetch_notifier():
    """Lazy import + fetch of the outbound TelegramNotifier singleton -- the
    deliberate mock-injection seam for /pending's per-item button upgrade
    (TG-3, spec F3), mirroring every other `_fetch_*` helper in this
    module."""
    from services.telegram import get_telegram_notifier

    return await get_telegram_notifier()


async def _send_pending_button(item) -> bool:
    """Best-effort per-item approve/reject button send for one /pending
    entry (TG-3 F3) -- reuses F1's `send_approval_request` verbatim rather
    than building a bespoke keyboard here. Returns False (never raises) on
    ANY failure so the caller falls back to `_format_pending_line`'s
    plain-text caption, mirroring this module's own `_safe()`
    degrade-not-fail contract. market is hardcoded "kiwoom" -- /pending's
    only source, `_fetch_operations()`, already defaults to (and is only
    ever called with) the kiwoom market."""
    try:
        notifier = await _fetch_notifier()
        proposal = item.proposal or {}
        return await notifier.send_approval_request(
            item.session_id, "kiwoom", proposal, item.auto_approve_at,
        )
    except Exception as e:  # noqa: BLE001 -- per-item independent degrade
        logger.warning(
            "telegram_pending_button_failed", session_id=item.session_id, error=str(e)
        )
        return False


# Telegram은 동일 채팅 초당 1건을 권고한다. 0.4초(초당 ~2.5건)로 처음
# 배포했다가 리뷰에서 그 권고를 정면으로 어긴다는 지적을 받고 1.0초로
# 올렸다(Important 3) -- 승인 대기열은 보통 짧아서, 429로 항목을 잃는
# 것보다 1초 기다리는 편이 낫다.
_PENDING_SEND_INTERVAL = 1.0


async def handle_pending(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    operations = await _safe("operations_pending", _fetch_operations())
    awaiting = operations.awaiting if operations is not None else None

    if awaiting is None:
        await _reply(update, f"[승인 대기]\n{_NO_DATA}")
        return
    if not awaiting:
        await _reply(update, "[승인 대기] 0건")
        return

    await _reply(update, f"[승인 대기] {len(awaiting)}건")
    for i, item in enumerate(awaiting):
        if i > 0:
            # Telegram은 동일 채팅 초당 1건을 권고하고 초과 시 429를 낸다.
            # 그 429는 _send_message가 조용히 삼켜서 뒷항목이 통째로
            # 유실된다 — 지연이 유일한 방어다. 리뷰 Important 3: 0.4초는
            # 초당 ~2.5건 페이싱이라 그 권고를 그대로 어겼다. 승인 대기열은
            # 보통 짧으니 429로 항목을 잃는 것보다 1초 기다리는 편이 낫다.
            #
            # 최종 전체 브랜치 리뷰 Minor 7: 항목 "사이"에만 넣는다 — 첫
            # 항목 앞에는 지연이 필요 없고(발송할 게 아직 없다), 마지막
            # 항목 뒤에 거는 구코드는(루프 끝의 무조건 sleep)
            # max_concurrent_updates=1인 receiver를 그만큼 더 묶어
            # `/halt`와 승인 버튼 탭을 굶긴다.
            await asyncio.sleep(_PENDING_SEND_INTERVAL)

        sent = await _send_pending_button(item)
        if not sent:
            # 리뷰 Important 2: 버튼 발송 실패는 방금 그 발송이 429로
            # 스로틀됐다는 신호일 수 있다. 그 직후 간격 없이 두 번째 발송
            # (텍스트 폴백)을 붙이면, 이 태스크가 막으려는 제로갭 쌍이
            # 반복 한 단계 아래에서 재현된다 — 그 폴백이 또 실패하면
            # _wrap_command가 잡아 루프 전체가 끊기고 남은 항목이 전부
            # 조용히 유실된다. 폴백 앞에도 같은 간격을 둔다.
            await asyncio.sleep(_PENDING_SEND_INTERVAL)
            await _reply(update, _format_pending_line(item))


# -------------------------------------------
# /report
# -------------------------------------------


async def _fetch_latest_eod_review() -> Optional[dict]:
    """storage_service.get_eod_reviews(limit=1) -- newest eod_review row
    (report_json is a JSON string, parsed by `_format_report` below)."""
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    rows = await storage.get_eod_reviews(limit=1)
    return rows[0] if rows else None


def _format_report(row: Optional[dict]) -> str:
    """Reuses TelegramNotifier's existing daily-summary formatting
    (`_format_daily_summary_narrative`/`_format_daily_summary_template`,
    services/telegram/service.py:563-648) rather than re-deriving the
    watch/account/holdings/strategy block layout here. A throwaway
    `TelegramNotifier()` is constructed purely to call those formatting
    methods -- the constructor only reads env-based config (no network,
    `initialize()` -- the step that opens a real bot connection -- is never
    called), and this function never calls `send_daily_summary`/
    `_send_message`, so no Telegram traffic is generated and the notifier's
    own send contract (frozen per spec §3) is untouched.
    """
    if row is None:
        return f"[장마감 리포트]\n{_NO_DATA}"

    try:
        report = json.loads(row.get("report_json") or "{}")
    except (TypeError, ValueError):
        report = {}

    digest = report.get("digest")
    if not digest:
        return f"[장마감 리포트]\n{_NO_DATA}"

    narrative = report.get("narrative")
    trade_date = digest.get("trade_date") or row.get("trade_date") or "-"

    from services.telegram.service import TelegramNotifier

    formatter = TelegramNotifier()
    if narrative and narrative.strip():
        return formatter._format_daily_summary_narrative(trade_date, digest, narrative)
    return formatter._format_daily_summary_template(trade_date, digest)


async def handle_report(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    row = await _safe("eod_review", _fetch_latest_eod_review())
    try:
        text = _format_report(row)
    except Exception as e:  # noqa: BLE001 -- formatting must never blank the reply
        logger.warning("telegram_command_source_failed", source="eod_review_format", error=str(e))
        text = f"[장마감 리포트]\n{_NO_DATA}"

    await _reply(update, text)


# -------------------------------------------
# /halt and /auto -- emergency stop + 2-step resume (TG-4)
#
# Spec: docs/superpowers/specs/2026-07-17-telegram-twoway-design.md F2.
# Both are Autonomous|HITL *mode* switches for kiwoom (settings.py's
# trading_mode:kiwoom setting the shared autonomy gate re-reads on every
# request, see services/autonomy/gate.py) -- NEITHER has anything to do
# with the existing `POST /trading/pause` / `POST /trading/resume`
# (trading.py:186-222), which pause/resume the trading COORDINATOR's own
# session scheduler. A halted kiwoom mode still lets the coordinator run;
# it only forces every future proposal through manual HITL approval
# instead of the 60s auto-approve countdown.
# -------------------------------------------

AUTO_CONFIRM_CALLBACK_PREFIX = "auto_confirm:"
"""callback_data PREFIX for /auto's step-2 confirm button (TG-4 review
fix). Unlike F1's `a:{session_id}:{pid8}` / `r:{session_id}:{pid8}`
buttons, this action is market/mode-scoped (kiwoom's Autonomous|HITL
setting), not proposal-scoped, so there is no session_id to pin --
instead each button carries a single-use NONCE:
`f"{AUTO_CONFIRM_CALLBACK_PREFIX}{nonce}"` (well under Telegram's 64-byte
callback_data budget: prefix 13 bytes + a 12-hex-char nonce = 25 bytes).
services/telegram/callbacks.py registers a handler for this exact prefix
(`register_callback(AUTO_CONFIRM_CALLBACK_PREFIX, ...)`) and imports this
module directly (`from services.telegram import commands`) to call
`consume_auto_confirm_nonce` below -- unlike the old fixed-literal design,
the two files must now actually share nonce STATE, not just agree on a
string by convention, so a real import replaces that convention (no
cycle: this module never imports callbacks.py)."""

AUTO_CONFIRM_TTL_SECONDS: float = 300.0
"""5 minutes. Long enough for a human to notice and tap the confirm
button; short enough that a truly stale button (the review scenario --
issued, never tapped, /halt used as an emergency stop, THEN tapped) reads
as obviously expired rather than staying live indefinitely."""

# Process-local nonce state for /auto's step-2 confirm button. Deliberately
# NOT persisted anywhere durable (SQLite/app_settings/...): a server
# restart naturally invalidates any outstanding confirm, which is the
# fail-safe direction (forces a fresh /auto rather than resurrecting a
# half-confirmed one after a restart), so in-memory-only is the correct
# choice here, not merely the convenient one.
_auto_confirm_nonce: Optional[str] = None
_auto_confirm_issued_at: Optional[datetime] = None


def _issue_auto_confirm_nonce() -> str:
    """Mint+store a fresh single-use nonce for /auto's confirm button,
    discarding whatever nonce (if any) was previously outstanding -- only
    the LATEST /auto's button is ever valid ("새 /auto 실행은 이전 논스를
    자연 대체" per the review fix's design)."""
    global _auto_confirm_nonce, _auto_confirm_issued_at
    _auto_confirm_nonce = uuid.uuid4().hex[:12]
    _auto_confirm_issued_at = datetime.now(timezone.utc)
    return _auto_confirm_nonce


def invalidate_auto_confirm_nonce() -> None:
    """Clear any outstanding /auto confirm nonce. Called from `handle_halt`
    below so an emergency stop can never be silently undone later by a
    stale confirm button issued before the halt and never tapped -- the
    exact scenario this review fix closes."""
    global _auto_confirm_nonce, _auto_confirm_issued_at
    _auto_confirm_nonce = None
    _auto_confirm_issued_at = None


def consume_auto_confirm_nonce(nonce: str) -> bool:
    """Validate+consume a /auto confirm nonce (called from
    `services.telegram.callbacks.handle_auto_confirm_callback`).

    Returns True only if `nonce` matches the single latest-issued nonce AND
    is still within `AUTO_CONFIRM_TTL_SECONDS`. On a MATCH (whether or not
    the TTL check itself passes) the stored nonce is cleared immediately --
    one-time use, so a second tap of the very same button (successful or
    already-expired) always falls through to "expired" on retry, never
    silently retries the same slot.

    On a MISMATCH (a different or no nonce is currently stored -- e.g. a
    stale/superseded nonce from a previous /auto, or `/halt` already
    cleared the slot) nothing is cleared: a stale replay must never be able
    to invalidate a DIFFERENT, still-legitimately-pending nonce that a real
    user might still tap.
    """
    global _auto_confirm_nonce, _auto_confirm_issued_at
    if _auto_confirm_nonce is None or _auto_confirm_issued_at is None:
        return False
    if nonce != _auto_confirm_nonce:
        return False
    issued_at = _auto_confirm_issued_at
    _auto_confirm_nonce = None
    _auto_confirm_issued_at = None
    age_seconds = (datetime.now(timezone.utc) - issued_at).total_seconds()
    return age_seconds <= AUTO_CONFIRM_TTL_SECONDS


async def _set_trading_mode(market: str, mode: str):
    """settings.py:143 `PUT /api/settings/trading-mode` handler -- an
    ordinary async function (FastAPI's `@router.put` only registers it, per
    this module's own docstring), called directly exactly like
    `_fetch_trading_mode` above reuses `_trading_mode_response`. Runs the
    SAME `storage_service.set_app_setting` write + `TradingModeUpdate`
    validation the HTTP route uses -- there is no second write path to
    keep in sync, and the shared autonomy gate re-reads SQLite on every
    request, so the effect is immediate."""
    from app.api.routes.settings import TradingModeUpdate, set_trading_mode

    return await set_trading_mode(TradingModeUpdate(market=market, mode=mode))


async def handle_halt(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    """/halt -- kiwoom 자율 매매 긴급 정지 (autonomous -> hitl). Fail-safe
    방향(자율에서 더 안전한 수동 승인 쪽으로 전환)이라 확인 스텝 없이
    즉시 실행한다 (spec F2 리스크 표: "이상 징후 시 폰에서 즉시 자율 차단").

    이름 충돌 주의: 기존 `POST /trading/pause`·`/resume`
    (trading.py:186-222, 트레이딩 코디네이터/세션 스케줄러 자체의
    일시정지·재개)와는 **무관**하다 -- /halt는 kiwoom의 Autonomous|HITL
    모드만 hitl로 되돌릴 뿐, 코디네이터는 계속 돌아가고 이후 제안은
    자동승인 대신 수동 승인을 거친다.

    이미 진행 중인 60초 자동승인 카운트다운은 여기서 직접 취소하지
    않는다 -- 유예 만료 시 게이트 재검
    (`app.api.routes._autonomy_injector._auto_approve_after_grace`)이
    `trading_mode:kiwoom`이 더 이상 'autonomous'가 아님을 보고 스스로
    stood-down 처리한다 (기존 동작, 이 커맨드는 그 앞단의 모드 전환만
    담당).

    TG-4 review fix (Important): also invalidates any outstanding /auto
    confirm nonce (`invalidate_auto_confirm_nonce`) BEFORE attempting the
    mode write, so a halt always clears the slot even if the mode write
    itself later fails -- an old, never-tapped confirm button can no longer
    silently re-arm autonomous mode after an emergency stop.
    """
    invalidate_auto_confirm_nonce()
    await _set_trading_mode("kiwoom", "hitl")
    await _reply(
        update,
        "⛔ 자율 매매 정지(kiwoom→HITL). 진행 중 카운트다운은 유예 만료 시 "
        "게이트 재검으로 자동 취소됩니다",
    )


async def handle_auto(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    """/auto -- kiwoom HITL -> autonomous 재개, **2-스텝**.

    1차 명령 응답에서는 master 게이트(env `AUTONOMY_ENABLED` -- 이 모듈이
    이미 재사용하는 `_fetch_trading_mode()`/`_trading_mode_response()`가
    유일한 공식 판독 경로, settings.py:132; 직접 `settings.
    AUTONOMY_ENABLED`를 다시 읽지 않는다) 상태만 확인한다:
    - OFF: 정직하게 "재시작 필요"를 답장하고 버튼 없이 종료한다 -- env는
      텔레그램으로 켤 수 없다.
    - ON: 새 논스를 발급(`_issue_auto_confirm_nonce`, 이전 미소모 논스는
      자연 대체)하고 `[⚠️ 자율 재개 확인]` 버튼을 그 논스가 실린
      callback_data(`f"{AUTO_CONFIRM_CALLBACK_PREFIX}{nonce}"`)로 보낸다.
      실제 모드 전환 + `rearm_awaiting_approvals()` 재호출은 여기서 하지
      않고 `services.telegram.callbacks.handle_auto_confirm_callback`이
      콜백에서 논스를 검증·소모(`consume_auto_confirm_nonce`)한 뒤에만
      수행한다 (spec F2 리스크 표: "/auto 오발 -> 2-스텝 확인 버튼"; TG-4
      review fix: 논스+TTL 5분+`/halt` 무효화로 "오래된 확인 버튼 오클릭"도
      막는다).

    이름 충돌 주의: 기존 `POST /trading/pause`·`/resume`과 무관
    (`handle_halt`의 docstring 참고).
    """
    mode = await _fetch_trading_mode()
    if not mode.master_enabled:
        await _reply(update, "env AUTONOMY_ENABLED=false — 재시작 필요")
        return

    nonce = _issue_auto_confirm_nonce()
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            "⚠️ 자율 재개 확인",
            callback_data=f"{AUTO_CONFIRM_CALLBACK_PREFIX}{nonce}",
        )]]
    )
    message = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if message is not None:
        await message.reply_text(
            "kiwoom 자율 매매를 재개할까요? (버튼을 눌러 확인, 5분 내)",
            reply_markup=keyboard,
        )


# -------------------------------------------
# Registration (import-time side effect -- see module docstring)
# -------------------------------------------

register_command(
    "status", handle_status,
    summary="자율 가능 여부·계좌·한도 여유", group="지금 상태",
    detail="목적: 지금 자율 실행이 가능한 상태인가",
)
register_command(
    "positions", handle_positions,
    summary="보유 종목·실효 손절 여유", group="지금 상태",
    detail="목적: 지금 손절까지 얼마 남았나",
    caution="손절이 엔진마다 다르면 둘 다 표시. 실제 발동은 값이 높은 쪽",
)
register_command(
    "pending", handle_pending,
    summary="승인 대기 제안 + 버튼", group="승인 대기",
    detail="목적: 사람 승인을 기다리는 제안 확인",
)
register_command(
    "report", handle_report,
    summary="장마감 요약", group="성과",
    usage="/report 또는 /report 2026-07-29",
    detail="목적: 하루가 어떻게 끝났나",
)
register_command(
    "halt", handle_halt,
    summary="자율 정지 (자동 손절도 수동 전환)", group="상태를 바꿈", risk="mutate",
    detail=(
        "목적: 자율 실행을 즉시 멈춘다\n"
        "위험: 신규 매수만 막는 것이 아니다 — 자동 손절도 함께 멈춘다"
    ),
    caution="정지 중에는 손절가에 닿아도 사람이 승인해야 청산된다",
)
register_command(
    "auto", handle_auto,
    summary="자율 재개 (버튼 확인 5분)", group="상태를 바꿈", risk="mutate",
    detail="목적: /halt로 멈춘 자율 실행을 되살린다",
    caution="확인 버튼은 1회용이며 5분 뒤 만료된다",
)

# -------------------------------------------
# 브리핑·조회 명령 (2026-08-06)
# -------------------------------------------
#
# 포맷터와 수집기는 `services/telegram/briefing.py`에 있다 -- 이 파일이 이미
# 600행을 넘었고, 브리핑은 자체 데이터 계약과 순수 포맷터를 갖는 별개 단위다.


def _kst_today() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


def _prev_business_day(today: str) -> str:
    """직전 거래일. 휴장일 서비스가 없으면 단순히 하루 전으로 떨어진다.

    브리핑의 '어제' 섹션은 값이 비어도 브리핑 전체를 죽이지 않으므로,
    여기서 정확도보다 never-raise를 택한다.
    """
    from datetime import date, timedelta

    try:
        from services.krx_holiday import get_holiday_service_sync

        svc = get_holiday_service_sync()
        d = date.fromisoformat(today) - timedelta(days=1)
        for _ in range(10):
            if svc.is_trading_day(d):
                return d.isoformat()
            d -= timedelta(days=1)
    except Exception:
        pass
    return (date.fromisoformat(today) - timedelta(days=1)).isoformat()


async def handle_brief(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    from services.telegram.briefing import collect_brief, format_brief

    today = _kst_today()
    data = await _safe("brief", collect_brief(today, _prev_business_day(today)))
    if data is None:
        await _reply(update, f"[장전 브리핑] {today}\n\n{_NO_DATA}")
        return
    await _reply(update, format_brief(data))


async def handle_why(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    from services.telegram.briefing import collect_why, format_why

    args = getattr(context, "args", None) or []
    if not args:
        await _reply(update, "사용법: /why 316140")
        return
    ticker = str(args[0]).strip()
    data = await _safe("why", collect_why(ticker, _kst_today()))
    if data is None:
        await _reply(update, f"[왜?] {ticker}\n\n{_NO_DATA}")
        return
    await _reply(update, format_why(data))


async def handle_slots(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    from services.telegram.briefing import collect_slots, format_slots

    args = getattr(context, "args", None) or []
    trade_date = str(args[0]).strip() if args else _kst_today()
    data = await _safe("slots", collect_slots(trade_date))
    if data is None:
        await _reply(update, f"[슬롯 경합] {trade_date}\n\n{_NO_DATA}")
        return
    await _reply(update, format_slots(data))


async def handle_exposure(update: Update, context: "ContextTypes.DEFAULT_TYPE") -> None:
    from services.telegram.briefing import (
        collect_exposure,
        collect_regime_row,
        format_exposure,
        format_regime,
    )

    # 레짐 판정(regime_judgment)과 목표 노출도 관측(exposure_shadow)은 서로
    # 다른 테이블·다른 기능이라 각자 독립적으로 없거나 있을 수 있다 --
    # 하나가 죽어도 다른 하나는 그대로 나가도록 별도 `_safe`로 감싼다.
    # `format_exposure`/`collect_exposure`의 기존 계약(ExposureData/None/
    # ExposureUnavailable 삼중 상태, 기존 테스트 다수)은 건드리지 않는다.
    regime_row = await _safe("exposure_regime", collect_regime_row())
    data = await _safe("exposure", collect_exposure())
    await _reply(update, f"{format_regime(regime_row)}\n\n{format_exposure(data)}")


register_command(
    "brief", handle_brief,
    summary="장전 브리핑 (자산 배분·보유·어제·오늘 준비)", group="지금 상태",
    detail="목적: 오늘 무엇을 알고 시작해야 하나",
    caution="목표 노출도는 장중에만 갱신된다 — 표시된 기준 시각을 함께 볼 것",
)
register_command(
    "why", handle_why,
    summary="왜 샀나 / 왜 안 샀나", group="지금 상태",
    usage="/why 316140",
    detail="목적: 결정이 실행으로 이어졌는지, 아니면 무엇이 막았는지",
    caution="거절 사유는 활성 로그 꼬리에서 찾는다 — 로그가 회전하면 안 보일 수 있다",
)
register_command(
    "slots", handle_slots,
    summary="자리가 없어 거절된 종목", group="지금 상태",
    usage="/slots 또는 /slots 2026-08-06",
    detail="목적: 슬롯 상한이 기회를 얼마나 버리고 있나",
)
register_command(
    "exposure", handle_exposure,
    summary="목표 노출도와 성분", group="지금 상태",
    detail="목적: 지금 얼마나 실려야 하는가, 무엇이 그것을 묶고 있나",
    caution="degraded가 비어 있지 않으면 그 성분은 신뢰할 수 없어 중립 처리된 것",
)
