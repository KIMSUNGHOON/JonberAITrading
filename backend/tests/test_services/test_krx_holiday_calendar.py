"""KRX 거래일 달력 — 대체공휴일 규칙 · 폴백 정직성 · 표 유효기간.

배경(2026-08-11 라이브 실측): KRX 연동은 죽어 있고(OTP 200/text-html,
직접 호출 404) 모든 갱신이 조용히 하드코딩 표로 떨어지고 있었다.
`holiday_metadata.last_update`만 남아 성공과 실패가 구별되지 않았고,
표는 2025에서 관리가 멈춰 2026 대체공휴일이 통째로 빠졌으며, 음력 표가
2026에서 끝나 2027부터는 설날·추석이 사라진 **부분 데이터**가 정상처럼
보였다.

이 파일은 그 셋을 각각 못 박는다:
  A. 대체공휴일을 표가 아니라 **규칙**으로 (법 제3조)
  B. 폴백을 썼다는 사실이 **데이터와 로그에** 남는다
  C. 음력 표에 없는 연도는 **조용한 부분 데이터로 흘러가지 않는다**

⚠️ DB에 닿는 테스트는 전부 tmp_path로 경로를 주입한다 --
`KRXHolidayService()`는 생성만으로 `CREATE TABLE`을 돌리므로 경로를
주입하지 않으면 라이브 `backend/data/holidays.db`를 건드린다.
"""

from datetime import date

import pytest

from services.krx_holiday.fetcher import (
    IncompleteHolidayDataError,
    KRXHolidayFetcher,
    SOURCE_FALLBACK_TABLE,
    SUBSTITUTE_HOLIDAY_NAME,
    compute_substitute_holidays,
)
from services.krx_holiday.service import KRXHolidayService


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _substitutes(year: int) -> set:
    """그 해 폴백 달력이 **규칙으로 계산한** 대체공휴일 날짜 집합."""
    holidays = KRXHolidayFetcher()._get_known_holidays(year)
    return {h.date for h in holidays if h.name == SUBSTITUTE_HOLIDAY_NAME}


def _all_dates(year: int) -> set:
    return {h.date for h in KRXHolidayFetcher()._get_known_holidays(year)}


@pytest.fixture
def svc(tmp_path):
    """tmp sqlite에 묶인 서비스. 네트워크·라이브 DB 어느 쪽도 건드리지 않는다."""
    service = KRXHolidayService(db_path=str(tmp_path / "holidays.db"))
    yield service


@pytest.fixture
def offline_fetcher(monkeypatch):
    """KRX 원격 경로 2종(OTP/직접)을 막아 폴백 표로 떨어지게 만든다.

    실측된 라이브 상태(OTP는 HTML, 직접 호출은 404)를 그대로 재현하는
    것이고, 테스트가 실제 네트워크에 나가지 않게 하는 장치이기도 하다.
    """

    async def _no_otp(self, year):
        return None

    async def _no_direct(self, session, year):
        return []

    monkeypatch.setattr(KRXHolidayFetcher, "_get_otp", _no_otp)
    monkeypatch.setattr(KRXHolidayFetcher, "_fetch_direct", _no_direct)


# ===========================================================================
# A. 대체공휴일 = 규칙
# ===========================================================================


def test_2026_substitute_days_are_exactly_the_statutory_four():
    """2026 대체공휴일은 정확히 넷이다.

    | 원 공휴일          | 요일 | 대체일       |
    |--------------------|------|--------------|
    | 03-01 삼일절       | 일   | 03-02(월)    |
    | 05-24 석가탄신일   | 일   | 05-25(월)    |
    | 08-15 광복절       | 토   | 08-17(월)    |
    | 10-03 개천절       | 토   | 10-05(월)    |

    ⚠️ 09-26(토) 추석 연휴에는 대체일이 **없다** -- 이건 태스크 명세가
    다섯 번째로 적었던 09-28이 사실과 다르다는 뜻이고, 별도 테스트
    (`test_chuseok_saturday_gets_no_substitute`)로 못 박는다.
    """
    assert _substitutes(2026) == {
        date(2026, 3, 2),
        date(2026, 5, 25),
        date(2026, 8, 17),
        date(2026, 10, 5),
    }


