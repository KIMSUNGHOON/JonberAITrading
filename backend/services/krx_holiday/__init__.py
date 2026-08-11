"""
KRX Holiday Service

Provides KRX market holiday data fetching and storage.
"""

from .fetcher import (
    HolidayFetchResult,
    HolidayInfo,
    IncompleteHolidayDataError,
    KRXHolidayFetcher,
    SOURCE_FALLBACK_TABLE,
    SOURCE_KRX_API,
    SOURCE_UNKNOWN,
    SUBSTITUTE_HOLIDAY_NAME,
    compute_substitute_holidays,
)
from .storage import HolidayStorage
from .service import (
    KRXHolidayService,
    TradingDayVerdict,
    get_holiday_service,
    get_holiday_service_sync,
)

__all__ = [
    "KRXHolidayFetcher",
    "HolidayInfo",
    "HolidayFetchResult",
    "HolidayStorage",
    "IncompleteHolidayDataError",
    "KRXHolidayService",
    "TradingDayVerdict",
    "SOURCE_KRX_API",
    "SOURCE_FALLBACK_TABLE",
    "SOURCE_UNKNOWN",
    "SUBSTITUTE_HOLIDAY_NAME",
    "compute_substitute_holidays",
    "get_holiday_service",
    "get_holiday_service_sync",
]
