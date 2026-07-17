"""E1-1: SELL/REDUCE unfilled-remainder registration via `_track_unfilled`.

Real incident: the ledger recorded 41 sold shares against a real 155-share
broker sell (114주 missing) because fill-tracker registration was BUY-only
(F3 gate `if side == OrderSide.BUY and result.status in ("pending",
"partial")`) — the 30s ka10076 poll never learned about SELL remainders.

This closes that gap: the F3 BUY block is generalized into
`ExecutionCoordinator._track_unfilled`, a side-agnostic helper that
`on_trade_approved` now calls for BOTH the BUY path and the SELL/REDUCE
order-result. BUY behavior must stay byte-identical through the helper —
pinned here (test 4) AND by the pre-existing `test_f3_fill_tracking.py`
suite staying GREEN (the real evidence, per the task brief).

`_poll_tracked_fills`'s sell POST-fill handling (closing/reducing a managed
position) is E1-2's job. This file only pins the temporary safety guard
that keeps a newly-tracked sell fill from flowing into
`register_fill_as_position` — which increases a position and would double-
count a sell as a buy if left unguarded (test 5).
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.storage_service as ss
from services.kiwoom.models import FilledOrder
from services.trading.coordinator import ExecutionCoordinator
from services.trading.market_hours import MarketSession
from services.trading.models import (
    AllocationPlan,
    OrderResult,
    OrderSide,
    TradingMode,
)
from services.trading.pending_order_tracker import TrackedOrder

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton
    (same pattern as test_f3_fill_tracking.py)."""
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _open_session() -> MarketSession:
    return MarketSession(
        is_open=True,
        current_time=datetime.now(),
        next_open=None,
        next_close=None,
        message="open",
    )


