"""
KRX Holiday Service

High-level service that combines fetching and storage of KRX holidays.
Provides automatic updates and integration with MarketHoursService.
"""

import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import NamedTuple, Optional, Set, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .fetcher import (
    IncompleteHolidayDataError,
    KRXHolidayFetcher,
    HolidayInfo,
)
from .storage import HolidayStorage

logger = logging.getLogger(__name__)


class TradingDayVerdict(NamedTuple):
    """거래일 판정 + **그 판정을 믿어도 되는지**.

    `is_trading_day()`는 불리언 하나라 "휴장일이다"와 "달력이 없어서
    모른다"가 같은 False/True로 접힌다. 접히면 안 되는 쪽은 **모른다 →
    거래일이다**다: 없는 달력은 휴장일이 0개로 보이므로 모든 날이
    거래일로 나오고, 그날 자율매매가 돌아 주문이 전부 거부되며 EOD
    체인이 유령 거래일을 원장에 쓴다(2026-03-02·05-25에 실제로 그렇게
    지나갔다).

    그렇다고 모르는 날에 예외를 던지거나 False를 돌려주면 노출도 계산·
    장중 판정이 통째로 무너지거나 시스템이 영구 정지한다. 그래서
    **불리언은 살려 두고 신뢰 여부를 별도 축으로 뺀다** -- 판단이 필요한
    호출자(EOD 원장 쓰기 등)는 `trusted`를 보고 스스로 멈출 수 있고,
    그렇지 않은 호출자는 예전과 똑같이 동작한다.
    """
    is_trading_day: bool
    trusted: bool
    reason: str


