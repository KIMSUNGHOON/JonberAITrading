"""Phase E3 Task 1: eod_digest 조립기 (aggregation, NO LLM).

The end-of-day digest joins four otherwise-siloed live/durable sources into
ONE dict that downstream tasks treat as a fixed contract: E3-2's LLM
narrative reads it as the source-of-truth for a Korean briefing, E3-3's
Telegram template and E3-5's FE render both render its 5 sections verbatim.
See docs/superpowers/specs/2026-07-17-three-issues-design.md §3 (Task
E3-1/T6) and docs/superpowers/plans/2026-07-17-three-issues.md's Task E3-1
for the authoritative schema this module implements.

Sources:
  - `coordinator.get_watch_list()` (sync — `services/trading/coordinator.
    py::ExecutionCoordinator.get_watch_list`) → `watch`.
  - `coordinator.get_portfolio_summary()` (sync) → `account`'s deposit/
    total_equity and `holdings`' quantity/avg_price/current_price/
    unrealized P&L.
  - `coordinator.state.positions` (sync property, `List[ManagedPosition]`)
    → best-effort enrichment of `holdings[].stop_loss`/`take_profit`, which
    `get_portfolio_summary()`'s dict does not carry. This is an optional
    read: a coordinator stand-in that only implements the two methods
    above (no `.state`) still assembles holdings fine — stop_loss/
    take_profit just degrade to None per position.
  - `storage.get_daily_perf_snapshots()` (async, scan-then-match on
    trade_date — no server-side date filter, mirrors eod_review.py's own
    idiom) → `account`'s daily_realized_pnl/cumulative_return_pct. Per
    spec §3: today's trades/P&L come from this ledger ONLY — never
    aggregate kr_stock_trades directly here (that table is raw fills, not
    the reconciled daily figure; see the spec's explicit warning).
  - `storage.get_strategy_revisions(limit=1)` (async, already sorted
    `created_at DESC`) → `strategy`, the single latest revision regardless
    of trade_date (it represents "the strategy currently in force", which
    may predate `trade_date` if today's EOD consensus hasn't run yet).
  - `storage.get_regime_snapshots(limit=1)` (async, same "true latest"
    idiom) → `regime`.

Failure-harmless by design, mirroring eod_review.build_eod_review: each
section is built by its own independently try/except-guarded helper, so
one broken/missing source degrades only that section (to None or []),
never the whole digest. The whole body is additionally wrapped so a truly
unexpected failure still returns a dict shaped exactly like the happy path
(all 5 keys present, degraded to None/[]) rather than raising or omitting
keys — every consumer can rely on the 5 keys always existing.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Upper bound on how many recent daily_perf_snapshot rows we scan to find
# trade_date's row in Python — there's no server-side date filter on
# get_daily_perf_snapshots. Mirrors eod_review.py's
# _DAILY_PERF_SNAPSHOT_SCAN_LIMIT.
_DAILY_PERF_SNAPSHOT_SCAN_LIMIT = 60

# strategy/regime sections want the single TRUE latest row (not scoped to
# trade_date — see module docstring), and both getters already return
# newest-first, so limit=1 is sufficient.
_LATEST_ROW_LIMIT = 1

# rationale is free-form Korean text (can run to several KB); the digest
# only ever needs a short excerpt for a briefing.
_RATIONALE_EXCERPT_CHARS = 300

_EMPTY_ACCOUNT: dict[str, Any] = {
    "deposit": None,
    "total_equity": None,
    "daily_realized_pnl": None,
    "cumulative_return_pct": None,
}


async def build_eod_digest(coordinator: Any, storage: Any, trade_date: str) -> dict[str, Any]:
    """Assemble the end-of-day digest for `trade_date`.

    Args:
        coordinator: ExecutionCoordinator (or any stand-in exposing
            synchronous `.get_watch_list()`/`.get_portfolio_summary()`,
            and optionally `.state.positions`).
        storage: StorageService (or compatible) — reads
            get_daily_perf_snapshots/get_strategy_revisions/
            get_regime_snapshots. Never writes.
        trade_date: "YYYY-MM-DD" — the day this digest is attributed to
            (scopes only the `account` section; `strategy`/`regime` are
            each the single latest row regardless of date).

    Returns:
        {"trade_date", "watch": [...], "account": {...}, "holdings": [...],
        "strategy": {...} | None, "regime": {...} | None}. Failure-harmless:
        a broken/missing individual source degrades only its section
        (to None or []); this function itself never raises.
    """
    try:
        watch = _build_watch_section(coordinator)
        account = await _build_account_section(coordinator, storage, trade_date)
        holdings = _build_holdings_section(coordinator)
        strategy = await _build_strategy_section(storage)
        regime = await _build_regime_section(storage)

        return {
            "trade_date": trade_date,
            "watch": watch,
            "account": account,
            "holdings": holdings,
            "strategy": strategy,
            "regime": regime,
        }
    except Exception as e:
        # Each section builder above is already independently
        # try/except-guarded, so this branch should be unreachable in
        # practice — it exists purely as defense-in-depth so the contract
        # ("always a dict with all 5 keys") holds even against a bug in
        # the assembly code itself, not just in a data source.
        logger.warning(f"[EODDigest] build_eod_digest failed for {trade_date}: {e}")
        return {
            "trade_date": trade_date,
            "watch": [],
            "account": dict(_EMPTY_ACCOUNT),
            "holdings": [],
            "strategy": None,
            "regime": None,
            "error": str(e),
        }


def _build_watch_section(coordinator: Any) -> list[dict[str, Any]]:
    try:
        watch_list = coordinator.get_watch_list()
    except Exception as e:
        logger.warning(f"[EODDigest] coordinator.get_watch_list failed: {e}")
        return []

    result = []
    for w in watch_list or []:
        try:
            current_price = getattr(w, "current_price", None)
            target_entry_price = getattr(w, "target_entry_price", None)
            result.append(
                {
                    "ticker": getattr(w, "ticker", None),
                    "stock_name": getattr(w, "stock_name", None),
                    "signal": getattr(w, "signal", None),
                    "confidence": getattr(w, "confidence", None),
                    "current_price": current_price,
                    "target_entry_price": target_entry_price,
                    "gap_pct": _gap_pct(current_price, target_entry_price),
                }
            )
        except Exception as e:
            logger.warning(f"[EODDigest] watch item skipped: {e}")
    return result


def _gap_pct(current_price: Any, target_entry_price: Any) -> Optional[float]:
    if current_price is None or not target_entry_price:
        return None
    try:
        return (current_price - target_entry_price) / target_entry_price * 100
    except (TypeError, ZeroDivisionError):
        return None


async def _build_account_section(
    coordinator: Any, storage: Any, trade_date: str
) -> dict[str, Any]:
    deposit = None
    total_equity = None
    try:
        summary = coordinator.get_portfolio_summary()
        deposit = summary.get("cash")
        total_equity = summary.get("total_equity")
    except Exception as e:
        logger.warning(f"[EODDigest] coordinator.get_portfolio_summary failed: {e}")

    daily_realized_pnl = None
    cumulative_return_pct = None
    try:
        snapshots = await storage.get_daily_perf_snapshots(
            limit=_DAILY_PERF_SNAPSHOT_SCAN_LIMIT
        )
        for row in snapshots:
            if row.get("trade_date") == trade_date:
                daily_realized_pnl = row.get("realized_pnl")
                cumulative_return_pct = row.get("cumulative_return_pct")
                break
    except Exception as e:
        logger.warning(f"[EODDigest] get_daily_perf_snapshots failed: {e}")

    return {
        "deposit": deposit,
        "total_equity": total_equity,
        "daily_realized_pnl": daily_realized_pnl,
        "cumulative_return_pct": cumulative_return_pct,
    }


def _build_holdings_section(coordinator: Any) -> list[dict[str, Any]]:
    try:
        summary = coordinator.get_portfolio_summary()
        positions = summary.get("positions") or []
    except Exception as e:
        logger.warning(f"[EODDigest] coordinator.get_portfolio_summary failed: {e}")
        return []

    # Best-effort stop_loss/take_profit enrichment: get_portfolio_summary's
    # dict doesn't carry these two fields (portfolio_agent.py deliberately
    # omits them), but coordinator.state.positions (ManagedPosition) has
    # them. Optional read — any failure (missing `.state`, malformed
    # position, etc.) just leaves the lookup empty so every holding falls
    # back to stop_loss/take_profit = None rather than raising.
    stops_by_ticker: dict[Any, tuple[Any, Any]] = {}
    try:
        for p in coordinator.state.positions:
            stops_by_ticker[p.ticker] = (
                getattr(p, "stop_loss", None),
                getattr(p, "take_profit", None),
            )
    except Exception as e:
        logger.debug(f"[EODDigest] coordinator.state.positions unavailable: {e}")

    holdings = []
    for p in positions:
        try:
            ticker = p.get("ticker")
            stop_loss, take_profit = stops_by_ticker.get(ticker, (None, None))
            holdings.append(
                {
                    "ticker": ticker,
                    "stock_name": p.get("stock_name"),
                    "quantity": p.get("quantity"),
                    "avg_price": p.get("avg_price"),
                    "current_price": p.get("current_price"),
                    "unrealized_pnl": p.get("unrealized_pnl"),
                    "unrealized_pnl_pct": p.get("unrealized_pnl_pct"),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                }
            )
        except Exception as e:
            logger.warning(f"[EODDigest] holding entry skipped: {e}")
    return holdings


async def _build_strategy_section(storage: Any) -> Optional[dict[str, Any]]:
    try:
        rows = await storage.get_strategy_revisions(limit=_LATEST_ROW_LIMIT)
    except Exception as e:
        logger.warning(f"[EODDigest] get_strategy_revisions failed: {e}")
        return None
    if not rows:
        return None

    row = rows[0]
    rationale = row.get("rationale") or ""
    key_knobs = {
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "max_position_pct": None,
        "max_trade_notional_pct": None,
    }
    try:
        strategy_json = row.get("strategy_json")
        if strategy_json:
            parsed = json.loads(strategy_json)
            exit_conditions = parsed.get("exit_conditions") or {}
            position_sizing = parsed.get("position_sizing") or {}
            key_knobs = {
                "stop_loss_pct": exit_conditions.get("stop_loss_pct"),
                "take_profit_pct": exit_conditions.get("take_profit_pct"),
                "max_position_pct": position_sizing.get("max_position_pct"),
                "max_trade_notional_pct": position_sizing.get("max_trade_notional_pct"),
            }
    except Exception as e:
        logger.warning(f"[EODDigest] strategy_json parse failed: {e}")

    return {
        "stance": row.get("stance"),
        "rationale_excerpt": rationale[:_RATIONALE_EXCERPT_CHARS],
        "key_knobs": key_knobs,
        "changed": bool(row.get("changed")),
    }


async def _build_regime_section(storage: Any) -> Optional[dict[str, Any]]:
    try:
        rows = await storage.get_regime_snapshots(limit=_LATEST_ROW_LIMIT)
    except Exception as e:
        logger.warning(f"[EODDigest] get_regime_snapshots failed: {e}")
        return None
    if not rows:
        return None

    row = rows[0]
    return {
        "label": row.get("market_sentiment_label"),
        "index_kospi_chg_pct": row.get("index_kospi_chg_pct"),
        "index_kosdaq_chg_pct": row.get("index_kosdaq_chg_pct"),
    }
