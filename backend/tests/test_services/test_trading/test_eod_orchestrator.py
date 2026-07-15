"""Task 4 (Phase2 EOD review): eod_orchestrator — wires Tasks 1-3 (regime
snapshot, per-agent calibration, EOD review) into ONE market-close run, and
backfills the `regime_snapshot_id` FK that Phase1/Task2 left nullable onto
both `daily_perf_snapshot` and that day's `agent_chat_decisions`.

`run_eod_review(coordinator, storage, trade_date)` is the single entry point
the LIVE trading coordinator calls off the market-close edge (see
services/trading/coordinator.py::_check_queue_on_market_open, right after
`.eod_snapshot.write_daily_snapshot` — build_eod_review reads
daily_perf_snapshot, so this must run after that row exists). Steps, in
order: compute_regime_snapshot (+save) -> label_and_calibrate ->
build_eod_review (+save) -> backfill_regime_id. NO LLM anywhere in this
chain. Failure-harmless by design, mirroring every other Phase1/Phase2 EOD
step: the WHOLE body is one try/except -> logger.warning -> return False,
since this runs off the live scheduler tick and must never break it.
"""

import inspect
import json
import sqlite3
import uuid
from unittest.mock import patch

from services.storage_service import StorageService
from services.trading import coordinator as coordinator_module
from services.trading import eod_orchestrator
from services.trading.eod_orchestrator import run_eod_review

TRADE_DATE = "2026-07-15"


class _StubCoordinator:
    """Minimal stand-in for ExecutionCoordinator — only
    `.get_portfolio_summary()` is read (sync, mirrors test_eod_review.py's
    stub — services/trading/coordinator.py:1729)."""

    def get_portfolio_summary(self) -> dict:
        return {
            "total_equity": 500_000_000,
            "stock_value": 50_000_000,
            "stock_ratio": 10.0,
            "positions": [],
        }


def _make_scanner_db(tmp_path) -> str:
    """Build a temp scanner_results.db with ONE completed scan_sessions row
    for TRADE_DATE (mirrors test_regime.py's _make_scanner_db DDL)."""
    db_path = tmp_path / "scanner_results.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE scan_sessions (
            id TEXT PRIMARY KEY,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            total_stocks INTEGER,
            completed INTEGER,
            failed INTEGER,
            buy_count INTEGER,
            sell_count INTEGER,
            hold_count INTEGER,
            watch_count INTEGER,
            avoid_count INTEGER,
            status TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO scan_sessions
        (id, started_at, completed_at, total_stocks, completed, failed,
         buy_count, sell_count, hold_count, watch_count, avoid_count, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            f"{TRADE_DATE} 09:00:00",
            f"{TRADE_DATE} 15:30:00",
            50,
            50,
            0,
            30,
            5,
            15,
            0,
            0,
            "completed",
        ),
    )
    conn.commit()
    conn.close()
    return str(db_path)


async def _seed_daily_perf_snapshot(storage: StorageService) -> None:
    await storage.save_daily_perf_snapshot(
        {
            "trade_date": TRADE_DATE,
            "equity": 500_000_000,
            "realized_pnl": 50_000,
            "commission": 500,
            "tax": 284,
            "net_pnl": 50_000,
            "win_trades": 1,
            "loss_trades": 0,
            "cumulative_return_pct": 0.01,
        }
    )


async def _seed_scorable_decision(storage: StorageService) -> str:
    """One decision with an already-backfilled outcome + one bullish vote,
    so label_and_calibrate has a closed decision to label/score (mirrors
    test_calibration.py's seed)."""
    decision_id = str(uuid.uuid4())
    await storage.save_agent_chat_decision(
        {
            "id": decision_id,
            "ticker": "005930",
            "stock_name": "삼성전자",
            "trade_date": TRADE_DATE,
            "status": "decided",
            "action": "BUY",
            "confidence": 0.7,
            "consensus_level": 0.8,
            "rationale": "test",
        },
        [
            {
                "decision_id": decision_id,
                "agent_type": "technical",
                "vote": "buy",
                "confidence": 0.8,
            }
        ],
    )
    await storage.update_decision_outcome(decision_id, 10_000.0)
    return decision_id