class KRXHolidayService:
    """
    Unified service for KRX holiday data management.

    Features:
    - Automatic fetching and storage
    - Scheduled updates (monthly)
    - Cache management
    - Integration with trading system
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the holiday service.

        Args:
            db_path: Optional path to SQLite database
        """
        self.fetcher = KRXHolidayFetcher()
        self.storage = HolidayStorage(db_path)
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._initialized = False
        # 신뢰 못 하는 연도를 물을 때마다 로그를 도배하지 않기 위한 래치.
        self._untrusted_warned: Set[int] = set()

    async def initialize(self, fetch_if_empty: bool = True):
        """
        Initialize the service.

        Args:
            fetch_if_empty: If True, fetch holidays if database is empty
        """
        if self._initialized:
            return

        current_year = datetime.now().year

        # Check if we need to fetch data
        if fetch_if_empty:
            # Check current and next year
            for year in [current_year, current_year + 1]:
                if not self.storage.has_year_data(year):
                    logger.info(f"No holiday data for {year}, fetching...")
                    await self.update_holidays(year)

        self._initialized = True
        logger.info("KRX Holiday Service initialized")

    async def close(self):
        """Close the service and release resources."""
        await self.fetcher.close()
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown()
        logger.info("KRX Holiday Service closed")

    async def update_holidays(self, year: Optional[int] = None) -> int:
        """
        Fetch and update holiday data.

        Args:
            year: Specific year to update. If None, updates current and next year.

        Returns:
            Number of holidays saved
        """
        if year:
            years_to_update = [year]
        else:
            current_year = datetime.now().year
            years_to_update = [current_year, current_year + 1]

        total_saved = 0

        for y in years_to_update:
            try:
                logger.info(f"Fetching holidays for {y}...")
                result = await self.fetcher.fetch_holidays_with_source(y)

                if result.holidays:
                    # `complete_years`를 넘기는 유일한 지점 -- 여기까지 온
                    # 배치는 원격 응답이거나 폴백 표의 **완전한** 연도다
                    # (불완전한 연도는 IncompleteHolidayDataError로 위에서
                    # 끊긴다). 조각 데이터가 완전한 척할 통로가 없다.
                    saved = self.storage.save_holidays(
                        result.holidays,
                        source=result.source,
                        complete_years=[y],
                    )
                    total_saved += saved
                    self._untrusted_warned.discard(y)
                    logger.info(
                        f"Updated {saved} holidays for {y} (source={result.source})"
                    )
                else:
                    logger.warning(f"No holidays fetched for {y}")

            except IncompleteHolidayDataError as e:
                # 부분 달력은 저장하지 않는다. 다른 연도 갱신은 계속된다 --
                # 한 해를 모른다고 시스템 전체가 멈추면 안 된다.
                logger.error(f"Refusing to store incomplete calendar for {y}: {e}")
            except Exception as e:
                logger.error(f"Error updating holidays for {y}: {e}")

        return total_saved

    def get_holidays(self, year: Optional[int] = None) -> List[HolidayInfo]:
        """Get holidays from storage."""
        return self.storage.get_holidays(year)

    def get_holiday_dates(self, year: Optional[int] = None) -> Set[date]:
        """Get holiday dates as a set for fast lookup."""
        return self.storage.get_holiday_dates(year)

    def is_holiday(self, check_date: date) -> bool:
        """Check if a date is a holiday."""
        return self.storage.is_holiday(check_date)

    def get_holiday_info(self, check_date: date) -> Optional[HolidayInfo]:
        """Get holiday information for a date."""
        return self.storage.get_holiday_info(check_date)

    def is_calendar_trusted(self, year: int) -> bool:
        """그 해 달력을 신뢰해도 되는가(완전한 배치로 저장된 적이 있는가)."""
        try:
            return self.storage.is_year_complete(year)
        except Exception as e:
            logger.warning(f"Could not read calendar coverage for {year}: {e}")
            return False

    def get_trading_day_verdict(self, check_date: date) -> TradingDayVerdict:
        """거래일 판정 + 신뢰 여부. **절대 예외를 던지지 않는다.**

        `is_trading_day()`의 불리언 뒤에 가려지던 세 번째 상태("달력이
        없어서 모른다")를 호출자가 볼 수 있게 한다. 자세한 배경은
        `TradingDayVerdict` docstring 참조.
        """
        weekday = check_date.weekday()
        if weekday >= 5:
            # 주말은 달력이 없어도 확실하다 -- KRX는 토·일에 열지 않는다.
            return TradingDayVerdict(False, True, "weekend")

        trusted = self.is_calendar_trusted(check_date.year)

        try:
            holiday = self.is_holiday(check_date)
        except Exception as e:
            # 조회가 깨져도 호출자를 깨뜨리지 않는다. 다만 "휴일이 아니다"로
            # 단정하지 않고 신뢰를 내린다.
            logger.warning(f"Holiday lookup failed for {check_date}: {e}")
            return TradingDayVerdict(True, False, "holiday_lookup_failed")

        if holiday:
            return TradingDayVerdict(False, trusted, "holiday")

        if not trusted:
            self._warn_untrusted_once(check_date.year)
            return TradingDayVerdict(
                True, False, f"calendar_incomplete_for_{check_date.year}"
            )

        return TradingDayVerdict(True, True, "trading_day")

    def _warn_untrusted_once(self, year: int):
        """연도당 한 번만 경고한다(장중 루프가 초당 여러 번 부른다)."""
        if year in self._untrusted_warned:
            return
        self._untrusted_warned.add(year)
        logger.error(
            "krx_calendar_untrusted year=%d -- 이 연도의 완전한 휴장일 달력이 "
            "저장돼 있지 않다. 거래일 판정은 '주말 아님 + 아는 휴일 아님'으로만 "
            "내려지고 있어, 모르는 휴장일은 **거래일로 보인다**. "
            "update_holidays(%d)를 돌리거나 fetcher.LUNAR_HOLIDAYS에 그 해를 "
            "추가할 것. (신뢰 필요한 호출자는 get_trading_day_verdict().trusted 참조)",
            year, year,
        )

    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if a date is a trading day.

        A trading day is:
        - Not a weekend (Saturday or Sunday)
        - Not a holiday

        ⚠️ 계약 유지: **절대 예외를 던지지 않고 불리언만 돌려준다.**
        노출도 계산·장중 판정·EOD 체인이 전부 이 위에 서 있어서, 여기서
        예외가 나가면 달력 하나 때문에 매매 전체가 무너진다. 달력이 없어
        "모르는" 경우에도 시스템이 멈추지 않도록 True를 유지하되, 그
        True에 근거가 없다는 사실은 `get_trading_day_verdict().trusted`와
        ERROR 로그로 드러난다.

        Args:
            check_date: Date to check

        Returns:
            True if it's a trading day
        """
        try:
            return self.get_trading_day_verdict(check_date).is_trading_day
        except Exception as e:  # pragma: no cover - 방어선
            logger.error(f"is_trading_day fell back for {check_date}: {e}")
            return check_date.weekday() < 5

    def get_next_trading_day(self, from_date: Optional[date] = None) -> date:
        """
        Get the next trading day.

        Args:
            from_date: Starting date. Defaults to today.

        Returns:
            Next trading day
        """
        if from_date is None:
            from_date = date.today()

        next_day = from_date + timedelta(days=1)

        # Find next trading day
        while not self.is_trading_day(next_day):
            next_day += timedelta(days=1)

            # Safety limit (shouldn't happen)
            if (next_day - from_date).days > 30:
                logger.error("Could not find trading day within 30 days")
                break

        return next_day

    def get_previous_trading_day(self, from_date: Optional[date] = None) -> date:
        """
        Get the previous trading day.

        Args:
            from_date: Starting date. Defaults to today.

        Returns:
            Previous trading day
        """
        if from_date is None:
            from_date = date.today()

        prev_day = from_date - timedelta(days=1)

        # Find previous trading day
        while not self.is_trading_day(prev_day):
            prev_day -= timedelta(days=1)

            # Safety limit
            if (from_date - prev_day).days > 30:
                logger.error("Could not find trading day within 30 days")
                break

        return prev_day

    def get_trading_days_in_range(self, start_date: date, end_date: date) -> List[date]:
        """
        Get all trading days in a date range.

        Args:
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            List of trading days
        """
        trading_days = []
        current = start_date

        while current <= end_date:
            if self.is_trading_day(current):
                trading_days.append(current)
            current += timedelta(days=1)

        return trading_days

    def start_scheduler(self, update_day: int = 1, update_hour: int = 6):
        """
        Start automatic update scheduler.

        Updates holidays on the specified day of each month.

        Args:
            update_day: Day of month to run update (1-28)
            update_hour: Hour to run update (0-23)
        """
        if self._scheduler and self._scheduler.running:
            logger.warning("Scheduler already running")
            return

        self._scheduler = AsyncIOScheduler()

        # Schedule monthly update
        self._scheduler.add_job(
            self._scheduled_update,
            trigger=CronTrigger(day=update_day, hour=update_hour, minute=0),
            id="holiday_update",
            name="Monthly Holiday Update",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(f"Holiday update scheduler started (day={update_day}, hour={update_hour})")

    def stop_scheduler(self):
        """Stop the automatic update scheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown()
            self._scheduler = None
            logger.info("Holiday update scheduler stopped")

    async def _scheduled_update(self):
        """Scheduled update task."""
        logger.info("Running scheduled holiday update...")
        try:
            saved = await self.update_holidays()
            logger.info(f"Scheduled update completed: {saved} holidays updated")
        except Exception as e:
            logger.error(f"Scheduled update failed: {e}")

    def get_status(self) -> dict:
        """
        Get service status.

        Returns:
            Status dictionary
        """
        stats = self.storage.get_year_stats()
        last_update = self.storage.get_last_update()

        try:
            source = self.storage.get_source()
            year_sources = self.storage.get_year_sources()
            untrusted = sorted(
                y for y in stats if not self.storage.is_year_complete(y)
            )
        except Exception as e:
            logger.warning(f"Could not read holiday metadata: {e}")
            source, year_sources, untrusted = None, {}, sorted(stats)

        return {
            "initialized": self._initialized,
            "scheduler_running": self._scheduler is not None and self._scheduler.running,
            "last_update": last_update.isoformat() if last_update else None,
            "year_stats": stats,
            "total_holidays": sum(stats.values()),
            # 출처와 신뢰 못 하는 연도를 함께 노출한다 -- `last_update`만
            # 보면 폴백을 쓴 실패도 정상 갱신처럼 보였다.
            "source": source,
            "year_sources": year_sources,
            "untrusted_years": untrusted,
            "fallback_covers_years": sorted(KRXHolidayFetcher.LUNAR_HOLIDAYS),
        }


