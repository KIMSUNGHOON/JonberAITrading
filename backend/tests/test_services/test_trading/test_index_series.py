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


# ---- 장중 재수집과 당일 진행 봉 (2026-08-12) ----
#
# 08:05 수집만으로는 전일 종가를 못 받는다 — Yahoo가 그 시각에 아직 안 낸다
# (2026-08-12 실측: 08:12에 없고 12:28에 있음). 그래서 09:30 재수집을 붙이는데,
# 장중에 부르면 히스토리에 **오늘 진행 봉**이 섞여 온다(12:28 6,629.37 →
# 12:33 6,626.09, 움직이는 중). 그것을 확정 종가로 upsert하면 변동성 계산이
# 오염되고, 장 마감 후에도 그 값이 남는다. 오늘 날짜는 저장하지 않는다.


@pytest.mark.asyncio
async def test_refresh_skips_todays_in_progress_bar():
    hist = _fake_history([("2026-08-11", 6345.53), ("2026-08-12", 6626.09)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)
    with patch("services.trading.index_series.yf.Ticker", return_value=tk):
        n = await refresh_index_daily(today=date(2026, 8, 12))

    assert n == 1
    storage = await get_storage_service()
    got = await storage.get_recent_index_closes()
    assert [d for d, _ in got] == ["2026-08-11"]


@pytest.mark.asyncio
async def test_refresh_writes_nothing_when_only_todays_bar_is_available():
    """개장 직후 재수집처럼 확정 행이 하나도 없으면 아무것도 쓰지 않는다 —
    빈 upsert를 성공으로 보고하면 '수집됐다'는 거짓 신호가 된다."""
    hist = _fake_history([("2026-08-12", 6626.09)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)
    with patch("services.trading.index_series.yf.Ticker", return_value=tk):
        assert await refresh_index_daily(today=date(2026, 8, 12)) is None

    storage = await get_storage_service()
    assert await storage.get_recent_index_closes() == []


# ---- 09:30 재수집 스케줄러 (2026-08-12) ----


@pytest.mark.asyncio
async def test_index_refresh_scheduler_registers_a_weekday_job():
    """08:05 수집이 전일 종가를 놓치는 것을 09:30 재수집이 메운다.

    2026-08-12 실측: 08:12에 08-11 종가가 없고 12:28에 있었다 — 08:05 단독
    수집은 구조적으로 항상 1거래일 뒤진다.

    ⚠️ async인 이유: `AsyncIOScheduler.start()`가 실행 중인 이벤트 루프를
    요구한다. 동기 테스트로 쓰면 `no running event loop`로 죽어 **아무것도
    검증하지 않은 채** never-raise 경로만 타게 된다(실제로 처음에 그랬다).
    """
    import services.trading.index_series as idx

    idx._refresh_scheduler = None
    sched = idx.start_index_refresh_scheduler(hour=9, minute=30)
    try:
        assert sched is not None
        jobs = sched.get_jobs()
        assert [j.id for j in jobs] == ["index_daily_refresh"]
        assert "day_of_week='mon-fri'" in str(jobs[0].trigger)
        assert "hour='9'" in str(jobs[0].trigger)
        assert "minute='30'" in str(jobs[0].trigger)
    finally:
        if sched is not None:
            sched.shutdown(wait=False)
        idx._refresh_scheduler = None


@pytest.mark.asyncio
async def test_index_refresh_scheduler_never_raises():
    """기동 경로에서 부른다 — 실패가 앱을 죽이면 안 된다.

    루프가 있는 async 컨텍스트에서 돌려야 patch한 예외가 실제로 발동한다.
    동기 테스트였다면 루프 부재로 None이 나와 **patch 없이도 통과**했다.
    """
    import services.trading.index_series as idx

    idx._refresh_scheduler = None
    try:
        with patch(
            "apscheduler.schedulers.asyncio.AsyncIOScheduler.start",
            side_effect=RuntimeError("boom"),
        ):
            assert idx.start_index_refresh_scheduler() is None
    finally:
        idx._refresh_scheduler = None


# ---- 토스 소스 (T2, 2026-08-12) ----
#
# yfinance는 08:05 수집 시점에 전일 종가를 안 내놔 index_daily가 상시
# 1거래일 뒤졌다(그래서 259ab7a로 09:30 재수집을 붙였다). 토스는 전일은
# 물론 **당일 종가까지** 준다 — 실호출 확인: 08-12 6579.04 / 08-11 6345.53.
#
# ⚠️ 그래서 당일 진행 봉 제외 가드가 토스 경로에도 반드시 걸려야 한다.
# 장중에 호출하면 오늘 봉이 확정 전이다.


class _FakeToss:
    def __init__(self, rows, boom=None):
        self.rows = rows
        self.boom = boom
        self.calls = 0
        self.enabled = True

    async def get_index_candles(self, symbol="KOSPI", *, interval="1d", count=100):
        self.calls += 1
        if self.boom:
            raise self.boom
        return self.rows


@pytest.mark.asyncio
async def test_toss_source_is_preferred_and_labeled(tmp_path):
    """토스가 성공하면 그 값을 쓰고 source도 토스로 남긴다 — 나중에
    '어느 소스에서 온 행인지'를 원장에서 구별할 수 있어야 한다."""
    import services.trading.index_series as idx

    toss = _FakeToss([("2026-08-11", 6345.53), ("2026-08-10", 6299.66)])
    n = await refresh_index_daily(today=date(2026, 8, 12), toss=toss)

    assert n == 2
    assert toss.calls == 1
    storage = await get_storage_service()
    got = await storage.get_recent_index_closes(limit=5)
    assert dict(got)["2026-08-11"] == pytest.approx(6345.53)


@pytest.mark.asyncio
async def test_toss_todays_bar_is_still_excluded(tmp_path):
    """토스는 당일 봉도 준다. 259ab7a의 제외 가드가 여기에도 걸려야 한다."""
    import services.trading.index_series as idx

    toss = _FakeToss([
        ("2026-08-12", 6579.04),   # 오늘 — 장중이면 확정 전이다
        ("2026-08-11", 6345.53),
    ])
    n = await refresh_index_daily(today=date(2026, 8, 12), toss=toss)

    assert n == 1
    storage = await get_storage_service()
    got = dict(await storage.get_recent_index_closes(limit=5))
    assert "2026-08-12" not in got
    assert got["2026-08-11"] == pytest.approx(6345.53)


@pytest.mark.asyncio
async def test_toss_failure_falls_back_to_yfinance(tmp_path):
    """토스가 죽어도 수집이 멈추면 안 된다 — yfinance가 폴백이다.
    403(IP 화이트리스트)도 여기로 떨어지지만, 클라이언트가 전용 예외를
    올리므로 로그에서 구별된다."""
    import services.trading.index_series as idx

    toss = _FakeToss([], boom=RuntimeError("403 edge-blocked"))
    hist = _fake_history([("2026-08-11", 6345.53)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)

    with patch("services.trading.index_series.yf.Ticker", return_value=tk):
        n = await refresh_index_daily(today=date(2026, 8, 12), toss=toss)

    assert n == 1
    assert tk.history.called


@pytest.mark.asyncio
async def test_no_toss_client_uses_yfinance(tmp_path):
    """`toss=None`이면 기존 동작 그대로 — 회귀 없음."""
    hist = _fake_history([("2026-08-11", 6345.53)])
    tk = MagicMock()
    tk.history = MagicMock(return_value=hist)

    with patch("services.trading.index_series.yf.Ticker", return_value=tk):
        n = await refresh_index_daily(today=date(2026, 8, 12))

    assert n == 1
