"""P2-4 Task P2: coin paper adverse slippage + entry re-fetch.

Background: `docs/superpowers/audits/2026-07-14-paper-fill-realism-audit.md`
(§C priority 2) found `_execute_paper_order` reused a STALE
`ticker.trade_price` captured at ANALYSIS time as the fill price, even
though HITL approval can take minutes/hours — silently erasing whatever the
market moved during the delay (a counterfactual "filled at the analysis-time
price"). The fix: (a) RE-FETCH the current price at execution time via
`UpbitClient.get_ticker`, then (b) apply ADVERSE slippage by side — BUY
fills at `live_price * (1 + slippage_bps/10000)`, SELL at
`live_price * (1 - slippage_bps/10000)` — using `paper_fill_settings.
slippage_bps` (added at P1). This stacks with P1's fee (fee is charged on
the slipped fill price, not the stale one).

Fixture pattern follows test_coin_execution_ledger.py (P0)/test_coin_fill_
fees.py (P1): real StorageService backed by an isolated temp-SQLite db,
monkeypatched into the get_storage_service() singleton — NOT a self-mocking
fixture. `UpbitClient` (the actual network-call site `_fetch_live_coin_price`
uses) is faked per-test so the "re-fetched" price is deterministic AND
provably distinct from the proposal's stale `entry_price`.
"""

import pytest
import structlog.testing

import agents.graph.coin_nodes as coin_nodes_module
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
def _zero_fee(monkeypatch):
    """Isolate the slippage dimension from P1's fee — fee stacking is
    covered by its own dedicated test below, with fee re-enabled there."""
    monkeypatch.setattr(paper_fill_settings, "coin_fee_bps", 0.0)


@pytest.fixture(autouse=True)
def _known_slippage_rate(monkeypatch):
    monkeypatch.setattr(paper_fill_settings, "slippage_bps", 100.0)  # 1.00%


class _FakeTicker:
    def __init__(self, trade_price):
        self.trade_price = trade_price


def _fake_upbit_client_class(live_price):
    """Stub for the QUOTATION-only `get_ticker` call `_fetch_live_coin_price`
    makes — proves the re-fetch actually goes through the real network-call
    site, not just an internal helper mock."""

    class _FakeUpbitClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_ticker(self, markets):
            return [_FakeTicker(trade_price=live_price)]

    return _FakeUpbitClient


def _fake_upbit_client_raising(exc):
    """Stub for the network-failure branch: `get_ticker` raises."""

    class _FakeUpbitClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get_ticker(self, markets):
            raise exc

    return _FakeUpbitClient


def _fake_upbit_client_empty():
    """Stub for the network-degrade branch: `get_ticker` returns `[]`."""

    class _FakeUpbitClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get_ticker(self, markets):
            return []

    return _FakeUpbitClient


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
        "session_id": "sess-coin-slippage-1",
    }
    state.update(overrides)
    return state


# -------------------------------------------
# BUY: fills ABOVE the re-fetched live price
# -------------------------------------------


async def test_buy_fills_above_refetched_live_price_by_slippage_bps(temp_storage, monkeypatch):
    stale_analysis_price = 100_000_000
    live_price = 105_000_000  # market moved up during HITL approval delay
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(live_price))

    await coin_execution_node(_state("BUY", entry_price=stale_analysis_price, quantity=0.1))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position is not None

    expected_fill = live_price * 1.01  # +100 bps adverse for BUY
    assert position["avg_entry_price"] == pytest.approx(expected_fill)
    assert position["avg_entry_price"] > live_price


async def test_buy_uses_refetched_price_not_stale_analysis_time_price(temp_storage, monkeypatch):
    """The core TDD assertion: the fill must track the RE-FETCHED live
    price, not the proposal's stale analysis-time entry_price."""
    stale_analysis_price = 100_000_000
    live_price = 130_000_000  # far from the stale price
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(live_price))

    await coin_execution_node(_state("BUY", entry_price=stale_analysis_price, quantity=0.1))

    position = await temp_storage.get_coin_position("KRW-BTC")
    # Must be anchored to live_price (+ slippage), nowhere near the stale price.
    assert position["avg_entry_price"] == pytest.approx(live_price * 1.01)
    assert position["avg_entry_price"] != pytest.approx(stale_analysis_price)


# -------------------------------------------
# SELL: fills BELOW the re-fetched live price
# -------------------------------------------


async def test_sell_fills_below_refetched_live_price_by_slippage_bps(temp_storage, monkeypatch):
    entry_price = 100_000_000
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(entry_price))
    await coin_execution_node(_state("BUY", entry_price=entry_price, quantity=0.1))

    stale_exit_price = 120_000_000
    live_exit_price = 115_000_000  # market moved down during approval delay
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(live_exit_price))

    await coin_execution_node(_state("SELL", entry_price=stale_exit_price, quantity=0.1))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    exit_price = records[0]["exit_price"]

    expected_fill = live_exit_price * 0.99  # -100 bps adverse for SELL
    assert exit_price == pytest.approx(expected_fill)
    assert exit_price < live_exit_price
    assert exit_price != pytest.approx(stale_exit_price)


# -------------------------------------------
# Slippage stacks with P1 fee (both applied to the same fill)
# -------------------------------------------


