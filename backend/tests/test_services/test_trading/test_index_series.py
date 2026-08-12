from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.storage_service import get_storage_service
from services.trading.index_series import (
    INDEX_SOURCE,
    closes_to_returns,
    evaluate_series_lag,
    is_series_stale,
    refresh_index_daily,
)

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


# ---- 순수 함수 ----

def test_closes_to_returns_basic():
    got = closes_to_returns([100.0, 110.0, 99.0])
    assert got == pytest.approx([10.0, -10.0])


def test_closes_to_returns_skips_unusable_pairs():
    """0·비유한 종가가 끼면 그 쌍만 건너뛴다 — 조용히 0을 만들지 않는다."""
    got = closes_to_returns([100.0, 0.0, 110.0, 121.0])
    assert got == pytest.approx([10.0])


def test_closes_to_returns_short_input():
    assert closes_to_returns([]) == []
    assert closes_to_returns([100.0]) == []


def test_is_series_stale_boundary():
    today = date(2026, 8, 14)
    assert is_series_stale("2026-08-07", today) is False   # 7일 == 경계, 신선
    assert is_series_stale("2026-08-06", today) is True    # 8일


def test_is_series_stale_survives_long_holiday():
    """설·추석 연휴(최대 5거래일 공백)에서 오탐이 나면 안 된다."""
    assert is_series_stale("2026-02-13", date(2026, 2, 18)) is False


def test_is_series_stale_unparseable_is_stale():
    """모르는 것을 신선하다고 보면 안 된다."""
    assert is_series_stale("not-a-date", date(2026, 8, 7)) is True


# ---- 거래일 기준 지연 검사 (2026-08-11) ----
#
# `is_series_stale`은 7**역일**이라 거래일 하루가 통째로 빠져도 아무 신호가
# 없다(2026-08-10 월요일 종가 누락을 우연히 조회하다 발견했다). 지연 검사는
# 그 공백을 보이게 만드는 **관측 신호**다 — 배수는 건드리지 않는다.
#
# ⚠️ 실물 `KRXHolidayService`를 부르면 `HolidayStorage.__init__`이
# 라이브 `data/holidays.db`에 `CREATE TABLE`을 친다. 테스트는 반드시
# 달력 대역을 주입한다.


class _FakeCalendar:
    """KRX 달력 대역 — 실물 `KRXHolidayService`와 같은 의미론.

    주말 + 지정 휴일만 비거래일이고, `get_previous_trading_day`는
    `from_date` **직전**(엄격히 이전)의 거래일을 돌려준다.
    """

    def __init__(self, holidays=()):
        self.holidays = set(holidays)

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def get_previous_trading_day(self, from_date: date) -> date:
        d = from_date - timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def get_trading_days_in_range(self, start: date, end: date) -> list:
        out, cur = [], start
        while cur <= end:
            if self.is_trading_day(cur):
                out.append(cur)
            cur += timedelta(days=1)
        return out


def test_todays_actual_gap_is_detected():
    """**이 수정의 재현 케이스** — 2026-08-11(화) 아침, 최신이 08-07(금).

    직전 거래일은 08-10(월)인데 그 종가가 없다. 역일로는 4일이라
    `is_series_stale`(7역일)은 조용하다.
    """
    lag = evaluate_series_lag(
        "2026-08-07", date(2026, 8, 11), holiday_service=_FakeCalendar()
    )
    assert lag.lagging is True
    assert lag.expected == date(2026, 8, 10)
    assert lag.trading_days_behind == 1
    assert is_series_stale("2026-08-07", date(2026, 8, 11)) is False, (
        "역일 문턱은 이 공백을 못 본다 — 그래서 이 검사가 필요하다"
    )


def test_monday_morning_with_friday_close_is_not_lagging():
    """주말 오탐 금지. 월요일 08:05에 최신이 금요일인 것은 정상이다 —
    월요일 종가는 아직 존재하지도 않는다."""
    lag = evaluate_series_lag(
        "2026-08-07", date(2026, 8, 10), holiday_service=_FakeCalendar()
    )
    assert lag.lagging is False
    assert lag.trading_days_behind == 0


