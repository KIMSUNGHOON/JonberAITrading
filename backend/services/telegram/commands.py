"""
Telegram Read-Only Query Commands (TG-2)

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
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Optional, TypeVar

import structlog
from telegram import Update
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


async def _reply(update: Update, text: str) -> None:
    message = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if message is not None:
        await message.reply_text(text)


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
        lines.append(f"모드: 키움={mode.kiwoom} 코인={mode.coin} (마스터 {master})")
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
    for item in awaiting:
        sent = await _send_pending_button(item)
        if not sent:
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
# Registration (import-time side effect -- see module docstring)
# -------------------------------------------

register_command("status", handle_status)
register_command("positions", handle_positions)
register_command("pending", handle_pending)
register_command("report", handle_report)