async def test_slippage_stacks_with_fee_on_buy(temp_storage, monkeypatch):
    monkeypatch.setattr(paper_fill_settings, "coin_fee_bps", 10.0)  # re-enable fee (0.10%)
    live_price = 100_000_000
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(live_price))

    quantity = 0.1
    await coin_execution_node(_state("BUY", entry_price=90_000_000, quantity=quantity))

    position = await temp_storage.get_coin_position("KRW-BTC")
    slipped_fill = live_price * 1.01
    fee = slipped_fill * quantity * (10.0 / 10_000)
    expected_avg_entry_price = slipped_fill + fee / quantity

    assert position["avg_entry_price"] == pytest.approx(expected_avg_entry_price)
    # Strictly worse than the live price alone, and worse still than a
    # slippage-only fill — both costs are present, not just one.
    assert position["avg_entry_price"] > slipped_fill


async def test_slippage_stacks_with_fee_on_sell(temp_storage, monkeypatch):
    monkeypatch.setattr(paper_fill_settings, "coin_fee_bps", 10.0)  # re-enable fee (0.10%)
    entry_live_price = 100_000_000
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(entry_live_price))
    quantity = 0.1
    await coin_execution_node(_state("BUY", entry_price=95_000_000, quantity=quantity))

    exit_live_price = 120_000_000
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(exit_live_price))
    await coin_execution_node(_state("SELL", entry_price=125_000_000, quantity=quantity))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    realized = records[0]["realized_amount"]

    entry_fill = entry_live_price * 1.01
    entry_fee = entry_fill * quantity * (10.0 / 10_000)
    stored_entry_price = entry_fill + entry_fee / quantity

    exit_fill = exit_live_price * 0.99
    exit_fee = exit_fill * quantity * (10.0 / 10_000)

    expected_realized = (exit_fill - stored_entry_price) * quantity - exit_fee
    assert realized == pytest.approx(expected_realized)


# -------------------------------------------
# Regression: with slippage_bps=0 the fill degrades to the re-fetched live
# price exactly (proves the slippage math itself, isolated from re-fetch).
# -------------------------------------------


async def test_zero_slippage_fills_exactly_at_refetched_live_price(temp_storage, monkeypatch):
    monkeypatch.setattr(paper_fill_settings, "slippage_bps", 0.0)
    live_price = 111_000_000
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(live_price))

    await coin_execution_node(_state("BUY", entry_price=100_000_000, quantity=0.1))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position["avg_entry_price"] == pytest.approx(live_price)


# -------------------------------------------
# P2 review LOW finding (P2-4 P4a): the network-failure degrade branch in
# `_fetch_live_coin_price` — `get_ticker` raises, or returns `[]` — had ZERO
# coverage. Per the review, the degraded path is STALE PRICE + slippage
# still applied (not a full reversion to a raw, un-slipped fill), and the
# failure must not crash the trade.
# -------------------------------------------


async def test_get_ticker_raises_degrades_to_stale_price_with_slippage_and_logs_warning(
    temp_storage, monkeypatch
):
    stale_entry_price = 100_000_000
    monkeypatch.setattr(
        coin_nodes_module,
        "UpbitClient",
        _fake_upbit_client_raising(ConnectionError("upbit unreachable")),
    )

    with structlog.testing.capture_logs() as logs:
        result = await coin_execution_node(
            _state("BUY", entry_price=stale_entry_price, quantity=0.1)
        )

    # No exception propagated out of the node — the trade still completed.
    assert result["execution_status"] == "completed"

    # Degrades to the stale proposal price, with slippage still applied ON
    # TOP of it (not a bare, un-slipped stale fill).
    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position is not None
    expected_fill = stale_entry_price * 1.01  # +100 bps adverse for BUY
    assert position["avg_entry_price"] == pytest.approx(expected_fill)

    # The failure is logged, not swallowed silently.
    warnings = [e for e in logs if e.get("event") == "coin_paper_live_price_refetch_failed"]
    assert len(warnings) == 1
    assert warnings[0]["market"] == "KRW-BTC"


async def test_get_ticker_empty_response_degrades_to_stale_price_with_slippage(
    temp_storage, monkeypatch
):
    stale_entry_price = 100_000_000
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_empty())

    result = await coin_execution_node(_state("BUY", entry_price=stale_entry_price, quantity=0.1))

    # No exception propagated out of the node — the trade still completed.
    assert result["execution_status"] == "completed"

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position is not None
    expected_fill = stale_entry_price * 1.01  # +100 bps adverse for BUY
    assert position["avg_entry_price"] == pytest.approx(expected_fill)


async def test_get_ticker_raises_on_sell_degrades_to_stale_price_with_slippage(
    temp_storage, monkeypatch
):
    """Same degrade path, exercised on the SELL/exit-leg side (adverse
    slippage direction is inverted vs. BUY)."""
    entry_price = 100_000_000
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _fake_upbit_client_class(entry_price))
    await coin_execution_node(_state("BUY", entry_price=entry_price, quantity=0.1))

    stale_exit_price = 120_000_000
    monkeypatch.setattr(
        coin_nodes_module,
        "UpbitClient",
        _fake_upbit_client_raising(TimeoutError("upbit timed out")),
    )

    result = await coin_execution_node(_state("SELL", entry_price=stale_exit_price, quantity=0.1))
    assert result["execution_status"] == "completed"

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    expected_fill = stale_exit_price * 0.99  # -100 bps adverse for SELL
    assert records[0]["exit_price"] == pytest.approx(expected_fill)