async def test_run_eod_review_runs_all_steps_and_backfills_regime_id(
    tmp_path, monkeypatch
):
    scanner_db_path = _make_scanner_db(tmp_path)
    monkeypatch.setattr(eod_orchestrator, "SCANNER_DB_PATH", scanner_db_path)

    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_daily_perf_snapshot(storage)
    await _seed_scorable_decision(storage)

    coordinator = _StubCoordinator()

    ok = await run_eod_review(coordinator, storage, TRADE_DATE)
    assert ok is True

    # (a) a regime_snapshot row exists
    regime_rows = await storage.get_regime_snapshots()
    assert len(regime_rows) == 1
    assert regime_rows[0]["trade_date"] == TRADE_DATE
    regime_id = regime_rows[0]["id"]

    # (b) agent_calibration rows exist
    calib_rows = await storage.get_agent_calibration(as_of_date=TRADE_DATE)
    assert len(calib_rows) >= 1
    assert any(r["agent_type"] == "technical" for r in calib_rows)

    # (c) an eod_review row exists
    review_rows = await storage.get_eod_reviews()
    assert len(review_rows) == 1
    assert review_rows[0]["trade_date"] == TRADE_DATE
    report = json.loads(review_rows[0]["report_json"])
    assert report["trade_date"] == TRADE_DATE
    assert report["regime"]["regime_snapshot_id"] == regime_id

    # (d) daily_perf_snapshot's regime_snapshot_id got backfilled (non-null)
    snapshots = await storage.get_daily_perf_snapshots()
    row = next(r for r in snapshots if r["trade_date"] == TRADE_DATE)
    assert row["regime_snapshot_id"] == regime_id

    # ... and so did that day's agent_chat_decisions.
    decisions = await storage.get_agent_chat_decisions(ticker="005930")
    assert all(d["regime_snapshot_id"] == regime_id for d in decisions)


async def test_run_eod_review_returns_false_never_raises_on_internal_failure(
    tmp_path, monkeypatch
):
    scanner_db_path = _make_scanner_db(tmp_path)
    monkeypatch.setattr(eod_orchestrator, "SCANNER_DB_PATH", scanner_db_path)

    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_daily_perf_snapshot(storage)

    coordinator = _StubCoordinator()

    with patch.object(
        eod_orchestrator, "build_eod_review", side_effect=RuntimeError("boom")
    ):
        ok = await run_eod_review(coordinator, storage, TRADE_DATE)

    assert ok is False


async def test_run_eod_review_handles_no_completed_scan_gracefully(
    tmp_path, monkeypatch
):
    """No completed scan_sessions row for trade_date -> compute_regime_snapshot
    returns None -> the chain still completes (regime section degrades to
    None) rather than failing outright."""
    scanner_db_path = _make_scanner_db(tmp_path)
    monkeypatch.setattr(eod_orchestrator, "SCANNER_DB_PATH", scanner_db_path)

    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_daily_perf_snapshot(storage)

    coordinator = _StubCoordinator()

    ok = await run_eod_review(coordinator, storage, "2099-01-01")
    assert ok is True

    assert await storage.get_regime_snapshots() == []
    review_rows = await storage.get_eod_reviews()
    assert len(review_rows) == 1


def test_coordinator_triggers_run_eod_review_immediately_after_write_daily_snapshot():
    """Code-content check (per the Task 4 brief): the market-close edge in
    _check_queue_on_market_open must call run_eod_review as the line right
    after write_daily_snapshot, so the EOD review always reads a
    daily_perf_snapshot row that already exists."""
    source = inspect.getsource(
        coordinator_module.ExecutionCoordinator._check_queue_on_market_open
    )
    lines = [ln.strip() for ln in source.splitlines() if ln.strip()]

    snapshot_idx = next(
        i for i, ln in enumerate(lines) if ln.startswith("await write_daily_snapshot(")
    )
    assert lines[snapshot_idx + 1].startswith("await run_eod_review(")

    assert "from .eod_orchestrator import run_eod_review" in inspect.getsource(
        coordinator_module
    )
