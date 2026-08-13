"""Phase 2 Task 1: per-agent calibration + decision outcome labeling.

Phase 1 backfills `outcome_realized_pnl` onto the entry decision but leaves
`outcome_label` nullable and never scores which agent's vote was actually
right. This covers `label_and_calibrate`: given closed decisions (non-null
outcome_realized_pnl) with known votes, it must label each decision
(correct/incorrect/flat against the config-driven flat_threshold) and
persist an exact per-agent accuracy/avg_confidence snapshot.

Decisions are seeded via `save_agent_chat_decision` (the normal write path)
then have their outcome backfilled via `update_decision_outcome` — mirroring
exactly how Phase 1's real close-position flow populates
outcome_realized_pnl before this task's calibration ever runs.

Expected values worked by hand against the default EOD_FLAT_THRESHOLD_KRW
(10_000.0, see app/config.py):
  - decision a: outcome=+10_000 -> abs(10_000) is NOT < 10_000 -> "correct"
    votes: technical=buy (bullish, hits since outcome>0),
           risk=sell (bearish, misses since outcome>0),
           moderator=strong_buy (excluded entirely — moderator never votes)
  - decision b: outcome=-50_000 -> "incorrect"
    votes: technical=buy (bullish, misses since outcome<0),
           risk=abstain (excluded — abstain never scores)
  - decision c: outcome=+5_000 -> abs(5_000) < 10_000 -> "flat"
    votes: sentiment=hold (neutral, hits since label=="flat")

  => technical: scored=2, correct=1 (a) -> accuracy=0.5, avg_confidence=0.7
  => risk:      scored=1, correct=0     -> accuracy=0.0, avg_confidence=0.7
  => sentiment: scored=1, correct=1     -> accuracy=1.0, avg_confidence=0.9
  => moderator: must not appear at all in per_agent_accuracy.
"""

import uuid

import pytest

from services.storage_service import StorageService
from services.trading.calibration import label_and_calibrate

pytestmark = pytest.mark.asyncio

AS_OF_DATE = "2026-07-15"


def _decision(decision_id: str, action: str = "BUY") -> dict:
    return {
        "id": decision_id,
        "ticker": "005930",
        "stock_name": "삼성전자",
        "trade_date": AS_OF_DATE,
        "status": "decided",
        "action": action,
        "confidence": 0.7,
        "consensus_level": 0.8,
        "rationale": "test",
    }


async def _seed(storage: StorageService) -> dict:
    ids = {"a": str(uuid.uuid4()), "b": str(uuid.uuid4()), "c": str(uuid.uuid4())}

    await storage.save_agent_chat_decision(
        _decision(ids["a"]),
        [
            {
                "decision_id": ids["a"],
                "agent_type": "technical",
                "vote": "buy",
                "confidence": 0.8,
            },
            {
                "decision_id": ids["a"],
                "agent_type": "risk",
                "vote": "sell",
                "confidence": 0.7,
            },
            {
                "decision_id": ids["a"],
                "agent_type": "moderator",
                "vote": "strong_buy",
                "confidence": 0.9,
            },
        ],
    )
    await storage.update_decision_outcome(ids["a"], 10_000.0)

    await storage.save_agent_chat_decision(
        _decision(ids["b"]),
        [
            {
                "decision_id": ids["b"],
                "agent_type": "technical",
                "vote": "buy",
                "confidence": 0.6,
            },
            {
                "decision_id": ids["b"],
                "agent_type": "risk",
                "vote": "abstain",
                "confidence": 0.5,
            },
        ],
    )
    await storage.update_decision_outcome(ids["b"], -50_000.0)

    await storage.save_agent_chat_decision(
        _decision(ids["c"]),
        [
            {
                "decision_id": ids["c"],
                "agent_type": "sentiment",
                "vote": "hold",
                "confidence": 0.9,
            },
        ],
    )
    await storage.update_decision_outcome(ids["c"], 5_000.0)

    return ids


async def test_label_and_calibrate_labels_each_decision(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    ids = await _seed(storage)

    result = await label_and_calibrate(storage, AS_OF_DATE)
    assert result["decisions_scored"] == 3

    decisions = {
        d["id"]: d for d in await storage.get_agent_chat_decisions(ticker="005930")
    }
    assert decisions[ids["a"]]["outcome_label"] == "correct"
    assert decisions[ids["b"]]["outcome_label"] == "incorrect"
    assert decisions[ids["c"]]["outcome_label"] == "flat"


async def test_label_and_calibrate_per_agent_accuracy(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    await _seed(storage)

    result = await label_and_calibrate(storage, AS_OF_DATE)
    per_agent = result["per_agent_accuracy"]

    assert per_agent["technical"]["decisions_scored"] == 2
    assert per_agent["technical"]["correct"] == 1
    assert per_agent["technical"]["accuracy"] == 0.5
    assert per_agent["technical"]["avg_confidence"] == pytest.approx(0.7)

    assert per_agent["risk"]["decisions_scored"] == 1
    assert per_agent["risk"]["correct"] == 0
    assert per_agent["risk"]["accuracy"] == 0.0
    assert per_agent["risk"]["avg_confidence"] == pytest.approx(0.7)

    assert per_agent["sentiment"]["decisions_scored"] == 1
    assert per_agent["sentiment"]["correct"] == 1
    assert per_agent["sentiment"]["accuracy"] == 1.0
    assert per_agent["sentiment"]["avg_confidence"] == pytest.approx(0.9)

    # moderator never votes and abstain never scores -> neither appears.
    assert "moderator" not in per_agent


async def test_label_and_calibrate_persists_calibration_rows(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    await _seed(storage)

    await label_and_calibrate(storage, AS_OF_DATE, window_days=30)

    rows = {r["agent_type"]: r for r in await storage.get_agent_calibration(AS_OF_DATE)}
    assert set(rows.keys()) == {"technical", "risk", "sentiment"}

    assert rows["technical"]["decisions_scored"] == 2
    assert rows["technical"]["correct"] == 1
    assert rows["technical"]["accuracy"] == pytest.approx(0.5)
    assert rows["technical"]["window_days"] == 30
    assert rows["technical"]["as_of_date"] == AS_OF_DATE

    assert rows["risk"]["accuracy"] == pytest.approx(0.0)
    assert rows["sentiment"]["accuracy"] == pytest.approx(1.0)

    # get_agent_calibration() with no filter must also surface the same rows.
    all_rows = await storage.get_agent_calibration()
    assert len(all_rows) == 3


async def test_label_and_calibrate_invalid_date_is_failure_harmless(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "t.db"))
    result = await label_and_calibrate(storage, "not-a-date")
    assert result == {}
