"""
Discovery Ledger (DS-3): candidate persistence + trading-day-accurate
forward-return backfill + strategy-tag performance summary.

Consumers:
- DS-4 writes candidate rows via StorageService.save_discovery_candidates
  (this module doesn't write candidates itself).
- DS-5's EOD chain calls backfill_forward_returns once per trading day
  with a price_lookup built from that day's discovery scan factor_json
  close_price (ka10001 cur_prc — an EOD run, so "current price" and
  "close price" are equivalent). No extra API calls happen here.
- get_discovery_performance feeds an EOD/strategy-review surface with a
  per-strategy-tag candidates/promoted/avg-forward-return/hit-rate
  breakdown.

Trading-day semantics (spec §4): "N일 경과"는 캘린더일이 아니라 KRX
거래일이다 — services/krx_holiday의 기존 서비스(HolidayStorage 기반
is_trading_day/get_trading_days_in_range)를 그대로 재사용하고, 이
모듈은 거래일 판정 로직을 자체 재구현하지 않는다.

Exact-slot semantics: 후보의 trade_date로부터 정확히 1/5/20 거래일이
지난 날에만 해당 fwd_Nd 슬롯을 채운다(>= 아님). backfill_forward_returns
는 EOD 체인에서 거래일마다 한 번씩 불리는 것을 전제로 하므로, 이 함수가
매 거래일 정상 호출되는 한 elapsed는 1,2,3,...와 같이 하루씩 증가하며
정확히 1/5/20을 지나간다. 만약 어느 거래일에 EOD 체인이 통째로 스킵되어
그 "정확히 N거래일째" 호출이 아예 일어나지 않으면, 다음 호출 시점의
elapsed는 이미 N을 넘어서 있으므로 그 슬롯은 영구히 NULL로 남는다 —
이는 의도된 동작이며 근사 채움(느슨한 매칭)으로 봉합하지 않는다(spec 요구).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

_UNKNOWN_STRATEGY_TAG = "unknown"


def _parse_date(value: Any) -> date:
    """"YYYY-MM-DD" (or a date/datetime already) -> date. Raises ValueError
    on anything else -- callers decide whether to skip or propagate."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _get_default_holiday_service():
    """Lazy import so importing this module never touches krx_holiday's
    apscheduler/aiohttp dependencies unless a caller actually needs the
    default (production) holiday service."""
    from services.krx_holiday import get_holiday_service_sync

    return get_holiday_service_sync()


def _trading_days_elapsed(holiday_service, start: date, end: date) -> int:
    """Trading days strictly after `start` through `end`, inclusive of
    `end`. Assumes `start` is itself a trading day (discovery candidates
    are only ever recorded on a trading day, since the discovery scan
    only runs then) -- under that assumption `get_trading_days_in_range`
    returns `start` as its first element, which this subtracts back out.

    Examples: start==end -> 0. start -> next trading day -> 1. A weekend
    or KRX holiday between start and end is excluded by
    get_trading_days_in_range itself (this function does no date-math of
    its own), so a Friday candidate reaches elapsed==1 on the following
    Monday, not on Saturday.
    """
    trading_days = holiday_service.get_trading_days_in_range(start, end)
    if trading_days and trading_days[0] == start:
        return len(trading_days) - 1
    return len(trading_days)


def _trading_day_n_before(holiday_service, end: date, n: int) -> date:
    """The date exactly `n` trading days before `end`, walking backward one
    trading day at a time via the holiday service's own
    get_previous_trading_day (an independent primitive from
    get_trading_days_in_range/_trading_days_elapsed above, but consistent
    with it: for d = _trading_day_n_before(svc, end, n),
    _trading_days_elapsed(svc, d, end) == n whenever `end` is itself a
    trading day -- which it always is here, since callers only ever pass
    an EOD run's own trade_date).

    Used to scope backfill_forward_returns' candidate query to exactly the
    three dates whose fwd_1d/fwd_5d/fwd_20d slot could possibly become
    newly-elapsed today, instead of pulling an unbounded (and, at
    real-world ledger volume, budget-exhausting -- see module docstring
    and the DS final-review fix) slice of the whole table.
    """
    d = end
    for _ in range(n):
        d = holiday_service.get_previous_trading_day(d)
    return d


