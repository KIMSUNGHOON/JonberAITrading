"""
Telegram Notification Service

Sends trading alerts and notifications via Telegram bot.
Uses polling mode - no external webhook required.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from typing import Optional

import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError

from services.telegram.config import get_telegram_config, TelegramConfig

logger = structlog.get_logger()


class TelegramNotifier:
    """
    Telegram notification service for trading alerts.

    Features:
    - Trade alerts (approval requests, executions)
    - Position updates (P&L changes)
    - Analysis completion notifications
    - System status messages
    """

    def __init__(self, config: Optional[TelegramConfig] = None):
        self._config = config or get_telegram_config()
        self._bot: Optional[Bot] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the Telegram bot."""
        if not self._config.is_configured:
            logger.warning(
                "telegram_not_configured",
                message="Telegram notifications disabled - missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
            )
            return False

        try:
            self._bot = Bot(token=self._config.TELEGRAM_BOT_TOKEN)
            # Test connection
            me = await self._bot.get_me()
            self._initialized = True
            logger.info(
                "telegram_initialized",
                bot_username=me.username,
                chat_id=self._config.TELEGRAM_CHAT_ID,
            )
            return True
        except TelegramError as e:
            logger.error("telegram_init_failed", error=str(e))
            return False

    def _split_message(self, text: str, max_length: int = 4000) -> list[str]:
        """
        Split a long message into chunks that fit within Telegram's limit.

        Telegram limit is 4096 chars, we use 4000 to be safe.
        Tries to split at newlines or spaces when possible.
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= max_length:
                chunks.append(remaining)
                break

            # Find best split point (prefer newlines, then spaces)
            split_pos = max_length

            # Try to find newline near the end of allowed length
            newline_pos = remaining.rfind("\n", 0, max_length)
            if newline_pos > max_length * 0.6:  # Only if not too far back
                split_pos = newline_pos + 1
            else:
                # Try to find space
                space_pos = remaining.rfind(" ", 0, max_length)
                if space_pos > max_length * 0.6:
                    split_pos = space_pos + 1

            chunks.append(remaining[:split_pos].rstrip())
            remaining = remaining[split_pos:].lstrip()

        return chunks

    async def _send_chunks(
        self,
        chunks: list[str],
        parse_mode: Optional[str],
        reply_markup: Optional["InlineKeyboardMarkup"],
        start_index: int = 0,
    ) -> tuple[int, Optional[TelegramError]]:
        """`chunks[start_index:]`를 순서대로 발송한다.

        primary 발송(마크다운 재시도 전 원본)과 평문 폴백이 이 한 곳을
        공유한다 — 청크 분할·연속 표시(`_(계속...)_`)·청크 간 지연·
        `reply_markup`을 첫 청크에만 붙이는 규칙이 두 곳에 따로 있으면
        어긋나기 쉽다.

        연속 표시는 `parse_mode`가 있을 때만 붙인다 — `_(계속...)_` 자체가
        밑줄로 시작하는 Markdown 마커라 평문(`parse_mode=None`) 경로에서는
        리터럴로 노출되기 때문이다.

        반환값은 (다음에 재개할 인덱스, 실패 시 그 예외 또는 성공 시 None).
        도중 실패하면 그 지점에서 멈추고 실패한 인덱스를 반환한다 — 호출부가
        이미 보낸 청크를 폴백에서 처음부터 다시 보내 중복 발송하는 일을
        막기 위함이다.
        """
        total = len(chunks)
        for i in range(start_index, total):
            chunk = chunks[i]
            if parse_mode and total > 1:
                if i == 0:
                    chunk = chunk + "\n\n_(계속...)_"
                elif i < total - 1:
                    chunk = f"_(...계속)_\n\n{chunk}\n\n_(계속...)_"
                else:
                    chunk = f"_(...계속)_\n\n{chunk}"

            try:
                await self._bot.send_message(
                    chat_id=self._config.TELEGRAM_CHAT_ID,
                    text=chunk,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup if i == 0 else None,
                )
            except TelegramError as e:
                return i, e

            # Small delay between chunks to maintain order
            if i < total - 1:
                await asyncio.sleep(0.3)

        return total, None

    async def _send_message(
        self,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: Optional["InlineKeyboardMarkup"] = None,
    ) -> bool:
        """Send a message to the configured chat. Handles long messages by splitting.

        `reply_markup` (TG-3): optional InlineKeyboardMarkup, attached only to
        the FIRST chunk of a (possibly split) message so a long message never
        ends up with the same keyboard duplicated across parts. Defaults to
        None, which is byte-identical to every pre-TG-3 call site (none of
        which pass this argument) -- PTB's own `send_message` already
        defaults `reply_markup=None`.
        """
        if not self._initialized or not self._bot:
            return False

        chunks = self._split_message(text)
        sent_index, error = await self._send_chunks(chunks, parse_mode, reply_markup)
        if error is None:
            return True

        # Markdown 파싱 실패는 재시도 가치가 있다 — 이 레포는 같은 원인으로
        # 라이브 통지를 두 번 잃었고(51227ca), 세 번째가 진행 중이었다
        # (_notify_decision의 'NO_ACTION' 밑줄, 07-30 하루 18건+).
        # 파싱 외 실패(네트워크·권한)는 재시도하면 중복 발송이 되므로 제외.
        reason = str(error)
        # BadRequest는 Telegram이 요청을 동기적으로 거부했다는 뜻이라
        # 메시지가 실제로 발송된 적이 없다 — 재시도해도 중복 발송 위험이
        # 없다. TimedOut/NetworkError/Forbidden 등 그 외 TelegramError는
        # 전송 여부가 불확실하므로(응답만 유실됐을 수 있음) 재시도하지
        # 않는다. 메시지 문자열(parse/entity 등)만으로 판별하면 Telegram
        # API가 문구를 바꿀 때마다 조용히 깨지므로 예외 타입으로 판별한다.
        is_parse_error = isinstance(error, BadRequest)
        logger.error(
            "telegram_send_failed",
            parse_mode=parse_mode,
            error_type=type(error).__name__,
            error=reason,
            # 본문 앞부분만 — 무엇이 유실됐는지 알 수 있어야 한다.
            # 토큰은 본문에 실리지 않으므로 안전하다.
            text_head=text[:120],
            will_retry_plain=bool(is_parse_error and parse_mode),
        )
        if not (is_parse_error and parse_mode):
            return False

        # sent_index부터 재개한다 — 이미 성공한 청크(예: 긴 메시지의 1번
        # 청크)를 처음부터 다시 보내면 그 청크만 두 번 발송되는 사고가 된다.
        _, error2 = await self._send_chunks(
            chunks, None, reply_markup, start_index=sent_index
        )
        if error2 is None:
            logger.warning("telegram_send_plain_fallback_ok", text_head=text[:120])
            return True

        logger.error(
            "telegram_send_plain_fallback_failed",
            error_type=type(error2).__name__,
            error=str(error2),
            text_head=text[:120],
        )
        return False

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a custom message to the Telegram chat.

        This is a public method for sending arbitrary messages.
        Use this for notifications that don't fit other specific methods.
        """
        return await self._send_message(text, parse_mode)

    # -------------------------------------------
    # Approval/Reject Inline Buttons (TG-3, spec F1)
    # -------------------------------------------

    async def send_approval_request(
        self,
        session_id: str,
        market: str,
        proposal: dict,
        auto_approve_at: Optional[str] = None,
    ) -> bool:
        """Send an approve/reject inline-keyboard request for a pending trade
        proposal.

        Fires for BOTH plain-HITL and autonomous sessions -- this is the
        single dispatch point the producer's awaiting-commit success path
        (via `_autonomy_injector.maybe_schedule_auto_approve`) always
        reaches once a session lands in awaiting_approval, replacing the
        injector's old auto-only `_notify_pending` text heads-up (spec F1).
        `auto_approve_at` (an ISO datetime, or None for plain HITL) controls
        whether the message includes the autonomous countdown line -- the
        button pair itself is identical either way.

        callback_data uses `a:{session_id}:{pid8}` / `r:{session_id}:{pid8}`
        (pid8 = the first 8 chars of proposal["id"]) rather than the full
        proposal id, to stay comfortably under Telegram's 64-byte
        callback_data limit (2 + 36 + 1 + 8 = 47B for a uuid4 session_id).
        This is a fast filter, not the security boundary -- the callback
        handler (services/telegram/callbacks.py) re-validates the prefix
        against the LIVE proposal id before acting, and `approval.
        submit_decision`'s actor='telegram' pin (approval.py, F1) closes the
        TOCTOU window inside the per-session lock.

        Best-effort like every other send_* method here: gated on
        TELEGRAM_NOTIFY_TRADE_ALERTS, and any send failure is absorbed by
        `_send_message`'s own bool-returning contract -- callers must never
        let this failure affect the approval pipeline that already
        committed by the time this runs.
        """
        if not self._config.TELEGRAM_NOTIFY_TRADE_ALERTS:
            return False

        action = str(proposal.get("action") or "-").upper()
        emoji = self._get_action_emoji(action)
        proposal_id = str(proposal.get("id") or "")
        pid8 = proposal_id[:8]

        quantity = proposal.get("quantity")
        entry_price = proposal.get("entry_price")

        lines = [
            f"{emoji} *승인 요청* ({market})",
            "",
            f"*행동:* {action}",
        ]
        if quantity is not None:
            try:
                lines.append(f"*수량:* {quantity:,}")
            except (TypeError, ValueError):
                lines.append(f"*수량:* {quantity}")
        if entry_price is not None:
            try:
                lines.append(f"*가격:* ₩{float(entry_price):,.0f}")
            except (TypeError, ValueError):
                lines.append(f"*가격:* {entry_price}")

        countdown = self._format_auto_approve_countdown(auto_approve_at)
        if countdown:
            lines.append("")
            lines.append(countdown)

        lines.append("")
        lines.append(f"_세션 {session_id[:8]}_")

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ 승인", callback_data=f"a:{session_id}:{pid8}"),
                    InlineKeyboardButton("❌ 거부", callback_data=f"r:{session_id}:{pid8}"),
                ]
            ]
        )

        return await self._send_message("\n".join(lines), reply_markup=keyboard)

    @staticmethod
    def _format_auto_approve_countdown(auto_approve_at: Optional[str]) -> Optional[str]:
        """`None`/blank -> no countdown line (plain HITL). A present value is
        parsed as an ISO datetime and rendered as remaining whole seconds --
        falls back to a countdown-free autonomous phrase if parsing fails
        rather than dropping the autonomy notice entirely."""
        if not auto_approve_at:
            return None
        try:
            target = datetime.fromisoformat(auto_approve_at)
        except (TypeError, ValueError):
            return "⏳ _자동승인 예정 — 거부하려면 지금 누르세요_"
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        remaining = max(0, int((target - datetime.now(timezone.utc)).total_seconds()))
        return f"⏳ _{remaining}초 후 자동승인 — 거부하려면 지금 누르세요_"

    # -------------------------------------------
    # Trade Alerts
    # -------------------------------------------

    async def send_trade_proposal(
        self,
        ticker: str,
        stock_name: str,
        action: str,
        entry_price: int,
        stop_loss: Optional[int] = None,
        take_profit: Optional[int] = None,
        confidence: float = 0.0,
        rationale: str = "",
    ) -> bool:
        """Send trade proposal notification."""
        if not self._config.TELEGRAM_NOTIFY_TRADE_ALERTS:
            return False

        emoji = self._get_action_emoji(action)

        message = f"""
{emoji} *거래 제안*

*종목:* {stock_name} ({ticker})
*행동:* {action}
*진입가:* ₩{entry_price:,}
*손절가:* {"₩" + f"{stop_loss:,}" if stop_loss else "미설정"}
*목표가:* {"₩" + f"{take_profit:,}" if take_profit else "미설정"}
*신뢰도:* {confidence:.0%}

📝 *분석 요약:*
{rationale[:500]}...

_승인 대기 중..._
"""
        return await self._send_message(message.strip())

    async def send_trade_executed(
        self,
        ticker: str,
        stock_name: str,
        action: str,
        quantity: int,
        price: int,
        total_amount: int,
    ) -> bool:
        """Send trade execution notification."""
        if not self._config.TELEGRAM_NOTIFY_TRADE_ALERTS:
            return False

        emoji = "✅" if action in ("BUY", "ADD") else "🔴"

        message = f"""
{emoji} *거래 체결*

*종목:* {stock_name} ({ticker})
*행동:* {action}
*수량:* {quantity:,}주
*체결가:* ₩{price:,}
*총액:* ₩{total_amount:,}

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        return await self._send_message(message.strip())

    async def send_trade_pending(
        self,
        ticker: str,
        stock_name: str,
        action: str,
        quantity: int,
        ord_no: Optional[str] = None,
    ) -> bool:
        """Send order-placed-but-unfilled notification.

        Distinct from send_trade_executed (F4b I5): the broker accepted the
        order (execution_status=='placed_pending_fill') but a fill has not
        been confirmed yet -- never word this as an execution.
        """
        if not self._config.TELEGRAM_NOTIFY_TRADE_ALERTS:
            return False

        message = f"""
