"""
Market Hours Service

Provides market open/close time checking for Korean stocks (KRX).

Updated to use dynamic KRX holiday data from KRXHolidayService.

Also provides KRX tick size (호가 단위) calculation functions.
"""

from datetime import datetime, time, date, timedelta, timezone
from enum import Enum
from typing import NamedTuple, Optional, Set

import structlog

logger = structlog.get_logger()


class MarketType(str, Enum):
    """Supported market types"""
    KRX = "krx"          # Korea Exchange (Korean stocks)


class MarketSession(NamedTuple):
    """Market trading session information"""
    is_open: bool
    current_time: datetime
    next_open: Optional[datetime]
    next_close: Optional[datetime]
    message: str


# Korea timezone — stdlib 고정 오프셋을 쓴다.
#
# pytz 객체(`pytz.timezone("Asia/Seoul")`)를 쓰면 안 된다. pytz는 `tzinfo=`나
# `.replace(tzinfo=...)`로 직접 붙이는 용법을 지원하지 않고, 그렇게 붙이면 그 존의
# **최초 역사적 오프셋**인 LMT `+08:28`이 적용된다. 이 파일은 경계 시각을
# `datetime.combine(..., tzinfo=KST)`로 만들기 때문에 정확히 그 함정에 빠져,
# 2026-08-03 라이브에서 `next_close`가 `15:30+08:28`로 나가고 카운트다운이 32분
# 초과됐다(`datetime.now(KST)`만 멀쩡했던 이유는 pytz가 `fromutc()`는 제대로
# 구현하기 때문이다).
#
# 고정 오프셋이 안전한 이유: 한국은 1988년 이후 서머타임이 없다. 그리고 이 관용구는
# `services/kiwoom/auth.py`·`services/kiwoom/models.py`가 이미 쓰고 있어 레포 전체가
# 하나로 통일된다.
KST = timezone(timedelta(hours=9))


class MarketHoursService:
    """
    Service for checking market trading hours.

    Supports:
    - KRX: 09:00-15:30 KST (Mon-Fri, excluding holidays)

    Note: KRX holidays are now dynamically loaded from KRXHolidayService.
    Fallback to hardcoded holidays if service is unavailable.
    """

    # KRXHolidayService를 못 쓸 때만 쓰이는 폴백 휴장일 집합.
    #
    # ⚠️ 예전에는 여기에 날짜를 **손으로 적은 사본**이 있었고, krx_holiday의
    # 하드코딩 표와 **똑같은 결손**을 갖고 있었다(2026-08-11 실측):
    #   2026-03-02 · 2026-05-25 · 2026-08-17 · 2026-10-05 (대체공휴일 전부)
    #   2025-03-03 (삼일절 대체공휴일)
    # 사본이 둘이면 어긋날 때 어느 쪽이 맞는지 알 수 없고, 실제로 둘 다
    # 같은 방식으로 틀려 있었다. 그래서 사본을 없애고 **같은 규칙 엔진에서
    # 파생**시킨다.
    #
    # import는 **함수 안에서** 한다 -- 아래 `_get_holiday_service`가 순환
    # import를 피하려 그러는 것과 같은 자리다.
    #
    # ⚠️ 지연의 효과를 정확히 적어 둔다: `from services.krx_holiday.fetcher
    # import ...`도 패키지 `__init__`을 먼저 실행하므로 **apscheduler를
    # 피하지는 못한다**(초판 주석이 이 메커니즘을 틀리게 적었다). 실제
    # 효과는 import 시점을 모듈 로드에서 **첫 사용 시점으로 미루는 것**이고,
    # 그래서 순환 import가 성립하지 않는다.
    _fallback_cache: Optional[Set[date]] = None

    @classmethod
    def fallback_holidays(cls) -> Set[date]:
        """폴백 휴장일 -- krx_holiday의 규칙 엔진에서 1회 파생 후 캐시.

        ⚠️ **실패는 캐시하지 않는다.** 예전에는 `except`를 지나서도 캐시에
        빈 집합이 들어가, 일시적 실패 한 번이 프로세스 수명 내내 폴백
        휴장일을 비웠다(휴장일 0개 = 모든 평일이 거래일). 실패해도 예외는
        내지 않는다 -- 그 경우 주말 규칙만 남고 호출자는 계속 동작한다.
        """
        if cls._fallback_cache is not None:
            return cls._fallback_cache

        derived: Set[date] = set()
        try:
            from services.krx_holiday.fetcher import KRXHolidayFetcher

            fetcher = KRXHolidayFetcher()
            for year in sorted(KRXHolidayFetcher.LUNAR_HOLIDAYS):
                derived.update(h.date for h in fetcher._get_known_holidays(year))
        except Exception as e:
            logger.error(
                "market_hours_fallback_holidays_unavailable",
                error=str(e),
                hint="휴장일 폴백이 비었다 -- 주말 규칙만 적용된다. "
                     "캐시하지 않으므로 다음 호출에서 재시도한다.",
            )
            return derived  # 캐시하지 않는다 -- 다음 호출에서 다시 시도

        cls._fallback_cache = derived
        return cls._fallback_cache

    def __init__(self):
        self._holiday_cache: Set[date] = set(self.fallback_holidays())
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

        if market == MarketType.KRX:
            return self._get_krx_session(now)
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


# -------------------------------------------
# KRX open TTL cache (E2-1)
# -------------------------------------------
# Shared no-op-cycle gate consumed by services/agent_chat/coordinator.py
# (_check_watch_list) and services/agent_chat/position_manager.py
# (_check_strategic_reeval, _check_all_positions) — and, per E2-2, the
# RiskMonitor 1s loop. Those call sites would otherwise re-derive market
# state (weekday/holiday/session-time math) on every tick; a short
# monotonic TTL keeps that cheap without ever going stale for more than
# ttl_seconds.

_krx_open_cache: dict = {"at": 0.0, "value": False}


def is_krx_open_cached(ttl_seconds: float = 30.0) -> bool:
    """KRX 개장 여부의 TTL 캐시 판정 (E2 no-op-cycle 게이트 공용).

    RiskMonitor의 1s 루프까지 이 판정을 쓰므로 매 호출 공휴일 서비스를
    재조회하지 않도록 monotonic TTL로 묶는다. 판정 소스는
    get_market_hours_service().is_market_open(MarketType.KRX) 단일.
    """
    import time
    now = time.monotonic()
    if now - _krx_open_cache["at"] > ttl_seconds:
        _krx_open_cache["value"] = get_market_hours_service().is_market_open(MarketType.KRX)
        _krx_open_cache["at"] = now
    return _krx_open_cache["value"]


def _reset_krx_open_cache() -> None:
    """테스트 전용: 캐시 무효화."""
    _krx_open_cache["at"] = 0.0

