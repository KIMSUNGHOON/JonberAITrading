"""P2-4 Task P1: coin paper trading fee simulation.

Background: coin paper trading has NO broker ledger — the app's own SQLite
storage IS the ledger (unlike KR, where the mock broker already deducts its
own commission+tax) — so `docs/superpowers/audits/
2026-07-14-paper-fill-realism-audit.md` (§C priority 1) calls for the
round-trip coin fee to be simulated directly in `_execute_paper_order`
(paper branch only — live uses real Upbit fills).

Fixture pattern follows test_coin_execution_ledger.py (P0): real
StorageService backed by an isolated temp-SQLite db, monkeypatched into the
get_storage_service() singleton, NOT a self-mocking fixture.
"""

import pytest

import services.storage_service as ss
from agents.graph.coin_nodes import coin_execution_node
from app.config import paper_fill_settings, settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


@pytest.fixture(autouse=True)
def _force_paper_mode(monkeypatch):
    monkeypatch.setattr(settings, "UPBIT_TRADING_MODE", "paper")


@pytest.fixture(autouse=True)
def _known_fee_rate(monkeypatch):
    """Deterministic, round-number fee rate for exact arithmetic in these
    tests — independent of whatever the real conservative default is
    tuned to later."""
    monkeypatch.setattr(paper_fill_settings, "coin_fee_bps", 10.0)  # 0.10%
    yield


def _state(action, market="KRW-BTC", entry_price=100_000_000, quantity=0.1, **overrides):
    state = {
        "approval_status": "approved",
        "trade_proposal": {
            "market": market,
            "action": action,
            "entry_price": entry_price,
            "quantity": quantity,
            "stop_loss": entry_price * 0.95,
            "take_profit": entry_price * 1.1,
        },
        "reasoning_log": [],
        "session_id": "sess-coin-fee-1",
    }
    state.update(overrides)
    return state


# -------------------------------------------
# BUY: fee is added to cost basis
# -------------------------------------------


async def test_buy_bakes_fee_into_stored_avg_entry_price(temp_storage):
    entry_price = 100_000_000
    quantity = 0.1
    await coin_execution_node(_state("BUY", entry_price=entry_price, quantity=quantity))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position is not None

    fee = entry_price * quantity * (10.0 / 10_000)  # 0.10% of notional
    expected_avg_entry_price = entry_price + fee / quantity
    assert position["avg_entry_price"] == pytest.approx(expected_avg_entry_price)
    assert position["avg_entry_price"] > entry_price  # strictly more expensive than raw price


async def test_buy_records_nonzero_fee_and_fee_inclusive_total_krw(temp_storage):
    entry_price = 100_000_000
    quantity = 0.1
    await coin_execution_node(_state("BUY", entry_price=entry_price, quantity=quantity))

    trades = await temp_storage.get_coin_trades(market="KRW-BTC")
    assert len(trades) == 1
    trade = trades[0]

    fee = entry_price * quantity * (10.0 / 10_000)
    assert trade["fee"] == pytest.approx(fee)
    assert trade["fee"] > 0
    # total_krw (cash OUT) includes the fee paid, on top of the notional.
    assert trade["total_krw"] == pytest.approx(entry_price * quantity + fee)


async def test_repeated_buy_still_weighted_averages_with_fee_included(temp_storage):
    """P0's weighted-average logic must still work correctly once fed a
    fee-inclusive incoming price for each buy."""
    await coin_execution_node(_state("BUY", quantity=1.0, entry_price=100_000_000))
    await coin_execution_node(_state("BUY", quantity=1.0, entry_price=120_000_000))

    position = await temp_storage.get_coin_position("KRW-BTC")
    fee1 = 100_000_000 * 1.0 * (10.0 / 10_000)
    fee2 = 120_000_000 * 1.0 * (10.0 / 10_000)
    price1 = 100_000_000 + fee1 / 1.0
    price2 = 120_000_000 + fee2 / 1.0
    expected_avg = (1.0 * price1 + 1.0 * price2) / 2.0

    assert position["quantity"] == pytest.approx(2.0)
    assert position["avg_entry_price"] == pytest.approx(expected_avg)


# -------------------------------------------
# SELL/close: round-trip fee subtracted from realized_amount
# -------------------------------------------


async def test_sell_realized_pnl_is_net_of_round_trip_fee(temp_storage):
    entry_price = 100_000_000
    exit_price = 120_000_000
    quantity = 0.5

    await coin_execution_node(_state("BUY", entry_price=entry_price, quantity=quantity))
    await coin_execution_node(_state("SELL", entry_price=exit_price, quantity=quantity))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    realized = records[0]["realized_amount"]

    gross = (exit_price - entry_price) * quantity  # 10,000,000
    entry_fee = entry_price * quantity * (10.0 / 10_000)
    exit_fee = exit_price * quantity * (10.0 / 10_000)
    expected_net = gross - entry_fee - exit_fee

    assert realized == pytest.approx(expected_net)
    # The core TDD assertion: net realized must be strictly less than gross
    # by exactly the round-trip fee amount.
    assert realized < gross
    assert (gross - realized) == pytest.approx(entry_fee + exit_fee)


async def test_sell_with_zero_fee_matches_p0_baseline_exactly(temp_storage, monkeypatch):
    """Sanity check against the P0 baseline test
    (test_coin_close_persists_realized_pnl_record): with fee_bps=0, this
    module's fee logic must degrade to exactly P0's pre-fee behavior."""
    monkeypatch.setattr(paper_fill_settings, "coin_fee_bps", 0.0)

    await coin_execution_node(_state("BUY", quantity=0.5, entry_price=100_000_000))
    await coin_execution_node(_state("SELL", quantity=0.5, entry_price=120_000_000))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert records[0]["realized_amount"] == pytest.approx(10_000_000)


async def test_partial_close_realized_pnl_fee_uses_matched_quantity_only(temp_storage):
    """Selling more than is actually held must charge fee on the MATCHED
    quantity only, not the raw over-sized sell request."""
    await coin_execution_node(_state("BUY", quantity=1.0, entry_price=100_000_000))
    # Attempt to sell more than held.
    await coin_execution_node(_state("SELL", quantity=1.5, entry_price=110_000_000))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    record = records[0]
    assert record["quantity"] == pytest.approx(1.0)  # matched, not the requested 1.5

    gross = (110_000_000 - 100_000_000) * 1.0
    entry_fee = 100_000_000 * 1.0 * (10.0 / 10_000)
    exit_fee = 110_000_000 * 1.0 * (10.0 / 10_000)  # fee on matched qty only
    assert record["realized_amount"] == pytest.approx(gross - entry_fee - exit_fee)


# -------------------------------------------
# Display: calculate_position_pnl (coin/helpers.py) nets out the projected
# exit fee for an open (unsold) position.
# -------------------------------------------


async def test_calculate_position_pnl_nets_out_projected_exit_fee():
    from app.api.routes.coin.helpers import calculate_position_pnl

    quantity, avg_entry_price, current_price = 0.5, 100_000_000, 120_000_000
    _, unrealized_pnl, _ = calculate_position_pnl(quantity, avg_entry_price, current_price)

    gross = (current_price - avg_entry_price) * quantity
    projected_exit_fee = current_price * quantity * (10.0 / 10_000)
    assert unrealized_pnl == pytest.approx(gross - projected_exit_fee)
    assert unrealized_pnl < gross
