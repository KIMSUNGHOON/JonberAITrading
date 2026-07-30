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
    TELEGRAM_NOTIFY_DAILY_SUMMARY: bool = Field(
        default=True,
        description="Send end-of-day summary (digest+narrative) notifications (E3-3)"
    )
    TELEGRAM_NOTIFY_DISCOVERY: bool = Field(
        default=True,
        description="Send autonomous discovery promotion notifications (concise, one-way)"
    )
    # 체결 통지만 따로 끌 수 있게 한다 — TELEGRAM_NOTIFY_TRADE_ALERTS와 별도.
    TELEGRAM_NOTIFY_FILL_ENABLED: bool = Field(
        default=True, description="자율·승인 체결 통지 발송 여부"
    )

    # 이벤트 통지 화이트리스트. 기본은 '체결·실패만'(2026-07-30 결정) —
    # _notify_event가 게이트를 전혀 거치지 않아 07-30 2시간에 13건,
    # trailing_stop만 7건(스탑 이동폭 ₩124에 4건)이 스팸으로 나갔다.
    #
    # 최종 전체 브랜치 리뷰 Important 5: take_profit_hit은 이 화이트리스트에
    # 있었지만 *_NEAR와 달리 래치가 없다 — position_manager.py의 주석대로
    # "이 값이 참인 동안 매 틱 재발화"가 의도된 동작이다(익절가 위에서
    # 재평가 로직이 계속 관찰해야 하므로). auto_execute_take_profit이 기본
    # False라 _handle_event가 조기 반환하지 않고 매번 _notify_event까지
    # 도달한다 — check_interval_seconds=30 기준 시간당 최대 120건.
    #
    # 결정: take_profit_hit을 기본 CSV에서 뺀다(래치를 새로 만드는 대신).
    # ①실제 매도는 어차피 체결 통지(_record_fill_ledger)로 별도 도달한다.
    # ②익절가 위에서 토론이 실제로 열리면 그 결과가 agent_chat 쪽
    # _notify_decision으로 통지된다 — "폰에 아무것도 안 온다"가 아니라
    # "raw HIT 이벤트 대신 결정 통지로 대체"다. ③stop_loss_hit은 그대로
    # 둔다 — auto_execute_stop_loss가 기본 True라 게이트 통과 시 즉시
    # 체결/포지션 제거로 자연 소멸하고, 거부/거절은 이미 래치된 별도
    # 알림(close_gate_denied_notified/close_order_rejected_notified)이
    # 있어 take_profit_hit과 같은 무래치 플러딩 경로가 아니다.
    TELEGRAM_NOTIFY_EVENT_KINDS: str = Field(
        default="stop_loss_hit",
        description="폰으로 보낼 PositionEventType 값 CSV",
    )

    # 상태 변경 명령(/halt, /auto)에만 적용되는 발신자 화이트리스트.
    # 미설정이면 현행 동작(chat_id 검증만) 유지 — 새 설정을 강제해 기존
    # 운용을 갑자기 막지 않는다. TELEGRAM_CHAT_ID를 그룹으로 바꾸는 순간
    # 그룹원 전원이 /halt(=자동 손절 무장해제)를 칠 수 있어 필요하다.
    TELEGRAM_ADMIN_USER_ID: Optional[str] = Field(
        default=None, description="상태 변경 명령을 칠 수 있는 Telegram user id"
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
