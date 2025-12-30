"""
Telegram Notification Service Package

Provides real-time trading alerts via Telegram bot.
Uses polling mode (no webhook required).
"""

from services.telegram.config import TelegramConfig, get_telegram_config
from services.telegram.service import TelegramNotifier, get_telegram_notifier

__all__ = [
    "TelegramConfig",
    "get_telegram_config",
    "TelegramNotifier",
    "get_telegram_notifier",
]