# Singleton instance
_holiday_service: Optional[KRXHolidayService] = None


async def get_holiday_service() -> KRXHolidayService:
    """
    Get singleton KRXHolidayService instance.

    Returns:
        Initialized KRXHolidayService
    """
    global _holiday_service

    if _holiday_service is None:
        _holiday_service = KRXHolidayService()
        await _holiday_service.initialize()

    return _holiday_service


def get_holiday_service_sync() -> KRXHolidayService:
    """
    Get singleton KRXHolidayService instance (synchronous).

    Note: This does not initialize the service.
    Call initialize() separately if needed.

    Returns:
        KRXHolidayService (may not be initialized)
    """
    global _holiday_service

    if _holiday_service is None:
        _holiday_service = KRXHolidayService()

    return _holiday_service


# Test function
async def test_service():
    """Test the holiday service."""
    service = KRXHolidayService(":memory:")

    try:
        await service.initialize(fetch_if_empty=False)

        # Manual update
        print("Fetching holidays...")
        saved = await service.update_holidays(2025)
        print(f"Saved {saved} holidays")

        # Check some dates
        test_dates = [
            date(2025, 1, 1),   # New Year
            date(2025, 1, 2),   # Regular day
            date(2025, 1, 4),   # Saturday
            date(2025, 1, 29),  # Seollal
            date(2025, 3, 1),   # Independence Day
        ]

        print("\nDate checks:")
        for d in test_dates:
            is_trading = service.is_trading_day(d)
            holiday_info = service.get_holiday_info(d)
            status = "Trading day" if is_trading else f"Non-trading ({holiday_info.name if holiday_info else 'Weekend'})"
            print(f"  {d} ({['월', '화', '수', '목', '금', '토', '일'][d.weekday()]}): {status}")

        # Get next/previous trading days
        today = date.today()
        print(f"\nFrom {today}:")
        print(f"  Next trading day: {service.get_next_trading_day(today)}")
        print(f"  Previous trading day: {service.get_previous_trading_day(today)}")

        # Status
        print(f"\nService status: {service.get_status()}")

    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(test_service())