def test_chuseok_saturday_gets_no_substitute():
    """음성 케이스 ①: 설날·추석 연휴는 **토요일**에 걸려도 대체일이 없다.

    근거 = 관공서의 공휴일에 관한 규정 제3조.
      ① 설날 연휴(제2조제4호)·추석 연휴(제9호)는 "**다른 공휴일**과
         겹칠 경우"에만 대체. 토요일은 제2조 어디에도 없어 공휴일이
         아니다(일요일만 제1호로 공휴일).
      ② 국경일·부처님오신날·어린이날·성탄절은 "**토요일이나** 다른
         공휴일과 겹칠 경우" 대체.

    실증: 2024 설날 2/10(토)·2/11(일) → 대체는 2/12 **하나**(일요일분).
    토요일도 트리거였다면 2/13까지 둘이어야 했다.

    이 테스트는 두 등급을 하나로 합치면(=설날/추석을 토요일 트리거
    집합에 넣으면) 실패한다.
    """
    subs = _substitutes(2026)
    assert date(2026, 9, 28) not in subs
    # 같은 해 광복절 8/15(토)는 국경일이라 대체가 붙는다 -- 요일이 아니라
    # **등급**이 결과를 가른다는 대조군.
    assert date(2026, 8, 17) in subs


def test_memorial_day_saturday_gets_no_substitute():
    """음성 케이스 ②: 현충일(2026-06-06 토)에는 대체일이 생기지 않는다.

    적용 제외 목록을 지우면 06-08(월)이 튀어나오며 실패한다.
    """
    subs = _substitutes(2026)
    assert date(2026, 6, 8) not in subs
    assert not any(d.month == 6 for d in subs)


def test_new_year_and_yearend_are_excluded_from_substitution():
    """음성 케이스 ③: 신정·연말 휴장도 적용 제외다.

    2027-01-01은 금요일이라 무해하지만, 2028-01-01은 **토요일**이다 --
    신정이 제외 목록에 없으면 2028-01-03(월)이 대체일로 나온다.
    12-31 연말 휴장은 법정공휴일이 아니라 KRX 자체 휴장일이라 애초에
    대체 대상이 아니다.
    """
    fixed_only = KRXHolidayFetcher()._fixed_holidays(2028)
    subs = {h.date for h in compute_substitute_holidays(fixed_only)}
    assert date(2028, 1, 3) not in subs  # 신정(토) → 대체 없음
    assert date(2029, 1, 1) not in subs  # 연말(2028-12-31 일) → 대체 없음
    assert date(2028, 6, 6) in {h.date for h in fixed_only}


def test_2025_rule_reproduces_hardcoded_chuseok_substitute():
    """연쇄 케이스: 2025 추석 10-05(일) → 대체는 10-08(수).

    10-06(월)·10-07(화)이 이미 추석 연휴라 후보가 두 칸 밀린다.
    제거된 하드코딩 항목 `(10, 8, "대체공휴일")`과 정확히 일치해야
    한다 -- 규칙이 옳다는 가장 강한 증거.
    """
    subs = _substitutes(2025)
    assert date(2025, 10, 8) in subs
    # 추석 연휴 3일 중 대체를 만드는 건 일요일 하나뿐이다.
    assert len([d for d in subs if d.month == 10]) == 1


def test_2025_rule_reproduces_hardcoded_buddha_children_collision():
    """겹침 케이스: 2025-05-05는 어린이날 **과** 석가탄신일이다(월).

    요일은 평일이지만 "다른 공휴일과 겹칠 경우"에 해당해 대체가 붙고,
    둘이 겹쳤다고 대체가 둘이 되지는 않는다(같은 날 → 하나).
    제거된 하드코딩 항목 `(5, 6, "대체공휴일")`과 일치해야 한다.
    """
    subs = _substitutes(2025)
    assert date(2025, 5, 6) in subs
    assert len([d for d in subs if d.month == 5]) == 1


def test_2024_rule_reproduces_hardcoded_seollal_substitute():
    """2024 설날 2/9(금)·2/10(토)·2/11(일) → 대체는 2/12(월) 하나.

    제거된 하드코딩 항목 `(2, 12, "대체공휴일")`과 일치해야 한다.
    2/13이 함께 나오면 토요일 트리거를 잘못 적용한 것이다.
    """
    subs = _substitutes(2024)
    assert date(2024, 2, 12) in subs
    assert date(2024, 2, 13) not in subs
    assert len([d for d in subs if d.month == 2]) == 1


