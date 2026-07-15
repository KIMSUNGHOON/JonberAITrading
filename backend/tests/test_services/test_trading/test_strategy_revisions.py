"""Phase3 T1: strategy_revisions ledger — save/get roundtrip, ordering,
single-id lookup, failure-harmless writes.

Mirrors test_eod_orchestrator.py's isolation pattern: real StorageService
on a tmp_path db (never the live backend/data/storage.db).
"""

import json

import pytest

from services.storage_service import StorageService

pytestmark = pytest.mark.asyncio


def _make_record(rid: str, trade_date: str = "2026-07-15", **overrides) -> dict:
    record = {
        "id": rid,
        "trade_date": trade_date,
        "source": "eod_consensus",
        "stance": "defensive",
        "consensus_level": 0.72,
        "changed": 1,
        "strategy_json": json.dumps({"name": "EOD 적응형 전략"}),
        "parent_revision_id": None,
        "rationale": "테스트 근거",
        "votes_json": json.dumps([{"panelist": "risk_officer", "stance": "defensive"}]),
        "regime_snapshot_id": "regime-1",
    }
    record.update(overrides)
    return record


async def test_save_and_get_roundtrip(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    assert await storage.save_strategy_revision(_make_record("rev-1")) is True

    rows = await storage.get_strategy_revisions()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "rev-1"
    assert row["source"] == "eod_consensus"
    assert row["stance"] == "defensive"
    assert row["consensus_level"] == pytest.approx(0.72)
    assert row["changed"] == 1
    assert json.loads(row["strategy_json"])["name"] == "EOD 적응형 전략"
    assert row["rationale"] == "테스트 근거"
    assert row["created_at"] is not None


async def test_get_revisions_newest_first_and_limit(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    for i in range(3):
        await storage.save_strategy_revision(
            _make_record(f"rev-{i}", trade_date=f"2026-07-1{i}")
        )
    rows = await storage.get_strategy_revisions(limit=2)
    assert len(rows) == 2
    # created_at DESC, id DESC 타이브레이크 — 같은 초에 저장돼도 최신 삽입이 먼저
    assert rows[0]["id"] == "rev-2"
    assert rows[1]["id"] == "rev-1"


async def test_get_single_revision_by_id(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await storage.save_strategy_revision(_make_record("rev-a"))
    await storage.save_strategy_revision(_make_record("rev-b"))

    row = await storage.get_strategy_revision("rev-a")
    assert row is not None and row["id"] == "rev-a"
    assert await storage.get_strategy_revision("no-such-id") is None


async def test_save_missing_required_is_failure_harmless(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    # strategy_json NOT NULL 위반 — False를 반환할 뿐 절대 raise하지 않는다
    bad = _make_record("rev-bad")
    bad["strategy_json"] = None
    assert await storage.save_strategy_revision(bad) is False
    assert await storage.get_strategy_revisions() == []


async def test_nullable_fields_roundtrip_none(tmp_path):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    rec = _make_record(
        "rev-manual", source="manual", stance=None, consensus_level=None,
        votes_json=None, regime_snapshot_id=None, changed=0,
    )
    assert await storage.save_strategy_revision(rec) is True
    row = await storage.get_strategy_revision("rev-manual")
    assert row["stance"] is None
    assert row["consensus_level"] is None
    assert row["changed"] == 0
