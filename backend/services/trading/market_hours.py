"""
Market Hours Service

Provides market open/close time checking for different markets.
Supports Korean stocks (KRX) and cryptocurrency (24/7).

Updated to use dynamic KRX holiday data from KRXHolidayService.

Also provides KRX tick size (호가 단위) calculation functions.
"""

from datetime import datetime, time, date, timedelta
from enum import Enum
from typing import NamedTuple, Optional, Set
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

    Note: KRX holidays are now dynamically loaded from KRXHolidayService.
    Fallback to hardcoded holidays if service is unavailable.
    """

    # Fallback Korean public holidays (used when KRXHolidayService unavailable)
    FALLBACK_HOLIDAYS = {
        # 2025
        date(2025, 1, 1),   # New Year
        date(2025, 1, 28),  # Lunar New Year
        date(2025, 1, 29),
        date(2025, 1, 30),
        date(2025, 3, 1),   # Independence Movement Day
        date(2025, 5, 5),   # Children's Day
        date(2025, 5, 6),   # Buddha's Birthday (substitute)
        date(2025, 6, 6),   # Memorial Day
        date(2025, 8, 15),  # Liberation Day
        date(2025, 10, 3),  # National Foundation Day
        date(2025, 10, 5),  # Chuseok Eve
        date(2025, 10, 6),  # Chuseok
        date(2025, 10, 7),  # Chuseok
        date(2025, 10, 8),  # Substitute
        date(2025, 10, 9),  # Hangul Day
        date(2025, 12, 25), # Christmas
        date(2025, 12, 31), # Year End
        # 2026
        date(2026, 1, 1),   # New Year
        date(2026, 2, 16),  # Lunar New Year
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 3, 1),   # Independence Movement Day
        date(2026, 5, 5),   # Children's Day
        date(2026, 5, 24),  # Buddha's Birthday
        date(2026, 6, 6),   # Memorial Day
        date(2026, 8, 15),  # Liberation Day
        date(2026, 9, 24),  # Chuseok
        date(2026, 9, 25),
        date(2026, 9, 26),
        date(2026, 10, 3),  # National Foundation Day
        date(2026, 10, 9),  # Hangul Day
        date(2026, 12, 25), # Christmas
        date(2026, 12, 31), # Year End
    }

    def __init__(self):
        self._holiday_cache: Set[date] = set(self.FALLBACK_HOLIDAYS)
        self._holiday_service = None
        self._holiday_service_checked = False

    def _get_holiday_service(self):
        """
        Try to get the KRXHolidayService.

        Returns None if not available (lazy loading to avoid circular imports).
        """
        if not self._holiday_service_checked:
            try:
                from services.krx_holiday import get_holiday_service_sync
                self._holiday_service = get_holiday_service_sync()
                logger.info("KRXHolidayService connected to MarketHoursService")
            except ImportError as e:
                logger.warning(f"KRXHolidayService not available: {e}")
                self._holiday_service = None
            except Exception as e:
                logger.error(f"Error loading KRXHolidayService: {e}")
                self._holiday_service = None

            self._holiday_service_checked = True

        return self._holiday_service

    def _is_krx_holiday(self, check_date: date) -> bool:
        """
        Check if a date is a KRX holiday.

        Uses KRXHolidayService if available, falls back to hardcoded holidays.
        """
        # Try to use dynamic holiday service
        holiday_service = self._get_holiday_service()
        if holiday_service:
            try:
                return holiday_service.is_holiday(check_date)
            except Exception as e:
                logger.warning(f"Error checking holiday via service: {e}")
                # Fall through to fallback

        # Fallback to hardcoded holidays
        return check_date in self._holiday_cache

    def _get_holiday_name(self, check_date: date) -> Optional[str]:
        """
        Get the holiday name for a date.

        Returns None if not a holiday.
        """
        holiday_service = self._get_holiday_service()
        if holiday_service:
            try:
                info = holiday_service.get_holiday_info(check_date)
                if info:
                    return info.name
            except Exception:
                pass
        return None

    async def refresh_holidays(self):
        """
        Manually refresh holiday data from KRX.

        Call this to update holidays after the system starts.
        """
        holiday_service = self._get_holiday_service()
        if holiday_service:
            try:
                await holiday_service.update_holidays()
                logger.info("Holiday data refreshed successfully")
            except Exception as e:
                logger.error(f"Error refreshing holidays: {e}")

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

        # Holiday check (using dynamic holiday service)
        if self._is_krx_holiday(today):
            holiday_name = self._get_holiday_name(today) or "Holiday"
            next_day = today + timedelta(days=1)
            while next_day.weekday() >= 5 or self._is_krx_holiday(next_day):
                next_day += timedelta(days=1)
                # Safety limit
                if (next_day - today).days > 30:
                    break
            next_open = datetime.combine(next_day, time(9, 0), tzinfo=KST)
            return MarketSession(
                is_open=False,
                current_time=now,
                next_open=next_open,
                next_close=None,
                message=f"Market closed ({holiday_name})"
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
            while next_day.weekday() >= 5 or self._is_krx_holiday(next_day):
                next_day += timedelta(days=1)
                # Safety limit
                if (next_day - today).days > 30:
                    break
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


# -------------------------------------------
# KRX Tick Size (호가 단위) Functions
# -------------------------------------------

# KRX tick size table based on price range
# Reference: KRX Trading Rules (한국거래소 시장 운영규정)
KRX_TICK_SIZE_TABLE = [
    # (max_price, tick_size)
    (1000, 1),           # 1,000원 미만: 1원
    (5000, 5),           # 1,000원 ~ 5,000원 미만: 5원
    (10000, 10),         # 5,000원 ~ 10,000원 미만: 10원
    (50000, 50),         # 10,000원 ~ 50,000원 미만: 50원
    (100000, 100),       # 50,000원 ~ 100,000원 미만: 100원
    (500000, 500),       # 100,000원 ~ 500,000원 미만: 500원
    (float('inf'), 1000),  # 500,000원 이상: 1,000원
]


def get_krx_tick_size(price: float) -> int:
    """
    Get the KRX tick size (호가 단위) for a given price.

    KRX defines different tick sizes based on price levels to ensure
    appropriate price precision for different stock price ranges.

    Args:
        price: The stock price in KRW

    Returns:
        The tick size (호가 단위) in KRW

    Examples:
        >>> get_krx_tick_size(500)    # Returns 1
        >>> get_krx_tick_size(3000)   # Returns 5
        >>> get_krx_tick_size(8000)   # Returns 10
        >>> get_krx_tick_size(30000)  # Returns 50
        >>> get_krx_tick_size(80000)  # Returns 100
        >>> get_krx_tick_size(200000) # Returns 500
        >>> get_krx_tick_size(600000) # Returns 1000
    """
    if price < 0:
        raise ValueError(f"Price cannot be negative: {price}")

    for max_price, tick_size in KRX_TICK_SIZE_TABLE:
        if price < max_price:
            return tick_size

    # Should never reach here due to infinity in table
    return 1000


def round_to_tick_size(price: float, direction: str = "nearest") -> int:
    """
    Round a price to the nearest valid tick size.

    Args:
        price: The price to round
        direction: Rounding direction
            - "nearest": Round to nearest valid price
            - "up": Round up to next valid price (useful for sell orders)
            - "down": Round down to previous valid price (useful for buy orders)

    Returns:
        The price rounded to a valid tick size

    Examples:
        >>> round_to_tick_size(33333, "nearest")  # Returns 33350
        >>> round_to_tick_size(33333, "up")       # Returns 33350
        >>> round_to_tick_size(33333, "down")     # Returns 33300
    """
    if price < 0:
        raise ValueError(f"Price cannot be negative: {price}")

    tick_size = get_krx_tick_size(price)

    if direction == "up":
        return int(((price + tick_size - 1) // tick_size) * tick_size)
    elif direction == "down":
        return int((price // tick_size) * tick_size)
    else:  # nearest
        return int(round(price / tick_size) * tick_size)


def is_valid_tick_price(price: float) -> bool:
    """
    Check if a price is a valid tick price.

    Args:
        price: The price to check

    Returns:
        True if the price is divisible by its tick size

    Examples:
        >>> is_valid_tick_price(33350)  # True (divisible by 50)
        >>> is_valid_tick_price(33333)  # False (not divisible by 50)
    """
    if price < 0:
        return False

    tick_size = get_krx_tick_size(price)
    return price % tick_size == 0


def get_price_with_slippage(
    price: float,
    slippage_pct: float,
    side: str = "buy"
) -> int:
    """
    Calculate order price with slippage, rounded to valid tick size.

    For buy orders, adds slippage (willing to pay more).
    For sell orders, subtracts slippage (willing to sell for less).

    Args:
        price: Base price
        slippage_pct: Slippage percentage (e.g., 0.5 for 0.5%)
        side: Order side ("buy" or "sell")

    Returns:
        Price adjusted for slippage, rounded to valid tick size

    Examples:
        >>> get_price_with_slippage(50000, 0.5, "buy")   # Returns 50250
        >>> get_price_with_slippage(50000, 0.5, "sell")  # Returns 49750
    """
    if side.lower() == "buy":
        adjusted_price = price * (1 + slippage_pct / 100)
        return round_to_tick_size(adjusted_price, "up")
    else:
        adjusted_price = price * (1 - slippage_pct / 100)
        return round_to_tick_size(adjusted_price, "down")


def get_tick_info(price: float) -> dict:
    """
    Get detailed tick information for a price.

    Returns a dictionary with:
    - tick_size: Current tick size
    - next_up: Next valid price above
    - next_down: Next valid price below
    - is_valid: Whether current price is valid
    - price_range: Human-readable price range description

    Args:
        price: The price to analyze

    Returns:
        Dictionary with tick information
    """
    tick_size = get_krx_tick_size(price)
    is_valid = is_valid_tick_price(price)

    # Find price range description
    if price < 1000:
        range_desc = "1,000원 미만"
    elif price < 5000:
        range_desc = "1,000원 ~ 5,000원 미만"
    elif price < 10000:
        range_desc = "5,000원 ~ 10,000원 미만"
    elif price < 50000:
        range_desc = "10,000원 ~ 50,000원 미만"
    elif price < 100000:
        range_desc = "50,000원 ~ 100,000원 미만"
    elif price < 500000:
        range_desc = "100,000원 ~ 500,000원 미만"
    else:
        range_desc = "500,000원 이상"

    return {
        "tick_size": tick_size,
        "next_up": round_to_tick_size(price + 1, "up"),
        "next_down": round_to_tick_size(price - 1, "down") if price > tick_size else 0,
        "is_valid": is_valid,
        "rounded_price": round_to_tick_size(price, "nearest"),
        "price_range": range_desc,
    }


# Singleton instance
_market_hours_service: Optional[MarketHoursService] = None


def get_market_hours_service() -> MarketHoursService:
    """Get singleton MarketHoursService instance."""
    global _market_hours_service
    if _market_hours_service is None:
        _market_hours_service = MarketHoursService()
    return _market_hours_service