def test_rule_recovers_substitutes_the_hardcoded_table_had_lost():
    """규칙은 하드코딩 표가 **빠뜨린** 실제 대체공휴일도 되찾는다.

    - 2024-05-06: 어린이날 5/5가 일요일 → 대체(실제로 공휴일이었다)
    - 2025-03-03: 삼일절 3/1이 토요일 → 대체(실제로 공휴일이었다)

    둘 다 `lunar_holidays`의 손입력 목록에 없었다. 표 관리가 2025에서
    멈춘 게 아니라 **처음부터 새고 있었다**는 증거다.
    """
    assert date(2024, 5, 6) in _substitutes(2024)
    assert date(2025, 3, 3) in _substitutes(2025)


def test_hardcoded_substitute_entries_are_gone():
    """출처는 하나여야 한다 -- 손입력 `대체공휴일` 항목은 표에서 제거됐다.

    두 출처가 공존하면 어긋날 때 어느 쪽이 맞는지 알 수 없다.
    """
    table = KRXHolidayFetcher.LUNAR_HOLIDAYS
    for year, entries in table.items():
        names = [name for _m, _d, name in entries]
        assert SUBSTITUTE_HOLIDAY_NAME not in names, (
            f"{year} 음력 표에 손입력 대체공휴일이 남아 있다: {names}"
        )


def test_substitute_never_lands_on_an_existing_holiday_or_weekend():
    """대체일은 주말에도, 이미 공휴일인 날에도 앉지 않는다(전 연도)."""
    for year in sorted(KRXHolidayFetcher.LUNAR_HOLIDAYS):
        holidays = KRXHolidayFetcher()._get_known_holidays(year)
        subs = [h for h in holidays if h.name == SUBSTITUTE_HOLIDAY_NAME]
        originals = {h.date for h in holidays if h.name != SUBSTITUTE_HOLIDAY_NAME}
        seen = set()
        for s in subs:
            assert s.date.weekday() < 5, f"{s.date} 대체일이 주말에 앉았다"
            assert s.date not in originals, f"{s.date} 대체일이 원 공휴일과 겹쳤다"
            assert s.date not in seen, f"{s.date} 대체일이 중복 생성됐다"
            seen.add(s.date)


def test_substitute_rule_is_pure_and_table_driven():
    """규칙은 순수 함수이고 대상 집합은 상수다 -- 코드에 흩어져 있지 않다."""
    assert isinstance(KRXHolidayFetcher.SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY, frozenset)
    assert isinstance(KRXHolidayFetcher.SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY, frozenset)
    assert isinstance(KRXHolidayFetcher.SUBSTITUTE_EXCLUDED, frozenset)
    # 두 등급은 서로소여야 한다(한 이름이 두 규칙을 타면 결과가 모호해진다).
    assert not (
        KRXHolidayFetcher.SUBSTITUTE_ON_WEEKEND_OR_HOLIDAY
        & KRXHolidayFetcher.SUBSTITUTE_ON_OTHER_HOLIDAY_ONLY
    )
    assert compute_substitute_holidays([]) == []


# ===========================================================================
# B. 조용한 실패를 시끄럽게
# ===========================================================================


@pytest.mark.asyncio
async def test_fallback_source_is_recorded_in_metadata(svc, offline_fetcher):
    """폴백을 썼으면 `holiday_metadata`에 출처가 남는다.

    수정 전에는 `last_update`만 있어 "KRX에서 받았다"와 "표를 베꼈다"가
    구별되지 않았다 -- 라이브 DB의 2026-08-01 갱신이 정확히 그랬다.
    """
    try:
        saved = await svc.update_holidays(2026)
    finally:
        await svc.close()

    assert saved > 0
    assert svc.storage.get_source() == SOURCE_FALLBACK_TABLE
    assert svc.storage.get_source(2026) == SOURCE_FALLBACK_TABLE
    assert svc.storage.get_last_update() is not None


