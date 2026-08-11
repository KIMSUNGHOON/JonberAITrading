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

# 음력→양력 변환. 순수 파이썬 92KB, 의존성 0(PyPI korean_lunar_calendar).
#
# ⚠️ **없으면 None으로 남긴다 -- import 실패가 모듈 로드를 깨뜨리면 안 된다.**
# 이 모듈은 부팅 경로(lifespan)와 장중 1초 루프(market_hours)가 둘 다
# 밟으므로, 여기서 ImportError가 나가면 달력 하나 때문에 매매가 통째로
# 멈춘다. 대신 아래 `compute_lunar_holidays()`가 **명시적으로 실패**해
# 그 연도가 신뢰 불가로 남는다(부분 달력을 조용히 만들지 않는다).
#
# 테스트는 이 전역을 None으로 바꿔 import 실패 상태를 재현한다.
try:  # pragma: no cover - 설치 여부에 따라 갈리는 분기
    from korean_lunar_calendar import KoreanLunarCalendar
except ImportError:  # pragma: no cover
    KoreanLunarCalendar = None

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

# 적용 제외 -- **명시적 거부권**이다(암묵적 "어느 집합에도 없음"이 아니라).
#   신정(제3호)·현충일(제8호)은 법이 제3조 대상에서 뺐다.
#   12/31 "연말"은 법정공휴일이 아니라 KRX 자체 휴장일이라 애초에 대상이
#   아니고, 아래 `_STATUTORY_EXCLUDED_FROM_COLLISION`에 의해 "다른 공휴일과
#   겹쳤다"는 판정에서도 빠진다.
#
# ⚠️ 이 상수는 `compute_substitute_holidays()`에서 **트리거 집합보다 먼저**
# 평가된다. 그래야 법 개정으로 어떤 공휴일이 대체 대상에서 빠졌을 때
# 유지보수자가 이름을 여기에 추가하는 것만으로 실제로 꺼진다 -- 트리거
# 집합에서 지우는 것을 잊어도 거부권이 이긴다.
SUBSTITUTE_EXCLUDED = frozenset({"신정", "현충일", "연말"})

# 겹침 판정에서 제외 -- 법정공휴일이 아니어서 "다른 공휴일"이 될 수 없다.
_STATUTORY_EXCLUDED_FROM_COLLISION = frozenset({"연말"})

# 세 집합은 달력에 등장하는 모든 이름을 **빠짐없이·겹치지 않게** 나눠야
# 한다. 분류되지 않은 이름은 조용히 "대체 없음"으로 처리되는데, 그건
# 이번에 봉합한 결함("빠진 것이 정상처럼 보인다")과 같은 형태다.
_ALL_CLASSIFIED = (
    SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY
    | SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY
    | SUBSTITUTE_EXCLUDED
)


def classify_holiday_name(name: str) -> str:
    """공휴일 이름 → 대체공휴일 등급.

    Returns:
        "weekend_or_holiday" (제3조②) | "other_holiday_only" (제3조①)
        | "excluded" (적용 제외) | "unclassified" (셋 어디에도 없음)
    """
    if name in SUBSTITUTE_EXCLUDED:
        return "excluded"          # 거부권 우선
    if name in SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY:
        return "weekend_or_holiday"
    if name in SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY:
        return "other_holiday_only"
    return "unclassified"


def unclassified_holiday_names(names) -> set:
    """세 상수 어디에도 속하지 않는 이름들(대체공휴일 자신은 제외)."""
    return {
        n for n in names
        if n != SUBSTITUTE_HOLIDAY_NAME and n not in _ALL_CLASSIFIED
    }


# 한 해 달력이 "완전하다"고 부르기 위한 최소 조건.
#
# 폴백 경로는 `IncompleteHolidayDataError`가 막지만 **원격 경로에는 아무
# 검증이 없었다** -- KRX가 3행짜리 응답을 주면 그 해가 신뢰 상태로 저장된다.
# C가 봉합한 것과 정확히 같은 실패 형태(부분 데이터가 정상으로 보인다)라
# KRX 복구 시점에 터질 잠복 결함이었다.
#
# 검사 방식은 **행 수 하한이 아니라 이름 존재**다. 행 수는 해마다 달라
# 임계값이 자의적이지만, 설날·추석은 어느 해에도 반드시 있다(음력 고정).
_REQUIRED_HOLIDAY_MARKERS = (
    ("설날", ("설날", "설날 연휴")),
    ("추석", ("추석", "추석 연휴")),
)


