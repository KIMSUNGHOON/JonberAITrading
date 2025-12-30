"""
Telegram Notification Service

Sends trading alerts and notifications via Telegram bot.
Uses polling mode - no external webhook required.
"""

import asyncio
from datetime import datetime
from functools import lru_cache
from typing import Optional

import structlog
from telegram import Bot
from telegram.error import TelegramError

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

    async def _send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a message to the configured chat."""
        if not self._initialized or not self._bot:
            return False

        try:
            await self._bot.send_message(
                chat_id=self._config.TELEGRAM_CHAT_ID,
                text=text,
                parse_mode=parse_mode,
            )
            return True
        except TelegramError as e:
            logger.error("telegram_send_failed", error=str(e))
            return False

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a custom message to the Telegram chat.

        This is a public method for sending arbitrary messages.
        Use this for notifications that don't fit other specific methods.
        """
        return await self._send_message(text, parse_mode)

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