def _live_coordinator(side: OrderSide, quantity: int) -> ExecutionCoordinator:
    """A coordinator wired to execute immediately, with allocation quantity
    fixed via a mocked `calculate_allocation` — mirrors
    test_r5_p0_autotrade_safety._live_coordinator. The order's REAL side is
    driven by `on_trade_approved`'s own `_order_side_for_action(action)`, not
    by this mock's `.side` (see coordinator.py's `order = OrderRequest(...,
    side=side, ...)`), so the mock's side value here is cosmetic."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.mode = TradingMode.ACTIVE
    coord._market_hours.get_market_session = MagicMock(return_value=_open_session())
    coord._refresh_account_info = AsyncMock()
    coord.portfolio_agent.calculate_allocation = MagicMock(
        return_value=AllocationPlan(
            ticker="005930",
            stock_name="삼성전자",
            side=side,
            quantity=quantity,
            entry_price=260_000,
            estimated_amount=quantity * 260_000,
            position_pct=1.0,
            rationale="stub allocation",
            rebalance_orders=[],
        )
    )
    return coord


def _stub_execute_order(coord, requested, filled, status, order_id, avg_price=260_000):
    async def _exec(order):
        return OrderResult(
            order_id=order_id,
            ticker=order.ticker,
            side=order.side,
            requested_quantity=requested,
            filled_quantity=filled,
            avg_price=avg_price,
            status=status,
        )

    coord._execute_order = _exec


# -------------------------------------------
# 1) SELL pending/partial registers with side="sell"
# -------------------------------------------


async def test_partial_sell_registers_tracked_order_with_sell_side(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=144)
    _stub_execute_order(coord, requested=144, filled=37, status="partial", order_id="SELL1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=144,
    )

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "sell"
    assert order.ord_no == "SELL1"
    assert order.total_quantity == 144
    assert order.filled_quantity == 37
    assert order.source_session_id == "s1"


# -------------------------------------------
# 2) SELL fully filled -> nothing registered
# -------------------------------------------


async def test_full_sell_does_not_register(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=144)
    _stub_execute_order(coord, requested=144, filled=144, status="filled", order_id="SELL2")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="SELL",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=144,
    )

    assert coord.fill_tracker.tracking() == []


# -------------------------------------------
# 3) REDUCE (partial exit) registers its own remainder too
# -------------------------------------------


async def test_partial_reduce_registers_tracked_order(temp_storage):
    coord = _live_coordinator(OrderSide.SELL, quantity=50)
    _stub_execute_order(coord, requested=50, filled=10, status="partial", order_id="REDUCE1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="REDUCE",
        entry_price=260_000,
        stop_loss=None,
        take_profit=None,
        risk_score=5,
        quantity_override=50,
    )

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "sell"
    assert order.total_quantity == 50
    assert order.filled_quantity == 10


# -------------------------------------------
# 4) BUY path through the shared helper stays unchanged — smoke-level pin;
#    full BUY coverage (incl. split parts) lives in test_f3_fill_tracking.py,
#    which staying GREEN is the byte-equivalence evidence for the refactor.
# -------------------------------------------


async def test_partial_buy_still_registers_with_buy_side(temp_storage):
    coord = _live_coordinator(OrderSide.BUY, quantity=144)
    _stub_execute_order(coord, requested=144, filled=37, status="partial", order_id="BUY1")

    await coord.on_trade_approved(
        session_id="s1",
        ticker="005930",
        stock_name="삼성전자",
        action="BUY",
        entry_price=260_000,
        stop_loss=246_560,
        take_profit=289_440,
        risk_score=5,
        quantity_override=144,
    )

    tracking = coord.fill_tracker.tracking()
    assert len(tracking) == 1
    order = tracking[0]
    assert order.side == "buy"
    assert order.stop_loss == 246_560
    assert order.take_profit == 289_440


# -------------------------------------------
# 5) _poll_tracked_fills temporary safety guard: a tracked SELL's fill delta
#    must NOT flow into register_fill_as_position (would wrongly GROW a
#    position from a sell fill). Full sell post-fill handling is E1-2's job —
#    this guard only prevents the E1-1 registration from silently creating a
#    double-count bug in the meantime.
# -------------------------------------------


class _FakeKiwoomClient:
    def __init__(self, filled_orders):
        self._filled_orders = filled_orders
        self.calls = 0

    async def get_filled_orders(self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True):
        self.calls += 1
        return list(self._filled_orders)


def _filled(ord_no, qty, price, buy_sell_tp="매도"):
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


def _tracked_sell_order(ord_no="SELL1", total=144, filled=0):
    return TrackedOrder(
        ord_no=ord_no,
        ticker="005930",
        stock_name="삼성전자",
        side="sell",
        total_quantity=total,
        filled_quantity=filled,
        filled_amount=filled * 260_000,
        trade_date=date.today().strftime("%Y%m%d"),
    )


async def test_poll_guard_skips_position_registration_for_sell_fill(temp_storage):
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("SELL1", 37, 260_000)])
    )
    coord.fill_tracker.register(_tracked_sell_order(ord_no="SELL1", total=144, filled=0))

    alerts = []

    async def _capture_alert(alert):
        alerts.append(alert)

    coord.set_alert_callback(_capture_alert)

    await coord._poll_tracked_fills()

    # No position was opened/grown from the sell fill (E1-2's job).
    assert coord._state.positions == []
    # No fill notification either — belongs to E1-2's full handling.
    assert alerts == []
    # But the delta WAS applied to the tracked order itself — apply_fills
    # already advanced filled_quantity before the guard short-circuits.
    order = coord.fill_tracker._orders["SELL1"]
    assert order.filled_quantity == 37


async def test_poll_guard_still_registers_buy_fill_as_position(temp_storage):
    """Guard regression check: the new sell-only guard must not swallow BUY
    fills — they still flow through register_fill_as_position as before."""
    coord = ExecutionCoordinator(
        kiwoom_client=_FakeKiwoomClient(filled_orders=[_filled("BUY1", 48, 260_000, buy_sell_tp="매수")])
    )
    coord.fill_tracker.register(
        TrackedOrder(
            ord_no="BUY1",
            ticker="005930",
            stock_name="삼성전자",
            side="buy",
            total_quantity=48,
            filled_quantity=0,
            trade_date=date.today().strftime("%Y%m%d"),
        )
    )

    await coord._poll_tracked_fills()

    assert len(coord._state.positions) == 1
    assert coord._state.positions[0].quantity == 48