def missing_required_markers(holidays: Sequence[HolidayInfo]) -> List[str]:
    """완전한 달력이라면 반드시 있어야 할 항목 중 빠진 것.

    빈 리스트면 완전하다고 볼 수 있다.
    """
    names = {h.name for h in holidays}
    return [
        label for label, aliases in _REQUIRED_HOLIDAY_MARKERS
        if not names.intersection(aliases)
    ]


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

    # 분류되지 않은 이름은 조용히 넘어가지 않는다 -- 새 공휴일이 표에
    # 들어왔는데 등급을 안 정하면 대체일이 영원히 안 생긴다.
    unknown = unclassified_holiday_names({n for ns in by_date.values() for n in ns})
    if unknown:
        logger.error(
            "substitute_rule_unclassified_holiday_names names=%s -- 이 이름들은 "
            "SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY · SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY · "
            "SUBSTITUTE_EXCLUDED 어디에도 없어 대체공휴일이 계산되지 않는다. "
            "셋 중 하나에 넣을 것.",
            sorted(unknown),
        )

    for d in sorted(by_date):
        names = by_date[d]

        # "다른 공휴일과 겹칠 경우" -- 같은 날짜에 법정공휴일 이름이 둘 이상.
        statutory = [n for n in names if n not in _STATUTORY_EXCLUDED_FROM_COLLISION]
        collides_with_other_holiday = len(set(statutory)) > 1

        is_saturday = d.weekday() == 5
        is_sunday = d.weekday() == 6

        # 등급 판정. `classify_holiday_name`이 **적용 제외를 먼저** 보므로
        # 거부권이 트리거 집합을 이긴다.
        grades = {classify_holiday_name(n) for n in names}

        triggered = False
        if "weekend_or_holiday" in grades:
            # 제3조② -- 토·일·다른 공휴일
            triggered = is_saturday or is_sunday or collides_with_other_holiday
        elif "other_holiday_only" in grades:
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


# ---------------------------------------------------------------------------
# 음력 공휴일 (관공서의 공휴일에 관한 규정 제2조 제4·6·9호)
# ---------------------------------------------------------------------------
#
# 예전에는 여기 대신 `LUNAR_HOLIDAYS`라는 손입력 딕셔너리가 있었고
# **2024·2025·2026 세 해뿐**이었다. 2027년 1월이 되면 설날이 거래일로
# 보이는 구조였다 -- 대체공휴일에서 이미 한 번 겪은 실패("표가 조용히
# 낡는다")와 같은 형태다. 그래서 같은 처방을 쓴다: 표를 지우고 계산한다.
#
# 세 공휴일은 전부 **평달**이라 윤달 인자는 항상 False다.
#   설날       = 음력 1/1  → 전날·당일·다음날 3일 (제2조제4호)
#   부처님오신날 = 음력 4/8               (제2조제6호)
#   추석       = 음력 8/15 → 전날·당일·다음날 3일 (제2조제9호)
#
# ⚠️ **여기에 대체공휴일을 넣지 말 것.** 대체일은 위
# `compute_substitute_holidays()`가 규칙으로 계산한다. 출처가 둘이면
# 어긋날 때 어느 쪽이 맞는지 알 수 없다.


class LunarHolidayRule(NamedTuple):
    """음력 날짜 → 공휴일. `neighbour_name`이 있으면 전날·다음날도 공휴일."""
    lunar_month: int
    lunar_day: int
    name: str
    neighbour_name: Optional[str]


LUNAR_HOLIDAY_RULES = (
    LunarHolidayRule(1, 1, "설날", "설날 연휴"),
    LunarHolidayRule(4, 8, "석가탄신일", None),
    LunarHolidayRule(8, 15, "추석", "추석 연휴"),
)

# 계산 유효 범위 -- **라이브러리의 실제 한계**다(임의의 정책값이 아니다).
#
# 실측(2026-08-11, korean_lunar_calendar 0.4.0): `setLunarDate()`가
# 1000~2050년에 True, 999년과 2051년에 False를 돌려준다. 범위 밖은
# 조용히 틀린 날짜가 아니라 **False**로 알려주므로, 아래 계산은 그것을
# 확인하고 명시적으로 실패한다.
#
# 상한이 조용히 낡지 않도록 테스트가 라이브러리에 직접 물어 대조한다
# (`test_declared_upper_bound_matches_the_library`). 라이브러리가 갱신돼
# 범위가 넓어지면 그 테스트가 실패하며 이 상수를 올리라고 알려준다.
LUNAR_CALC_MIN_YEAR = 1000
LUNAR_CALC_MAX_YEAR = 2050

# 라이브러리가 없을 때 사용자가 해야 할 일. 예외 메시지·로그에 그대로 실린다.
_LUNAR_INSTALL_HINT = (
    "pip install korean_lunar_calendar (순수 파이썬·의존성 0). "
    "environment.yml · backend/requirements.txt에 선언돼 있다."
)