def test_weekend_is_not_lagging():
    lag = evaluate_series_lag(
        "2026-08-07", date(2026, 8, 8), holiday_service=_FakeCalendar()
    )
    assert lag.lagging is False


def test_day_after_a_holiday_is_not_lagging():
    """광복절 대체휴일(월) 다음 화요일 아침 — 최신은 그 전 금요일이 맞다."""
    cal = _FakeCalendar(holidays={date(2026, 8, 17)})
    lag = evaluate_series_lag("2026-08-14", date(2026, 8, 18), holiday_service=cal)
    assert lag.lagging is False
    assert lag.expected == date(2026, 8, 14)


def test_long_holiday_is_not_lagging():
    """설 연휴(최대 5거래일 공백)에서도 오탐이 없어야 한다."""
    cal = _FakeCalendar(holidays={date(2026, 2, 16), date(2026, 2, 17)})
    lag = evaluate_series_lag("2026-02-13", date(2026, 2, 18), holiday_service=cal)
    assert lag.lagging is False


def test_multi_day_lag_counts_trading_days_not_calendar_days():
    """08-13(목) 아침에 최신이 08-07(금)이면 08-10·11·12 세 거래일이 빈다
    (역일로는 6일)."""
    lag = evaluate_series_lag(
        "2026-08-07", date(2026, 8, 13), holiday_service=_FakeCalendar()
    )
    assert lag.lagging is True
    assert lag.expected == date(2026, 8, 12)
    assert lag.trading_days_behind == 3


def test_future_dated_row_is_not_lagging():
    """최신이 직전 거래일보다 뒤(= 오늘 종가가 이미 들어옴)면 지연이 아니다."""
    lag = evaluate_series_lag(
        "2026-08-11", date(2026, 8, 11), holiday_service=_FakeCalendar()
    )
    assert lag.lagging is False
    assert lag.trading_days_behind == 0


def test_calendar_failure_is_unknown_not_false():
    """달력이 죽어도 노출도 계산은 계속돼야 한다(never-raise). 그때
    지연 여부는 **모름**이지 "지연 아님"이 아니다 — 둘을 합치면 달력이
    죽은 날 공백이 영원히 안 보인다."""

    class _Broken:
        def get_previous_trading_day(self, from_date):
            raise RuntimeError("holiday db down")

        def get_trading_days_in_range(self, start, end):
            raise RuntimeError("holiday db down")

    lag = evaluate_series_lag("2026-08-07", date(2026, 8, 11), holiday_service=_Broken())
    assert lag.lagging is None
    assert lag.trading_days_behind is None


def test_unparseable_latest_date_is_unknown():
    lag = evaluate_series_lag(
        "not-a-date", date(2026, 8, 11), holiday_service=_FakeCalendar()
    )
    assert lag.lagging is None


def test_default_holiday_service_is_resolved_lazily():
    """`services/discovery/ledger.py:53`과 같은 관행 — 모듈 임포트가
    krx_holiday의 apscheduler/aiohttp 의존을 끌고 오지 않도록 호출
    시점에 가져온다."""
    import services.trading.index_series as idx

    cal = _FakeCalendar()
    with patch("services.krx_holiday.get_holiday_service_sync", return_value=cal) as p:
        lag = idx.evaluate_series_lag("2026-08-07", date(2026, 8, 11))
    p.assert_called_once()
    assert lag.lagging is True


# ---- 수집 ----

def _fake_history(dates_closes):
    """yfinance history() 흉내 — .index와 ["Close"]만 쓴다."""
    import pandas as pd

    idx = pd.to_datetime([d for d, _ in dates_closes])
    return pd.DataFrame({"Close": [c for _, c in dates_closes]}, index=idx)


