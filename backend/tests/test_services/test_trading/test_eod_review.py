"""Phase 2 Task 3: EOD 종합 리뷰 리포트 (aggregation, NO LLM).

There is no holistic end-of-day review joining portfolio/per-stock/agent/
regime signals anywhere in this codebase — each Phase1/Phase2 ledger
(daily_perf_snapshot, kr_realized_pnl, agent_calibration, regime_snapshot)
lives in isolation. `build_eod_review` is pure aggregation over those
durable ledgers plus `coordinator.get_portfolio_summary()` (for
exposure/concentration); it does NOT write anywhere — persisting the
returned dict via `storage_service.save_eod_review` is left to a later
orchestrator task (Task 4).

Failure-harmless by design, mirroring `eod_snapshot.write_daily_snapshot`/
`calibration.label_and_calibrate`: any read failure must degrade to
None/0/[] for that section rather than raising, and a totally unexpected
failure returns `{"trade_date": ..., "error": ...}` rather than raising —
this must never break an EOD job.
"""

import json
import uuid

import pytest

from services.storage_service import StorageService
from services.trading.eod_review import build_eod_review

pytestmark = pytest.mark.asyncio


class _StubCoordinator:
    """Minimal stand-in for ExecutionCoordinator — only
    `.get_portfolio_summary()` is read, mirroring
    `services/trading/coordinator.py:1729`'s (sync, not async) shape."""

    def __init__(self, summary: dict):
        self._summary = summary

    def get_portfolio_summary(self) -> dict:
        return self._summary


def _portfolio_summary() -> dict:
    return {
        "total_equity": 500_000_000,
        "cash": 400_000_000,
        "cash_ratio": 80.0,
        "stock_value": 100_000_000,
        "stock_ratio": 20.0,
        "positions": [
            {"ticker": "005930", "stock_name": "삼성전자", "weight_pct": 15.0, "value": 75_000_000},
            {"ticker": "000660", "stock_name": "SK하이닉스", "weight_pct": 5.0, "value": 25_000_000},
        ],
        "total_unrealized_pnl": 1_000_000,
        "total_unrealized_pnl_pct": 0.2,
        "daily_trades": 2,
        "max_daily_trades": 20,
    }


async def _seed(storage: StorageService, trade_date: str, regime_id: str) -> tuple[str, str]:
    """Seed one daily_perf_snapshot, 2 kr_realized_pnl rows (one win/one
    loss, each with an entry_decision_id), 2 agent_calibration rows, and one
    regime_snapshot row for `trade_date`. Returns the (win, loss)
    entry_decision_ids."""
    await storage.save_daily_perf_snapshot(
        {
            "trade_date": trade_date,
            "equity": 500_000_000,
            "realized_pnl": 50_000,
            "commission": 500,
            "tax": 284,
            "net_pnl": 50_000,
            "win_trades": 1,
            "loss_trades": 1,
            "cumulative_return_pct": 0.01,
        }
    )

    win_decision_id = str(uuid.uuid4())
    loss_decision_id = str(uuid.uuid4())

    # Entry decisions backing the two realized rows — outcome_label is set
    # via update_decision_label (mirrors calibration.py's own writer), so
    # thesis_valid's "outcome_label != incorrect" rule has something real to
    # read for one of them, and the not-"incorrect" default is exercised for
    # the other.
    await storage.save_agent_chat_decision(
        {
            "id": win_decision_id,
            "ticker": "005930",
            "stock_name": "삼성전자",
            "trade_date": trade_date,
            "status": "decided",
            "action": "BUY",
            "confidence": 0.7,
            "consensus_level": 0.8,
            "rationale": "돌파",
            "dissenting_opinions": [],
            "entry_price": 70000,
            "stop_loss": None,
            "take_profit": None,
            "position_pct": 0.1,
            "news_sentiment": None,
            "news_count": 0,
            "behavioral_signals": {},
            "market_sentiment": None,
            "flow": None,
        },
        [],
    )
    await storage.update_decision_label(win_decision_id, "correct")

    await storage.save_agent_chat_decision(
        {
            "id": loss_decision_id,
            "ticker": "000660",
            "stock_name": "SK하이닉스",
            "trade_date": trade_date,
            "status": "decided",
            "action": "BUY",
            "confidence": 0.6,
            "consensus_level": 0.6,
            "rationale": "반등",
            "dissenting_opinions": [],
            "entry_price": 100000,
            "stop_loss": None,
            "take_profit": None,
            "position_pct": 0.1,
            "news_sentiment": None,
            "news_count": 0,
            "behavioral_signals": {},
            "market_sentiment": None,
            "flow": None,
        },
        [],
    )
    await storage.update_decision_label(loss_decision_id, "incorrect")

    await storage.save_kr_realized_pnl(
        {
            "id": str(uuid.uuid4()),
            "stk_cd": "005930",
            "entry_price": 70000,
            "exit_price": 72000,
            "quantity": 10,
            "realized_amount": 20000.0,
            "entry_decision_id": win_decision_id,
            "created_at": f"{trade_date} 10:00:00",
        }
    )
    await storage.save_kr_realized_pnl(
        {
            "id": str(uuid.uuid4()),
            "stk_cd": "000660",
            "entry_price": 100000,
            "exit_price": 95000,
            "quantity": 5,
            "realized_amount": -25000.0,
            "entry_decision_id": loss_decision_id,
            "created_at": f"{trade_date} 11:00:00",
        }
    )
    # A row from a DIFFERENT day must not leak into per_stock.
    await storage.save_kr_realized_pnl(
        {
            "id": str(uuid.uuid4()),
            "stk_cd": "035420",
            "entry_price": 200000,
            "exit_price": 210000,
            "quantity": 1,
            "realized_amount": 10000.0,
            "created_at": "2020-01-01 09:00:00",
        }
    )

    await storage.save_agent_calibration(
        {
            "id": str(uuid.uuid4()),
            "agent_type": "technical",
            "as_of_date": trade_date,
            "window_days": 30,
            "decisions_scored": 10,
            "correct": 7,
            "accuracy": 0.7,
            "avg_confidence": 0.65,
        }
    )
    await storage.save_agent_calibration(
        {
            "id": str(uuid.uuid4()),
            "agent_type": "risk",
            "as_of_date": trade_date,
            "window_days": 30,
            "decisions_scored": 10,
            "correct": 4,
            "accuracy": 0.4,
            "avg_confidence": 0.55,
        }
    )

    await storage.save_regime_snapshot(
        {
            "id": regime_id,
            "trade_date": trade_date,
            "breadth_buy": 300,
            "breadth_sell": 100,
            "breadth_hold": 100,
            "breadth_ratio": 0.4,
            "regime_label": "risk_on",
            "source": "scanner",
        }
    )

    return win_decision_id, loss_decision_id