🟡 *거래 접수 — 체결 대기*

*종목:* {stock_name} ({ticker})
*행동:* {action}
*수량:* {quantity:,}주
*주문번호:* {ord_no or "확인 불가"}

_체결이 아직 확인되지 않았습니다._

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        return await self._send_message(message.strip())

    async def send_trade_rejected(
        self,
        ticker: str,
        stock_name: str,
        reason: str = "",
    ) -> bool:
        """Send trade rejection notification."""
        if not self._config.TELEGRAM_NOTIFY_TRADE_ALERTS:
            return False

        message = f"""
❌ *거래 거절*

*종목:* {stock_name} ({ticker})
*사유:* {reason or "사용자 거절"}

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        return await self._send_message(message.strip())

    async def send_watch_list_added(
        self,
        ticker: str,
        stock_name: str,
        signal: str = "hold",
        confidence: float = 0.0,
        current_price: int = 0,
        target_price: Optional[int] = None,
        risk_score: int = 5,
    ) -> bool:
        """Send watch list addition notification."""
        if not self._config.TELEGRAM_NOTIFY_TRADE_ALERTS:
            return False

        signal_emoji = {
            "strong_buy": "🟢",
            "buy": "🔵",
            "hold": "🟡",
            "sell": "🟠",
            "strong_sell": "🔴",
        }.get(signal.lower(), "🟡")

        message = f"""
