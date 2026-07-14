"""P2-4 Task P0: StorageService-level coin ledger fixes.

Pins the storage-layer half of the coin ledger corruption fix directly
against StorageService (independent of coin_nodes.py, which
tests/test_agents/test_coin_execution_ledger.py covers end-to-end):

(b) `save_coin_position` weighted-averaging repeat buys instead of
    `INSERT OR REPLACE` overwriting avg_entry_price/quantity with the last
    buy.
(c) new `save_coin_realized_pnl`/`get_coin_realized_pnl` methods — coin had
    no realized-P&L record at all before this.

Same temp-db pattern as test_storage_trades.py.
"""

from datetime import datetime

import pytest
import pytest_asyncio

import services.storage_service as ss

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def temp_storage(tmp_path):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    yield storage


def _position(**overrides) -> dict:
    record = {
        "market": "KRW-BTC",
        "currency": "BTC",
        "quantity": 1.0,
        "avg_entry_price": 100_000_000,
        "stop_loss": 95_000_000,
        "take_profit": 110_000_000,
        "session_id": "sess-1",
    }
    record.update(overrides)
    return record


async def test_first_buy_inserts_position_as_is(temp_storage):
    ok = await temp_storage.save_coin_position(_position())
    assert ok is True

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position["quantity"] == pytest.approx(1.0)
    assert position["avg_entry_price"] == pytest.approx(100_000_000)


async def test_second_buy_weighted_averages_not_overwrites(temp_storage):
    await temp_storage.save_coin_position(_position(quantity=1.0, avg_entry_price=100_000_000))
    await temp_storage.save_coin_position(_position(quantity=1.0, avg_entry_price=120_000_000))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position["quantity"] == pytest.approx(2.0)
    # Before the fix (INSERT OR REPLACE), this would be 120,000,000 (the
    # last buy overwriting the first entirely).
    assert position["avg_entry_price"] == pytest.approx(110_000_000)


async def test_third_buy_continues_weighted_average(temp_storage):
    await temp_storage.save_coin_position(_position(quantity=3.0, avg_entry_price=100))
    await temp_storage.save_coin_position(_position(quantity=1.0, avg_entry_price=300))
    await temp_storage.save_coin_position(_position(quantity=4.0, avg_entry_price=200))

    # (3*100 + 1*300 + 4*200) / 8 = 175
    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position["quantity"] == pytest.approx(8.0)
    assert position["avg_entry_price"] == pytest.approx(175)


async def test_buy_after_full_close_starts_fresh_average(temp_storage):
    await temp_storage.save_coin_position(_position(quantity=1.0, avg_entry_price=100_000_000))
    await temp_storage.delete_coin_position("KRW-BTC")

    # A brand-new position after a full close should NOT average against
    # the closed lot (quantity is 0 in storage, but the row itself was
    # deleted so there's nothing to combine with anyway).
    await temp_storage.save_coin_position(_position(quantity=2.0, avg_entry_price=200_000_000))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position["quantity"] == pytest.approx(2.0)
    assert position["avg_entry_price"] == pytest.approx(200_000_000)


async def test_buy_lowercase_market_still_averages_against_existing(temp_storage):
    """Market keys are uppercased at graph entry (coin_state.py), but the
    storage method itself should not silently double-count a
    differently-cased market as a separate position."""
    await temp_storage.save_coin_position(_position(market="KRW-BTC", quantity=1.0, avg_entry_price=100))
    await temp_storage.save_coin_position(_position(market="krw-btc", quantity=1.0, avg_entry_price=300))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position["quantity"] == pytest.approx(2.0)
    assert position["avg_entry_price"] == pytest.approx(200)


def _realized(**overrides) -> dict:
    record = {
        "id": "r1",
        "session_id": "sess-1",
        "market": "KRW-BTC",
        "entry_price": 100_000_000,
        "exit_price": 120_000_000,
        "quantity": 0.5,
        "realized_amount": 10_000_000,
        "created_at": datetime(2026, 7, 14, 9, 5, 0),
    }
    record.update(overrides)
    return record


async def test_save_and_get_realized_pnl_round_trips(temp_storage):
    ok = await temp_storage.save_coin_realized_pnl(_realized())
    assert ok is True

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    record = records[0]
    assert record["market"] == "KRW-BTC"
    assert record["entry_price"] == pytest.approx(100_000_000)
    assert record["exit_price"] == pytest.approx(120_000_000)
    assert record["quantity"] == pytest.approx(0.5)
    assert record["realized_amount"] == pytest.approx(10_000_000)
    assert record["session_id"] == "sess-1"


async def test_get_realized_pnl_filters_by_market(temp_storage):
    await temp_storage.save_coin_realized_pnl(_realized(id="r1", market="KRW-BTC"))
    await temp_storage.save_coin_realized_pnl(_realized(id="r2", market="KRW-ETH"))

    btc_records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert [r["id"] for r in btc_records] == ["r1"]


async def test_get_realized_pnl_ordered_newest_first(temp_storage):
    await temp_storage.save_coin_realized_pnl(
        _realized(id="r1", created_at=datetime(2026, 7, 14, 9, 0, 0))
    )
    await temp_storage.save_coin_realized_pnl(
        _realized(id="r2", created_at=datetime(2026, 7, 14, 9, 5, 0))
    )

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert [r["id"] for r in records] == ["r2", "r1"]


async def test_get_realized_pnl_empty_when_none_saved(temp_storage):
    assert await temp_storage.get_coin_realized_pnl() == []
    assert await temp_storage.get_coin_realized_pnl(market="KRW-BTC") == []
