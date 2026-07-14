"""P2-4 Task P0: coin ledger corruption — pins the three bugs identified by
the 2026-07-14 paper-fill-realism audit (§B point 1) against a real
(temp-SQLite) StorageService, calling the actual `coin_execution_node`
end-to-end (paper trading mode, the default).

Bugs pinned:
(a) Autonomous SELL never touched the ledger — the position-save call in
    `_execute_paper_order` was gated inside `if side == "bid":` (buy only),
    so a sold coin position stayed "held" forever at the old avg price.
(b) `save_coin_position` used `INSERT OR REPLACE`, so a second BUY of the
    same market overwrote avg_entry_price/quantity with the last buy
    instead of a weighted average.
(c) No coin realized-P&L record was ever persisted on close.

Fixture pattern follows test_kr_execution_trade_log.py (real StorageService
backed by an isolated temp-SQLite db, monkeypatched into the
get_storage_service() singleton) — NOT a self-mocking fixture, since that
was exactly the failure mode the Paper-Proof Phase A audit called out.
"""

import pytest

import services.storage_service as ss
from agents.graph.coin_nodes import coin_execution_node
from app.config import settings, paper_fill_settings

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
    """Deployed .env sets UPBIT_TRADING_MODE=live (Phase C live coin
    autotrade) — force paper mode for these tests so they exercise
    `_execute_paper_order` deterministically, regardless of the running
    environment's mode. Live-path coverage is separate, below."""
    monkeypatch.setattr(settings, "UPBIT_TRADING_MODE", "paper")


@pytest.fixture(autouse=True)
def _zero_coin_fee(monkeypatch):
    """P2-4 Task P1 added a non-zero conservative default coin_fee_bps,
    which would otherwise perturb every exact-value assertion in this file
    (all written before fees existed, at P0). This file's job is to pin
    the P0 ledger-structure bugs (SELL persistence, weighted averaging,
    realized-P&L existence) in isolation from the fee dimension — fee
    behavior itself is covered separately in test_coin_fill_fees.py.
    Zeroing the rate here keeps every assertion below byte-for-byte
    identical to P0, proving Task P1 did not disturb P0's ledger math."""
    monkeypatch.setattr(paper_fill_settings, "coin_fee_bps", 0.0)


@pytest.fixture(autouse=True)
def _no_live_refetch_or_slippage(monkeypatch):
    """P2-4 Task P2 added a live-price re-fetch + adverse slippage to
    `_execute_paper_order` (`_fetch_live_coin_price` + `slippage_bps`),
    which would otherwise perturb every exact-value assertion in this file
    (all written before either existed, at P0). Isolate this file to the
    ledger-structure dimension by short-circuiting the re-fetch to return
    exactly the `entry_price` each call already passes as its fallback —
    the same price these assertions were written against — and zeroing
    slippage. Price-refetch/slippage behavior itself is covered separately
    in test_coin_fill_slippage.py."""
    import agents.graph.coin_nodes as coin_nodes_module

    async def _identity_fetch(market, fallback):
        return fallback

    monkeypatch.setattr(coin_nodes_module, "_fetch_live_coin_price", _identity_fetch)
    monkeypatch.setattr(paper_fill_settings, "slippage_bps", 0.0)


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
        "session_id": "sess-coin-1",
    }
    state.update(overrides)
    return state


# -------------------------------------------
# (a) autonomous SELL must update the ledger
# -------------------------------------------


async def test_autonomous_sell_removes_position_on_full_exit(temp_storage):
    # Seed an open position (as if a prior BUY had run).
    await coin_execution_node(_state("BUY", quantity=0.1, entry_price=100_000_000))
    assert await temp_storage.get_coin_position("KRW-BTC") is not None

    # Autonomous SELL of the full quantity at a higher price.
    await coin_execution_node(_state("SELL", quantity=0.1, entry_price=110_000_000))

    # The phantom-holding bug: before the fix, SELL never touched the
    # ledger, so this position would still be present at the old avg price.
    positions = await temp_storage.get_coin_positions()
    assert all(p["market"] != "KRW-BTC" for p in positions)
    assert await temp_storage.get_coin_position("KRW-BTC") is None


async def test_autonomous_sell_decrements_position_on_partial_exit(temp_storage):
    await coin_execution_node(_state("BUY", quantity=1.0, entry_price=100_000_000))

    # Sell only 40% of the position.
    await coin_execution_node(_state("SELL", quantity=0.4, entry_price=110_000_000))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position is not None
    assert position["quantity"] == pytest.approx(0.6)
    # Partial exit must not touch the remaining lot's avg entry price.
    assert position["avg_entry_price"] == pytest.approx(100_000_000)


async def test_autonomous_sell_with_no_open_position_is_a_noop(temp_storage):
    # No prior BUY — a stray SELL must not create a phantom short position
    # or blow up the node.
    result = await coin_execution_node(_state("SELL", quantity=0.1, entry_price=110_000_000))

    assert result["execution_status"] == "completed"
    assert await temp_storage.get_coin_position("KRW-BTC") is None


# -------------------------------------------
# (b) repeated BUY must weighted-average, not overwrite
# -------------------------------------------


