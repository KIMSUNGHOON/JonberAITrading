"""L1 (decision lineage restoration, 2026-07-19): agent_chat_decisions
promoted to the durable ledger for BOTH the agent-chat debate path AND the
LangGraph analysis/execution path. `persist_analysis_decision` is the
write helper for the latter -- L2 calls it just before graph-path order
placement so kr_stock_trades.decision_id can finally be threaded (today it
is 100% NULL for that path, see spec D1).

Covers (brief Step 1):
1. persist -> get round trip: decision_source='analysis', session_ref
   threaded, id is a fresh uuid4.
2. storage exception during the write -> None, never raises (never-raise
   contract -- a ledger-write failure must not block order placement).
3. mixed agent_chat + analysis rows coexist in get_agent_chat_decisions,
   and the new `source` filter separates them (NULL/agent_chat rows use
   the D1-stated COALESCE(NULL, 'agent_chat') fallback).
4. label_and_calibrate's per-agent aggregation naturally excludes analysis
   rows (they have no backing agent_chat_votes rows) even when mixed into
   the same decisions scan -- pinning D1's "no calibration-side guard
   needed" call.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from services.storage_service import StorageService
from services.trading.calibration import label_and_calibrate
from services.trading.decision_ledger import persist_analysis_decision

pytestmark = pytest.mark.asyncio


async def test_persist_analysis_decision_roundtrip(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-abc123",
        ticker="005930",
        action="BUY",
        confidence=0.71,
        rationale="그래프 승인 발주",
    )

    assert decision_id is not None
    # must be a fresh uuid4 -- round-trips via uuid.UUID without error.
    assert uuid.UUID(decision_id).version == 4

    rows = await storage.get_agent_chat_decisions(ticker="005930")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == decision_id
    assert row["decision_source"] == "analysis"
    assert row["session_ref"] == "sess-abc123"
    assert row["action"] == "BUY"
    assert row["confidence"] == pytest.approx(0.71)
    assert row["rationale"] == "그래프 승인 발주"


async def test_persist_analysis_decision_never_raises_on_storage_failure():
    storage = AsyncMock()
    storage.save_agent_chat_decision.side_effect = RuntimeError("db locked")

    decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-xyz",
        ticker="000660",
        action="SELL",
        confidence=None,
        rationale=None,
    )

    assert decision_id is None
    storage.save_agent_chat_decision.assert_awaited_once()


async def test_persist_analysis_decision_returns_none_on_save_failure(tmp_path):
    # save_agent_chat_decision returns False (its own internal except path)
    # rather than raising -- persist_analysis_decision must treat that the
    # same as an exception: None, no propagation.
    storage = AsyncMock()
    storage.save_agent_chat_decision.return_value = False

    decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-false",
        ticker="005930",
        action="HOLD",
        confidence=0.5,
        rationale="test",
    )

    assert decision_id is None


async def test_mixed_sources_coexist_and_source_filter_separates_them(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    # Pre-existing agent_chat row (normal debate-path write -- never sets
    # decision_source/session_ref, so both land NULL).
    agent_chat_id = str(uuid.uuid4())
    await storage.save_agent_chat_decision(
        {
            "id": agent_chat_id,
            "ticker": "005930",
            "trade_date": "2026-07-19",
            "status": "decided",
            "action": "BUY",
            "confidence": 0.8,
            "consensus_level": 0.9,
            "rationale": "토론 합의",
        },
        [],
    )

    analysis_id = await persist_analysis_decision(
        storage,
        session_id="sess-mixed",
        ticker="005930",
        action="ADD",
        confidence=0.65,
        rationale="분석 경로",
    )
    assert analysis_id is not None

    # No filter: byte-unchanged existing behavior -- both rows come back.
    all_rows = await storage.get_agent_chat_decisions(ticker="005930")
    assert {r["id"] for r in all_rows} == {agent_chat_id, analysis_id}

    # decision_source is NULL on the pre-existing row (D1 fallback: NULL ==
    # 'agent_chat', not backfilled).
    by_id = {r["id"]: r for r in all_rows}
    assert by_id[agent_chat_id]["decision_source"] is None
    assert by_id[analysis_id]["decision_source"] == "analysis"

    # source filter: 'analysis' only matches the explicitly-tagged row.
    analysis_rows = await storage.get_agent_chat_decisions(
        ticker="005930", source="analysis"
    )
    assert {r["id"] for r in analysis_rows} == {analysis_id}

    # source filter: 'agent_chat' matches the NULL row via the stated
    # COALESCE(decision_source, 'agent_chat') fallback.
    agent_chat_rows = await storage.get_agent_chat_decisions(
        ticker="005930", source="agent_chat"
    )
    assert {r["id"] for r in agent_chat_rows} == {agent_chat_id}


async def test_calibration_naturally_excludes_analysis_rows_from_per_agent(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    as_of_date = "2026-07-19"

    # Normal agent_chat decision WITH a backing vote -- must be scored.
    agent_chat_id = str(uuid.uuid4())
    await storage.save_agent_chat_decision(
        {
            "id": agent_chat_id,
            "ticker": "005930",
            "trade_date": as_of_date,
            "status": "decided",
            "action": "BUY",
            "confidence": 0.7,
            "consensus_level": 0.8,
            "rationale": "test",
        },
        [
            {
                "decision_id": agent_chat_id,
                "agent_type": "technical",
                "vote": "buy",
                "confidence": 0.7,
            },
        ],
    )
    await storage.update_decision_outcome(agent_chat_id, 10_000.0)

    # Analysis-path decision (persisted via persist_analysis_decision, so it
    # has NO backing agent_chat_votes rows) that also gets an outcome
    # backfilled -- e.g. by L2's future wiring. Must still count toward the
    # top-level decisions_scored (outcome labeling is source-agnostic), but
    # must NOT contribute to any agent's per-agent accuracy since it has no
    # votes to score.
    analysis_id = await persist_analysis_decision(
        storage,
        session_id="sess-cal",
        ticker="005930",
        action="BUY",
        confidence=0.6,
        rationale="analysis path",
    )
    assert analysis_id is not None
    await storage.update_decision_outcome(analysis_id, 20_000.0)

    result = await label_and_calibrate(storage, as_of_date)

    # Both decisions got labeled (outcome backfill/labeling is source-blind).
    assert result["decisions_scored"] == 2

    # Only 'technical' appears -- the analysis row contributed no votes to
    # any agent's per-agent stats, so it is naturally excluded rather than
    # needing a source-based guard in calibration.py.
    per_agent = result["per_agent_accuracy"]
    assert set(per_agent.keys()) == {"technical"}
    assert per_agent["technical"]["decisions_scored"] == 1


# -------------------------------------------
# I3 (final-review fix): persist_analysis_decision must stamp `trade_date`
# (KST "today", "%Y-%m-%d" -- the same format app/api/routes/trading.py's
# own trade_date default and calibration._within_window both use) on every
# analysis-path decision row. Pre-fix, `trade_date` was never set at all
# (always NULL) -- calibration._within_window fail-opens on a missing
# trade_date (always included, by design, for a genuinely unknown date), so
# an analysis decision silently bypassed `window_days` entirely regardless
# of how stale it actually was.
# -------------------------------------------


async def test_persist_analysis_decision_sets_trade_date_kst_today(tmp_path):
    from datetime import datetime, timedelta, timezone

    storage = StorageService(db_path=str(tmp_path / "t.db"))

    decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-td",
        ticker="005930",
        action="BUY",
        confidence=0.5,
        rationale="trade_date coverage",
    )
    assert decision_id is not None

    rows = await storage.get_agent_chat_decisions(ticker="005930")
    assert len(rows) == 1
    expected = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    assert rows[0]["trade_date"] == expected


async def test_persist_analysis_decision_threads_optional_stock_name(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-sn",
        ticker="005930",
        action="BUY",
        confidence=0.5,
        rationale="stock_name coverage",
        stock_name="삼성전자",
    )
    assert decision_id is not None

    rows = await storage.get_agent_chat_decisions(ticker="005930")
    assert rows[0]["stock_name"] == "삼성전자"


async def test_persist_analysis_decision_stock_name_defaults_to_none(tmp_path):
    """Existing callers (this file's other tests, none of which pass
    stock_name) must stay byte-for-byte unchanged."""
    storage = StorageService(db_path=str(tmp_path / "t.db"))

    decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-sn-none",
        ticker="005930",
        action="BUY",
        confidence=0.5,
        rationale="test",
    )
    rows = await storage.get_agent_chat_decisions(ticker="005930")
    assert rows[0]["stock_name"] is None


async def test_stale_analysis_decision_excluded_from_calibration_window(
    tmp_path, monkeypatch
):
    """I3 regression: `label_and_calibrate`'s 30-day (default) window must
    correctly EXCLUDE a stale analysis-path decision now that trade_date is
    actually populated -- pre-fix, the missing trade_date fail-opened
    _within_window (always True), so a decision from 31+ days ago was
    silently scored on every calibration run regardless of window_days.

    Monkeypatches decision_ledger's own KST-today helper (not calibration)
    to simulate a decision persisted 31 days before `as_of_date` -- proves
    the fix end-to-end through the REAL persist_analysis_decision function,
    not a hand-rolled row."""
    import services.trading.decision_ledger as decision_ledger_module

    as_of_date = "2026-07-19"
    stale_trade_date = "2026-06-18"  # 31 days before as_of -> outside [cutoff, as_of]

    monkeypatch.setattr(
        decision_ledger_module, "_trade_date_kst_today", lambda: stale_trade_date
    )

    storage = StorageService(db_path=str(tmp_path / "t.db"))
    decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-stale",
        ticker="005930",
        action="BUY",
        confidence=0.5,
        rationale="stale decision",
    )
    assert decision_id is not None
    await storage.update_decision_outcome(decision_id, 10_000.0)

    result = await label_and_calibrate(storage, as_of_date, window_days=30)

    # Excluded entirely: not scored, and never labeled.
    assert result["decisions_scored"] == 0
    row = (await storage.get_agent_chat_decisions(ticker="005930"))[0]
    assert row["outcome_label"] is None


async def test_recent_analysis_decision_included_in_calibration_window(
    tmp_path, monkeypatch
):
    """Sanity counterpart to the exclusion test above: a decision inside the
    window (10 days before as_of) must still be scored -- the fix narrows
    the window correctly rather than excluding everything."""
    import services.trading.decision_ledger as decision_ledger_module

    as_of_date = "2026-07-19"
    recent_trade_date = "2026-07-09"  # 10 days before as_of -> inside window

    monkeypatch.setattr(
        decision_ledger_module, "_trade_date_kst_today", lambda: recent_trade_date
    )

    storage = StorageService(db_path=str(tmp_path / "t.db"))
    decision_id = await persist_analysis_decision(
        storage,
        session_id="sess-recent",
        ticker="005930",
        action="BUY",
        confidence=0.5,
        rationale="recent decision",
    )
    assert decision_id is not None
    await storage.update_decision_outcome(decision_id, 10_000.0)

    result = await label_and_calibrate(storage, as_of_date, window_days=30)

    assert result["decisions_scored"] == 1
    row = (await storage.get_agent_chat_decisions(ticker="005930"))[0]
    assert row["outcome_label"] == "correct"