def lunar_calendar_available() -> bool:
    """음력 변환 라이브러리를 쓸 수 있는가."""
    return KoreanLunarCalendar is not None


def lunar_year_supported(year: int) -> bool:
    """라이브러리가 그 연도를 다룰 수 있는가(선언된 범위 기준)."""
    return LUNAR_CALC_MIN_YEAR <= year <= LUNAR_CALC_MAX_YEAR


def solar_date_of_lunar(year: int, month: int, day: int) -> Optional[date]:
    """평달 음력 날짜 → 양력 날짜. 변환할 수 없으면 None.

    None을 돌려주는 경우는 셋이다: 라이브러리 없음 · 범위 밖 연도 ·
    라이브러리가 변환을 거부. **어느 쪽도 조용한 근사치를 내지 않는다.**
    """
    if KoreanLunarCalendar is None:
        return None

    cal = KoreanLunarCalendar()
    # 네 번째 인자 = 윤달 여부. 설날·부처님오신날·추석은 전부 평달이다.
    if not cal.setLunarDate(year, month, day, False):
        return None

    try:
        return date.fromisoformat(cal.SolarIsoFormat()[:10])
    except (TypeError, ValueError) as e:  # pragma: no cover - 방어선
        logger.error(
            "lunar_solar_conversion_unparsable year=%d lunar=%d/%d error=%s",
            year, month, day, e,
        )
        return None