@pytest.mark.asyncio
async def test_refresh_writes_rows_and_reports_count():
    hist = _fake_history([("2026-08-05", 6598.26), ("2026-08-06", 6296.38)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)
    with patch("services.trading.index_series.yf.Ticker", return_value=tk):
        n = await refresh_index_daily(lookback_days=40)
    assert n == 2

    storage = await get_storage_service()
    got = await storage.get_recent_index_closes()
    assert [d for d, _ in got] == ["2026-08-05", "2026-08-06"]


@pytest.mark.asyncio
async def test_refresh_empty_history_writes_nothing():
    tk = MagicMock()
    tk.history = MagicMock(return_value=_fake_history([]))
    with patch("services.trading.index_series.yf.Ticker", return_value=tk):
        assert await refresh_index_daily() is None

    storage = await get_storage_service()
    assert await storage.get_recent_index_closes() == []


@pytest.mark.asyncio
async def test_refresh_never_raises():
    """스케줄 잡이 직접 부른다 — 예외가 새면 잡이 죽는다."""
    with patch(
        "services.trading.index_series.yf.Ticker",
        side_effect=RuntimeError("yahoo down"),
    ):
        assert await refresh_index_daily() is None


@pytest.mark.asyncio
async def test_refresh_reports_none_when_persist_fails():
    """upsert가 실패-무해(0 반환)라 반환값을 안 보면 거짓 성공을 보고하게 된다."""
    hist = _fake_history([("2026-08-07", 6258.77)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)
    storage = await get_storage_service()
    with patch("services.trading.index_series.yf.Ticker", return_value=tk), patch.object(
        type(storage), "upsert_index_daily", AsyncMock(return_value=0)
    ):
        assert await refresh_index_daily() is None


@pytest.mark.asyncio
async def test_refresh_uses_the_designed_source_label():
    hist = _fake_history([("2026-08-07", 6258.77)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)
    storage = await get_storage_service()
    captured = {}

    # ⚠️ 클래스 메서드를 갈아끼우므로 `self`가 첫 인자로 들어온다.
    async def _spy(self, rows, source):
        captured["source"] = source
        return len(rows)

    with patch("services.trading.index_series.yf.Ticker", return_value=tk), patch.object(
        type(storage), "upsert_index_daily", _spy
    ):
        await refresh_index_daily()
    assert captured["source"] == INDEX_SOURCE


# ---- 지연 경고 래치 (2026-08-12) ----
#
# `index_daily`는 08:05 수집이 Yahoo의 전일 종가 반영보다 일러 **상시 1거래일
# 뒤진다**. 그래서 이 경고는 장중 감시 루프에서 5분마다, 하루 288회 찍혔다.
# 매번 같은 말을 하는 경고는 정보가 아니라 소음이고, 진짜 수집 실패가 났을 때
# 구별되지 않는다. 같은 (latest, expected) 조합에 대해서는 한 번만 남긴다.


def _count_lag_warnings(idx, monkeypatch):
    """`logger.warning` 호출 중 index_series_lagging 건수만 센다."""
    calls = []
    real = idx.logger.warning

    def _spy(event, *a, **k):
        if event == "index_series_lagging":
            calls.append((event, k))
        return real(event, *a, **k) if False else None

    monkeypatch.setattr(idx.logger, "warning", _spy)
    return calls


def test_lagging_warning_is_latched_while_the_gap_is_unchanged(monkeypatch):
    """같은 지연 상태가 이어지는 동안에는 한 번만 경고한다."""
    import services.trading.index_series as idx

    idx._LAST_LAG_LOG_KEY = None
    calls = _count_lag_warnings(idx, monkeypatch)

    for _ in range(3):
        lag = idx.evaluate_series_lag(
            "2026-08-10", date(2026, 8, 12), holiday_service=_FakeCalendar()
        )
        assert lag.lagging is True  # 판정 자체는 매번 정상이어야 한다

    assert len(calls) == 1


def test_lagging_warning_fires_again_when_the_gap_changes(monkeypatch):
    """래치는 **침묵**이 아니다 — 지연이 깊어지면 다시 말해야 한다.

    이게 없으면 '하루 뒤짐'으로 한 번 찍힌 뒤 '사흘 뒤짐'이 되어도 조용하다."""
    import services.trading.index_series as idx

    idx._LAST_LAG_LOG_KEY = None
    calls = _count_lag_warnings(idx, monkeypatch)

    idx.evaluate_series_lag(
        "2026-08-10", date(2026, 8, 12), holiday_service=_FakeCalendar()
    )
    idx.evaluate_series_lag(  # 같은 latest, 하루 지난 today → 지연이 깊어졌다
        "2026-08-10", date(2026, 8, 13), holiday_service=_FakeCalendar()
    )

    assert len(calls) == 2
