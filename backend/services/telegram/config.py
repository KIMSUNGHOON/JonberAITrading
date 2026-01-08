"""
Telegram Configuration

Settings for Telegram bot notifications.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramConfig(BaseSettings):
    """Telegram bot configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Bot settings
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(
        default=None,
        description="Telegram Bot API token from @BotFather"
    )
    TELEGRAM_CHAT_ID: Optional[str] = Field(
        default=None,
        description="Your Telegram chat ID to receive notifications"
    )
    TELEGRAM_ENABLED: bool = Field(
        default=False,
        description="Enable/disable Telegram notifications"
    )

    # Notification settings
    TELEGRAM_NOTIFY_TRADE_ALERTS: bool = Field(
        default=True,
        description="Send trade approval/execution alerts"
    )
    TELEGRAM_NOTIFY_POSITION_UPDATES: bool = Field(
        default=True,
        description="Send position P&L updates"
    )
    TELEGRAM_NOTIFY_ANALYSIS_COMPLETE: bool = Field(
        default=True,
        description="Send analysis completion notifications"
    )
    TELEGRAM_NOTIFY_SYSTEM_STATUS: bool = Field(
        default=True,
        description="Send system start/stop/error notifications"
    )

    @property
    def is_configured(self) -> bool:
        """Check if Telegram is properly configured."""
        return bool(
            self.TELEGRAM_ENABLED and
            self.TELEGRAM_BOT_TOKEN and
            self.TELEGRAM_CHAT_ID
        )


@lru_cache
def get_telegram_config() -> TelegramConfig:
    """Get cached Telegram configuration."""
    return TelegramConfig()
