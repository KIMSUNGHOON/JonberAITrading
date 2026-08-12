"""KOSPI 일별 종가 시계열 — 변동성 계산 전용 입력.

2026-08-07 이전에는 `regime_snapshot`의 지수 컬럼을 썼는데, 그 행은
**EOD 체인이 도는 날에만** 생겼다. 체인은 장 마감 스케줄 틱이고
따라잡기가 없어, 그 순간 프로세스가 내려가 있으면 그날 데이터가
영구히 유실됐다(07-21·08-06 실제 누락). `annualized_vol`이 최근 20
**행**을 쓰므로 행과 거래일이 1:1이 아니면 창이 조용히 넓어진다.

여기서는 **매 실행이 창 전체를 다시 upsert**한다 — 구멍이 자가치유되고
따라잡기 로직이 필요 없다.

설계: docs/superpowers/specs/2026-08-07-volatility-correction-design.md
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

import structlog
import yfinance as yf

from services.storage_service import get_storage_service

logger = structlog.get_logger(__name__)

INDEX_TICKER: str = "^KS11"
INDEX_SOURCE: str = "yfinance:^KS11"
INDEX_LOOKBACK_DAYS: int = 40

# 최신 행이 이보다 오래되면 시계열을 못 믿는다. 7역일인 이유: 설·추석
# 연휴(최대 5거래일 공백)에서 오탐이 나지 않으면서 수집이 죽은 것은
# 일주일 안에 잡는다. 거래일 계산이 필요 없어 휴장일 서비스에 의존하지
# 않는다(순수 함수 유지).
INDEX_SERIES_MAX_AGE_DAYS: int = 7


def closes_to_returns(closes: list[float]) -> list[float]:
    """종가 시계열(시간 오름차순) → 일간 등락률(%). 길이 n-1.

    0·비유한 종가가 끼면 **그 쌍만 건너뛴다** -- 조용히 0을 만들면
    "안 움직였다"와 "못 읽었다"가 구별되지 않는다.
    """
    out: list[float] = []
    for i in range(1, len(closes or [])):
        prev, cur = closes[i - 1], closes[i]
        if (
            not prev
            or not cur
            or not math.isfinite(prev)
            or not math.isfinite(cur)
        ):
            continue
        out.append((cur / prev - 1.0) * 100.0)
    return out


def is_series_stale(latest_trade_date: str, today: date) -> bool:
    """최신 행이 `INDEX_SERIES_MAX_AGE_DAYS` 역일보다 오래됐으면 True.

    파싱이 실패하면 **True**(노후로 취급) -- 모르는 것을 신선하다고
    보면 안 된다.
    """
    latest = _parse_trade_date(latest_trade_date)
    if latest is None:
        return True
    return (today - latest).days > INDEX_SERIES_MAX_AGE_DAYS


def _parse_trade_date(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# -------------------------------------------
# 거래일 기준 지연 검사 (2026-08-11)
#
# `is_series_stale`은 7**역일**이라 거래일로 치면 약 5일이다 -- 거래일
# 하루가 통째로 빠져도 아무 신호가 없다. 2026-08-10(월) KOSPI 종가가
# Yahoo에 안 올라온 날, 수집은 성공했고(`index_series_refreshed
# rows=39 last=2026-08-07`) `degraded`는 `[]`였다. 공백을 우연히
# 조회하다 발견했다.
#
# ⚠️ 이 검사는 **관측 신호**다 -- `m_vol`을 바꾸지 않는다. 거래일 하루
# 뒤진 것이 20일 변동성을 의미 있게 바꾸지 않기 때문이다. 배수를 바꾸는
# 것은 `is_series_stale`(7역일)과 표본 부족(`annualized_vol` → None)이다.
# -------------------------------------------


@dataclass(frozen=True)
class SeriesLag:
    """시계열이 직전 거래일보다 뒤졌는지.

    `lagging`은 **3-상태**다 -- `True`(지연) / `False`(최신) /
    `None`(판정 불가). 달력 조회 실패를 `False`로 접으면 달력이 죽은 날
    공백이 영원히 안 보인다("오류와 부재를 합치지 않는다").
    """

    lagging: Optional[bool]
    latest: Optional[date]
    expected: Optional[date]          # 직전 거래일
    trading_days_behind: Optional[int]


_LAG_UNKNOWN = SeriesLag(lagging=None, latest=None, expected=None,
                         trading_days_behind=None)

# 마지막으로 경고를 남긴 (latest, expected) 조합. 같은 조합이 이어지는 동안은
# 침묵한다 -- `evaluate_series_lag`는 08:05 판정뿐 아니라 **장중 감시 루프에서도
# 5분마다** 호출되는데, `index_daily`는 08:05 수집이 Yahoo의 전일 종가 반영보다
# 일러 상시 1거래일 뒤진다. 2026-08-12에 하루 288회 페이스로 같은 줄이 찍혔다.
# 매번 같은 말을 하는 경고는 정보가 아니라 소음이고, 진짜 수집 실패가 났을 때
# 구별되지 않는다. 지연이 **깊어지면** 키가 바뀌므로 다시 말한다 -- 래치는
# 침묵이 아니다.
_LAST_LAG_LOG_KEY: Optional[tuple] = None


def _default_holiday_service():
    """KRX 거래일 달력. **lazy import** -- `services/discovery/ledger.py:53`과
    같은 이유로, 이 모듈을 import하는 것만으로 krx_holiday의
    apscheduler/aiohttp 의존이 딸려오지 않게 한다."""
    from services.krx_holiday import get_holiday_service_sync

    return get_holiday_service_sync()


def evaluate_series_lag(
    latest_trade_date: str,
    today: date,
    holiday_service: Optional[Any] = None,
) -> SeriesLag:
    """`index_daily` 최신 행이 **직전 거래일**보다 이전이면 지연이다.

    never-raise -- 달력을 못 읽으면 `lagging=None`(모름)을 돌려준다.
    노출도 계산이 이 검사 때문에 멈추면 관측 신호가 방어를 죽이는 셈이다.

    직전 거래일을 기준으로 삼는 이유: 오늘 종가는 장이 닫히기 전에는
    존재하지 않는다. 08:05 판정 시점에 있어야 할 최신 행은 어제(거래일
    기준)의 종가다. 그래서 월요일 아침의 금요일 종가나 연휴 다음날의
    연휴 전 종가는 **지연이 아니다** -- KRX 달력이 그 판단을 한다.
    """
    latest = _parse_trade_date(latest_trade_date)
    if latest is None:
        logger.warning("index_series_lag_unknown",
                       reason="unparseable", latest=str(latest_trade_date))
        return _LAG_UNKNOWN

    try:
        svc = holiday_service if holiday_service is not None else _default_holiday_service()
        expected = svc.get_previous_trading_day(today)
        if latest >= expected:
            return SeriesLag(lagging=False, latest=latest, expected=expected,
                             trading_days_behind=0)
        # 빠진 거래일 수 = [latest, expected] 구간의 거래일 수 - 1(latest 자신).
        # `services/discovery/ledger.py::_trading_days_elapsed`와 같은 관행.
        days = svc.get_trading_days_in_range(latest, expected)
        behind = len(days) - 1 if days and days[0] == latest else len(days)
    except Exception as e:
        logger.warning("index_series_lag_unknown", reason="calendar_failed",
                       latest=latest.isoformat(), error=str(e))
        return _LAG_UNKNOWN

    global _LAST_LAG_LOG_KEY
    log_key = (latest, expected)
    if _LAST_LAG_LOG_KEY != log_key:
        _LAST_LAG_LOG_KEY = log_key
        logger.warning(
            "index_series_lagging",
            latest=latest.isoformat(),
            expected=expected.isoformat(),
            trading_days_behind=behind,
        )
    return SeriesLag(lagging=True, latest=latest, expected=expected,
                     trading_days_behind=behind)


def _fetch_history(lookback_days: int) -> list[tuple[str, float]]:
    """동기 yfinance 호출 — 호출자가 `asyncio.to_thread`로 감싼다."""
    hist = yf.Ticker(INDEX_TICKER).history(period=f"{lookback_days}d")
    if hist is None or len(hist) == 0:
        return []
    return [
        (str(idx)[:10], float(close))
        for idx, close in zip(hist.index, hist["Close"])
        if close is not None and math.isfinite(float(close))
    ]


async def refresh_index_daily(
    lookback_days: int = INDEX_LOOKBACK_DAYS,
    today: Optional[date] = None,
) -> Optional[int]:
    """최근 `lookback_days`의 KOSPI 종가를 upsert하고 쓴 행 수를 돌려준다.
    never-raise -- 실패는 `None`.

    **오늘 날짜 행은 저장하지 않는다.** 장중에 부르면(09:30 재수집)
    yfinance 히스토리에 아직 확정되지 않은 **진행 봉**이 섞여 온다
    (2026-08-12 실측: 12:28 6,629.37 → 12:33 6,626.09). 그것을 확정 종가로
    굳히면 변동성 계산이 오염되고 장 마감 후에도 틀린 값이 남는다.
    08:05 수집은 장 시작 전이라 이 문제가 없었다 -- 장중 재수집을 붙이면서
    생긴 위험이라 여기서 막는다.

    `today`는 테스트가 날짜를 고정하려고 주입한다(`evaluate_series_lag`와
    같은 관행). 프로덕션은 항상 생략한다.

    ⚠️ `upsert_index_daily`는 실패-무해(0 반환)라 반환값을 검사하지 않으면
    쓰기가 실패해도 성공을 보고하게 된다.
    """
    try:
        rows = await asyncio.to_thread(_fetch_history, lookback_days)
    except Exception as e:
        logger.warning("index_series_fetch_failed", error=str(e))
        return None

    cutoff = (today or date.today()).isoformat()
    intraday = [d for d, _ in rows if d >= cutoff]
    if intraday:
        rows = [(d, c) for d, c in rows if d < cutoff]
        logger.info("index_series_intraday_bar_skipped", dates=intraday)

    if not rows:
        logger.warning("index_series_empty", ticker=INDEX_TICKER)
        return None

    try:
        storage = await get_storage_service()
        written = await storage.upsert_index_daily(rows, source=INDEX_SOURCE)
    except Exception as e:
        logger.warning("index_series_persist_failed", error=str(e))
        return None

    if not written:
        logger.warning("index_series_persist_wrote_nothing", fetched=len(rows))
        return None

    logger.info(
        "index_series_refreshed",
        rows=written, first=rows[0][0], last=rows[-1][0],
    )
    return written


_refresh_scheduler = None


def start_index_refresh_scheduler(hour: int = 9, minute: int = 30):
    """평일 hour:minute에 `refresh_index_daily`를 한 번 더 돌린다.

    **왜 두 번 수집하나**: 08:05 사이클(`run_daily_regime_cycle`) 시점에는
    Yahoo가 아직 전일 KOSPI 종가를 내놓지 않는다. 2026-08-12 실측 --
    08:12 조회에 08-11 종가가 없고, 12:28 조회에는 있었다(6,345.53, 전날
    17:55에 본 값과 동일 = 확정치). 그래서 08:05 단독 수집은 구조적으로
    항상 1거래일 뒤지고, `index_series_lagging`이 **매일** 떴다.

    도착 시각을 08:12~12:28 구간까지만 좁혀 놓은 상태라 09:30은 보수적인
    추정이다. 놓치더라도 손해는 없다 -- 다음 날 08:05 수집이 어차피 40일치를
    통째로 다시 받는다. 이 잡은 "더 일찍 메운다"이지 "유일한 기회"가 아니다.

    ⚠️ 장중 호출이라 `refresh_index_daily`의 **당일 봉 제외**가 짝을 이룬다.
    그것 없이 이 스케줄러만 켜면 진행 봉이 확정치로 굳는다.

    `start_regime_scheduler`와 같은 형태 -- 기동 시 1회 호출, 실패해도 앱을
    죽이지 않는다.
    """
    global _refresh_scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    try:
        if _refresh_scheduler is not None:
            return _refresh_scheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            refresh_index_daily,
            CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute),
            id="index_daily_refresh",
            replace_existing=True,
        )
        scheduler.start()
        _refresh_scheduler = scheduler
        logger.info("index_refresh_scheduler_started", hour=hour, minute=minute)
        return scheduler
    except Exception as e:
        logger.warning("index_refresh_scheduler_failed", error=str(e))
        return None
