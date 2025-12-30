"""
Market Hours Service

Provides market open/close time checking for different markets.
Supports Korean stocks (KRX) and cryptocurrency (24/7).
"""

from datetime import datetime, time, timedelta
from enum import Enum
from typing import NamedTuple, Optional
import pytz

import structlog

logger = structlog.get_logger()


class MarketType(str, Enum):
    """Supported market types"""
    KRX = "krx"          # Korea Exchange (Korean stocks)
    CRYPTO = "crypto"    # Cryptocurrency (24/7)
    NYSE = "nyse"        # New York Stock Exchange
    NASDAQ = "nasdaq"    # NASDAQ


class MarketSession(NamedTuple):
    """Market trading session information"""
    is_open: bool
    current_time: datetime
    next_open: Optional[datetime]
    next_close: Optional[datetime]
    message: str


# Korea timezone
KST = pytz.timezone("Asia/Seoul")
EST = pytz.timezone("America/New_York")


class MarketHoursService:
    """
    Service for checking market trading hours.

    Supports:
    - KRX: 09:00-15:30 KST (Mon-Fri, excluding holidays)
    - Crypto: 24/7
    - NYSE/NASDAQ: 09:30-16:00 EST (Mon-Fri, excluding holidays)
    """

    # Korean public holidays 2025 (simplified - should use a proper calendar)
    KRX_HOLIDAYS_2025 = [
        datetime(2025, 1, 1),   # New Year
        datetime(2025, 1, 28),  # Lunar New Year
        datetime(2025, 1, 29),
        datetime(2025, 1, 30),
        datetime(2025, 3, 1),   # Independence Movement Day
        datetime(2025, 5, 5),   # Children's Day
        datetime(2025, 5, 6),   # Buddha's Birthday (substitute)
        datetime(2025, 6, 6),   # Memorial Day
        datetime(2025, 8, 15),  # Liberation Day
        datetime(2025, 10, 3),  # National Foundation Day
        datetime(2025, 10, 6),  # Chuseok
        datetime(2025, 10, 7),
        datetime(2025, 10, 8),
        datetime(2025, 10, 9),  # Hangul Day
        datetime(2025, 12, 25), # Christmas
    ]

    def __init__(self):
        self._holiday_cache = set(d.date() for d in self.KRX_HOLIDAYS_2025)

    def get_market_session(self, market: MarketType) -> MarketSession:
        """
        Get current market session status.

        Args:
            market: Market type to check

        Returns:
            MarketSession with open/close information
        """
        now = datetime.now(KST)

        if market == MarketType.CRYPTO:
            return self._get_crypto_session(now)
        elif market == MarketType.KRX:
            return self._get_krx_session(now)
        elif market in (MarketType.NYSE, MarketType.NASDAQ):
            return self._get_us_session(now, market)
        else:
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=None,
                next_close=None,
                message=f"Unknown market: {market}"
            )

    def is_market_open(self, market: MarketType) -> bool:
        """Quick check if market is currently open."""
        return self.get_market_session(market).is_open

    def _get_crypto_session(self, now: datetime) -> MarketSession:
        """Crypto market is always open."""
        return MarketSession(
            is_open=True,
            current_time=now,
            next_open=None,
            next_close=None,
            message="Cryptocurrency market is open 24/7"
        )

    def _get_krx_session(self, now: datetime) -> MarketSession:
        """
        KRX trading hours:
        - Regular session: 09:00-15:30 KST
        - Pre-market: 08:30-09:00 (order acceptance only)
        - After-hours: 15:40-18:00 (single price auction)
        """
        today = now.date()
        weekday = now.weekday()  # 0=Monday, 6=Sunday

        # Weekend check
        if weekday >= 5:
            next_monday = today + timedelta(days=(7 - weekday))
            next_open = datetime.combine(next_monday, time(9, 0), tzinfo=KST)
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=next_open,
                next_close=None,
                message="Market closed (Weekend)"
            )

        # Holiday check
        if today in self._holiday_cache:
            next_day = today + timedelta(days=1)
            while next_day.weekday() >= 5 or next_day in self._holiday_cache:
                next_day += timedelta(days=1)
            next_open = datetime.combine(next_day, time(9, 0), tzinfo=KST)
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=next_open,
                next_close=None,
                message="Market closed (Holiday)"
            )

        # Regular trading hours: 09:00-15:30
        market_open = time(9, 0)
        market_close = time(15, 30)
        current_time = now.time()

        if current_time < market_open:
            next_open = datetime.combine(today, market_open, tzinfo=KST)
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=next_open,
                next_close=None,
                message=f"Market opens at 09:00 KST ({self._time_until(now, next_open)} remaining)"
            )

        if current_time > market_close:
            next_day = today + timedelta(days=1)
            while next_day.weekday() >= 5 or next_day in self._holiday_cache:
                next_day += timedelta(days=1)
            next_open = datetime.combine(next_day, market_open, tzinfo=KST)
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=next_open,
                next_close=None,
                message=f"Market closed (After hours). Opens {next_open.strftime('%Y-%m-%d %H:%M')}"
            )

        # Market is open
        today_close = datetime.combine(today, market_close, tzinfo=KST)
        return MarketSession(
            is_open=True,
            current_time=now,
            next_open=None,
            next_close=today_close,
            message=f"Market open. Closes at 15:30 KST ({self._time_until(now, today_close)} remaining)"
        )

    def _get_us_session(self, now: datetime, market: MarketType) -> MarketSession:
        """
        US market trading hours:
        - Regular session: 09:30-16:00 EST
        """
        now_est = now.astimezone(EST)
        today = now_est.date()
        weekday = now_est.weekday()

        # Weekend check
        if weekday >= 5:
            next_monday = today + timedelta(days=(7 - weekday))
            next_open = datetime.combine(next_monday, time(9, 30), tzinfo=EST)
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=next_open.astimezone(KST),
                next_close=None,
                message=f"{market.value.upper()} closed (Weekend)"
            )

        market_open = time(9, 30)
        market_close = time(16, 0)
        current_time = now_est.time()

        if current_time < market_open:
            next_open = datetime.combine(today, market_open, tzinfo=EST)
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=next_open.astimezone(KST),
                next_close=None,
                message=f"{market.value.upper()} opens at 09:30 EST"
            )

        if current_time > market_close:
            next_day = today + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            next_open = datetime.combine(next_day, market_open, tzinfo=EST)
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=next_open.astimezone(KST),
                next_close=None,
                message=f"{market.value.upper()} closed (After hours)"
            )

        today_close = datetime.combine(today, market_close, tzinfo=EST)
        return MarketSession(
            is_open=True,
            current_time=now,
            next_open=None,
            next_close=today_close.astimezone(KST),
            message=f"{market.value.upper()} open. Closes at 16:00 EST"
        )

    def _time_until(self, now: datetime, target: datetime) -> str:
        """Format time until target as human-readable string."""
        delta = target - now
        total_seconds = int(delta.total_seconds())

        if total_seconds < 0:
            return "now"

        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"


# Singleton instance
_market_hours_service: Optional[MarketHoursService] = None


def get_market_hours_service() -> MarketHoursService:
    """Get singleton MarketHoursService instance."""
    global _market_hours_service
    if _market_hours_service is None:
        _market_hours_service = MarketHoursService()
    return _market_hours_service