# 따라잡기가 거슬러 올라가는 최대 거래일. `fwd_20d`가 가장 먼 슬롯이라
# 그보다 오래된 행은 어떤 슬롯도 새로 채울 게 없다.
_MAX_FWD_HORIZON = 20


def _trading_day_n_after(holiday_service, start: date, n: int) -> Optional[date]:
    """`start`로부터 정확히 `n` 거래일 뒤. 범위를 못 만들면 None.

    `_trading_day_n_before`의 반대 방향이고, 같은
    `get_trading_days_in_range` 프리미티브를 쓴다(테스트 헬퍼는
    `get_next_trading_day`를 쓰므로 둘은 여전히 독립 경로다).
    역일 여유 `n*3+10`은 최장 연휴(설·추석)를 넉넉히 덮는다.
    """
    try:
        days = holiday_service.get_trading_days_in_range(
            start, start + timedelta(days=n * 3 + 10)
        )
    except Exception:
        return None
    if not days or days[0] != start or len(days) <= n:
        return None
    return days[n]


async def _catch_up_missed_slots(
    storage,
    end_date: date,
    holiday_service,
    close_on_date,
    limit: int,
) -> int:
    """EOD 체인이 걸러서 영구히 비어버린 슬롯을 뒤늦게 채운다.

    2026-08-06에 체인이 안 돌아 07-30분 `fwd_5d`와 08-05분 `fwd_1d`가
    비었다 -- `elapsed == N` 정확 일치라 다음날은 N+1이 되어 어떤 분기에도
    안 걸린다.

    ⚠️ **오늘 종가를 쓰면 안 된다.** `fwd_5d`는 "5거래일째 수익률"이라
    뒤늦게 채울 때도 **그날 종가**로 계산해야 한다. `close_on_date`가
    그 값을 돌려주지 못하면 **채우지 않는다** -- 비어 있는 편이 의미가
    바뀐 값보다 낫다.
    """
    oldest = _trading_day_n_before(holiday_service, end_date, _MAX_FWD_HORIZON)
    rows = await storage.get_discovery_candidates(
        since_trade_date=oldest.isoformat(), unfilled_fwd_only=True, limit=20_000
    )

    filled = 0
    for row in rows:
        if filled >= limit:
            logger.info("discovery_fwd_catchup_limited", limit=limit)
            break

        ticker = row.get("ticker")
        close_price = row.get("close_price")
        row_trade_date = row.get("trade_date")
        if not ticker or not row_trade_date or not close_price:
            continue
        try:
            start_date = _parse_date(row_trade_date)
        except ValueError:
            continue

        elapsed = _trading_days_elapsed(holiday_service, start_date, end_date)

        for n, slot in ((1, "fwd_1d"), (5, "fwd_5d"), (20, "fwd_20d")):
            # `>` 로 좁힌다 -- `==`는 위의 정상 경로가 price_lookup으로
            # 이미 처리했다(그쪽이 API 호출 0회라 항상 우선한다).
            if elapsed <= n or row.get(slot) is not None:
                continue
            day_n = _trading_day_n_after(holiday_service, start_date, n)
            if day_n is None:
                continue
            try:
                px = await close_on_date(ticker, day_n.isoformat())
            except Exception as e:
                logger.warning(
                    "discovery_fwd_catchup_lookup_failed",
                    ticker=ticker, day=day_n.isoformat(), error=str(e),
                )
                continue
            if not px or px <= 0:
                continue
            ok = await storage.update_discovery_forward_returns(
                row["id"], **{slot: (px / close_price) - 1.0}
            )
            if ok:
                filled += 1
                logger.info(
                    "discovery_fwd_catchup_filled",
                    ticker=ticker, slot=slot,
                    trade_date=row_trade_date, day_n=day_n.isoformat(),
                    elapsed=elapsed,
                )
    return filled


