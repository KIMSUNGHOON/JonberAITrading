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
build_eod_review -> E3-2 build_eod_digest+narrate_eod_digest (LLM,
never-raise) merged into the same report (+save) -> backfill_regime_id.
Failure-harmless by design, mirroring every other Phase1/Phase2 EOD
step: the WHOLE body is one try/except -> logger.warning -> return False,
since this runs off the live scheduler tick and must never break it.

E3-2 note: `run_eod_review` now makes exactly ONE LLM call
(`narrate_eod_digest`, via `services.trading.eod_digest.get_llm_provider`).
The autouse `_stub_llm_provider` fixture below patches that to a fast stub
for EVERY test in this file — including the pre-existing tests above the
E3-2 section, which predate the LLM call and must keep running at their
original (sub-second) speed rather than hitting a real backend. Tests that
care about narrative content layer their own `patch.object(...)` on top,
inside their body.
"""

import inspect
import json
import sqlite3
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from services.storage_service import StorageService
from services.trading import coordinator as coordinator_module
from services.trading import eod_digest as eod_digest_module
from services.trading import eod_orchestrator
from services.trading.eod_orchestrator import run_eod_review

import pytest

TRADE_DATE = "2026-07-15"


@pytest.fixture(autouse=True)
def _stub_llm_provider():
    """E3-2 added ONE LLM call into run_eod_review's chain
    (narrate_eod_digest). This project's binding constraints forbid real
    LLM calls in tests, and this file's tests historically ran with no LLM
    involved at all — autouse-patch a fast stub so every test here
    (including the pre-existing ones that predate E3-2 and don't know
    narrate_eod_digest exists) completes near-instantly instead of
    blocking on a real backend. Tests that DO care about narrative content
    apply their own nested `patch.object(eod_digest_module,
    "get_llm_provider", ...)`, which overrides this for its `with` block
    and reverts back to this stub afterwards.
    """
    provider = MagicMock()
    provider.generate = AsyncMock(return_value="stub narrative")
    with patch.object(eod_digest_module, "get_llm_provider", return_value=provider):
        yield


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


# -------------------------------------------
# E3-2: digest/narrative merged into eod_review.report_json
# -------------------------------------------


class _StubCoordinatorWithWatch(_StubCoordinator):
    """Adds `.get_watch_list()` so build_eod_digest's watch section has
    something to work with too (still no `.state` — degrades stop_loss/
    take_profit to None, exercised elsewhere in test_eod_digest.py)."""

    def get_watch_list(self):
        return []


async def test_run_eod_review_merges_digest_and_narrative_into_report_json(
    tmp_path, monkeypatch
):
    scanner_db_path = _make_scanner_db(tmp_path)
    monkeypatch.setattr(eod_orchestrator, "SCANNER_DB_PATH", scanner_db_path)

    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_daily_perf_snapshot(storage)

    coordinator = _StubCoordinatorWithWatch()

    provider = MagicMock()
    provider.generate = AsyncMock(return_value="오늘 EOD 브리핑 본문입니다.")

    with patch.object(eod_digest_module, "get_llm_provider", return_value=provider):
        ok = await run_eod_review(coordinator, storage, TRADE_DATE)
    assert ok is True

    review_rows = await storage.get_eod_reviews()
    assert len(review_rows) == 1
    report = json.loads(review_rows[0]["report_json"])

    # Pre-existing keys/shape (build_eod_review's own contract) are
    # untouched — this is the "무회귀" contract E3-2 must not break.
    assert report["trade_date"] == TRADE_DATE
    assert "portfolio" in report
    assert "per_stock" in report
    assert "agents" in report
    assert "regime" in report

    # New: digest + narrative are merged in as additional keys.
    assert report["digest"]["trade_date"] == TRADE_DATE
    assert set(report["digest"].keys()) == {
        "trade_date", "watch", "account", "holdings", "strategy", "regime",
        "discovery",  # DS-5: null-tolerant section, see test_eod_digest.py
    }
    assert report["narrative"] == "오늘 EOD 브리핑 본문입니다."


async def test_run_eod_review_llm_failure_still_saves_full_report(
    tmp_path, monkeypatch
):
    """narrate_eod_digest failing (never-raise -> None) must not drop or
    corrupt any of build_eod_review's pre-existing keys — only
    report["narrative"] degrades to None, per E3-D2."""
    scanner_db_path = _make_scanner_db(tmp_path)
    monkeypatch.setattr(eod_orchestrator, "SCANNER_DB_PATH", scanner_db_path)

    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_daily_perf_snapshot(storage)
    await _seed_scorable_decision(storage)

    coordinator = _StubCoordinatorWithWatch()

    provider = MagicMock()
    provider.generate = AsyncMock(side_effect=RuntimeError("all backends down"))

    with patch.object(eod_digest_module, "get_llm_provider", return_value=provider):
        ok = await run_eod_review(coordinator, storage, TRADE_DATE)
    assert ok is True

    review_rows = await storage.get_eod_reviews()
    report = json.loads(review_rows[0]["report_json"])

    assert report["trade_date"] == TRADE_DATE
    assert "portfolio" in report
    assert "per_stock" in report
    assert "agents" in report
    assert "regime" in report
    assert report["digest"] is not None
    assert report["digest"]["trade_date"] == TRADE_DATE
    assert report["narrative"] is None
