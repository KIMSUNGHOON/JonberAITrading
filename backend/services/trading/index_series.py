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
from datetime import date, datetime
from typing import Optional

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
    try:
        latest = datetime.strptime(latest_trade_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return True
    return (today - latest).days > INDEX_SERIES_MAX_AGE_DAYS


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
) -> Optional[int]:
    """최근 `lookback_days`의 KOSPI 종가를 upsert하고 쓴 행 수를 돌려준다.
    never-raise -- 실패는 `None`.

    ⚠️ `upsert_index_daily`는 실패-무해(0 반환)라 반환값을 검사하지 않으면
    쓰기가 실패해도 성공을 보고하게 된다.
    """
    try:
        rows = await asyncio.to_thread(_fetch_history, lookback_days)
    except Exception as e:
        logger.warning("index_series_fetch_failed", error=str(e))
        return None

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