async def backfill_forward_returns(
    storage,
    price_lookup: dict[str, float],
    trade_date: str,
    holiday_service=None,
    close_on_date=None,
    catchup_limit: int = 50,
) -> int:
    """
    Fill in fwd_1d/fwd_5d/fwd_20d on past discovery_candidates rows whose
    trading-day distance from their own trade_date to `trade_date` (i.e.
    "today", the day this is called) exactly matches 1, 5, or 20.

    Args:
        storage: a StorageService instance (already initialized or not --
            its methods self-initialize).
        price_lookup: {ticker: current_price} for tickers scanned today.
            Built by the caller (DS-5) from today's discovery scan
            factor_json close_price -- this module makes zero extra API
            calls. A candidate ticker absent from this dict is skipped
            (not an error -- it just wasn't in today's discovery sweep).
        trade_date: "YYYY-MM-DD" for "today" (the EOD run date this call
            represents), used as the elapsed-trading-days end date.
        holiday_service: optional KRXHolidayService-like object exposing
            get_trading_days_in_range(start, end); defaults to the
            production singleton (services.krx_holiday.
            get_holiday_service_sync()). Tests should inject a
            tmp-seeded instance instead of hitting the real one.

    Returns:
        Number of fwd_Nd slots actually filled across all candidates.
    """
    if holiday_service is None:
        holiday_service = _get_default_holiday_service()

    end_date = _parse_date(trade_date)

    # Scope the query to exactly the three dates that could possibly have
    # a newly-elapsed 1/5/20-trading-day slot today, pushed down as SQL
    # trade_date IN (...) -- see _trading_day_n_before. This is what makes
    # `limit` below a pure safety net rather than the operative bound: at
    # real-world ledger volume (~2,500 rows/day across the whole
    # universe, quality-dropped rows included), an unscoped
    # created_at-DESC/limit=5000 query only ever sees the most recent ~2
    # days, silently starving fwd_5d/fwd_20d forever (the bug this fixes).
    scoped_dates = [
        _trading_day_n_before(holiday_service, end_date, n).isoformat()
        for n in (1, 5, 20)
    ]

    candidates = await storage.get_discovery_candidates(
        trade_dates=scoped_dates, unfilled_fwd_only=True, limit=20_000
    )

    filled = 0
    for row in candidates:
        ticker = row.get("ticker")
        close_price = row.get("close_price")
        row_trade_date = row.get("trade_date")

        if not ticker or not row_trade_date or not close_price:
            continue
        if ticker not in price_lookup:
            continue

        try:
            start_date = _parse_date(row_trade_date)
        except ValueError:
            continue

        elapsed = _trading_days_elapsed(holiday_service, start_date, end_date)

        slot: Optional[str] = None
        if elapsed == 1 and row.get("fwd_1d") is None:
            slot = "fwd_1d"
        elif elapsed == 5 and row.get("fwd_5d") is None:
            slot = "fwd_5d"
        elif elapsed == 20 and row.get("fwd_20d") is None:
            slot = "fwd_20d"

        if slot is None:
            continue

        fwd_value = (price_lookup[ticker] / close_price) - 1.0
        ok = await storage.update_discovery_forward_returns(
            row["id"], **{slot: fwd_value}
        )
        if ok:
            filled += 1

    # 놓친 슬롯 따라잡기. `close_on_date`가 없으면 건너뛴다 -- 과거 종가를
    # 구할 방법이 없는데 오늘 종가로 대신 채우면 원장이 조용히 오염된다.
    if close_on_date is not None:
        filled += await _catch_up_missed_slots(
            storage, end_date, holiday_service, close_on_date, catchup_limit
        )

    return filled


