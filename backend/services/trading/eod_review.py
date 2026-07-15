"""Phase 2 Task 3: EOD 종합 리뷰 리포트 (aggregation, NO LLM).

There is no holistic end-of-day review anywhere in this codebase — the
portfolio-level snapshot (`daily_perf_snapshot`, Phase1 Task 5/C3b),
per-stock realized P&L (`kr_realized_pnl`, Phase1 Task 4/C3a), per-agent
calibration (`agent_calibration`, Phase2 Task 1), and market regime
(`regime_snapshot`, Phase2 Task 2) each live in isolation, with nothing
joining them into a single reviewable artifact. `build_eod_review` is that
join: pure aggregation over those four durable ledgers plus
`coordinator.get_portfolio_summary()` (`services/trading/coordinator.py:
1729`, a synchronous method — NOT awaited) for the day's exposure/
concentration. This is the input Phase 3's strategic-consensus re-weighting
will read.

It does NOT write anywhere — persisting the returned dict via
`storage_service.save_eod_review` is left to a later orchestrator task
(Task 4) that decides IF/WHEN to save.

Failure-harmless by design, mirroring `eod_snapshot.write_daily_snapshot`/
`calibration.label_and_calibrate`: each source read is independently
try/except-guarded so one missing/broken ledger degrades that section to
None/0/[] rather than dragging down the rest of the report, and the whole
body is wrapped in an outer try/except so a truly unexpected failure
returns a minimal `{"trade_date": ..., "error": ...}` rather than raising —
this must never break whatever EOD job calls it.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Upper bound on how many recent rows we scan to filter down to trade_date
# in Python. Mirrors eod_snapshot.py's _KR_REALIZED_PNL_SCAN_LIMIT /
# calibration.py's _DECISION_SCAN_LIMIT scan-then-filter pattern — neither
# get_kr_realized_pnl nor get_agent_chat_decisions has a date-range query
# parameter.
_KR_REALIZED_PNL_SCAN_LIMIT = 500
_DECISION_SCAN_LIMIT = 1000
_DAILY_PERF_SNAPSHOT_SCAN_LIMIT = 60
_REGIME_SNAPSHOT_SCAN_LIMIT = 60


def _portfolio_exposure_concentration(
    summary: Any,
) -> tuple[Optional[float], Optional[float]]:
    """Derive exposure (% of equity held in stock) and concentration (%
    of equity in the single largest position) from a
    `coordinator.get_portfolio_summary()` dict.

    `portfolio_agent.get_portfolio_summary` already gives both directly
    (`stock_ratio`, and each position's `weight_pct`) — used as-is when
    present. Falls back to computing from `stock_value`/`positions[].value`
    against `total_equity` if a stand-in summary omits the pre-computed
    percentages. Any missing/malformed input degrades to `None` rather
    than raising.
    """
    if not isinstance(summary, dict):
        return None, None

    equity = summary.get("total_equity")
    positions = summary.get("positions") or []
    if not isinstance(positions, list):
        positions = []

    exposure = summary.get("stock_ratio")
    if exposure is None:
        stock_value = summary.get("stock_value")
        if stock_value is not None and equity:
            try:
                exposure = (stock_value / equity) * 100
            except (TypeError, ZeroDivisionError):
                exposure = None

    concentration = None
    weights = [
        p.get("weight_pct")
        for p in positions
        if isinstance(p, dict) and p.get("weight_pct") is not None
    ]
    if weights:
        concentration = max(weights)
    else:
        values = [
            p.get("value")
            for p in positions
            if isinstance(p, dict) and p.get("value") is not None
        ]
        if values and equity:
            try:
                concentration = (max(values) / equity) * 100
            except (TypeError, ZeroDivisionError):
                concentration = None

    return exposure, concentration


async def build_eod_review(
    storage: Any,
    coordinator: Any,
    trade_date: str,
    regime_snapshot_id: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble the end-of-day review report for `trade_date`.

    Args:
        storage: StorageService (or compatible) — reads
            get_daily_perf_snapshots/get_kr_realized_pnl/
            get_agent_chat_decisions/get_agent_calibration/
            get_regime_snapshots. Never writes.
        coordinator: ExecutionCoordinator (or any stand-in exposing a
            synchronous `.get_portfolio_summary()`).
        trade_date: "YYYY-MM-DD" — the day this review is attributed to.
        regime_snapshot_id: id of the regime_snapshot row to attach under
            `regime`, or None (regime section degrades to label/
            breadth_ratio = None).

    Returns:
        {"trade_date", "portfolio": {equity, realized_pnl, net_pnl,
        win_trades, loss_trades, cumulative_return_pct, exposure,
        concentration}, "per_stock": [{stk_cd, realized_amount,
        entry_decision_id, thesis_valid}], "agents": [{agent_type,
        accuracy, decisions_scored}], "regime": {regime_snapshot_id, label,
        breadth_ratio}}. Failure-harmless: missing individual sources
        degrade to None/0/[]; on a totally unexpected failure returns
        `{"trade_date": trade_date, "error": str(e)}` — never raises.
    """
    try:
        portfolio = await _build_portfolio_section(storage, coordinator, trade_date)
        per_stock = await _build_per_stock_section(storage, trade_date)
        agents = await _build_agents_section(storage, trade_date)
        regime = await _build_regime_section(storage, regime_snapshot_id)

        return {
            "trade_date": trade_date,
            "portfolio": portfolio,
            "per_stock": per_stock,
            "agents": agents,
            "regime": regime,
        }
    except Exception as e:
        logger.warning(f"[EODReview] build_eod_review failed for {trade_date}: {e}")
        return {"trade_date": trade_date, "error": str(e)}


async def _build_portfolio_section(
    storage: Any, coordinator: Any, trade_date: str
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    try:
        snapshots = await storage.get_daily_perf_snapshots(
            limit=_DAILY_PERF_SNAPSHOT_SCAN_LIMIT
        )
        for row in snapshots:
            if row.get("trade_date") == trade_date:
                snapshot = row
                break
    except Exception as e:
        logger.warning(f"[EODReview] get_daily_perf_snapshots failed: {e}")

    summary: Any = None
    try:
        summary = coordinator.get_portfolio_summary()
    except Exception as e:
        logger.warning(f"[EODReview] coordinator.get_portfolio_summary failed: {e}")
    exposure, concentration = _portfolio_exposure_concentration(summary)

    return {
        "equity": snapshot.get("equity"),
        "realized_pnl": snapshot.get("realized_pnl"),
        "net_pnl": snapshot.get("net_pnl"),
        "win_trades": snapshot.get("win_trades"),
        "loss_trades": snapshot.get("loss_trades"),
        "cumulative_return_pct": snapshot.get("cumulative_return_pct"),
        "exposure": exposure,
        "concentration": concentration,
    }


async def _build_per_stock_section(
    storage: Any, trade_date: str
) -> list[dict[str, Any]]:
    try:
        realized_rows = await storage.get_kr_realized_pnl(
            limit=_KR_REALIZED_PNL_SCAN_LIMIT
        )
    except Exception as e:
        logger.warning(f"[EODReview] get_kr_realized_pnl failed: {e}")
        return []

    day_rows = [
        r
        for r in realized_rows
        if str(r.get("exit_at") or r.get("created_at") or "").startswith(trade_date)
    ]
    if not day_rows:
        return []

    try:
        decisions = await storage.get_agent_chat_decisions(limit=_DECISION_SCAN_LIMIT)
    except Exception as e:
        logger.warning(f"[EODReview] get_agent_chat_decisions failed: {e}")
        decisions = []
    decisions_by_id = {d.get("id"): d for d in decisions if d.get("id")}

    per_stock = []
    for r in day_rows:
        entry_decision_id = r.get("entry_decision_id")
        decision = decisions_by_id.get(entry_decision_id)
        # Minimal thesis_valid rule (Phase3 will refine): an entry decision
        # is considered valid unless explicitly labeled "incorrect" — a
        # missing/unlabeled decision (outcome_label is None) counts as
        # valid rather than penalizing a match we simply couldn't find.
        outcome_label = decision.get("outcome_label") if decision else None
        per_stock.append(
            {
                "stk_cd": r.get("stk_cd"),
                "realized_amount": r.get("realized_amount"),
                "entry_decision_id": entry_decision_id,
                "thesis_valid": outcome_label != "incorrect",
            }
        )
    return per_stock


async def _build_agents_section(storage: Any, trade_date: str) -> list[dict[str, Any]]:
    try:
        rows = await storage.get_agent_calibration(as_of_date=trade_date)
    except Exception as e:
        logger.warning(f"[EODReview] get_agent_calibration failed: {e}")
        return []

    return [
        {
            "agent_type": row.get("agent_type"),
            "accuracy": row.get("accuracy"),
            "decisions_scored": row.get("decisions_scored"),
        }
        for row in rows
    ]


async def _build_regime_section(
    storage: Any, regime_snapshot_id: Optional[str]
) -> dict[str, Any]:
    regime_row: dict[str, Any] = {}
    if regime_snapshot_id:
        try:
            rows = await storage.get_regime_snapshots(
                limit=_REGIME_SNAPSHOT_SCAN_LIMIT
            )
            for row in rows:
                if row.get("id") == regime_snapshot_id:
                    regime_row = row
                    break
        except Exception as e:
            logger.warning(f"[EODReview] get_regime_snapshots failed: {e}")

    return {
        "regime_snapshot_id": regime_snapshot_id,
        "label": regime_row.get("regime_label"),
        "breadth_ratio": regime_row.get("breadth_ratio"),
    }
