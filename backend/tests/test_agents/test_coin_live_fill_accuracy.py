"""P2-4 Task P3: coin live executed_volume bug — pins §C priority 3 / §D
verification #5 (partial) of the 2026-07-14 paper-fill-realism audit.

Bug: `_execute_live_order`'s BUY branch recorded
`quantity=executed_volume if executed_volume else float(quantity)` when
persisting the position. Since a Upbit `"wait"` (unfilled/still-open) order
reports `executed_volume=0`, and a partial fill reports something between 0
and the requested amount, the `if executed_volume else <requested>` fallback
only fires on exactly-zero fills — but when it *does* fire, an order that
filled 0% gets recorded as if it filled 100% of the requested quantity. This
mirrors the ledger-corruption bug P0 already fixed on the SELL side
(`fix(coin): 장부오염 봉합`, commit dcd5c44) — SELL was already gated strictly
on `executed_volume > 0`; BUY was not.

Fixture pattern follows test_coin_execution_ledger.py's live-mode section
(real temp-SQLite StorageService, monkeypatched UpbitClient/
UpbitExecutionAdapter — NOT a self-mocking fixture of the thing under test).
"""

import pytest

import services.storage_service as ss
from agents.graph.coin_nodes import coin_execution_node
from app.config import settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


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
        "session_id": "sess-coin-live-fill",
    }
    state.update(overrides)
    return state


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


def _make_fake_execution_adapter(order_state, executed_volume):
    """Build a fake UpbitExecutionAdapter whose `.place()` reports a FIXED
    `executed_volume` regardless of the requested `qty` — lets tests
    simulate an unfilled ("wait", executed_volume=0) or partially-filled
    order distinct from the requested quantity."""
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
                executed_volume=executed_volume,
                price=price,
            )
            return ExecutionResult(success=True, order_id=order.uuid, status=order_state, raw=order)

    return _FakeExecutionAdapter


def _live_mode(monkeypatch, order_state, executed_volume):
    import agents.graph.coin_nodes as coin_nodes_module

    monkeypatch.setattr(settings, "UPBIT_TRADING_MODE", "live")
    monkeypatch.setattr(coin_nodes_module, "UpbitClient", _FakeUpbitClient)
    monkeypatch.setattr(
        coin_nodes_module,
        "UpbitExecutionAdapter",
        _make_fake_execution_adapter(order_state, executed_volume),
    )
    monkeypatch.setattr(coin_nodes_module, "get_upbit_access_key", lambda: "fake-access")
    monkeypatch.setattr(coin_nodes_module, "get_upbit_secret_key", lambda: "fake-secret")


async def test_live_buy_wait_zero_fill_does_not_create_position(temp_storage, monkeypatch):
    """An order still `"wait"`ing with executed_volume=0 (nothing filled at
    all) must NOT create a position — the pre-fix code recorded it as a
    fully-filled 0.1 BTC position via the `else float(quantity)` fallback."""
    _live_mode(monkeypatch, order_state="wait", executed_volume=0)

    await coin_execution_node(_state("BUY", quantity=0.1, entry_price=100_000_000))

    assert await temp_storage.get_coin_position("KRW-BTC") is None


async def test_live_buy_partial_fill_records_actual_executed_volume(temp_storage, monkeypatch):
    """A partially-filled order (0.04 of a requested 0.1) must be recorded
    at its ACTUAL filled quantity, not the requested quantity."""
    _live_mode(monkeypatch, order_state="wait", executed_volume=0.04)

    await coin_execution_node(_state("BUY", quantity=0.1, entry_price=100_000_000))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position is not None
    assert position["quantity"] == pytest.approx(0.04)


async def test_live_buy_full_fill_records_full_executed_volume(temp_storage, monkeypatch):
    """Sanity: a fully-filled ("done") order still records the full
    executed_volume — the fix must not regress the normal-fill case."""
    _live_mode(monkeypatch, order_state="done", executed_volume=0.1)

    await coin_execution_node(_state("BUY", quantity=0.1, entry_price=100_000_000))

    position = await temp_storage.get_coin_position("KRW-BTC")
    assert position is not None
    assert position["quantity"] == pytest.approx(0.1)


async def test_live_buy_zero_fill_does_not_record_inflated_trade_total(temp_storage, monkeypatch):
    """The saved trade record's `total_krw` must reflect the actual (zero)
    fill, not `exec_price * requested_quantity` — the pre-fix code's
    `total_krw` field had the identical `if executed_volume else <requested
    notional>` fallback, so a 0-fill order was recorded as if
    `entry_price * requested_quantity` KRW had actually changed hands."""
    _live_mode(monkeypatch, order_state="wait", executed_volume=0)

    await coin_execution_node(_state("BUY", quantity=0.1, entry_price=100_000_000))

    trades = await temp_storage.get_coin_trades(market="KRW-BTC")
    assert len(trades) == 1
    assert trades[0]["executed_volume"] == pytest.approx(0.0)
    assert trades[0]["total_krw"] == pytest.approx(0.0)