def _top_strategy_tag(strategy_scores_json: Optional[str]) -> str:
    """Strategy tag with the highest (pre-regime-weight) raw score in a
    candidate's strategy_scores_json (compute_strategy_scores' output
    shape: {"momentum": f, "pullback": f, "flow": f, "meanrev": f, ...}).
    Falls back to _UNKNOWN_STRATEGY_TAG on missing/malformed/empty JSON
    so one bad row never breaks the whole summary."""
    if not strategy_scores_json:
        return _UNKNOWN_STRATEGY_TAG

    try:
        scores = json.loads(strategy_scores_json)
    except (TypeError, ValueError):
        return _UNKNOWN_STRATEGY_TAG

    if not isinstance(scores, dict):
        return _UNKNOWN_STRATEGY_TAG

    numeric_scores = {
        k: v for k, v in scores.items() if isinstance(v, (int, float))
    }
    if not numeric_scores:
        return _UNKNOWN_STRATEGY_TAG

    return max(numeric_scores, key=numeric_scores.get)


async def get_discovery_performance(storage, days: int = 14) -> dict[str, Any]:
    """
    Per-strategy-tag performance summary over the last `days` calendar
    days of discovery_candidates rows (grouped by each candidate's top-
    contributing strategy tag -- see _top_strategy_tag).

    Args:
        storage: a StorageService instance.
        days: lookback window in calendar days from today, compared
            against each row's trade_date.

    Returns:
        {strategy_tag: {"candidates": int, "promoted": int,
         "avg_fwd_1d": float|None, "avg_fwd_5d": float|None,
         "hit_rate_5d": float|None}}. avg_fwd_1d/avg_fwd_5d/hit_rate_5d
        are computed only over candidates whose corresponding fwd slot is
        already backfilled (None if none are). Empty ledger (or nothing
        in the window) returns {} -- never raises.
    """
    cutoff = date.today() - timedelta(days=days)

    try:
        candidates = await storage.get_discovery_candidates(
            since_trade_date=cutoff.isoformat(), limit=100_000
        )
    except Exception as e:
        logger.error("discovery_performance_fetch_failed", error=str(e))
        return {}

    if not candidates:
        return {}

    buckets: dict[str, dict[str, Any]] = {}

    for row in candidates:
        if not row.get("trade_date"):
            continue

        tag = _top_strategy_tag(row.get("strategy_scores_json"))
        bucket = buckets.setdefault(
            tag,
            {
                "candidates": 0,
                "promoted": 0,
                "_fwd_1d_sum": 0.0,
                "_fwd_1d_n": 0,
                "_fwd_5d_sum": 0.0,
                "_fwd_5d_n": 0,
                "_fwd_5d_hits": 0,
            },
        )

        bucket["candidates"] += 1
        if row.get("promoted"):
            bucket["promoted"] += 1

        fwd_1d = row.get("fwd_1d")
        if fwd_1d is not None:
            bucket["_fwd_1d_sum"] += fwd_1d
            bucket["_fwd_1d_n"] += 1

        fwd_5d = row.get("fwd_5d")
        if fwd_5d is not None:
            bucket["_fwd_5d_sum"] += fwd_5d
            bucket["_fwd_5d_n"] += 1
            if fwd_5d > 0:
                bucket["_fwd_5d_hits"] += 1

    summary: dict[str, Any] = {}
    for tag, bucket in buckets.items():
        n1, n5 = bucket["_fwd_1d_n"], bucket["_fwd_5d_n"]
        summary[tag] = {
            "candidates": bucket["candidates"],
            "promoted": bucket["promoted"],
            "avg_fwd_1d": (bucket["_fwd_1d_sum"] / n1) if n1 else None,
            "avg_fwd_5d": (bucket["_fwd_5d_sum"] / n5) if n5 else None,
            "hit_rate_5d": (bucket["_fwd_5d_hits"] / n5) if n5 else None,
        }

    return summary