👁️ *Watch List 등록*

*종목:* {stock_name} ({ticker})
*신호:* {signal_emoji} {signal.upper()}
*신뢰도:* {confidence:.0%}
*현재가:* ₩{current_price:,}
*목표가:* {"₩" + f"{target_price:,}" if target_price else "미설정"}
*위험도:* {risk_score}/10

_모니터링 중..._

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        return await self._send_message(message.strip())

    # -------------------------------------------
    # Position Updates
    # -------------------------------------------

    async def send_position_update(
        self,
        ticker: str,
        stock_name: str,
        quantity: int,
        avg_price: int,
        current_price: int,
        pnl_amount: int,
        pnl_pct: float,
    ) -> bool:
        """Send position P&L update."""
        if not self._config.TELEGRAM_NOTIFY_POSITION_UPDATES:
            return False

        emoji = "📈" if pnl_pct >= 0 else "📉"
        pnl_sign = "+" if pnl_pct >= 0 else ""

        message = f"""
{emoji} *포지션 업데이트*

*종목:* {stock_name} ({ticker})
*보유:* {quantity:,}주
*평균단가:* ₩{avg_price:,}
*현재가:* ₩{current_price:,}
*손익:* {pnl_sign}₩{pnl_amount:,} ({pnl_sign}{pnl_pct:.2f}%)

⏰ {datetime.now().strftime("%H:%M:%S")}
"""
        return await self._send_message(message.strip())

    async def send_stop_loss_triggered(
        self,
        ticker: str,
        stock_name: str,
        trigger_price: int,
        stop_loss_price: int,
    ) -> bool:
        """Send stop-loss trigger alert."""
        if not self._config.TELEGRAM_NOTIFY_TRADE_ALERTS:
            return False

        message = f"""
🚨 *손절가 도달*

*종목:* {stock_name} ({ticker})
*현재가:* ₩{trigger_price:,}
*손절가:* ₩{stop_loss_price:,}

⚠️ 손절 매도를 검토하세요!
"""
        return await self._send_message(message.strip())

    async def send_take_profit_triggered(
        self,
        ticker: str,
        stock_name: str,
        trigger_price: int,
        take_profit_price: int,
    ) -> bool:
        """Send take-profit trigger alert."""
        if not self._config.TELEGRAM_NOTIFY_TRADE_ALERTS:
            return False

        message = f"""
🎯 *목표가 도달*

*종목:* {stock_name} ({ticker})
*현재가:* ₩{trigger_price:,}
*목표가:* ₩{take_profit_price:,}

💰 익절 매도를 검토하세요!
"""
        return await self._send_message(message.strip())

    # -------------------------------------------
    # Analysis Notifications
    # -------------------------------------------

    async def send_analysis_started(
        self,
        ticker: str,
        stock_name: str,
        session_id: str,
    ) -> bool:
        """Send analysis started notification."""
        if not self._config.TELEGRAM_NOTIFY_ANALYSIS_COMPLETE:
            return False

        message = f"""
🔍 *분석 시작*

*종목:* {stock_name} ({ticker})
*세션:* {session_id[:8]}...

분석 진행 중...
"""
        return await self._send_message(message.strip())

    async def send_analysis_complete(
        self,
        ticker: str,
        stock_name: str,
        action: str,
        confidence: float,
        summary: str,
    ) -> bool:
        """Send analysis completion notification."""
        if not self._config.TELEGRAM_NOTIFY_ANALYSIS_COMPLETE:
            return False

        emoji = self._get_action_emoji(action)

        message = f"""
{emoji} *분석 완료*

*종목:* {stock_name} ({ticker})
*추천:* {action}
*신뢰도:* {confidence:.0%}

📊 *요약:*
{summary[:500]}

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        return await self._send_message(message.strip())

    async def send_subagent_decision(
        self,
        ticker: str,
        stock_name: str,
        agent_type: str,
        signal: str,
        confidence: float,
        key_factors: list[str],
    ) -> bool:
        """Send sub-agent analysis decision."""
        if not self._config.TELEGRAM_NOTIFY_ANALYSIS_COMPLETE:
            return False

        agent_emoji = {
            "technical": "📈",
            "fundamental": "📊",
            "sentiment": "📰",
            "risk": "🛡️",
        }.get(agent_type.lower(), "🤖")

        factors_text = "\n".join([f"• {f}" for f in key_factors[:5]])

        message = f"""
{agent_emoji} *{agent_type.title()} 분석 완료*

