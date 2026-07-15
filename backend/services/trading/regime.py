"""Phase 2 Task 2: minimal daily market-regime snapshot (scanner breadth
proxy).

There is no market-wide sentiment/regime signal anywhere in this codebase
(confirmed by audit). The only durable, market-wide artifact is the
background scanner's `scan_sessions` row
(`services/background_scanner/scanner.py`) — its buy/sell/hold/watch/avoid
counts across a full KOSPI/KOSDAQ sweep stand in as a breadth proxy for
market-wide risk appetite. A real index/flow-data fetcher is a later phase;
this is intentionally minimal.

`compute_regime_snapshot` is a pure, SYNCHRONOUS function (no LLM, no
network, no dependency on this app's own storage) that reads the LATEST
completed `scan_sessions` row for a given trade_date directly off the
scanner's own sqlite db via the stdlib `sqlite3` module (there is no async
reader/writer contract to honor here — the scanner db is read read-only and
independently of this app's aiosqlite storage). It does NOT write anywhere;
persisting the returned dict (via
`storage_service.StorageService.save_regime_snapshot`) is left to a later
orchestrator task that decides IF/WHEN to save.

Failure-harmless by design, mirroring `calibration.label_and_calibrate`/
`eod_snapshot.write_daily_snapshot`: any error (missing db file, missing
table, malformed row) — or simply no completed scan for that day — returns
`None` rather than raising, since this must never break whatever EOD job
calls it.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Mirrors services/background_scanner/scanner.py::DB_PATH's resolution
# exactly (backend/data/scanner_results.db) so a future caller that needs a
# default path agrees with the scanner's own writer. compute_regime_snapshot
# itself takes scanner_db_path as a required param for testability — this
# constant is not used internally, only exposed for callers.
SCANNER_DB_PATH = Path(__file__).parent.parent.parent / "data" / "scanner_results.db"


def compute_regime_snapshot(scanner_db_path: str, trade_date: str) -> Optional[dict]:
    """Compute a market-regime snapshot from the day's latest completed scan.

    Args:
        scanner_db_path: path to the background scanner's sqlite db
            (contains `scan_sessions`).
        trade_date: "YYYY-MM-DD" — the day to look up.

    Returns:
        dict with keys id (new uuid4), trade_date, breadth_buy, breadth_sell,
        breadth_hold, breadth_ratio, regime_label ("risk_on"/"risk_off"/
        "neutral"), source ("scanner"). `None` if no completed scan exists
        for trade_date, or on any error (missing db file, missing table,
        etc.) — never raises.
    """
    try:
        conn = sqlite3.connect(scanner_db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT buy_count, sell_count, hold_count
                FROM scan_sessions
                WHERE status = 'completed' AND date(started_at) = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (trade_date,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None:
            return None

        buy_count = int(row["buy_count"] or 0)
        sell_count = int(row["sell_count"] or 0)
        hold_count = int(row["hold_count"] or 0)

        breadth_ratio = (buy_count - sell_count) / max(
            1, buy_count + sell_count + hold_count
        )

        threshold = get_settings().EOD_REGIME_BREADTH_THRESHOLD
        if breadth_ratio > threshold:
            regime_label = "risk_on"
        elif breadth_ratio < -threshold:
            regime_label = "risk_off"
        else:
            regime_label = "neutral"

        return {
            "id": str(uuid.uuid4()),
            "trade_date": trade_date,
            "breadth_buy": buy_count,
            "breadth_sell": sell_count,
            "breadth_hold": hold_count,
            "breadth_ratio": breadth_ratio,
            "regime_label": regime_label,
            "source": "scanner",
        }
    except Exception as e:
        logger.warning(
            f"[Regime] compute_regime_snapshot failed for {trade_date}: {e}"
        )
        return None
