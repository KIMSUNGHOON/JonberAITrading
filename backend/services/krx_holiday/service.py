"""
KRX Holiday Service

High-level service that combines fetching and storage of KRX holidays.
Provides automatic updates and integration with MarketHoursService.
"""

import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Set, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .fetcher import KRXHolidayFetcher, HolidayInfo
from .storage import HolidayStorage

logger = logging.getLogger(__name__)


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
                holidays = await self.fetcher.fetch_holidays(y)

                if holidays:
                    saved = self.storage.save_holidays(holidays)
                    total_saved += saved
                    logger.info(f"Updated {saved} holidays for {y}")
                else:
                    logger.warning(f"No holidays fetched for {y}")

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

    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if a date is a trading day.

        A trading day is:
        - Not a weekend (Saturday or Sunday)
        - Not a holiday

        Args:
            check_date: Date to check

        Returns:
            True if it's a trading day
        """
        # Check weekend
        if check_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return False

        # Check holiday
        if self.is_holiday(check_date):
            return False

        return True

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

        return {
            "initialized": self._initialized,
            "scheduler_running": self._scheduler is not None and self._scheduler.running,
            "last_update": last_update.isoformat() if last_update else None,
            "year_stats": stats,
            "total_holidays": sum(stats.values()),
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
