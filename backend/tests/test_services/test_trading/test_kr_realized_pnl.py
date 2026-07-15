"""Task 4 (Phase1 C3a): KR per-trade realized-P&L ledger + decision outcome
backfill.

KR had no per-trade realized-P&L record anywhere — only the broker's
day-level ka10074 (ephemeral, not matched to entry/exit). This mirrors
`coin_realized_pnl`'s storage shape (save/get) plus a decision-outcome
backfill (`update_decision_outcome`) so an agent-chat decision's eventual
realized P&L can be attributed back to it, and a fire-and-forget wrapper
(`record_kr_realized_pnl`) mirroring `record_trade_fill`'s contract so a
storage failure can never break the sell path.
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

import services.storage_service as ss
from services.storage_service import StorageService
from services.trading import trade_log

pytestmark = pytest.mark.asyncio


# -------------------------------------------
# (a) Storage: save/get round-trip + outcome backfill
# -------------------------------------------


async def test_kr_realized_pnl_roundtrip(tmp_path):
    st = StorageService(db_path=str(tmp_path / "t.db"))
    rid = str(uuid.uuid4())
    record = {
        "id": rid,
        "stk_cd": "005930",
        "entry_price": 70000.0,
        "exit_price": 72000.0,
        "quantity": 10,
        "realized_amount": 20000.0,
        "entry_decision_id": "dec-entry-1",
        "exit_decision_id": "dec-exit-1",
        "holding_period_seconds": 3600,
    }
    assert await st.save_kr_realized_pnl(record) is True

    st2 = StorageService(db_path=str(tmp_path / "t.db"))  # reopen → durable
    got = await st2.get_kr_realized_pnl(stk_cd="005930")
    assert len(got) == 1
    row = got[0]
    assert row["realized_amount"] == 20000.0
    assert row["entry_decision_id"] == "dec-entry-1"
    assert row["exit_decision_id"] == "dec-exit-1"
    assert row["holding_period_seconds"] == 3600
    assert row["entry_price"] == 70000.0
    assert row["exit_price"] == 72000.0
    assert row["quantity"] == 10


async def test_kr_realized_pnl_get_without_filter_returns_all(tmp_path):
    st = StorageService(db_path=str(tmp_path / "t.db"))
    for stk in ("005930", "000660"):
        await st.save_kr_realized_pnl(
            {
                "id": str(uuid.uuid4()),
                "stk_cd": stk,
                "entry_price": 1000.0,
                "exit_price": 1100.0,
                "quantity": 1,
                "realized_amount": 100.0,
            }
        )
    got = await st.get_kr_realized_pnl()
    assert len(got) == 2


async def test_update_decision_outcome_backfills_agent_chat_decisions(tmp_path):
    st = StorageService(db_path=str(tmp_path / "t.db"))
    did = str(uuid.uuid4())
    dec = {
        "id": did,
        "ticker": "005930",
        "stock_name": "삼성전자",
        "trade_date": "2026-07-15",
        "status": "decided",
        "action": "BUY",
        "confidence": 0.7,
        "consensus_level": 0.8,
        "rationale": "돌파",
        "dissenting_opinions": None,
        "entry_price": 70000.0,
        "stop_loss": 65000.0,
        "take_profit": 75000.0,
        "position_pct": 0.1,
        "news_sentiment": "positive",
        "news_count": 3,
        "behavioral_signals": None,
        "market_sentiment": None,
        "flow": None,
    }
    assert await st.save_agent_chat_decision(dec, []) is True

    assert await st.update_decision_outcome(did, 12345.0) is True

    got = await st.get_agent_chat_decisions(ticker="005930")
    assert len(got) == 1
    assert got[0]["outcome_realized_pnl"] == 12345.0


async def test_update_decision_outcome_missing_id_returns_false_not_raise(tmp_path):
    st = StorageService(db_path=str(tmp_path / "t.db"))
    # No matching row — UPDATE affects 0 rows. Must not raise; contract only
    # requires "never breaks the caller", not that it report a hard failure.
    result = await st.update_decision_outcome("nonexistent-id", 1.0)
    assert result in (True, False)


# -------------------------------------------
# (b) Fire-and-forget wrapper — mirrors record_trade_fill's contract
# -------------------------------------------


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _kwargs(**overrides) -> dict:
    base = dict(
        stk_cd="005930",
        entry_price=70000.0,
        exit_price=72000.0,
        quantity=10,
        realized_amount=20000.0,
        entry_decision_id="dec-entry-1",
        exit_decision_id="dec-exit-1",
    )
    base.update(overrides)
    return base


async def test_record_kr_realized_pnl_async_writes_expected_row(temp_storage):
    await trade_log.record_kr_realized_pnl_async(**_kwargs())

    rows = await temp_storage.get_kr_realized_pnl(stk_cd="005930")
    assert len(rows) == 1
    row = rows[0]
    assert row["realized_amount"] == 20000.0
    assert row["entry_decision_id"] == "dec-entry-1"
    assert row["exit_decision_id"] == "dec-exit-1"


async def test_record_kr_realized_pnl_async_persists_holding_period(temp_storage):
    """Important review finding (Phase1 C3a): holding_period_seconds/entry_at/
    exit_at must be captured at write time — the source (ManagedPosition.
    entry_time) is destroyed by _remove_position immediately after, so it's
    capture-now-or-lose-forever. The async core must accept and forward
    these params through to storage."""
    entry_at = datetime(2026, 7, 15, 9, 0, 0)
    exit_at = datetime(2026, 7, 15, 10, 0, 0)

    await trade_log.record_kr_realized_pnl_async(
        **_kwargs(
            entry_at=entry_at,
            exit_at=exit_at,
            holding_period_seconds=3600,
        )
    )

    rows = await temp_storage.get_kr_realized_pnl(stk_cd="005930")
    assert len(rows) == 1
    row = rows[0]
    assert row["holding_period_seconds"] == 3600
    assert row["entry_at"] == entry_at.isoformat(sep=" ")
    assert row["exit_at"] == exit_at.isoformat(sep=" ")


async def test_record_kr_realized_pnl_async_backfills_decision_outcome(
    temp_storage,
):
    did = str(uuid.uuid4())
    dec = {
        "id": did,
        "ticker": "005930",
        "stock_name": "삼성전자",
        "trade_date": "2026-07-15",
        "status": "decided",
        "action": "BUY",
        "confidence": 0.7,
        "consensus_level": 0.8,
        "rationale": "돌파",
        "dissenting_opinions": None,
        "entry_price": 70000.0,
        "stop_loss": 65000.0,
        "take_profit": 75000.0,
        "position_pct": 0.1,
        "news_sentiment": "positive",
        "news_count": 3,
        "behavioral_signals": None,
        "market_sentiment": None,
        "flow": None,
    }
    await temp_storage.save_agent_chat_decision(dec, [])

    await trade_log.record_kr_realized_pnl_async(
        **_kwargs(entry_decision_id=did, realized_amount=5555.0)
    )

    got = await temp_storage.get_agent_chat_decisions(ticker="005930")
    assert got[0]["outcome_realized_pnl"] == 5555.0


async def test_record_kr_realized_pnl_async_never_raises_on_storage_failure(
    monkeypatch,
):
    async def _boom():
        raise RuntimeError("db boom")

    monkeypatch.setattr(ss, "get_storage_service", _boom)

    # Must swallow the failure — a recording failure can never break the
    # caller's trading flow (mirrors record_trade_fill_async's contract).
    await trade_log.record_kr_realized_pnl_async(**_kwargs())


async def test_record_kr_realized_pnl_schedules_background_task_and_writes(
    temp_storage,
):
    trade_log.record_kr_realized_pnl(**_kwargs(stk_cd="000660"))
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_realized_pnl(stk_cd="000660")
    assert len(rows) == 1


async def test_record_kr_realized_pnl_without_running_loop_logs_and_does_not_raise(
    monkeypatch,
):
    monkeypatch.setattr(
        trade_log.asyncio,
        "get_running_loop",
        MagicMock(side_effect=RuntimeError("no running loop")),
    )

    # Must not raise even without an event loop to schedule onto.
    trade_log.record_kr_realized_pnl(**_kwargs())