def compute_lunar_holidays(year: int) -> List[HolidayInfo]:
    """그 해의 음력 공휴일을 **계산**한다(연휴 전날·다음날 포함).

    Raises:
        IncompleteHolidayDataError: 라이브러리가 없거나 · 연도가 범위
            밖이거나 · 변환이 실패했을 때. 고정 공휴일만 돌려주는 선택지는
            없다 -- 설날·추석이 빠진 달력은 "휴장일이 적다"가 "거래일이
            많다"로 접혀 없느니만 못하다(라이브 DB의 2027년 9행이 실물
            증거다).
    """
    if KoreanLunarCalendar is None:
        raise IncompleteHolidayDataError(
            f"{year}년 음력 공휴일(설날·부처님오신날·추석)을 계산할 수 없다: "
            f"korean_lunar_calendar 라이브러리가 없다. {_LUNAR_INSTALL_HINT} "
            f"고정 공휴일만 반환하면 설날·추석이 빠진 달력이 정상처럼 보이므로 "
            f"반환하지 않는다."
        )

    if not lunar_year_supported(year):
        raise IncompleteHolidayDataError(
            f"{year}년은 음력 변환 유효 범위 밖이다"
            f"({LUNAR_CALC_MIN_YEAR}~{LUNAR_CALC_MAX_YEAR}, "
            f"korean_lunar_calendar의 한계). 이 해의 달력은 KRX 연동이 "
            f"복구되거나 라이브러리가 범위를 넓혀야 만들 수 있다."
        )

    out: List[HolidayInfo] = []
    for rule in LUNAR_HOLIDAY_RULES:
        solar = solar_date_of_lunar(year, rule.lunar_month, rule.lunar_day)
        if solar is None:
            raise IncompleteHolidayDataError(
                f"{year}년 '{rule.name}'(음력 {rule.lunar_month}/{rule.lunar_day}) "
                f"양력 변환에 실패했다. 부분 달력을 반환하지 않는다."
            )

        days = [(solar, rule.name)]
        if rule.neighbour_name:
            days.append((solar - timedelta(days=1), rule.neighbour_name))
            days.append((solar + timedelta(days=1), rule.neighbour_name))

        for d, name in days:
            # 연휴 앞뒤가 연도를 넘으면 저장 계층의 연도별 완전성 회계가
            # 어긋난다. 음력 1/1은 양력 1월 하순~2월 하순, 음력 8/15는
            # 9~10월이라 구조적으로 불가능하지만, 조용히 어긋나느니
            # 시끄럽게 실패한다.
            if d.year != year:
                raise IncompleteHolidayDataError(
                    f"{year}년 '{name}' 계산 결과 {d}가 연도 경계를 넘었다 -- "
                    f"음력 변환 결과가 예상 범위를 벗어났다."
                )
            out.append(HolidayInfo(
                date=d, day_of_week=_weekday_name(d), name=name, year=year,
            ))

    out.sort(key=lambda h: h.date)
    return out


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

    # ⚠️ 음력 공휴일 표(`LUNAR_HOLIDAYS`)는 **제거됐다.** 2024·2025·2026만
    # 손으로 들어 있어 2027년 1월이면 설날이 거래일로 보이는 구조였다.
    # 이제 `compute_lunar_holidays(year)`가 매번 계산한다 -- 고정 공휴일
    # 표(`FIXED_HOLIDAYS`)만 표로 남는다(어느 해든 같은 날짜라 낡지 않는다).

    # 규칙 상수는 모듈 상수를 그대로 노출한다(호출자가 한 곳만 보면 되도록).
    SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY = SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY
    SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY = SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY
    SUBSTITUTE_EXCLUDED = SUBSTITUTE_EXCLUDED

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    # KRX 원격 호출 타임아웃(초).
    #
    # ⚠️ aiohttp 기본값은 `ClientTimeout(total=300)`이다. `initialize()`는
    # `current_year+1`을 매 부팅 검사하는데 그 해는 **구조적으로 영원히
    # 불완전하다**(표가 항상 뒤처진다). 따라서 부팅마다 죽은 엔드포인트로
    # OTP + 직접 호출 2회가 반드시 나간다. KRX가 404 대신 **무응답**이 되면
    # 기본값에서는 2 x 300s = 최대 10분간 부팅이 블로킹된다 --
    # `get_holiday_service()`가 lifespan에서 await되기 때문이고, 이 리포의
    # "장중 재시작 = 무방비 창"을 그만큼 넓힌다.
    #
    # 10초인 이유: 정상 응답은 1초 안쪽이고(실측 404가 즉답), 휴장일 달력은
    # 부팅을 지연시킬 만큼 급한 데이터가 아니다. 최악이 2 x 10s = 20초로
    # 묶인다. 실패하면 폴백 표가 받으므로 짧은 타임아웃의 대가는 없다.
    REQUEST_TIMEOUT_SECONDS = 10

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT_SECONDS),
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
        """폴백 경로가 그 연도의 **완전한** 달력을 만들 수 있는가.

        예전에는 "손입력 표에 그 해가 있는가"였다. 이제는 "음력을 계산할
        수 있는가" -- 라이브러리가 있고 연도가 유효 범위 안이면 참이다.
        실제 변환 실패는 `compute_lunar_holidays()`가 다시 잡는다(이중 방어).
        """
        return lunar_calendar_available() and lunar_year_supported(year)

    @classmethod
    def coverage_description(cls) -> str:
        """유효기간을 사람이 읽을 한 줄로. 부팅 진단 로그에 실린다.

        예전에는 표의 키 목록(`[2024, 2025, 2026]`)이었다. 이제는 구간이라
        문자열이 정직하다 -- 그리고 라이브러리가 없으면 그 사실 자체가
        여기 드러난다(빈 목록은 "덮는 연도가 없다"로만 보여 원인을 숨긴다).
        """
        if not lunar_calendar_available():
            return (
                "unavailable -- korean_lunar_calendar 미설치라 음력 공휴일을 "
                f"계산할 수 없다. {_LUNAR_INSTALL_HINT}"
            )
        return (
            f"computed {LUNAR_CALC_MIN_YEAR}-{LUNAR_CALC_MAX_YEAR} "
            f"(korean_lunar_calendar)"
        )

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
            "가 모두 실패해 로컬 폴백(고정 표 + 음력 계산 + 대체공휴일 규칙)으로 "
            "달력을 만든다. 이 값은 KRX에서 받은 것이 아니다. 유효 범위: %s",
            SOURCE_FALLBACK_TABLE, year, self.coverage_description(),
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
        """그 해의 폴백 달력 = 고정 표 + **계산한 음력** + **규칙 대체공휴일**.

        세 부분 중 손으로 유지되는 것은 `FIXED_HOLIDAYS`뿐이고, 그건 어느
        해든 같은 날짜라 낡지 않는다.

        Raises:
            IncompleteHolidayDataError: 음력을 계산할 수 없을 때(라이브러리
                없음 · 범위 밖 연도 · 변환 실패). 부분 달력을 조용히
                반환하면 "휴장일이 적다"가 "거래일이 많다"로 접힌다 --
                라이브 DB의 2027년 9행이 그 결과다.
        """
        # 음력을 **먼저** 계산한다. 실패하면 고정분을 만들기도 전에 나가야
        # 부분 달력이 존재할 수 있는 창 자체가 없다.
        lunar = compute_lunar_holidays(year)

        base = self._fixed_holidays(year) + lunar
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
        this_year = date.today().year
        print(f"coverage: {KRXHolidayFetcher.coverage_description()}")
        for year in range(this_year, this_year + 3):
            result = await fetcher.fetch_holidays_with_source(year)
            print(f"\n=== KRX Holidays {year} "
                  f"({len(result.holidays)} days, source={result.source}) ===")
            for h in result.holidays:
                print(f"  {h.date} ({h.day_of_week}) - {h.name}")
    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(test_fetcher())
