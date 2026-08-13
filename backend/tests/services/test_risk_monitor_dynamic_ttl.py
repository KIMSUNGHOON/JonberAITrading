"""RiskMonitor -> dynamic held-price TTL (monitoring-cadence-tuning arc).

Root cause: RiskMonitor polls every held ticker once a second
(`_monitor_loop` -> `_check_all_positions` -> `_check_position`), but the
injected price fetcher (`ExecutionCoordinator._get_current_price` ->
`KiwoomClient.get_stock_info`) cached at a hardcoded 3.0s TTL — so
responsiveness was capped at 3s regardless of N held positions, and the
Kiwoom request cost (N/TTL req/s) blew past the ~1.43 req/s ceiling once N
grew past a couple of tickers with a fixed TTL small enough to be useful.

Fix: `_check_position` now calls the injected fetcher with
`ttl=compute_held_ttl(len(self._watching))` — TTL shrinks (more responsive)
when few positions are held and grows (cheaper) as N grows, keeping the
per-ticker request rate bounded. This suite pins that call contract.
"""

from unittest.mock import AsyncMock

import pytest

from services.trading.cadence import compute_held_ttl
from services.trading.models import ManagedPosition, StopLossMode
from services.trading.risk_monitor import RiskMonitor

pytestmark = pytest.mark.asyncio


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


async def test_check_position_calls_fetcher_with_dynamic_ttl_for_single_watched():
    """N=1 watched ticker -> ttl == compute_held_ttl(1)."""
    fetcher = AsyncMock(return_value=71_000.0)
    monitor = RiskMonitor(price_fetcher=fetcher)
    position = _position(ticker="005930")
    monitor.add_position(position)

    config = monitor._watching["005930"]
    await monitor._check_position("005930", config)

    fetcher.assert_awaited_once_with("005930", ttl=compute_held_ttl(1))


async def test_check_position_calls_fetcher_with_dynamic_ttl_scaling_with_n():
    """N=5 watched tickers -> every tick's ttl reflects the current N, not a
    fixed constant — proving the TTL is recomputed from `len(_watching)`
    rather than hardcoded at construction time."""
    fetcher = AsyncMock(return_value=71_000.0)
    monitor = RiskMonitor(price_fetcher=fetcher)
    tickers = ["005930", "000660", "035420", "005380", "051910"]
    for t in tickers:
        monitor.add_position(_position(ticker=t))

    config = monitor._watching[tickers[0]]
    await monitor._check_position(tickers[0], config)

    fetcher.assert_awaited_once_with(tickers[0], ttl=compute_held_ttl(5))


async def test_check_position_simulation_branch_unaffected():
    """No price_fetcher injected (simulation mode) must stay untouched —
    no fetcher call, no ttl computation involved, `config.last_price` used
    as-is."""
    monitor = RiskMonitor(price_fetcher=None)
    position = _position(ticker="005930", current_price=71_000.0)
    monitor.add_position(position)

    config = monitor._watching["005930"]
    config.last_price = 71_000.0
    await monitor._check_position("005930", config)

    # No exception, and nothing to assert on a fetcher since none exists.
    assert monitor._watching["005930"].last_price == 71_000.0