async def test_repeated_buy_averages_entry_price_not_last_price(temp_storage):
    await coin_execution_node(_state("BUY", quantity=1.0, entry_price=100_000_000))
    await coin_execution_node(_state("BUY", quantity=1.0, entry_price=120_000_000))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position is not None
    assert position["quantity"] == pytest.approx(2.0)
    # Weighted average of (1.0 @ 100M) + (1.0 @ 120M) = 110M.
    # Before the fix (INSERT OR REPLACE), this would be 120M (the last buy).
    assert position["avg_entry_price"] == pytest.approx(110_000_000)


async def test_repeated_buy_uneven_quantities_weighted_correctly(temp_storage):
    await coin_execution_node(_state("BUY", quantity=3.0, entry_price=100))
    await coin_execution_node(_state("BUY", quantity=1.0, entry_price=300))

    position = await temp_storage.get_coin_position("KRW-BTC")
    # (3*100 + 1*300) / 4 = 150
    assert position["quantity"] == pytest.approx(4.0)
    assert position["avg_entry_price"] == pytest.approx(150)


# -------------------------------------------
# (c) coin close must persist a realized-P&L record
# -------------------------------------------


async def test_coin_close_persists_realized_pnl_record(temp_storage):
    await coin_execution_node(_state("BUY", quantity=0.5, entry_price=100_000_000))
    await coin_execution_node(_state("SELL", quantity=0.5, entry_price=120_000_000))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    record = records[0]
    assert record["market"] == "KRW-BTC"
    assert record["entry_price"] == pytest.approx(100_000_000)
    assert record["exit_price"] == pytest.approx(120_000_000)
    assert record["quantity"] == pytest.approx(0.5)
    # (120M - 100M) * 0.5 = 10,000,000 realized gain.
    assert record["realized_amount"] == pytest.approx(10_000_000)


async def test_coin_partial_close_realized_pnl_uses_sold_quantity_only(temp_storage):
    await coin_execution_node(_state("BUY", quantity=1.0, entry_price=100_000_000))
    await coin_execution_node(_state("SELL", quantity=0.4, entry_price=90_000_000))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    record = records[0]
    assert record["quantity"] == pytest.approx(0.4)
    # (90M - 100M) * 0.4 = -4,000,000 realized loss.
    assert record["realized_amount"] == pytest.approx(-4_000_000)


async def test_no_realized_pnl_record_when_sell_has_no_open_position(temp_storage):
    await coin_execution_node(_state("SELL", quantity=0.1, entry_price=110_000_000))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert records == []


# -------------------------------------------
# Live-path coverage — the deployed .env has UPBIT_TRADING_MODE=live for
# coin (Phase C autonomous coin trading), so `_execute_live_order` is the
# code path actually running in production right now. It has the exact
# same "only handles side == bid" bug as the paper path.
# -------------------------------------------


class _FakeOrder:
    def __init__(self, uuid, market, side, state, executed_volume, price, paid_fee=0):
        self.uuid = uuid
        self.market = market
        self.side = side
        self.state = state
        self.executed_volume = executed_volume
        self.price = price
        self.paid_fee = paid_fee


class _FakeUpbitClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_fake_execution_adapter(order_state="done"):
    """Build a fake UpbitExecutionAdapter class whose `.place()` fills the
    full requested quantity at the requested price (mirrors a normal
    successful live order for these ledger tests)."""
    from services.execution.models import ExecutionResult

    class _FakeExecutionAdapter:
        def __init__(self, client):
            self._client = client

        async def place(self, *, ticker, side, qty, price=None, order_type=None):
            from services.execution.models import ExecutionSide

            native_side = "bid" if side == ExecutionSide.BUY else "ask"
            order = _FakeOrder(
                uuid=f"live-{native_side}-1",
                market=ticker,
                side=native_side,
                state=order_state,
                executed_volume=qty,
                price=price,
            )
            return ExecutionResult(success=True, order_id=order.uuid, status=order_state, raw=order)

    return _FakeExecutionAdapter


@pytest.fixture
def _live_mode(monkeypatch):
    """Force live trading mode and stub out the Upbit client/adapter so the
    live coin-execution path runs with no network access."""
    import agents.graph.coin_nodes as coin_nodes_module

    monkeypatch.setattr(settings, "UPBIT_TRADING_MODE", "live")
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _FakeUpbitClient)
    monkeypatch.setattr(
        coin_nodes_module, "UpbitExecutionAdapter", _make_fake_execution_adapter("done")
    )
    monkeypatch.setattr(
        coin_nodes_module, "get_upbit_access_key", lambda: "fake-access"
    )
    monkeypatch.setattr(
        coin_nodes_module, "get_upbit_secret_key", lambda: "fake-secret"
    )


async def test_live_autonomous_sell_removes_position_on_full_exit(temp_storage, _live_mode):
    await coin_execution_node(_state("BUY", quantity=0.1, entry_price=100_000_000))
    assert await temp_storage.get_coin_position("KRW-BTC") is not None

    await coin_execution_node(_state("SELL", quantity=0.1, entry_price=110_000_000))

    assert await temp_storage.get_coin_position("KRW-BTC") is None


async def test_live_autonomous_sell_persists_realized_pnl(temp_storage, _live_mode):
    await coin_execution_node(_state("BUY", quantity=0.1, entry_price=100_000_000))
    await coin_execution_node(_state("SELL", quantity=0.1, entry_price=110_000_000))

    records = await temp_storage.get_coin_realized_pnl(market="KRW-BTC")
    assert len(records) == 1
    assert records[0]["realized_amount"] == pytest.approx(1_000_000)
