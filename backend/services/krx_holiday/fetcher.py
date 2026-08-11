"""
KRX Holiday Data Fetcher

Fetches holiday data from KRX (Korea Exchange) website.
Handles OTP authentication required by KRX API.

⚠️ 2026-08-11 라이브 실측: KRX 원격 경로는 **둘 다 죽어 있다**
(OTP는 200이지만 text/html을 돌려주고, 직접 호출은 404). 즉 모든 갱신이
아래 `_fetch_alternative` 폴백 표로 떨어져 왔고, 이 시스템은 KRX에서
달력을 받은 적이 한 번도 없다. 엔드포인트 복구는 별건(백로그)이고,
이 파일의 목표는 **폴백이 정확하고 정직해지는 것**이다.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, NamedTuple, Sequence
import aiohttp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 출처 라벨 -- 어떤 경로로 얻은 달력인지가 데이터에 남는다.
# ---------------------------------------------------------------------------
SOURCE_KRX_API = "krx_api"
SOURCE_FALLBACK_TABLE = "fallback_table"
SOURCE_UNKNOWN = "unknown"

_DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

SUBSTITUTE_HOLIDAY_NAME = "대체공휴일"


class HolidayInfo(NamedTuple):
    """Holiday information from KRX."""
    date: date
    day_of_week: str  # 월, 화, 수, 목, 금
    name: str  # 휴장일 사유 (설날, 추석 등)
    year: int


class HolidayFetchResult(NamedTuple):
    """가져온 휴장일 + **어디서** 가져왔는지.

    `fetch_holidays()`가 리스트만 돌려주던 시절에는 KRX 응답과 폴백 표가
    호출자에게 똑같이 보였다 -- 라이브 `holiday_metadata`에 성공처럼 남은
    2026-08-01 갱신이 실제로는 한 번도 KRX에 닿은 적 없는 표였다.
    """
    holidays: List[HolidayInfo]
    source: str


class IncompleteHolidayDataError(RuntimeError):
    """폴백 표에 그 연도의 **음력** 공휴일이 없다.

    고정 공휴일(신정·삼일절·광복절...)은 어느 해든 계산되지만 설날·추석·
    석가탄신일은 표에 손으로 넣은 연도만 있다. 그 연도를 넘어가면 예전
    구현은 고정분만 조용히 돌려줬고, 설날·추석이 통째로 빠진 달력이
    정상 데이터처럼 저장됐다(라이브 DB의 2027년 9행이 실물 증거).

    부분 달력은 "휴장일이 적다" = "거래일이 많다"로 접히므로, 없느니만
    못하다. 조용히 반환하는 대신 명시적으로 실패한다.
    """


def _weekday_name(d: date) -> str:
    return _DAY_NAMES[d.weekday()]


# ---------------------------------------------------------------------------
# 대체공휴일 규칙 (관공서의 공휴일에 관한 규정 제2조·제3조)
# ---------------------------------------------------------------------------
#
# 기준일(as of): 2026-08-11 시행 중인 대통령령.
#
# 제2조(공휴일) 발췌 -- 호 번호가 제3조에서 그대로 참조된다:
#   1호 일요일 · 2호 3·1절/광복절/개천절/한글날 · 3호 1월 1일
#   4호 설날 전날·설날·설날 다음날 · 6호 부처님오신날 · 7호 5월 5일
#   8호 6월 6일(현충일) · 9호 추석 전날·추석·추석 다음날
#   10호 12월 25일(기독탄신일)
#
# 제3조(대체공휴일):
#   ① 제4호(설날 연휴) 또는 제9호(추석 연휴)가 **다른 공휴일과 겹칠 경우**
#   ② 그 밖의 대상 공휴일이 **토요일이나 다른 공휴일과 겹칠 경우**
#      → 해당 공휴일 다음의 첫 번째 비공휴일을 공휴일로 한다.
#
# ⚠️ 두 항의 차이가 결과를 가른다. **토요일은 공휴일이 아니다**(제2조에
#    일요일만 있다). 따라서 설날·추석 연휴는 토요일에 걸려도 대체일이
#    생기지 않고, 일요일에 걸려야(=다른 공휴일과 겹쳐야) 생긴다.
#      실증 ①: 2024 설날 2/10(토)·2/11(일) → 대체는 2/12 하나뿐.
#              토요일도 트리거였다면 2/13까지 둘이어야 했다.
#      실증 ②: 2026 추석 연휴 9/26(토) → 대체 **없음**. 같은 해 광복절
#              8/15(토)는 제2호 국경일이라 8/17(월) 대체가 붙는다.
#              요일이 아니라 **등급**이 결과를 가른다.
#
# ⚠️ **적용 대상 집합은 법으로 정해지고 바뀐다.** 개정되면 아래 세 상수만
#    고치면 된다 -- 아래 규칙 코드는 이름을 보고 등급을 나눌 뿐 어떤 날짜도
#    알지 못한다. 상수를 코드 안에 흩어 놓지 말 것.

# 제3조② -- 토요일·일요일·다른 공휴일 어느 것과 겹쳐도 대체일이 생긴다.
SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY = frozenset({
    "삼일절",       # 제2조제2호 국경일
    "광복절",       # 제2조제2호 국경일
    "개천절",       # 제2조제2호 국경일
    "한글날",       # 제2조제2호 국경일
    "석가탄신일",   # 제2조제6호 부처님오신날
    "어린이날",     # 제2조제7호
    "크리스마스",   # 제2조제10호 기독탄신일
})

# 제3조① -- **다른 공휴일**(일요일 포함)과 겹칠 때만. 토요일은 해당 없음.
SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY = frozenset({
    "설날",         # 제2조제4호
    "설날 연휴",    # 제2조제4호 (전날·다음날)
    "추석",         # 제2조제9호
    "추석 연휴",    # 제2조제9호 (전날·다음날)
})

# 적용 제외.
#   신정(제3호)·현충일(제8호)은 법이 제3조 대상에서 뺐다.
#   12/31 "연말"은 법정공휴일이 아니라 KRX 자체 휴장일이라 애초에 대상이
#   아니고, 아래 `_STATUTORY_EXCLUDED_FROM_COLLISION`에 의해 "다른 공휴일과
#   겹쳤다"는 판정에서도 빠진다.
SUBSTITUTE_EXCLUDED = frozenset({"신정", "현충일", "연말"})

# 겹침 판정에서 제외 -- 법정공휴일이 아니어서 "다른 공휴일"이 될 수 없다.
_STATUTORY_EXCLUDED_FROM_COLLISION = frozenset({"연말"})


def compute_substitute_holidays(
    base_holidays: Sequence[HolidayInfo],
) -> List[HolidayInfo]:
    """원 공휴일 목록에서 대체공휴일을 **계산**한다(순수 함수).

    매년 손으로 채우던 표를 대신한다. 손입력은 2026년치가 통째로 빠지는
    방식으로 실패했고(빠진 4일 중 2일이 아직 오지 않은 거래일이었다),
    두 출처가 공존하면 어긋날 때 어느 쪽이 맞는지 알 수 없다.

    알고리즘:
      1. 원 공휴일을 **날짜별로** 묶는다. 같은 날 두 공휴일이 겹쳐도
         대체일은 하나다(2025-05-05 어린이날+석가탄신일 → 05-06 하나).
      2. 날짜 오름차순으로 훑으며 등급별 트리거를 판정한다.
      3. 트리거되면 다음날부터 걸어가며 **평일이면서 아직 비어 있는**
         첫 날을 잡는다. 이미 배정된 대체일도 점유로 친다 -- 그래야
         연쇄가 풀린다(2025 추석 10-05(일) → 10-06·10-07이 연휴라
         두 칸 밀려 10-08).

    ⚠️ 3의 "평일"에 대하여: 법문은 "첫 번째 **비공휴일**"이라 토요일도
    문자 그대로는 후보다. 실제로 그런 사례(대상 공휴일 둘이 금요일에
    겹치는 경우)는 아직 없었고, 공표된 달력은 전부 평일에 앉는다.
    거래일 달력 입장에서 토요일 대체일은 어차피 비거래일이라 무의미하다.
    검증된 2024·2025·2026 세 해 모두 결과가 같으므로 평일 해석을 쓴다.

    Args:
        base_holidays: 대체일을 **뺀** 원 공휴일 목록.

    Returns:
        새로 계산된 대체공휴일 목록(날짜 오름차순).
    """
    by_date: Dict[date, List[str]] = defaultdict(list)
    for h in base_holidays:
        if h.name not in by_date[h.date]:
            by_date[h.date].append(h.name)

    occupied = set(by_date)
    substitutes: List[HolidayInfo] = []

    for d in sorted(by_date):
        names = by_date[d]

        # "다른 공휴일과 겹칠 경우" -- 같은 날짜에 법정공휴일 이름이 둘 이상.
        statutory = [n for n in names if n not in _STATUTORY_EXCLUDED_FROM_COLLISION]
        collides_with_other_holiday = len(set(statutory)) > 1

        is_saturday = d.weekday() == 5
        is_sunday = d.weekday() == 6

        triggered = False
        if any(n in SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY for n in names):
            # 제3조② -- 토·일·다른 공휴일
            triggered = is_saturday or is_sunday or collides_with_other_holiday
        elif any(n in SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY for n in names):
            # 제3조① -- 다른 공휴일만(일요일은 제2조제1호로 공휴일)
            triggered = is_sunday or collides_with_other_holiday

        if not triggered:
            continue

        candidate = d + timedelta(days=1)
        # 안전 상한: 연휴가 아무리 길어도 2주 안에는 빈 평일이 나온다.
        limit = d + timedelta(days=14)
        while candidate <= limit and (
            candidate.weekday() >= 5 or candidate in occupied
        ):
            candidate += timedelta(days=1)

        if candidate > limit:
            logger.error(
                "substitute_holiday_search_exhausted origin=%s -- 대체일 후보를 "
                "14일 안에 찾지 못했다(달력 데이터가 이상하다)",
                d.isoformat(),
            )
            continue

        occupied.add(candidate)
        substitutes.append(HolidayInfo(
            date=candidate,
            day_of_week=_weekday_name(candidate),
            name=SUBSTITUTE_HOLIDAY_NAME,
            year=candidate.year,
        ))

    substitutes.sort(key=lambda h: h.date)
    return substitutes


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

    # 고정 공휴일 -- 어느 해든 같은 날짜다.
    FIXED_HOLIDAYS = (
        (1, 1, "신정"),
        (3, 1, "삼일절"),
        (5, 5, "어린이날"),
        (6, 6, "현충일"),
        (8, 15, "광복절"),
        (10, 3, "개천절"),
        (10, 9, "한글날"),
        (12, 25, "크리스마스"),
        (12, 31, "연말"),  # 법정공휴일이 아닌 KRX 자체 휴장일
    )

    # 음력 공휴일 -- 해마다 날짜가 달라 손으로 채운다.
    #
    # ⚠️ **여기 없는 연도는 폴백 달력을 만들 수 없다.** 고정분만 돌려주면
    # 설날·추석이 빠진 채 정상처럼 보이므로, `_get_known_holidays`가
    # `IncompleteHolidayDataError`로 명시적으로 실패한다.
    # 여기에 새 연도를 추가하는 것이 유일한 연장 방법이다(음력 계산
    # 라이브러리가 이 환경에 없다 -- 백로그).
    #
    # ⚠️ `"대체공휴일"`을 손으로 넣지 말 것. 대체일은
    # `compute_substitute_holidays()`가 규칙으로 계산한다 -- 출처가
    # 둘이면 어긋날 때 어느 쪽이 맞는지 알 수 없다.
    LUNAR_HOLIDAYS: Dict[int, Sequence] = {
        2024: (
            (2, 9, "설날 연휴"),
            (2, 10, "설날"),
            (2, 11, "설날 연휴"),
            (5, 15, "석가탄신일"),
            (9, 16, "추석 연휴"),
            (9, 17, "추석"),
            (9, 18, "추석 연휴"),
        ),
        2025: (
            (1, 28, "설날 연휴"),
            (1, 29, "설날"),
            (1, 30, "설날 연휴"),
            (5, 5, "석가탄신일"),  # 2025년 석가탄신일은 5/5 (어린이날과 겹침)
            (10, 5, "추석 연휴"),
            (10, 6, "추석"),
            (10, 7, "추석 연휴"),
        ),
        2026: (
            (2, 16, "설날 연휴"),
            (2, 17, "설날"),
            (2, 18, "설날 연휴"),
            (5, 24, "석가탄신일"),
            (9, 24, "추석 연휴"),
            (9, 25, "추석"),
            (9, 26, "추석 연휴"),
        ),
    }

    # 규칙 상수는 모듈 상수를 그대로 노출한다(호출자가 한 곳만 보면 되도록).
    SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY = SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY
    SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY = SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY
    SUBSTITUTE_EXCLUDED = SUBSTITUTE_EXCLUDED

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

    @classmethod
    def covers_year(cls, year: int) -> bool:
        """폴백 표가 그 연도의 **완전한** 달력을 만들 수 있는가."""
        return year in cls.LUNAR_HOLIDAYS

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

        기존 계약 유지(리스트 반환). 출처가 필요하면
        `fetch_holidays_with_source()`를 쓴다.

        Args:
            year: Year to fetch holidays for (e.g., 2025)

        Returns:
            List of HolidayInfo objects

        Raises:
            IncompleteHolidayDataError: 원격이 전부 실패했고 폴백 표에도
                그 연도가 없을 때.
        """
        return (await self.fetch_holidays_with_source(year)).holidays

    async def fetch_holidays_with_source(self, year: int) -> HolidayFetchResult:
        """휴장일 + **출처**를 함께 돌려준다.

        출처를 리스트에 실어 보내지 않으면 저장 계층이 "KRX에서 받았다"와
        "표를 베꼈다"를 구별할 수 없다. 라이브 `holiday_metadata`가
        2026-08-01에 성공처럼 보였던 이유가 정확히 그것이다.
        """
        session = await self._get_session()

        # Try method 1: OTP-based request
        otp = await self._get_otp(year)
        if otp:
            holidays = await self._fetch_with_otp(session, otp, year)
            if holidays:
                return HolidayFetchResult(holidays, SOURCE_KRX_API)

        # Try method 2: Direct API request
        holidays = await self._fetch_direct(session, year)
        if holidays:
            return HolidayFetchResult(holidays, SOURCE_KRX_API)

        # Try method 3: 폴백 표 (원격 실패)
        holidays = await self._fetch_alternative(session, year)
        return HolidayFetchResult(holidays, SOURCE_FALLBACK_TABLE)

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
        """원격이 전부 실패했을 때의 폴백 -- 하드코딩 표 + 대체공휴일 규칙.

        ⚠️ 이건 **성공이 아니라 실패**다. 2026-08-11 라이브 실측 기준 KRX
        연동은 죽어 있고(OTP는 200이지만 text/html, 직접 호출은 404) 모든
        갱신이 조용히 이 경로로 떨어져 왔다 -- 이 시스템은 KRX에서 달력을
        받은 적이 **한 번도 없다**. 예전에는 WARNING 한 줄이 전부라
        `holiday_metadata.last_update`만 보면 정상 갱신처럼 보였다.
        """
        logger.error(
            "krx_holiday_fetch_failed_using_%s year=%d -- KRX 원격 경로(OTP·직접)"
            "가 모두 실패해 하드코딩 폴백 표로 달력을 만든다. 이 값은 KRX에서 "
            "받은 것이 아니다. 표가 덮는 연도: %s",
            SOURCE_FALLBACK_TABLE, year, sorted(self.LUNAR_HOLIDAYS),
        )

        return self._get_known_holidays(year)

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

    def _fixed_holidays(self, year: int) -> List[HolidayInfo]:
        """그 해의 고정 공휴일만(음력·대체 제외). 어느 해든 계산된다."""
        out: List[HolidayInfo] = []
        for month, day, name in self.FIXED_HOLIDAYS:
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            out.append(HolidayInfo(
                date=d, day_of_week=_weekday_name(d), name=name, year=year,
            ))
        return out

    def _get_known_holidays(self, year: int) -> List[HolidayInfo]:
        """그 해의 폴백 달력 = 고정 + 음력 + **규칙으로 계산한 대체공휴일**.

        Raises:
            IncompleteHolidayDataError: 음력 표에 그 연도가 없을 때.
                부분 달력을 조용히 반환하면 "휴장일이 적다"가 "거래일이
                많다"로 접힌다 -- 라이브 DB의 2027년 9행이 그 결과다.
        """
        if not self.covers_year(year):
            raise IncompleteHolidayDataError(
                f"폴백 표에 {year}년 음력 공휴일(설날·추석·석가탄신일)이 없다. "
                f"현재 표가 덮는 연도: {sorted(self.LUNAR_HOLIDAYS)}. "
                f"고정 공휴일만 반환하면 설날·추석이 빠진 달력이 정상처럼 "
                f"보이므로 반환하지 않는다. "
                f"services/krx_holiday/fetcher.py의 LUNAR_HOLIDAYS에 "
                f"{year}년을 추가하거나 KRX 연동을 복구할 것."
            )

        base = self._fixed_holidays(year)
        for month, day, name in self.LUNAR_HOLIDAYS[year]:
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            base.append(HolidayInfo(
                date=d, day_of_week=_weekday_name(d), name=name, year=year,
            ))

        holidays = base + compute_substitute_holidays(base)
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
            except IncompleteHolidayDataError as e:
                # 부분 달력을 섞어 넣지 않는다 -- 그 해만 건너뛴다.
                logger.error(f"Skipping {year}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error fetching holidays for {year}: {e}")
                continue

        return all_holidays


# Test function
async def test_fetcher():
    """Test the KRX holiday fetcher."""
    fetcher = KRXHolidayFetcher()

    try:
        for year in sorted(KRXHolidayFetcher.LUNAR_HOLIDAYS):
            result = await fetcher.fetch_holidays_with_source(year)
            print(f"\n=== KRX Holidays {year} "
                  f"({len(result.holidays)} days, source={result.source}) ===")
            for h in result.holidays:
                print(f"  {h.date} ({h.day_of_week}) - {h.name}")
    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(test_fetcher())
