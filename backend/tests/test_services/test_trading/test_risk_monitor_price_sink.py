"""RiskMonitor -> ExecutionCoordinator price-sink (T1, MEDIUM finding A, review 2026-07-13).

RiskMonitor._monitor_loop already polls a fresh price for every watched
ticker once a second via the same `_get_current_price` the coordinator
injects as `price_fetcher` — but that fresh price was written only to
`WatchConfig.last_price` and discarded. The coordinator's own
`ManagedPosition.current_price` (and unrealized_pnl/exposure math derived
from it, see test_position_reprice.py) was only refreshed at trade-decision
time (`_refresh_account_info`), so the displayed P&L/exposure went stale
between decisions even though live 1s price data was already flowing
through the monitor.

Fix: RiskMonitor takes a `price_sink(ticker, price)` callback (parallel to
`price_fetcher`) and calls it every tick right after fetching a price.
ExecutionCoordinator wires `self._on_price_update` as that sink, applying
the same T2 stale-price contract enforced by `_reprice_positions` (a falsy
0/None quote must never overwrite a live position's last-known price) at
1s cadence, not just at decision time.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.kiwoom.models import StockBasicInfo
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import ManagedPosition, StopLossMode

pytestmark = pytest.mark.asyncio


def _stock_info(cur_prc, stk_cd: str = "005930") -> StockBasicInfo:
    return StockBasicInfo(stk_cd=stk_cd, stk_nm="삼성전자", cur_prc=cur_prc)


def _position(ticker="005930", avg_price=70_000.0, quantity=10, **kw) -> ManagedPosition:
    kw.setdefault("current_price", avg_price)
    return ManagedPosition(
        ticker=ticker,
        stock_name="삼성전자",
        quantity=quantity,
        avg_price=avg_price,
        stop_loss_mode=StopLossMode.USER_APPROVAL,
        **kw,
    )


async def test_monitor_tick_reprices_coordinator_position():
    """A single RiskMonitor tick (_check_position) must feed its fetched
    price back into the coordinator's ManagedPosition, updating
    unrealized_pnl — not just WatchConfig.last_price."""
    client = MagicMock()
    client.get_stock_info = AsyncMock(return_value=_stock_info(80_000))
    coord = ExecutionCoordinator(kiwoom_client=client)
    position = _position(avg_price=70_000.0)
    coord._add_position(position)

    config = coord.risk_monitor._watching[position.ticker]
    await coord.risk_monitor._check_position(position.ticker, config)

    tracked = coord._state.positions[0]
    assert tracked.current_price == 80_000.0
    assert tracked.unrealized_pnl == (80_000.0 - 70_000.0) * 10


async def test_monitor_tick_zero_price_does_not_overwrite():
    """A fail-safe 0 price (broker error / ghost quote) from the SAME
    fetch RiskMonitor uses must not zero out the coordinator's tracked
    current_price (T2 stale-price contract, same as _reprice_positions)."""
    client = MagicMock()
    client.get_stock_info = AsyncMock(return_value=_stock_info(0))
    coord = ExecutionCoordinator(kiwoom_client=client)
    position = _position(avg_price=70_000.0, current_price=71_500.0)
    coord._add_position(position)

    config = coord.risk_monitor._watching[position.ticker]
    await coord.risk_monitor._check_position(position.ticker, config)

    tracked = coord._state.positions[0]
    assert tracked.current_price == 71_500.0


async def test_price_sink_ignores_unknown_ticker():
    """A price_sink callback for a ticker no longer tracked (e.g. removed
    between the poll starting and the sink firing) must be a no-op, not a
    KeyError/crash."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    coord._on_price_update("999999", 12345.0)  # no such position tracked

    assert coord._state.positions == []


async def test_price_sink_none_does_not_overwrite():
    """Belt-and-suspenders: an explicit None must be treated the same as a
    falsy 0 — no overwrite."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.positions.append(_position(avg_price=70_000.0, current_price=71_500.0))

    coord._on_price_update("005930", None)

    assert coord._state.positions[0].current_price == 71_500.0


async def test_price_sink_only_updates_matching_ticker():
    """Multiple positions: the sink must update only the ticker it was
    called for, not every tracked position."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.positions.append(_position(ticker="005930", avg_price=70_000.0))
    coord._state.positions.append(_position(ticker="000660", avg_price=140_000.0))

    coord._on_price_update("005930", 99_000.0)

    by_ticker = {p.ticker: p for p in coord._state.positions}
    assert by_ticker["005930"].current_price == 99_000.0
    assert by_ticker["000660"].current_price == 140_000.0
