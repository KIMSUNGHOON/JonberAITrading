"""ExecutionCoordinator position repricing (DI2 — unrealized P&L permanently 0).

Root cause: `ManagedPosition.current_price` was set once, at open, to
`avg_price` (coordinator.py `_execute_order_from_monitor`/on-approval fill
handling) and never touched again. Since `unrealized_pnl = (current_price -
avg_price) * quantity`, this made unrealized P&L (and %) permanently 0 for
every live position, and `portfolio_agent`'s exposure math — which also reads
`current_price` for position value/weight — silently drifted from the live
`total_equity` that `_refresh_account_info` DOES keep current.

Fix: `_refresh_account_info` now also calls `_reprice_positions`, which
refreshes each open position's `current_price` via `_get_current_price`. Per
the T2 stale-price contract (`_get_current_price` fails safe to 0 on any
broker error — see test_current_price_feed.py), a falsy quote must never be
written into a live position: it would fabricate a zeroed-out P&L/exposure
rather than simply staying stale. Such positions keep their last-known price.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.kiwoom.models import AccountBalance, StockBasicInfo
from services.trading.coordinator import ExecutionCoordinator
from services.trading.models import ManagedPosition

pytestmark = pytest.mark.asyncio


def _stock_info(cur_prc: int, stk_cd: str = "005930") -> StockBasicInfo:
    return StockBasicInfo(stk_cd=stk_cd, stk_nm="삼성전자", cur_prc=cur_prc)


def _position(ticker="005930", quantity=10, avg_price=70_000.0, **kw) -> ManagedPosition:
    kw.setdefault("current_price", avg_price)
    return ManagedPosition(
        ticker=ticker,
        stock_name="삼성전자",
        quantity=quantity,
        avg_price=avg_price,
        **kw,
    )


def _balance() -> AccountBalance:
    return AccountBalance(
        pchs_amt=0,
        evlu_amt=0,
        evlu_pfls_amt=0,
        evlu_pfls_rt=0.0,
        d2_ord_psbl_amt=1_000_000,
        holdings=[],
    )


async def test_refresh_account_info_reprices_open_position():
    """A live quote higher than avg_price updates current_price and makes
    unrealized_pnl reflect the real, non-zero gain."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())
    client.get_stock_info = AsyncMock(return_value=_stock_info(75_000))
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord._state.positions.append(_position(avg_price=70_000.0))

    await coord._refresh_account_info()

    position = coord._state.positions[0]
    assert position.current_price == 75_000.0
    assert position.unrealized_pnl == (75_000.0 - 70_000.0) * 10
    assert position.unrealized_pnl != 0


async def test_refresh_account_info_skips_reprice_on_failed_quote():
    """`_get_current_price` failing safe to 0 (broker error) must NOT
    overwrite the position's last-known current_price — a fabricated 0 would
    be worse than staying stale (T2 contract)."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())
    client.get_stock_info = AsyncMock(side_effect=RuntimeError("kiwoom down"))
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord._state.positions.append(_position(avg_price=70_000.0, current_price=71_500.0))

    await coord._refresh_account_info()

    position = coord._state.positions[0]
    assert position.current_price == 71_500.0, (
        "a failed quote (fails safe to 0) must keep the last-known price, "
        "not zero it out"
    )


async def test_refresh_account_info_skips_reprice_when_quote_is_zero():
    """Belt-and-suspenders: even an explicit 0 quote (not just an exception)
    must be treated as 'no fresh data' and skipped."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())
    client.get_stock_info = AsyncMock(return_value=_stock_info(0))
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord._state.positions.append(_position(avg_price=70_000.0, current_price=71_500.0))

    await coord._refresh_account_info()

    position = coord._state.positions[0]
    assert position.current_price == 71_500.0


async def test_reprice_only_updates_matching_ticker():
    """Multiple positions each get their own ticker's quote, not a shared one."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())

    async def _get_stock_info(stk_cd, ttl=None):
        prices = {"005930": _stock_info(80_000, "005930"), "000660": _stock_info(150_000, "000660")}
        return prices[stk_cd]

    client.get_stock_info = AsyncMock(side_effect=_get_stock_info)
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord._state.positions.append(_position(ticker="005930", avg_price=70_000.0))
    coord._state.positions.append(_position(ticker="000660", avg_price=140_000.0))

    await coord._refresh_account_info()

    by_ticker = {p.ticker: p for p in coord._state.positions}
    assert by_ticker["005930"].current_price == 80_000.0
    assert by_ticker["000660"].current_price == 150_000.0


async def test_portfolio_exposure_reflects_repriced_value():
    """portfolio_agent's exposure math (position value / weight) reads
    `current_price` directly — after a reprice, its output must reflect the
    live price, not the stale open-time avg_price."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=_balance())
    client.get_stock_info = AsyncMock(return_value=_stock_info(100_000))
    coord = ExecutionCoordinator(kiwoom_client=client)
    coord._state.positions.append(_position(avg_price=70_000.0, quantity=10))

    await coord._refresh_account_info()

    summary = coord.portfolio_agent.get_portfolio_summary(coord._state)
    position_summary = summary["positions"][0]
    assert position_summary["current_price"] == 100_000.0
    assert position_summary["value"] == 100_000.0 * 10
    assert position_summary["unrealized_pnl"] == (100_000.0 - 70_000.0) * 10
    assert summary["total_unrealized_pnl"] == (100_000.0 - 70_000.0) * 10


async def test_simulation_mode_reprices_with_mock_price():
    """No kiwoom client (simulation) still reprices via the mock price feed,
    keeping the simulation-mode contract of `_get_current_price` intact."""
    coord = ExecutionCoordinator(kiwoom_client=None)
    coord._state.positions.append(_position(avg_price=40_000.0))

    await coord._refresh_account_info()

    position = coord._state.positions[0]
    assert position.current_price == 50_000  # simulation mock price
