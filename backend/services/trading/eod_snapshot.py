"""EOD daily performance snapshot (Phase1 Task 5/C3b).

Equity/realized-P&L/win-rate today are recomputed live from ka10074
(get_realized_pnl) + kt00004 (get_account_balance) on every `/performance`
request — both have a rolling broker query window, so once a day scrolls
out of that window its numbers are gone for good; there is no durable
performance time series. `write_daily_snapshot` closes that gap: it is
called exactly once per KRX open→closed transition (the coordinator's
`_check_queue_on_market_open` edge guard, see coordinator.py) and persists
one row per trade_date into `daily_perf_snapshot`
(storage_service.save_daily_perf_snapshot, INSERT OR IGNORE so a second call
for the same day is a no-op).

Failure-harmless by design: the whole body is wrapped in try/except so a
broker hiccup, a storage failure, or any other exception can never break the
market-close scheduler tick that calls this. Callers should treat a `False`
return as "no snapshot was written this time", not as something to retry or
propagate.
"""

from __future__ import annotations

import logging
from typing import Any

from .paper_performance import compute_cumulative_return_pct

logger = logging.getLogger(__name__)

# Mirrors app/api/routes/trading.py:DEFAULT_BASE_ASSET_KRW (Paper-Proof C1
# 운용 개시 기준 자산). There is no persisted base-asset setting yet (that is
# Phase 5 regime-tracking work) so this constant is duplicated here rather
# than imported, to avoid a coordinator -> eod_snapshot -> app.api.routes ->
# (dependencies) -> coordinator import cycle at module load time.
_DEFAULT_BASE_ASSET_KRW = 500_000_000

# Upper bound on how many kr_realized_pnl rows we scan to count today's
# win/loss trades. The table has no trade_date column (Phase1 C3a predates
# this task), so filtering happens in Python over a recent slice returned
# newest-first — comfortably above any plausible single-day trade count.
_KR_REALIZED_PNL_SCAN_LIMIT = 500

# Mirrors scripts/backfill_realized_pnl.py's BACKFILL_STK_CD_SENTINEL (not
# imported — same reasoning as _DEFAULT_BASE_ASSET_KRW above: this module
# only ever receives `storage` as a duck-typed Any, and scripts/ is a
# one-shot tool outside the app that imports FROM services/, never the
# reverse). E1-6 리뷰픽스: that script backfills account-wide daily
# aggregates into kr_realized_pnl (ka10074 has no per-stock breakdown) using
# this sentinel stk_cd because a real matched-close trade never has one — a
# backfill row is NOT a "matched-close trade" (no entry/exit price/quantity
# at all) and must never be counted as a win or loss here.
_BACKFILL_STK_CD_SENTINEL = "ALL"


async def write_daily_snapshot(coordinator: Any, storage: Any, trade_date: str) -> bool:
    """Compute and persist one end-of-day performance snapshot row.

    Args:
        coordinator: ExecutionCoordinator (or any stand-in exposing a
            `._kiwoom` client with `get_realized_pnl`/`get_account_balance`).
        storage: StorageService — read kr_realized_pnl for win/loss counts,
            write the snapshot via save_daily_perf_snapshot.
        trade_date: "YYYY-MM-DD" (the coordinator trigger passes
            `datetime.now().strftime("%Y-%m-%d")`).

    Returns:
        True if a snapshot row was written (or already existed for this
        trade_date — save_daily_perf_snapshot's INSERT OR IGNORE makes a
        repeat call a no-op, not a failure). False on ANY failure —
        never raises.
    """
    try:
        client = getattr(coordinator, "_kiwoom", None)
        if client is None:
            logger.warning(
                f"[EODSnapshot] No kiwoom client on coordinator — skipping "
                f"snapshot for {trade_date}"
            )
            return False

        compact_dt = trade_date.replace("-", "")

        pnl = await client.get_realized_pnl(strt_dt=compact_dt, end_dt=compact_dt)
        balance = await client.get_account_balance()

        equity = balance.total_value
        # ka10074's realized_pnl (rlzt_pl) is already NET of commission/tax —
        # see paper_performance.build_performance_report's docstring for the
        # documented proof. commission/tax are reference cost breakdowns
        # only; net_pnl must NOT subtract them again (double-counting).
        realized_pnl = pnl.realized_pnl
        net_pnl = pnl.realized_pnl

        cumulative_return_pct = compute_cumulative_return_pct(
            equity, _DEFAULT_BASE_ASSET_KRW
        )

        win_trades, loss_trades = await _count_win_loss_trades(storage, trade_date)

        record = {
            "trade_date": trade_date,
            "equity": equity,
            "realized_pnl": realized_pnl,
            "commission": pnl.commission,
            "tax": pnl.tax,
            "net_pnl": net_pnl,
            "win_trades": win_trades,
            "loss_trades": loss_trades,
            "cumulative_return_pct": cumulative_return_pct,
            "regime_snapshot_id": None,  # Phase 5
        }
        return await storage.save_daily_perf_snapshot(record)
    except Exception as e:
        logger.warning(f"[EODSnapshot] Failed to write snapshot for {trade_date}: {e}")
        return False


async def _count_win_loss_trades(storage: Any, trade_date: str) -> tuple[int, int]:
    """Count matched-close win/loss trades for trade_date from kr_realized_pnl.

    A row counts toward trade_date if its exit_at (falls back to created_at
    when exit_at is unset) starts with the "YYYY-MM-DD" trade_date prefix —
    both timestamp columns are stored via Python's default sqlite3 datetime
    adapter / SQLite's CURRENT_TIMESTAMP, which both begin with that prefix.
    Positive realized_amount = win, negative = loss, zero counts as neither
    (mirrors compute_daily_win_loss's day-level flat-day treatment).
    """
    rows = await storage.get_kr_realized_pnl(limit=_KR_REALIZED_PNL_SCAN_LIMIT)
    win_trades = 0
    loss_trades = 0
    for row in rows:
        if row.get("stk_cd") == _BACKFILL_STK_CD_SENTINEL:
            continue  # account-wide backfill aggregate, not a matched trade
        stamp = str(row.get("exit_at") or row.get("created_at") or "")
        if not stamp.startswith(trade_date):
            continue
        amount = row.get("realized_amount")
        if amount is None:
            continue
        if amount > 0:
            win_trades += 1
        elif amount < 0:
            loss_trades += 1
    return win_trades, loss_trades
