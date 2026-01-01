"""
Holiday Storage Service

SQLite-based storage for KRX market holidays.
Provides caching and persistence for holiday data.
"""

import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Set, Dict
from contextlib import contextmanager

from .fetcher import HolidayInfo

logger = logging.getLogger(__name__)


class HolidayStorage:
    """
    SQLite-based storage for market holidays.

    Features:
    - Persistent storage of holiday data
    - Fast lookup by date
    - Year-based caching
    - Automatic table creation
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the storage.

        Args:
            db_path: Path to SQLite database file.
                     Defaults to 'data/holidays.db' in project root.
        """
        if db_path is None:
            # Default path in project's data directory
            data_dir = Path(__file__).parent.parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "holidays.db")

        self.db_path = db_path
        self._init_database()

        # In-memory cache for fast lookups
        self._holiday_cache: Dict[int, Set[date]] = {}
        self._cache_loaded = False

    @contextmanager
    def _get_connection(self):
        """Get database connection with context management."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Create holidays table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS krx_holidays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    year INTEGER NOT NULL,
                    day_of_week TEXT,
                    name TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create index for fast date lookup
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_holidays_date ON krx_holidays(date)
            """)

            # Create index for year-based queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_holidays_year ON krx_holidays(year)
            """)

            # Create metadata table for tracking updates
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS holiday_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            logger.debug(f"Initialized holiday database at {self.db_path}")

    def save_holidays(self, holidays: List[HolidayInfo]) -> int:
        """
        Save holidays to database.

        Args:
            holidays: List of HolidayInfo objects

        Returns:
            Number of holidays saved (new + updated)
        """
        if not holidays:
            return 0

        saved_count = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()

            for holiday in holidays:
                try:
                    cursor.execute("""
                        INSERT INTO krx_holidays (date, year, day_of_week, name, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(date) DO UPDATE SET
                            day_of_week = excluded.day_of_week,
                            name = excluded.name,
                            updated_at = excluded.updated_at
                    """, (
                        holiday.date.isoformat(),
                        holiday.year,
                        holiday.day_of_week,
                        holiday.name,
                        datetime.now().isoformat(),
                    ))
                    saved_count += 1
                except Exception as e:
                    logger.error(f"Error saving holiday {holiday.date}: {e}")

            # Update metadata
            cursor.execute("""
                INSERT INTO holiday_metadata (key, value, updated_at)
                VALUES ('last_update', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (datetime.now().isoformat(), datetime.now().isoformat()))

            conn.commit()

        # Invalidate cache
        self._cache_loaded = False
        self._holiday_cache.clear()

        logger.info(f"Saved {saved_count} holidays to database")
        return saved_count

    def get_holidays(self, year: Optional[int] = None) -> List[HolidayInfo]:
        """
        Get holidays from database.

        Args:
            year: Optional year filter. If None, returns all holidays.

        Returns:
            List of HolidayInfo objects
        """
        holidays = []

        with self._get_connection() as conn:
            cursor = conn.cursor()

            if year:
                cursor.execute("""
                    SELECT date, year, day_of_week, name
                    FROM krx_holidays
                    WHERE year = ?
                    ORDER BY date
                """, (year,))
            else:
                cursor.execute("""
                    SELECT date, year, day_of_week, name
                    FROM krx_holidays
                    ORDER BY date
                """)

            for row in cursor.fetchall():
                try:
                    holiday_date = date.fromisoformat(row["date"])
                    holidays.append(HolidayInfo(
                        date=holiday_date,
                        day_of_week=row["day_of_week"] or "",
                        name=row["name"] or "",
                        year=row["year"],
                    ))
                except Exception as e:
                    logger.warning(f"Error parsing holiday row: {e}")

        return holidays

    def get_holiday_dates(self, year: Optional[int] = None) -> Set[date]:
        """
        Get holiday dates as a set for fast lookup.

        Args:
            year: Optional year filter

        Returns:
            Set of date objects
        """
        # Check cache
        if self._cache_loaded and year in self._holiday_cache:
            return self._holiday_cache[year]

        holidays = self.get_holidays(year)
        dates = {h.date for h in holidays}

        # Update cache
        if year:
            self._holiday_cache[year] = dates
        else:
            # Build year-based cache
            for h in holidays:
                if h.year not in self._holiday_cache:
                    self._holiday_cache[h.year] = set()
                self._holiday_cache[h.year].add(h.date)
            self._cache_loaded = True

        return dates

    def is_holiday(self, check_date: date) -> bool:
        """
        Check if a date is a holiday.

        Args:
            check_date: Date to check

        Returns:
            True if the date is a holiday
        """
        year = check_date.year
        holiday_dates = self.get_holiday_dates(year)
        return check_date in holiday_dates

    def get_holiday_info(self, check_date: date) -> Optional[HolidayInfo]:
        """
        Get holiday information for a specific date.

        Args:
            check_date: Date to check

        Returns:
            HolidayInfo if it's a holiday, None otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT date, year, day_of_week, name
                FROM krx_holidays
                WHERE date = ?
            """, (check_date.isoformat(),))

            row = cursor.fetchone()
            if row:
                return HolidayInfo(
                    date=date.fromisoformat(row["date"]),
                    day_of_week=row["day_of_week"] or "",
                    name=row["name"] or "",
                    year=row["year"],
                )

        return None

    def get_last_update(self) -> Optional[datetime]:
        """
        Get the last update timestamp.

        Returns:
            Last update datetime or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT value FROM holiday_metadata WHERE key = 'last_update'
            """)
            row = cursor.fetchone()
            if row:
                try:
                    return datetime.fromisoformat(row["value"])
                except Exception:
                    pass
        return None

    def has_year_data(self, year: int) -> bool:
        """
        Check if holiday data exists for a year.

        Args:
            year: Year to check

        Returns:
            True if data exists for the year
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM krx_holidays WHERE year = ?
            """, (year,))
            row = cursor.fetchone()
            return row["count"] > 0 if row else False

    def get_year_stats(self) -> Dict[int, int]:
        """
        Get statistics about stored holiday data.

        Returns:
            Dictionary mapping year to holiday count
        """
        stats = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT year, COUNT(*) as count
                FROM krx_holidays
                GROUP BY year
                ORDER BY year
            """)
            for row in cursor.fetchall():
                stats[row["year"]] = row["count"]
        return stats

    def delete_year(self, year: int) -> int:
        """
        Delete all holidays for a specific year.

        Args:
            year: Year to delete

        Returns:
            Number of deleted records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM krx_holidays WHERE year = ?
            """, (year,))
            conn.commit()
            deleted = cursor.rowcount

        # Invalidate cache
        if year in self._holiday_cache:
            del self._holiday_cache[year]

        logger.info(f"Deleted {deleted} holidays for year {year}")
        return deleted

    def clear_all(self):
        """Clear all holiday data."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM krx_holidays")
            cursor.execute("DELETE FROM holiday_metadata")
            conn.commit()

        self._holiday_cache.clear()
        self._cache_loaded = False

        logger.info("Cleared all holiday data")


# Test function
def test_storage():
    """Test the holiday storage."""
    from .fetcher import HolidayInfo

    # Use temp database for testing
    storage = HolidayStorage(":memory:")

    # Create test holidays
    test_holidays = [
        HolidayInfo(date=date(2025, 1, 1), day_of_week="수", name="신정", year=2025),
        HolidayInfo(date=date(2025, 1, 29), day_of_week="수", name="설날", year=2025),
        HolidayInfo(date=date(2025, 3, 1), day_of_week="토", name="삼일절", year=2025),
    ]

    # Save
    saved = storage.save_holidays(test_holidays)
    print(f"Saved {saved} holidays")

    # Query
    holidays = storage.get_holidays(2025)
    print(f"\nHolidays for 2025 ({len(holidays)}):")
    for h in holidays:
        print(f"  {h.date} ({h.day_of_week}) - {h.name}")

    # Check
    print(f"\n2025-01-01 is holiday: {storage.is_holiday(date(2025, 1, 1))}")
    print(f"2025-01-02 is holiday: {storage.is_holiday(date(2025, 1, 2))}")

    # Stats
    print(f"\nYear stats: {storage.get_year_stats()}")
    print(f"Last update: {storage.get_last_update()}")


if __name__ == "__main__":
    test_storage()
