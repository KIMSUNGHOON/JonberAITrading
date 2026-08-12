"""Discovery EOD post-processing orchestrator (DS-5).

The single entry point the market-close chain
(services/trading/coordinator.py::ExecutionCoordinator._check_queue_on_
market_open) calls AFTER the existing 8-step chain's steps 3-7
(write_daily_snapshot -> run_eod_review -> run_strategy_consensus ->
wait_for_pending_trade_fill_writes -> reconcile_trade_ledger) and BEFORE
step 8 (_notify_eod_summary) -- see spec §3's chain reordering diagram.

`run_discovery_pipeline` batches the four DS-3/DS-4 post-scan steps into
one never-raise call:

  1. Build a same-day `{ticker: price}` lookup from the discovery scan
     the coordinator just ran (or attempted) this same tick.
  2. `ledger.backfill_forward_returns` -- fills fwd_1d/fwd_5d/fwd_20d on
     PAST candidates whose trading-day distance from their own trade_date
     to today is exactly 1/5/20 (DS-3). This step runs regardless of
     `scan_ok` -- a same-day price is still useful for backfilling
     yesterday's/last-week's/last-month's candidates even if TODAY's own
     scan timed out, as long as SOME of today's tickers were collected
     before the cutoff (see `_build_price_lookup`).
  3. Only when `scan_ok` is True: `ranker.rank_candidates` ->
     `ranker.llm_review_top` -> `ranker.promote_candidates` (DS-4) --
     regime-weighted ranking, top-N LLM suitability review, and the
     conservative promotion gate chain, which ALSO persists the full
     candidate batch (promoted/skipped/quality-excluded alike) to the
     `discovery_candidates` ledger via `storage.save_discovery_candidates`
     (owned by `promote_candidates` itself -- this module never writes
     that table directly). Skipped when `scan_ok` is False (spec §3: "타임
     아웃/실패=... 승격 스킵") -- a partial/incomplete scan session won't
     even be found as 'completed' by `rank_candidates` anyway (it filters
     on `scan_sessions.status = 'completed'`), so this branch is also a
     defensive short-circuit, not just an optimization.
  4. Return a summary dict for the EOD digest to consume (see
     services/trading/eod_digest.py::_build_discovery_section, which reads
     this same day's `discovery_candidates` ledger rows directly rather
     than this dict -- this return value exists for the coordinator/tests/
     callers that want a cheap one-shot summary without a second storage
     read).

Never-raise by design, mirroring every other EOD chain step
(eod_orchestrator.run_eod_review / strategy_orchestrator.
run_strategy_consensus): the WHOLE body is one try/except -> logger.error
-> None. This runs off the LIVE market-close scheduler tick (behind the
`DISCOVERY_ENABLED` kill switch) and must never break the rest of the
chain, especially not the final `_notify_eod_summary` step that runs
right after this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import structlog

from services.discovery.ledger import backfill_forward_returns
from services.discovery.enrich import enrich_fundamentals, enrich_news
from services.discovery.ranker import llm_review_top, promote_candidates, rank_candidates

logger = structlog.get_logger()

# Mirrors services/trading/regime.py::SCANNER_DB_PATH's own independent
# recomputation of the same physical path (both modules sit two levels
# under services/, so parent.parent.parent resolves to the backend root
# the same way) -- the background scanner's sqlite db is a cross-module
# read-only dependency several EOD-chain modules each point at
# separately, not a single shared import, per that module's own
# precedent.
SCANNER_DB_PATH = Path(__file__).parent.parent.parent / "data" / "scanner_results.db"

# Candidates above this many LLM-reviewed-and-passed suitability checks
# never even reach the top of the ranking in practice (daily/watch caps
# gate promotion well below this), but this bounds the LLM spend per EOD
# tick regardless of universe size. Mirrors ranker.llm_review_top's own
# default.
_LLM_REVIEW_TOP_N = 25


def _build_price_lookup(scanner: Any) -> dict[str, float]:
    """{ticker: today's discovery-scan price}, read from the LIVE scanner
    object's in-memory results rather than re-querying scanner_results.db.

    `BackgroundScanner._results` (exposed via the public `get_results()`)
    is populated progressively, one `ScanResult` per successfully-
    collected ticker, DURING the scan -- not only once the session reaches
    'completed'. `stop_scan()` (called by the coordinator on a discovery-
    scan timeout) does not clear it either. So this still yields whatever
    prices were actually collected before a timeout/cutoff even when
    `scan_ok` is False, which is exactly what backfill_forward_returns
    needs (spec §3: a timed-out scan should still attempt best-effort
    backfill). `ScanResult.current_price` is set for BOTH quality-filter-
    passed AND quality-filter-excluded tickers (as long as the underlying
    ka10001/ka10081 fetch itself succeeded) -- a candidate ticker that
    fails today's quality filter (e.g. a transient low-market-cap read)
    still gets its forward-return backfilled correctly, unlike reading
    close_price out of factor_json alone (quality-excluded rows never
    carry a close_price key there). Zero extra API calls either way --
    this is a pure read of state the coordinator's own scan trigger this
    same tick already populated.

    A non-positive price (failed fetch, current_price left at its 0
    default) is excluded -- a zero price would corrupt the forward-return
    ratio `backfill_forward_returns` computes (price_lookup[ticker] /
    close_price - 1.0).
    """
    lookup: dict[str, float] = {}
    try:
        results = scanner.get_results() or []
    except Exception as e:
        logger.warning("discovery_pipeline_price_lookup_failed", error=str(e))
        return lookup

    for r in results:
        ticker = getattr(r, "stk_cd", None)
        price = getattr(r, "current_price", None)
        if ticker and price and price > 0:
            lookup[ticker] = float(price)
    return lookup


async def _notify_promotions(candidates: Any, promote_summary: Any, trade_date: str) -> None:
    """Best-effort Telegram notice for today's discovery promotions
    (discovery-notify T2) -- covers BOTH the manual trigger (POST
    /trading/discovery/run) and the 15:30 EOD close-edge path, since both
    funnel through `run_discovery_pipeline`.

    Builds the `promoted` detail list `TelegramNotifier.
    send_discovery_promotion` expects ({"ticker","name","composite",
    "strategy","target"}) by looking each promoted ticker back up in the
    ranked `candidates` list. `strategy` is the candidate's top raw
    (un-weighted) strategy tag -- the same "highest score in raw_scores"
    computation as `ledger._top_strategy_tag`, just done directly on the
    in-memory dict instead of round-tripping through its JSON-serialized
    form. `target` is the candidate's discovery-scan close price (a watch
    reference level, not an order price -- discovery only ever promotes to
    the watchlist).

    No-op when nothing was promoted this run (skips the Telegram call
    entirely -- `send_discovery_promotion` itself also no-ops on an empty
    list, but checking here avoids the dict/sort work for the common
    zero-promotion tick).

    Never raises: gated behind its own try/except (network/Telegram
    failures are logged and swallowed) so a notification problem can never
    take down the promotion pipeline this runs immediately after -- mirrors
    every other best-effort Telegram call site in coordinator.py.
    """
    if not promote_summary.promoted:
        return

    try:
        by_ticker = {c.ticker: c for c in candidates}
        details: list[dict[str, Any]] = []
        for ticker in promote_summary.promoted:
            c = by_ticker.get(ticker)
            if c is None:
                continue
            top_strategy = max(c.raw_scores, key=c.raw_scores.get) if c.raw_scores else None
            details.append(
                {
                    "ticker": ticker,
                    "name": c.name or ticker,
                    "composite": c.composite,
                    "strategy": top_strategy,
                    "target": c.close_price,
                }
            )
        details.sort(key=lambda d: float(d.get("composite") or 0), reverse=True)

        daily_cap_waiting = sum(
            1 for reason in promote_summary.skipped.values() if reason == "daily_cap"
        )

        from services.telegram import get_telegram_notifier

        notifier = await get_telegram_notifier()
        if notifier.is_ready:
            await notifier.send_discovery_promotion(
                trade_date=trade_date, promoted=details, daily_cap_waiting=daily_cap_waiting
            )
    except Exception as e:
        logger.warning("discovery_promotion_notify_failed", trade_date=trade_date, error=str(e))


def _make_close_on_date(kiwoom):
    """`backfill_forward_returns(close_on_date=...)`에 넣을 과거 종가 조회기.

    `(ticker, "YYYY-MM-DD") -> 종가 | None`. 클라이언트가 없으면 `None`을
    돌려주는 함수를 만들어 준다 -- 그러면 따라잡기가 통째로 스킵되고
    기존 동작(정상 슬롯만 채움)이 그대로 남는다.

    **종목당 일봉 1회.** `get_daily_chart`는 600봉을 주므로 한 번 받아
    `{YYYYMMDD: 종가}`로 펼쳐 두면 그 종목의 fwd_1d/5d/20d를 전부 커버한다.
    Kiwoom은 ~1.4 req/s이고 2026-08-12에 22종 연속 조회만으로 ka10001
    초과가 실제로 났다 -- 슬롯마다 조회하면 그 한도를 바로 넘는다.

    never-raise: 조회가 실패하면 `None`. 호출자는 그것을 "채우지 않는다"로
    해석한다(비어 있는 편이 의미가 바뀐 값보다 낫다). EOD 체인 안에서
    도는 코드라 예외가 새면 뒤 단계가 통째로 죽는다.
    """
    cache: dict[str, dict[str, float]] = {}

    async def _close_on_date(ticker: str, day: str) -> Optional[float]:
        if kiwoom is None or not ticker or not day:
            return None
        if ticker not in cache:
            try:
                rows = await kiwoom.get_daily_chart(ticker)
            except Exception as e:
                logger.warning(
                    "discovery_fwd_daily_chart_failed", ticker=ticker, error=str(e)
                )
                cache[ticker] = {}
                return None
            table: dict[str, float] = {}
            for r in rows or []:
                dt = getattr(r, "dt", None)
                close = getattr(r, "clos_prc", None)
                if dt and close:
                    table[str(dt)] = float(close)
            cache[ticker] = table
        return cache[ticker].get(day.replace("-", ""))

    return _close_on_date


def _make_stock_info_fetch(kiwoom):
    """`enrich_fundamentals(fetch=...)`에 넣을 Kiwoom `ka10001` 조회기.

    클라이언트가 없으면 `None`을 돌려준다 -- 그러면 수집이 통째로 스킵되고
    기존 동작(재료 없이 지표만)이 그대로 남는다. 기본 구현을 몰래
    끌어오지 않는 것과 같은 이유로, 여기서 `None`을 돌려주는 것이
    "조용히 도는 것"보다 낫다.
    """
    if kiwoom is None:
        return None

    async def _fetch(ticker: str):
        return await kiwoom.get_stock_info(ticker)

    return _fetch


def _make_news_fetch():
    """`enrich_news(fetch=...)`에 넣을 네이버 뉴스 헤드라인 조회기.

    서비스를 못 만들면 `None` -- 수집을 건너뛸 뿐 파이프라인은 계속 돈다.
    `NewsService`는 한 번만 만들어 재사용한다(종목마다 새로 만들면 세션이
    쌓인다).
    """
    try:
        from services.news import create_news_service
    except Exception as e:  # noqa: BLE001 -- import 실패도 "수집 불가"일 뿐
        logger.warning("discovery_news_service_unavailable", error=str(e))
        return None

    holder: dict = {}

    async def _fetch(ticker: str, name: str):
        if "svc" not in holder:
            holder["svc"] = await create_news_service()
        result = await holder["svc"].search_stock_news(
            stock_code=ticker, stock_name=name, count=5
        )
        return [a.title for a in (getattr(result, "articles", None) or [])]

    return _fetch


async def run_discovery_pipeline(
    *,
    coordinator: Any,
    storage: Any,
    scanner: Any,
    trade_date: str,
    scan_ok: bool,
) -> Optional[dict[str, Any]]:
    """Run the DS-3/DS-4 post-scan batch for `trade_date`. Never raises.

    Args:
        coordinator: ExecutionCoordinator (or compatible) -- passed
            through unchanged to `promote_candidates` (reads
            `.state.positions`/`.get_watch_list()`, calls
            `.add_to_watch_list()`).
        storage: StorageService (or compatible) -- passed through to
            every DS-3/DS-4 call.
        scanner: the BackgroundScanner (or compatible) instance the
            coordinator just triggered this same tick -- see
            `_build_price_lookup`.
        trade_date: "YYYY-MM-DD" for today (the EOD run date).
        scan_ok: whether today's discovery scan actually completed (set
            by the coordinator's own scan-trigger-and-wait step, BEFORE
            this function is called). False skips ranking/review/
            promotion entirely (step 3 above) but still attempts the
            forward-return backfill (step 2) with whatever prices were
            collected before the cutoff.

    Returns:
        None on any internal failure (logged). Otherwise a summary dict:
        {"trade_date", "scan_ok", "backfilled" (int, slots filled),
        "total_candidates" (int, this run's ranked+excluded count -- 0
        when scan_ok is False), "promoted" (list[str] tickers),
        "skipped" (dict[str, str] ticker -> skip_reason)}.
    """
    try:
        price_lookup = _build_price_lookup(scanner)
        backfilled = await backfill_forward_returns(
            storage,
            price_lookup,
            trade_date,
            close_on_date=_make_close_on_date(getattr(coordinator, "_kiwoom", None)),
        )

        summary: dict[str, Any] = {
            "trade_date": trade_date,
            "scan_ok": scan_ok,
            "backfilled": backfilled,
            "total_candidates": 0,
            "promoted": [],
            "skipped": {},
        }

        if not scan_ok:
            return summary

        candidates = await rank_candidates(storage, SCANNER_DB_PATH, trade_date)

        # 승격 판단 재료 (2026-08-12). LLM 리뷰 **앞**에 와야 프롬프트에
        # 실린다 -- 뒤에 오면 U1~U3이 통째로 무의미해지는데 예외도 로그도
        # 남지 않아 조용히 사라진다. `top_n`은 `llm_review_top`과 같은
        # 값이어야 재료를 모은 종목과 프롬프트를 받는 종목이 일치한다.
        #
        # 수집기는 fetch가 None이면 통째로 스킵한다 -- Kiwoom 클라이언트가
        # 없거나 뉴스 서비스를 못 만들면 재료 없이 기존대로 돈다(회귀 없음).
        await enrich_fundamentals(
            candidates,
            top_n=_LLM_REVIEW_TOP_N,
            fetch=_make_stock_info_fetch(getattr(coordinator, "_kiwoom", None)),
        )
        await enrich_news(candidates, top_n=_LLM_REVIEW_TOP_N, fetch=_make_news_fetch())

        await llm_review_top(candidates, top_n=_LLM_REVIEW_TOP_N)
        promote_summary = await promote_candidates(coordinator, storage, candidates)

        summary["total_candidates"] = promote_summary.total_candidates
        summary["promoted"] = promote_summary.promoted
        summary["skipped"] = promote_summary.skipped

        await _notify_promotions(candidates, promote_summary, trade_date)

        return summary
    except Exception as e:
        logger.error("discovery_pipeline_failed", trade_date=trade_date, error=str(e))
        return None
