"""F3 t5: KR execution node must confirm the ACTUAL fill (ka10076) before
reporting a position — an accepted order is not a filled order. Before this
fix the node assumed placement==fill and fabricated a ghost position for the
full requested quantity even when the broker hadn't filled it yet.

Fixture pattern follows `tests/test_services/test_f3_fill_tracking.py`: a
minimal fake Kiwoom client returning real `OrderResponse`/`FilledOrder`
Pydantic models, `asyncio.sleep` patched away so the (3 attempts / 0.5s
interval) confirm-fill poll doesn't slow the suite.

Coordinator side effects (`register_fill_as_position`, `fill_tracker.register`)
are mocked at their origin modules — this node uses LAZY in-node imports
(mirrors `kr_stock_nodes/decision_nodes.py`'s WATCH-list pattern), so the
patch target is the source module, not the node module's namespace.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.graph.kr_stock_nodes.execution import kr_stock_execution_node
from services.kiwoom.models import FilledOrder, OrderResponse
from services.trading.models import StopLossMode
from services.trading.pending_order_tracker import TrackedOrder

pytestmark = pytest.mark.asyncio


async def _no_sleep(_seconds):
    return None


class _FakeKiwoomClient:
    """Minimal Kiwoom client: places an order, reports fills from a fixed
    ka10076 snapshot (or raises, to simulate a query failure)."""

    def __init__(
        self,
        filled_orders=None,
        raise_on_query=False,
        ord_no="ORD1",
        reject_placement=False,
    ):
        self._filled_orders = filled_orders if filled_orders is not None else []
        self._raise_on_query = raise_on_query
        self._ord_no = ord_no
        self._reject_placement = reject_placement
        self.buy_calls = []
        self.sell_calls = []
        self.fill_query_calls = 0

    def _order_response(self):
        if self._reject_placement:
            # Real broker-rejection shape: return_code != 0, empty ord_no.
            # KiwoomExecutionAdapter.place does NOT raise on this — it returns
            # ExecutionResult(success=False); the node must branch on it.
            return OrderResponse(ord_no="", return_code=1, return_msg="주문 거부: 증거금 부족")
        return OrderResponse(ord_no=self._ord_no, return_code=0, return_msg="정상")

    async def place_buy_order(self, stk_cd, qty, price=None, order_type=None):
        self.buy_calls.append((stk_cd, qty, price))
        return self._order_response()

    async def place_sell_order(self, stk_cd, qty, price=None, order_type=None):
        self.sell_calls.append((stk_cd, qty, price))
        return self._order_response()

    async def get_filled_orders(self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True):
        self.fill_query_calls += 1
        if self._raise_on_query:
            raise RuntimeError("ka10076 query boom")
        return list(self._filled_orders)


def _filled(ord_no, qty, price, buy_sell_tp="매수"):
    return FilledOrder(
        ord_no=ord_no,
        stk_cd="005930",
        stk_nm="삼성전자",
        ccld_qty=qty,
        ccld_uv=price,
        ccld_amt=qty * price,
        ccld_dt="",
        ccld_tm="",
        buy_sell_tp=buy_sell_tp,
    )


def _state(action="BUY", quantity=10, entry_price=70000, existing_position=None, **overrides):
    state = {
        "approval_status": "approved",
        "trade_proposal": {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "action": action,
            "entry_price": entry_price,
            "quantity": quantity,
            "stop_loss": 66500,
            "take_profit": 77000,
            # KRStockTradeProposal scale: float 0-1. The coordinator layer
            # (TrackedOrder / ManagedPosition) uses int 1-10; the node converts
            # via int(x * 10), the same convention as decision_nodes.py:330.
            "risk_score": 0.6,
        },
        "existing_position": existing_position,
        "reasoning_log": [],
        "session_id": "sess-1",
    }
    state.update(overrides)
    return state


def _mock_coordinator():
    coordinator = MagicMock()
    coordinator.fill_tracker = MagicMock()
    coordinator.fill_tracker.register = MagicMock()
    coordinator._schedule_persist = MagicMock()
    coordinator.risk_params = MagicMock()
    coordinator.risk_params.stop_loss_mode = StopLossMode.AGENT_AUTO
    return coordinator


def _patches(client, coordinator):
    """Common patch stack: broker client + trading coordinator + the
    registration helper (mocked at its own module, matching the lazy-import
    convention used by register_fill_as_position's own test suite)."""
    return (
        patch("agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async", AsyncMock(return_value=client)),
        patch("app.dependencies.get_trading_coordinator", AsyncMock(return_value=coordinator)),
        patch("services.trading.position_registration.register_fill_as_position", new_callable=AsyncMock),
    )


# ---------------------------------------------------------------------------
# Broker rejection — adapter returns success=False WITHOUT raising
# ---------------------------------------------------------------------------

async def test_broker_rejection_fails_without_phantom_tracking(monkeypatch):
    """A broker-rejected placement (return_code != 0, empty ord_no) must take
    the node's existing failure path: execution_status "failed", NO fill
    confirmation poll, NO TrackedOrder (a phantom "" ord_no would be polled
    against real ka10076 and expire at close as '미체결 만료' for an order the
    broker refused), NO position, NO registration."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(reject_placement=True)
    coordinator = _mock_coordinator()
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "failed"
    assert "error" in result
    assert result.get("active_position") is None
    # Rejection short-circuits BEFORE fill confirmation — no ka10076 calls.
    assert client.fill_query_calls == 0
    mock_register.assert_not_awaited()
    coordinator.fill_tracker.register.assert_not_called()
    coordinator._schedule_persist.assert_not_called()


# ---------------------------------------------------------------------------
# (a) Full fill
# ---------------------------------------------------------------------------

async def test_full_fill_registers_position_and_completes(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(filled_orders=[_filled("ORD1", 10, 70000)])
    coordinator = _mock_coordinator()
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "completed"
    assert result["active_position"]["quantity"] == 10
    mock_register.assert_awaited_once()
    kwargs = mock_register.call_args.kwargs
    assert kwargs["ticker"] == "005930"
    assert kwargs["quantity"] == 10
    assert kwargs["session_id"] == "sess-1"
    # Parity with coordinator.py:1560-1561 (_poll_tracked_fills): position
    # registers with the coordinator's stop_loss_mode + the proposal's risk.
    assert kwargs["stop_loss_mode"] == StopLossMode.AGENT_AUTO
    assert kwargs["risk_score"] == 6  # int(0.6 * 10)
    # Nothing left unfilled — no remainder tracked, nothing new to persist.
    coordinator.fill_tracker.register.assert_not_called()
    coordinator._schedule_persist.assert_not_called()


# ---------------------------------------------------------------------------
# (b) Zero fill
# ---------------------------------------------------------------------------

async def test_zero_fill_tracks_remainder_no_ghost_position(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(filled_orders=[])
    coordinator = _mock_coordinator()
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "placed_pending_fill"
    assert result.get("active_position") is None
    mock_register.assert_not_awaited()
    coordinator.fill_tracker.register.assert_called_once()
    tracked = coordinator.fill_tracker.register.call_args.args[0]
    assert isinstance(tracked, TrackedOrder)
    assert tracked.ord_no == "ORD1"
    assert tracked.ticker == "005930"
    assert tracked.side == "buy"
    assert tracked.total_quantity == 10
    assert tracked.filled_quantity == 0
    assert tracked.stop_loss == 66500
    assert tracked.take_profit == 77000
    assert tracked.source_session_id == "sess-1"
    assert tracked.trade_date == date.today().strftime("%Y%m%d")
    assert tracked.risk_score == 6  # threaded from the proposal (0.6 -> 6)
    # A memory-only TrackedOrder dies with the process — registration must
    # schedule the coordinator's blob persistence (the R5-P1 mechanism).
    coordinator._schedule_persist.assert_called_once()


# ---------------------------------------------------------------------------
# (c) Partial fill
# ---------------------------------------------------------------------------

async def test_partial_fill_registers_confirmed_qty_and_tracks_remainder(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(filled_orders=[_filled("ORD1", 4, 70000)])
    coordinator = _mock_coordinator()
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "completed"
    assert result["active_position"]["quantity"] == 4
    mock_register.assert_awaited_once()
    assert mock_register.call_args.kwargs["quantity"] == 4
    coordinator.fill_tracker.register.assert_called_once()
    tracked = coordinator.fill_tracker.register.call_args.args[0]
    assert tracked.filled_quantity == 4
    assert tracked.total_quantity == 10
    coordinator._schedule_persist.assert_called_once()


# ---------------------------------------------------------------------------
# (d) Fill-confirm query exception -> treated as zero fill
# ---------------------------------------------------------------------------

async def test_fill_confirm_query_exception_treated_as_zero_fill(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(raise_on_query=True)
    coordinator = _mock_coordinator()
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "placed_pending_fill"
    assert result.get("active_position") is None
    mock_register.assert_not_awaited()
    coordinator.fill_tracker.register.assert_called_once()
    tracked = coordinator.fill_tracker.register.call_args.args[0]
    assert tracked.filled_quantity == 0


# ---------------------------------------------------------------------------
# ADD / REDUCE — "same principle" (execution.py:271-300 originally)
# ---------------------------------------------------------------------------

async def test_add_partial_fill_averages_confirmed_qty_only(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(filled_orders=[_filled("ORD1", 8, 72000)])
    coordinator = _mock_coordinator()
    existing = {
        "quantity": 50,
        "entry_price": 70000,
        "stop_loss": 66500,
        "take_profit": 77000,
    }
    state = _state(action="ADD", quantity=20, entry_price=72000, existing_position=existing)
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(state)

    assert result["execution_status"] == "completed"
    # 50 existing + 8 CONFIRMED (not the requested 20) = 58
    assert result["active_position"]["quantity"] == 58
    mock_register.assert_awaited_once()
    assert mock_register.call_args.kwargs["quantity"] == 8
    coordinator.fill_tracker.register.assert_called_once()
    tracked = coordinator.fill_tracker.register.call_args.args[0]
    assert tracked.filled_quantity == 8
    assert tracked.total_quantity == 20


async def test_add_zero_fill_leaves_existing_position_untouched(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(filled_orders=[])
    coordinator = _mock_coordinator()
    existing = {
        "quantity": 50,
        "entry_price": 70000,
        "stop_loss": 66500,
        "take_profit": 77000,
    }
    state = _state(action="ADD", quantity=20, entry_price=72000, existing_position=existing)
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(state)

    assert result["execution_status"] == "placed_pending_fill"
    assert result.get("active_position") is None
    mock_register.assert_not_awaited()
    coordinator.fill_tracker.register.assert_called_once()


async def test_reduce_partial_fill_uses_confirmed_qty_no_buy_side_coordinator_calls(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(filled_orders=[_filled("ORD1", 12, 71000, buy_sell_tp="매도")])
    coordinator = _mock_coordinator()
    existing = {
        "quantity": 100,
        "entry_price": 65000,
        "stop_loss": 60000,
        "take_profit": 75000,
    }
    state = _state(action="REDUCE", quantity=30, entry_price=71000, existing_position=existing)
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(state)

    assert result["execution_status"] == "completed"
    # 100 existing - 12 CONFIRMED (not the requested 30) = 88
    assert result["active_position"]["quantity"] == 88
    # Sell-side fills never go through the BUY-oriented registration helper,
    # and unfilled SELL remainders are explicitly out of scope (R5-P4).
    mock_register.assert_not_awaited()
    coordinator.fill_tracker.register.assert_not_called()


async def test_reduce_zero_fill_leaves_existing_position_untouched(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(filled_orders=[])
    coordinator = _mock_coordinator()
    existing = {
        "quantity": 100,
        "entry_price": 65000,
        "stop_loss": 60000,
        "take_profit": 75000,
    }
    state = _state(action="REDUCE", quantity=30, entry_price=71000, existing_position=existing)
    p1, p2, p3 = _patches(client, coordinator)
    with p1, p2, p3 as mock_register:
        result = await kr_stock_execution_node(state)

    assert result["execution_status"] == "placed_pending_fill"
    assert result.get("active_position") is None
    mock_register.assert_not_awaited()
    coordinator.fill_tracker.register.assert_not_called()


# ---------------------------------------------------------------------------
# Coordinator failure must never crash the graph run
# ---------------------------------------------------------------------------

async def test_coordinator_failure_is_boxed_execution_status_still_honest(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(filled_orders=[_filled("ORD1", 10, 70000)])
    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(side_effect=RuntimeError("coordinator boom")),
    ):
        result = await kr_stock_execution_node(_state())

    # The coordinator side effect failed, but the graph run must still
    # complete with an honest status reflecting the CONFIRMED fill.
    assert result["execution_status"] == "completed"
    assert result["active_position"]["quantity"] == 10