async def test_build_eod_review_assembles_all_sections(tmp_path):
    trade_date = "2026-07-15"
    regime_id = str(uuid.uuid4())
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    win_decision_id, loss_decision_id = await _seed(storage, trade_date, regime_id)
    coordinator = _StubCoordinator(_portfolio_summary())

    report = await build_eod_review(storage, coordinator, trade_date, regime_id)

    assert report["trade_date"] == trade_date

    portfolio = report["portfolio"]
    assert portfolio["equity"] == 500_000_000
    assert portfolio["realized_pnl"] == 50_000
    assert portfolio["net_pnl"] == 50_000
    assert portfolio["win_trades"] == 1
    assert portfolio["loss_trades"] == 1
    assert portfolio["cumulative_return_pct"] == 0.01
    assert portfolio["exposure"] == 20.0
    assert portfolio["concentration"] == 15.0

    per_stock = report["per_stock"]
    assert len(per_stock) == 2
    by_stk = {row["stk_cd"]: row for row in per_stock}
    assert by_stk["005930"]["realized_amount"] == 20000.0
    assert by_stk["005930"]["entry_decision_id"] == win_decision_id
    assert by_stk["005930"]["thesis_valid"] is True
    assert by_stk["000660"]["realized_amount"] == -25000.0
    assert by_stk["000660"]["entry_decision_id"] == loss_decision_id
    assert by_stk["000660"]["thesis_valid"] is False

    agents = report["agents"]
    assert len(agents) == 2
    by_agent = {row["agent_type"]: row for row in agents}
    assert by_agent["technical"]["accuracy"] == 0.7
    assert by_agent["technical"]["decisions_scored"] == 10
    assert by_agent["risk"]["accuracy"] == 0.4

    regime = report["regime"]
    assert regime["label"] == "risk_on"
    assert regime["breadth_ratio"] == 0.4
    assert regime["regime_snapshot_id"] == regime_id


async def test_build_eod_review_degrades_gracefully_when_sources_missing(tmp_path):
    """No data seeded at all, no regime_snapshot_id passed — every section
    must degrade to empty/None rather than raising."""
    trade_date = "2026-07-15"
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    coordinator = _StubCoordinator({})

    report = await build_eod_review(storage, coordinator, trade_date, None)

    assert report["trade_date"] == trade_date
    assert report["portfolio"]["equity"] is None
    assert report["per_stock"] == []
    assert report["agents"] == []
    assert report["regime"]["label"] is None
    assert report["regime"]["regime_snapshot_id"] is None


async def test_build_eod_review_never_raises_when_coordinator_explodes(tmp_path):
    trade_date = "2026-07-15"
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    class _ExplodingCoordinator:
        def get_portfolio_summary(self):
            raise RuntimeError("boom")

    report = await build_eod_review(storage, _ExplodingCoordinator(), trade_date, None)

    # Must degrade (exposure/concentration -> None), not raise or error-out
    # the whole report.
    assert report["trade_date"] == trade_date
    assert "error" not in report
    assert report["portfolio"]["exposure"] is None
    assert report["portfolio"]["concentration"] is None


async def test_save_and_get_eod_review_roundtrip_and_replace(tmp_path):
    trade_date = "2026-07-15"
    regime_id = str(uuid.uuid4())
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    await _seed(storage, trade_date, regime_id)
    coordinator = _StubCoordinator(_portfolio_summary())

    report = await build_eod_review(storage, coordinator, trade_date, regime_id)
    assert await storage.save_eod_review(
        {"trade_date": trade_date, "report_json": json.dumps(report)}
    ) is True

    rows = await storage.get_eod_reviews()
    assert len(rows) == 1
    saved = json.loads(rows[0]["report_json"])
    assert saved["portfolio"]["equity"] == 500_000_000

    # Re-running the same day's review and saving again must UPDATE the
    # existing row (INSERT OR REPLACE), not accrete a second one.
    report2 = dict(report)
    report2["portfolio"] = dict(report["portfolio"])
    report2["portfolio"]["equity"] = 600_000_000
    assert await storage.save_eod_review(
        {"trade_date": trade_date, "report_json": json.dumps(report2)}
    ) is True

    rows2 = await storage.get_eod_reviews()
    assert len(rows2) == 1
    assert json.loads(rows2[0]["report_json"])["portfolio"]["equity"] == 600_000_000
