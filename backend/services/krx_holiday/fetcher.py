"""
KRX Holiday Data Fetcher

Fetches holiday data from KRX (Korea Exchange) website.
Handles OTP authentication required by KRX API.
"""

import asyncio
import logging
from datetime import datetime, date
from typing import List, Dict, Optional, NamedTuple
import aiohttp

logger = logging.getLogger(__name__)


class HolidayInfo(NamedTuple):
    """Holiday information from KRX."""
    date: date
    day_of_week: str  # 월, 화, 수, 목, 금
    name: str  # 휴장일 사유 (설날, 추석 등)
    year: int


class KRXHolidayFetcher:
    """
    Fetches KRX market holidays using the open.krx.co.kr API.

    The KRX API requires:
    1. First get an OTP (One-Time Password) token
    2. Then make the actual data request with the OTP
    """

    # KRX API endpoints
    OTP_URL = "http://open.krx.co.kr/contents/COM/GenerateOTP.jspx"
    DATA_URL = "http://open.krx.co.kr/contents/OPN/99/OPN99000001.jspx"

    # Alternative direct API endpoint (if OTP doesn't work)
    DIRECT_API_URL = "http://open.krx.co.kr/proframealt/front/OpenAPIListData.cmd"

    # BLD identifier for holiday data
    HOLIDAY_BLD = "MKD/01/0110/01100305/mkd01100305_01"

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": "http://open.krx.co.kr/contents/MKD/01/0110/01100305/MKD01100305.jsp",
                }
            )
        return self._session

    async def close(self):
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_otp(self, year: int) -> Optional[str]:
        """
        Get OTP token from KRX.

        Args:
            year: Year to fetch holidays for

        Returns:
            OTP token string or None if failed
        """
        session = await self._get_session()

        params = {
            "bld": self.HOLIDAY_BLD,
            "name": "form",
            "schyy": str(year),
        }

        try:
            async with session.get(self.OTP_URL, params=params) as response:
                if response.status == 200:
                    otp = await response.text()
                    logger.debug(f"Got OTP for year {year}: {otp[:20]}...")
                    return otp.strip()
                else:
                    logger.error(f"Failed to get OTP: status {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error getting OTP: {e}")
            return None

    async def fetch_holidays(self, year: int) -> List[HolidayInfo]:
        """
        Fetch holidays for a specific year from KRX.

        Args:
            year: Year to fetch holidays for (e.g., 2025)

        Returns:
            List of HolidayInfo objects
        """
        session = await self._get_session()
        holidays = []

        # Try method 1: OTP-based request
        otp = await self._get_otp(year)
        if otp:
            holidays = await self._fetch_with_otp(session, otp, year)
            if holidays:
                return holidays

        # Try method 2: Direct API request
        holidays = await self._fetch_direct(session, year)
        if holidays:
            return holidays

        # Try method 3: Alternative parsing
        holidays = await self._fetch_alternative(session, year)

        return holidays

    async def _fetch_with_otp(
        self, session: aiohttp.ClientSession, otp: str, year: int
    ) -> List[HolidayInfo]:
        """Fetch holidays using OTP authentication."""
        holidays = []

        data = {
            "code": otp,
            "schyy": str(year),
            "gridTp": "KRX",  # Korea Exchange
        }

        try:
            async with session.post(self.DATA_URL, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    holidays = self._parse_response(result, year)
                    logger.info(f"Fetched {len(holidays)} holidays for {year} (OTP method)")
                else:
                    logger.warning(f"OTP request failed: status {response.status}")
        except Exception as e:
            logger.error(f"Error in OTP fetch: {e}")

        return holidays

    async def _fetch_direct(
        self, session: aiohttp.ClientSession, year: int
    ) -> List[HolidayInfo]:
        """Fetch holidays using direct API request."""
        holidays = []

        params = {
            "bld": self.HOLIDAY_BLD,
            "schyy": str(year),
            "gridTp": "KRX",
        }

        try:
            async with session.get(self.DIRECT_API_URL, params=params) as response:
                if response.status == 200:
                    result = await response.json()
                    holidays = self._parse_response(result, year)
                    logger.info(f"Fetched {len(holidays)} holidays for {year} (direct method)")
                else:
                    logger.warning(f"Direct request failed: status {response.status}")
        except Exception as e:
            logger.error(f"Error in direct fetch: {e}")

        return holidays

    async def _fetch_alternative(
        self, session: aiohttp.ClientSession, year: int
    ) -> List[HolidayInfo]:
        """
        Alternative method: Use publicly known Korean holidays as fallback.

        This provides a reliable fallback when API access fails.
        """
        logger.warning(f"Using fallback holiday data for {year}")

        # Define known Korean public holidays (recurring every year)
        known_holidays = self._get_known_holidays(year)

        return known_holidays

    def _parse_response(self, response: Dict, year: int) -> List[HolidayInfo]:
        """Parse KRX API response into HolidayInfo objects."""
        holidays = []

        # KRX response format: {"OutBlock_1": [...], "CURRENT_DATETIME": "..."}
        data_list = response.get("OutBlock_1", response.get("block1", []))

        if not data_list:
            # Try alternative keys
            for key in response.keys():
                if isinstance(response[key], list) and len(response[key]) > 0:
                    data_list = response[key]
                    break

        for item in data_list:
            try:
                # Parse date (format: YYYY/MM/DD or YYYY-MM-DD or YYYYMMDD)
                date_str = item.get("calnd_dd", item.get("calnd_dd_dy", item.get("date", "")))

                # Clean and parse date
                date_str = date_str.replace("/", "-").replace(".", "-")
                if len(date_str) == 8 and date_str.isdigit():
                    # YYYYMMDD format
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

                holiday_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                # Day of week
                day_of_week = item.get("kr_dy_tp", item.get("dy_tp", ""))

                # Holiday name
                name = item.get("holdy_nm", item.get("dy_nm", item.get("name", "휴장일")))

                holidays.append(HolidayInfo(
                    date=holiday_date,
                    day_of_week=day_of_week,
                    name=name,
                    year=year,
                ))
            except Exception as e:
                logger.warning(f"Failed to parse holiday item: {item}, error: {e}")
                continue

        return holidays

    def _get_known_holidays(self, year: int) -> List[HolidayInfo]:
        """
        Get known Korean public holidays for a year.

        Note: Lunar holidays (설날, 추석, 석가탄신일) vary by year.
        This method provides approximate dates that should be updated.
        """
        # Fixed holidays (same date every year)
        fixed_holidays = [
            (1, 1, "신정"),
            (3, 1, "삼일절"),
            (5, 5, "어린이날"),
            (6, 6, "현충일"),
            (8, 15, "광복절"),
            (10, 3, "개천절"),
            (10, 9, "한글날"),
            (12, 25, "크리스마스"),
            (12, 31, "연말"),  # KRX 휴장
        ]

        # Lunar holidays vary by year (approximate for common years)
        lunar_holidays = {
            2024: [
                (2, 9, "설날 연휴"),
                (2, 10, "설날"),
                (2, 11, "설날 연휴"),
                (2, 12, "대체공휴일"),
                (5, 15, "석가탄신일"),
                (9, 16, "추석 연휴"),
                (9, 17, "추석"),
                (9, 18, "추석 연휴"),
            ],
            2025: [
                (1, 28, "설날 연휴"),
                (1, 29, "설날"),
                (1, 30, "설날 연휴"),
                (5, 5, "석가탄신일"),  # 2025년 석가탄신일은 5/5 (어린이날과 겹침)
                (5, 6, "대체공휴일"),
                (10, 5, "추석 연휴"),
                (10, 6, "추석"),
                (10, 7, "추석 연휴"),
                (10, 8, "대체공휴일"),
            ],
            2026: [
                (2, 16, "설날 연휴"),
                (2, 17, "설날"),
                (2, 18, "설날 연휴"),
                (5, 24, "석가탄신일"),
                (9, 24, "추석 연휴"),
                (9, 25, "추석"),
                (9, 26, "추석 연휴"),
            ],
        }

        holidays = []

        # Add fixed holidays
        for month, day, name in fixed_holidays:
            try:
                holiday_date = date(year, month, day)
                day_of_week = ["월", "화", "수", "목", "금", "토", "일"][holiday_date.weekday()]
                holidays.append(HolidayInfo(
                    date=holiday_date,
                    day_of_week=day_of_week,
                    name=name,
                    year=year,
                ))
            except ValueError:
                continue

        # Add lunar holidays for known years
        if year in lunar_holidays:
            for month, day, name in lunar_holidays[year]:
                try:
                    holiday_date = date(year, month, day)
                    day_of_week = ["월", "화", "수", "목", "금", "토", "일"][holiday_date.weekday()]
                    holidays.append(HolidayInfo(
                        date=holiday_date,
                        day_of_week=day_of_week,
                        name=name,
                        year=year,
                    ))
                except ValueError:
                    continue

        # Sort by date
        holidays.sort(key=lambda h: h.date)

        return holidays

    async def fetch_multiple_years(self, start_year: int, end_year: int) -> List[HolidayInfo]:
        """
        Fetch holidays for multiple years.

        Args:
            start_year: Starting year
            end_year: Ending year (inclusive)

        Returns:
            List of all holidays across the years
        """
        all_holidays = []

        for year in range(start_year, end_year + 1):
            try:
                holidays = await self.fetch_holidays(year)
                all_holidays.extend(holidays)
                logger.info(f"Fetched {len(holidays)} holidays for {year}")

                # Small delay between requests
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error fetching holidays for {year}: {e}")
                continue

        return all_holidays


# Test function
async def test_fetcher():
    """Test the KRX holiday fetcher."""
    fetcher = KRXHolidayFetcher()

    try:
        # Fetch 2025 holidays
        holidays = await fetcher.fetch_holidays(2025)

        print(f"\n=== KRX Holidays 2025 ({len(holidays)} days) ===")
        for h in holidays:
            print(f"  {h.date} ({h.day_of_week}) - {h.name}")

        # Fetch 2026 holidays
        holidays_2026 = await fetcher.fetch_holidays(2026)

        print(f"\n=== KRX Holidays 2026 ({len(holidays_2026)} days) ===")
        for h in holidays_2026:
            print(f"  {h.date} ({h.day_of_week}) - {h.name}")

    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(test_fetcher())