@pytest.mark.asyncio
async def test_fallback_use_is_logged_as_an_error(svc, offline_fetcher, caplog):
    """폴백은 WARNING이 아니라 실패로 격상돼 기록된다."""
    import logging

    caplog.set_level(logging.DEBUG)
    try:
        await svc.update_holidays(2026)
    finally:
        await svc.close()

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "폴백을 썼는데 ERROR 로그가 하나도 없다"
    blob = " ".join(r.getMessage() for r in errors)
    assert "KRX" in blob
    assert SOURCE_FALLBACK_TABLE in blob


def test_status_surfaces_source_and_untrusted_years(svc):
    """`get_status()`가 출처와 신뢰 못 하는 연도를 드러낸다(부팅 로그용)."""
    status = svc.get_status()
    assert "source" in status
    assert "year_sources" in status
    assert "untrusted_years" in status


# ===========================================================================
# C. 표의 유효기간
# ===========================================================================


def test_year_without_lunar_data_fails_explicitly():
    """음력 표에 없는 연도는 부분 데이터를 조용히 돌려주지 않는다.

    수정 전에는 2030을 물으면 `fixed_holidays`만 9개 돌려주고 설날·추석이
    통째로 빠진 채 정상처럼 보였다. 라이브 DB의 2027행 9개가 실물 증거다.
    """
    with pytest.raises(IncompleteHolidayDataError):
        KRXHolidayFetcher()._get_known_holidays(2030)


@pytest.mark.asyncio
async def test_uncovered_year_is_not_persisted(svc, offline_fetcher):
    """부분 데이터는 저장 계층에 도달하지 않는다."""
    try:
        saved = await svc.update_holidays(2030)
    finally:
        await svc.close()

    assert saved == 0
    assert svc.storage.get_year_stats().get(2030, 0) == 0
    assert not svc.storage.has_year_data(2030)


@pytest.mark.asyncio
async def test_uncovered_year_does_not_break_the_covered_one(svc, offline_fetcher):
    """한 해가 실패해도 다른 해 갱신은 계속된다(시스템이 멈추지 않는다)."""
    try:
        await svc.update_holidays(2026)
        await svc.update_holidays(2030)
    finally:
        await svc.close()

    assert svc.storage.has_year_data(2026)
    assert not svc.storage.has_year_data(2030)


def test_fallback_coverage_is_queryable():
    """호출자가 표의 유효기간을 직접 물어볼 수 있다."""
    assert KRXHolidayFetcher.covers_year(2026) is True
    assert KRXHolidayFetcher.covers_year(2030) is False
    assert max(KRXHolidayFetcher.LUNAR_HOLIDAYS) >= 2026


# ---------------------------------------------------------------------------
# C-균형: "모른다"가 "거래일이다"로 접히지 않되, 시스템이 멈추지도 않는다
# ---------------------------------------------------------------------------


def test_is_trading_day_never_raises(svc):
    """어떤 입력에도 `is_trading_day`가 호출자를 깨뜨리지 않는다.

    노출도 계산·장중 판정·EOD 체인이 전부 이 불리언 위에 서 있다.
    """
    for d in [
        date(2026, 8, 17),   # 대체공휴일(데이터 없음)
        date(2030, 2, 4),    # 표 밖 연도
        date(2030, 2, 2),    # 표 밖 연도 + 주말
        date(1900, 1, 1),    # 극단
        date(2099, 12, 31),
    ]:
        assert isinstance(svc.is_trading_day(d), bool)


def test_range_and_neighbour_helpers_never_raise_on_uncovered_years(svc):
    """소비처가 실제로 부르는 파생 API도 표 밖 연도에서 예외를 안 낸다."""
    assert isinstance(svc.get_previous_trading_day(date(2030, 2, 4)), date)
    assert isinstance(svc.get_next_trading_day(date(2030, 2, 4)), date)
    days = svc.get_trading_days_in_range(date(2030, 2, 1), date(2030, 2, 28))
    assert isinstance(days, list) and days


def test_unknown_is_distinguishable_from_trading_day(svc):
    """"모른다"가 "거래일이다"로 **접히지 않는다**.

    불리언은 살아 있는 채로(=시스템이 멈추지 않는다) 신뢰 여부를
    별도 축으로 물어볼 수 있어야 한다.
    """
    verdict = svc.get_trading_day_verdict(date(2030, 2, 4))
    assert verdict.is_trading_day is True   # 시스템은 계속 돈다
    assert verdict.trusted is False         # 그러나 이건 근거 없는 True다
    assert verdict.reason