*종목:* {stock_name} ({ticker})
*시그널:* {signal}
*신뢰도:* {confidence:.0%}

*주요 요인:*
{factors_text}
"""
        return await self._send_message(message.strip())

    # -------------------------------------------
    # System Status
    # -------------------------------------------

    async def send_system_status(
        self,
        status: str,
        message: str = "",
    ) -> bool:
        """Send system status notification."""
        if not self._config.TELEGRAM_NOTIFY_SYSTEM_STATUS:
            return False

        emoji_map = {
            "started": "🟢",
            "stopped": "🔴",
            "paused": "🟡",
            "resumed": "🟢",
            "error": "❌",
        }
        emoji = emoji_map.get(status.lower(), "ℹ️")

        msg = f"""
{emoji} *시스템 상태: {status.upper()}*

{message if message else ""}

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        return await self._send_message(msg.strip())

    async def send_error_alert(
        self,
        error_type: str,
        error_message: str,
        context: str = "",
    ) -> bool:
        """Send error alert."""
        if not self._config.TELEGRAM_NOTIFY_SYSTEM_STATUS:
            return False

        message = f"""
❌ *오류 발생*

*유형:* {error_type}
*메시지:* {error_message}
{f"*컨텍스트:* {context}" if context else ""}

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
        return await self._send_message(message.strip())

    # -------------------------------------------
    # Daily Summary (E3-3)
    # -------------------------------------------

    async def send_daily_summary(
        self,
        digest: dict,
        narrative: Optional[str] = None,
    ) -> bool:
        """Send the end-of-day summary notification.

        Reuses the digest/narrative E3-1/E3-2 already computed and
        persisted (services/trading/eod_digest.py::build_eod_digest /
        narrate_eod_digest) -- this method never recomputes either or
        calls the LLM itself, it only formats what it's handed:

          - `narrative` present (and non-blank) -> the narrative body plus
            a compact key-figures header pulled straight from
            `digest["account"]` (total_equity/daily_realized_pnl).
          - `narrative` None/blank (LLM failure or timeout, per
            narrate_eod_digest's never-raise contract) -> a DETERMINISTIC
            4-block Markdown template (watch/account/holdings/strategy)
            built purely from `digest`'s fields, plus an OPTIONAL 5th
            discovery block appended only when `digest["discovery"]` is
            present (DS-5 review fix) -- absent for every digest that
            predates the discovery feature or ran with DISCOVERY_ENABLED
            off, in which case the output is unchanged from before this
            block existed. Each block independently degrades to a "no
            data" placeholder rather than raising or omitting the section,
            mirroring build_eod_digest's own failure-harmless contract --
            a caller can pass a partially-degraded digest (e.g.
            strategy=None) and still get a well-formed message.

        Delegates to the existing `_send_message` (and its `_split_message`
        4000-char chunking) exactly like every other send_* method here --
        no bespoke chunking added for what can be a long narrative or a
        long watch/holdings list.

        Gate: TELEGRAM_NOTIFY_DAILY_SUMMARY (new category flag, default
        True) mirrors every other TELEGRAM_NOTIFY_* category gate above.
        The `is_configured` master gate is enforced by the untouched
        `_send_message` initialized/bot check, same as every other method.
        """
        if not self._config.TELEGRAM_NOTIFY_DAILY_SUMMARY:
            return False

        trade_date = digest.get("trade_date") or "-"

        if narrative and narrative.strip():
            message = self._format_daily_summary_narrative(trade_date, digest, narrative)
        else:
            message = self._format_daily_summary_template(trade_date, digest)

        return await self._send_message(message.strip())

    async def send_discovery_promotion(
        self, *, trade_date: str, promoted: list[dict], daily_cap_waiting: int = 0
    ) -> bool:
        """Concise, one-way notification for autonomous discovery
        promotions (no buttons/HITL -- discovery promotes stocks to the
        watchlist for the NEXT open's discussion/vote, it never trades
        directly, so there is nothing to approve here).

        `promoted` items: {"ticker","name","composite","strategy","target"}
        (the discovery pipeline's promoted-candidate shape -- distinct from
        `_format_discovery_block`'s digest["discovery"]["promoted"] shape
        used by the EOD summary, which carries composite_score/
        top_strategy_tag instead).

        No-op (returns False, no send) when the gate is off OR `promoted`
        is empty -- mirrors every other TELEGRAM_NOTIFY_* category gate
        above, plus discovery's own "0 promotions -> nothing worth
        notifying about" case.
        """
        if not self._config.TELEGRAM_NOTIFY_DISCOVERY:
            return False
        if not promoted:
            return False

        message = self._format_discovery_promotion(trade_date, promoted, daily_cap_waiting)
        return await self._send_message(message.strip())

    def _format_discovery_promotion(
        self, trade_date: str, promoted: list[dict], daily_cap_waiting: int
    ) -> str:
        _MAX = 10
        lines = [f"🔍 *자율 발굴 승격 {len(promoted)}종* · {trade_date}"]
        for p in promoted[:_MAX]:
            # 종목명/전략은 자유텍스트 → Markdown 특수문자 이스케이프(발송 실패 방지)
            name = self._md_escape(str(p.get("name") or p.get("ticker") or "-"))
            strategy = self._md_escape(str(p.get("strategy") or "-"))
            lines.append(
                f"• {name} {p['ticker']} · {self._fmt_composite(p.get('composite'))} "
                f"{strategy} · 워치 {self._fmt_price(p.get('target'))}"
            )
        if len(promoted) > _MAX:
            lines.append(f"• 외 {len(promoted) - _MAX}종")
        tail = "개장 시 토론→투표"
        if daily_cap_waiting > 0:
            # "daily_cap"의 밑줄은 Telegram Markdown italic 시작으로 오해돼 발송 실패 → 한글 표기
            tail = f"+{daily_cap_waiting}종 일일한도 대기 · {tail}"
        lines.append(tail)
        return "\n".join(lines)

    @staticmethod
    def _md_escape(text: str) -> str:
        """Telegram 레거시 Markdown 특수문자 이스케이프(자유텍스트용)."""
        for ch in ("_", "*", "`", "["):
            text = text.replace(ch, "\\" + ch)
        return text

    @staticmethod
    def _fmt_price(value) -> str:
        """워치 진입가격(레벨) 플레인 천단위 표기 — 승인 형식 "3,850".
        `_fmt_krw`는 P&L용 부호(+₩)를 붙여 가격 레벨엔 부적절하므로 별도."""
        try:
            return f"{int(round(float(value))):,}" if value is not None else "―"
        except (TypeError, ValueError):
            return "―"

    @staticmethod
    def _fmt_composite(value) -> str:
        """Format a composite score to 2 decimals, ROUND_HALF_UP.

        Plain `f"{value:.2f}"` uses banker's rounding on the float's
        underlying binary representation, which silently rounds
        .xx5-ending values DOWN more often than not (e.g. 0.725 is stored
        as 0.72499999999999997779... and formats to "0.72", not the
        expected "0.73") -- surprising for a score display where users
        expect familiar half-up rounding. Round via `Decimal(str(value))`
        (the shortest decimal string that round-trips to the same float,
        i.e. what a human almost certainly intended) rather than
        `Decimal(value)` (which would re-expose the raw binary noise).
        """
        try:
            d = Decimal(str(float(value) if value is not None else 0))
        except (TypeError, ValueError, InvalidOperation):
            return "0.00"
        return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def _format_daily_summary_narrative(
        self, trade_date: str, digest: dict, narrative: str
    ) -> str:
        account = digest.get("account") or {}
        regime = digest.get("regime") or {}
        regime_line = f"\n시장: {regime['label']}" if regime.get("label") else ""

        return f"""
📋 *장마감 요약 ({trade_date})*

{narrative.strip()}

*핵심 수치*
총평가: {self._fmt_krw(account.get("total_equity"))}
당일 실현손익: {self._fmt_krw(account.get("daily_realized_pnl"))}{regime_line}

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    def _format_daily_summary_template(self, trade_date: str, digest: dict) -> str:
        regime = digest.get("regime") or {}
        regime_line = f"\n🌐 시장: {regime['label']}" if regime.get("label") else ""

        # Minor (DS-5 review fix): discovery block appended AFTER the
        # existing 4 blocks, only when `digest` actually carries a
        # "discovery" key -- most digests never do (DISCOVERY_ENABLED off,
        # or a digest built before this feature existed at all), and for
        # those `discovery_section` is simply "" so the rendered message is
        # byte-identical to before this fix (key-absent-safe via `.get`,
        # existing 4-block format/order untouched).
        discovery = digest.get("discovery")
        discovery_section = (
            f"\n\n*🔍 발굴*\n{self._format_discovery_block(discovery)}" if discovery else ""
        )

        return f"""
📋 *장마감 요약 ({trade_date})*{regime_line}

*👁️ 워치리스트*
{self._format_watch_block(digest.get("watch") or [])}

*💰 계좌*
{self._format_account_block(digest.get("account"))}

*📦 보유 종목*
{self._format_holdings_block(digest.get("holdings") or [])}

*🧭 전략*
{self._format_strategy_block(digest.get("strategy"))}{discovery_section}

⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    def _format_watch_block(self, watch: list) -> str:
        if not watch:
            return "데이터 없음"
        lines = []
        for w in watch[:10]:
            ticker = w.get("ticker") or "-"
            name = w.get("stock_name") or ticker
            signal = str(w.get("signal") or "-").upper()
            gap = self._fmt_pct(w.get("gap_pct"))
            lines.append(f"• {name}({ticker}) {signal} 갭 {gap}")
        return "\n".join(lines)

    def _format_account_block(self, account: Optional[dict]) -> str:
        if not account:
            return "데이터 없음"
        return (
            f"예수금: {self._fmt_krw(account.get('deposit'))}\n"
            f"총평가: {self._fmt_krw(account.get('total_equity'))}\n"
            f"당일 실현손익: {self._fmt_krw(account.get('daily_realized_pnl'))}\n"
            f"누적 수익률: {self._fmt_pct(account.get('cumulative_return_pct'))}"
        )

    def _format_holdings_block(self, holdings: list) -> str:
        if not holdings:
            return "보유 종목 없음"
        lines = []
        for h in holdings[:10]:
            ticker = h.get("ticker") or "-"
            name = h.get("stock_name") or ticker
            qty = h.get("quantity") or 0
            pnl = self._fmt_krw(h.get("unrealized_pnl"))
            pnl_pct = self._fmt_pct(h.get("unrealized_pnl_pct"))
            lines.append(f"• {name}({ticker}) {qty:,}주 손익 {pnl} ({pnl_pct})")
        return "\n".join(lines)

    def _format_strategy_block(self, strategy: Optional[dict]) -> str:
        if not strategy:
            return "데이터 없음"
        stance = strategy.get("stance") or "-"
        changed = "변경됨" if strategy.get("changed") else "유지"
        rationale = (strategy.get("rationale_excerpt") or "").strip()
        text = f"스탠스: {stance} ({changed})"
        if rationale:
            text += f"\n{rationale[:300]}"
        return text

    def _format_discovery_block(self, discovery: dict) -> str:
        """Minor (DS-5 review fix): compact 승격 종목 요약 -- 티커/이름/
        composite 스코어. `digest["discovery"]` shape is
        `eod_digest._build_discovery_section`'s return dict
        (promoted/skip_counts/total_candidates/prev_day); only `promoted`
        is rendered here, mirroring the other blocks' "몇 줄 요약" brevity."""
        promoted = discovery.get("promoted") or []
        if not promoted:
            return "승격 없음"
        lines = []
        for p in promoted[:10]:
            ticker = p.get("ticker") or "-"
            name = p.get("name") or ticker
            score = p.get("composite_score")
            score_text = f"{score:.1f}" if isinstance(score, (int, float)) else "―"
            lines.append(f"• {name}({ticker}) 스코어 {score_text}")
        return "\n".join(lines)

    @staticmethod
    def _fmt_krw(value) -> str:
        if value is None:
            return "―"
        try:
            if value < 0:
                return f"-₩{abs(value):,.0f}"
            sign = "+" if value > 0 else ""
            return f"{sign}₩{value:,.0f}"
        except (TypeError, ValueError):
            return "―"

    @staticmethod
    def _fmt_pct(value) -> str:
        if value is None:
            return "―"
        try:
            sign = "+" if value >= 0 else ""
            return f"{sign}{value:.2f}%"
        except (TypeError, ValueError):
            return "―"

    # -------------------------------------------
    # Helpers
    # -------------------------------------------

    @staticmethod
    def _get_action_emoji(action: str) -> str:
        """Get emoji for trade action."""
        emoji_map = {
            "BUY": "🟢",
            "SELL": "🔴",
            "HOLD": "🟡",
            "ADD": "➕",
            "REDUCE": "➖",
            "AVOID": "⛔",
            "WATCH": "👀",
        }
        return emoji_map.get(action.upper(), "📊")

    @property
    def is_ready(self) -> bool:
        """Check if notifier is ready to send messages."""
        return self._initialized and self._bot is not None


# Singleton instance
_notifier_instance: Optional[TelegramNotifier] = None


async def get_telegram_notifier() -> TelegramNotifier:
    """Get or create the Telegram notifier singleton."""
    global _notifier_instance

    if _notifier_instance is None:
        _notifier_instance = TelegramNotifier()
        await _notifier_instance.initialize()

    return _notifier_instance