@pytest.mark.asyncio
async def test_covered_year_becomes_trusted_after_update(svc, offline_fetcher):
    """폴백이라도 **완전한** 연도를 쓰면 그 해는 신뢰 상태가 된다."""
    try:
        await svc.update_holidays(2026)
    finally:
        await svc.close()

    trusted = svc.get_trading_day_verdict(date(2026, 8, 18))
    assert trusted.trusted is True
    assert trusted.is_trading_day is True

    # 그리고 오늘의 실제 피해가 봉합된다: 8/17은 대체공휴일이다.
    blocked = svc.get_trading_day_verdict(date(2026, 8, 17))
    assert blocked.is_trading_day is False
    assert blocked.trusted is True


@pytest.mark.asyncio
async def test_live_damage_dates_are_now_non_trading(svc, offline_fetcher):
    """2026년에 빠져 있던 대체공휴일들이 이제 비거래일로 판정된다."""
    try:
        await svc.update_holidays(2026)
    finally:
        await svc.close()

    for d in [date(2026, 3, 2), date(2026, 5, 25), date(2026, 8, 17), date(2026, 10, 5)]:
        assert svc.is_trading_day(d) is False, f"{d}는 대체공휴일인데 거래일로 나왔다"

    # 반대로 09-28은 **거래일이다** -- 없는 휴일을 만들어내지도 않는다.
    assert svc.is_trading_day(date(2026, 9, 28)) is True


# ===========================================================================
# 8. 소비처 회귀 가드
# ===========================================================================


def test_public_api_signatures_unchanged():
    """소비처 3곳이 부르는 이름·형태가 그대로 살아 있다."""
    import inspect

    from services.krx_holiday import (
        get_holiday_service,
        get_holiday_service_sync,
    )

    assert inspect.iscoroutinefunction(get_holiday_service)
    assert not inspect.iscoroutinefunction(get_holiday_service_sync)
    for name in (
        "is_trading_day",
        "is_holiday",
        "get_holiday_info",
        "get_next_trading_day",
        "get_previous_trading_day",
        "get_trading_days_in_range",
        "update_holidays",
        "get_status",
        "start_scheduler",
    ):
        assert hasattr(KRXHolidayService, name), name

    # 1인자 = 날짜 하나 (briefing.py / regime_judge.py 호출 형태)
    sig = inspect.signature(KRXHolidayService.is_trading_day)
    assert list(sig.parameters) == ["self", "check_date"]


@pytest.mark.asyncio
async def test_discovery_ledger_still_walks_trading_days(svc, offline_fetcher):
    """소비처 ①: services/discovery/ledger.py의 두 원시함수."""
    from services.discovery import ledger as ledger_module

    try:
        await svc.update_holidays(2026)
    finally:
        await svc.close()

    # 2026-08-17(월)이 대체공휴일이 됐으므로 08-14(금)의 다음 거래일은 08-18(화).
    elapsed = ledger_module._trading_days_elapsed(svc, date(2026, 8, 14), date(2026, 8, 18))
    assert elapsed == 1
    assert ledger_module._trading_day_n_before(svc, date(2026, 8, 18), 1) == date(2026, 8, 14)


@pytest.mark.asyncio
async def test_market_hours_still_reads_the_service(svc, offline_fetcher, monkeypatch):
    """소비처 ②: services/trading/market_hours.py의 `_is_krx_holiday`."""
    from services.trading.market_hours import MarketHoursService

    try:
        await svc.update_holidays(2026)
    finally:
        await svc.close()

    mh = MarketHoursService()
    mh._holiday_service = svc
    mh._holiday_service_checked = True

    assert mh._is_krx_holiday(date(2026, 8, 17)) is True
    assert mh._is_krx_holiday(date(2026, 8, 18)) is False
    assert mh._get_holiday_name(date(2026, 8, 17)) == SUBSTITUTE_HOLIDAY_NAME


@pytest.mark.asyncio
async def test_telegram_briefing_style_call_still_works(svc, offline_fetcher):
    """소비처 ③: services/telegram/briefing.py의 `svc.is_trading_day(date.today())`."""
    try:
        await svc.update_holidays(2026)
    finally:
        await svc.close()

    assert svc.is_trading_day(date(2026, 8, 11)) is True
