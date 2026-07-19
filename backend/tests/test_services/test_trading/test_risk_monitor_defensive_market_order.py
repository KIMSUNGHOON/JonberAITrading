"""P2-4 Task P2: KR defensive-sell order_type -> MARKET (fill-realism audit
§C priority 2).

Background: `_execute_stop_loss`/`_execute_take_profit` previously built
their `OrderRequest` with no explicit `order_type`, so it defaulted to
`OrderType.LIMIT` (models.py) submitted AT the trigger price. In a gap/crash
a mock/live broker that fills that LIMIT order records the fill at the
(favorable) trigger price instead of the worse real fill — understating
loss-scenario risk. This is an ORDER-CONSTRUCTION fix, not a simulation: KR
still gets its fill price from the broker (ka10076) — MARKET just makes that
reported fill realistic, in both paper and live. No synthetic slippage is
added to the KR ledger anywhere by this change.

Follows the direct-RiskMonitor instantiation pattern already used by
test_risk_monitor_sudden_move.py (no full ExecutionCoordinator needed).
"""

import pytest

from services.trading.models import AlertType, ManagedPosition, OrderType, RiskParameters, StopLossMode
from services.trading.risk_monitor import RiskMonitor

pytestmark = pytest.mark.asyncio


def _position(ticker="005930", avg_price=70_000, stop_loss=None, take_profit=None, quantity=10, **overrides):
    kwargs = dict(
        ticker=ticker,
        stock_name=ticker,
        quantity=quantity,
        avg_price=avg_price,
        current_price=avg_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        stop_loss_mode=StopLossMode.AGENT_AUTO,
    )
    kwargs.update(overrides)
    return ManagedPosition(**kwargs)


def _monitor(**risk_kwargs):
    return RiskMonitor(risk_params=RiskParameters(**risk_kwargs))


async def test_execute_stop_loss_submits_market_order():
    """The defensive SELL order built by _execute_stop_loss must be
    order_type=MARKET, side=SELL — not the OrderRequest default of LIMIT."""
    monitor = _monitor()
    captured = {}

    async def executor(order):
        captured["order"] = order

    monitor._execute_order = executor
    position = _position(stop_loss=65_000)
    monitor.add_position(position)
    config = monitor._watching["005930"]

    await monitor._execute_stop_loss("005930", config, 64_000)

    order = captured["order"]
    assert order.order_type == OrderType.MARKET
    assert order.side == "sell"
    assert order.ticker == "005930"


async def test_execute_take_profit_submits_market_order():
    """Same fix for the take-profit defensive exit."""
    monitor = _monitor()
    captured = {}

    async def executor(order):
        captured["order"] = order

    monitor._execute_order = executor
    position = _position(take_profit=75_000)
    monitor.add_position(position)
    config = monitor._watching["005930"]

    await monitor._execute_take_profit("005930", config, 76_000)

    order = captured["order"]
    assert order.order_type == OrderType.MARKET
    assert order.side == "sell"


async def test_stop_loss_fires_as_market_order_through_check_position():
    """End-to-end through the normal monitor tick (_check_position), not just
    a direct call to _execute_stop_loss — proves the real trigger path also
    submits MARKET, not just the unit-level helper."""
    monitor = _monitor()
    captured = {}

    async def executor(order):
        captured["order"] = order

    monitor._execute_order = executor
    position = _position(avg_price=70_000, stop_loss=65_000)
    monitor.add_position(position)
    config = monitor._watching["005930"]

    async def fetcher(_ticker, ttl=None):
        return 64_000  # below stop_loss -> triggers

    monitor._get_price = fetcher

    await monitor._check_position("005930", config)

    assert "order" in captured
    assert captured["order"].order_type == OrderType.MARKET


async def test_take_profit_fires_as_market_order_through_check_position():
    # take_profit auto-execution reads RiskParameters.take_profit_mode
    # (position-level stop_loss_mode is stop-loss only; there is no
    # per-position take_profit_mode field).
    monitor = _monitor(take_profit_mode=StopLossMode.AGENT_AUTO)
    captured = {}

    async def executor(order):
        captured["order"] = order

    monitor._execute_order = executor
    position = _position(avg_price=70_000, take_profit=75_000)
    monitor.add_position(position)
    config = monitor._watching["005930"]

    async def fetcher(_ticker, ttl=None):
        return 76_000  # above take_profit -> triggers

    monitor._get_price = fetcher

    await monitor._check_position("005930", config)

    assert "order" in captured
    assert captured["order"].order_type == OrderType.MARKET


# -------------------------------------------
# S-2: stop_loss_mode live-read symmetry (survival discipline, 2026-07-19)
# -------------------------------------------
#
# Before this fix, _handle_stop_loss branched on config.stop_loss_mode -- a
# WatchConfig snapshot frozen once at add_position() time -- while
# _handle_take_profit already branched on the LIVE self.risk_params.
# take_profit_mode. A runtime mode change (e.g. PUT /trading/risk-params)
# therefore reached newly-added positions but never ones already being
# watched. This test pins the fix: flipping risk_params.stop_loss_mode
# AFTER a position is already watched must change ITS very next
# stop-loss-hit outcome, with no re-registration.
#
# Spec: docs/superpowers/specs/2026-07-19-survival-discipline-design.md §1/§2 S-2


async def test_stop_loss_mode_runtime_change_reaches_already_watched_position():
    """A position added while risk_params.stop_loss_mode is USER_APPROVAL
    (so its WatchConfig snapshot is frozen at USER_APPROVAL) must start
    auto-executing on its NEXT stop-loss hit the moment risk_params.
    stop_loss_mode flips to AGENT_AUTO at runtime -- without ever touching
    the position's own WatchConfig.stop_loss_mode snapshot."""
    monitor = _monitor(stop_loss_mode=StopLossMode.USER_APPROVAL)
    captured = {}

    async def executor(order):
        captured["order"] = order

    monitor._execute_order = executor
    # Explicit USER_APPROVAL at the position level too, isolating this test
    # from the (separate, position-level) stop_loss_mode override -- only
    # the RiskMonitor-level runtime read is under test here.
    position = _position(stop_loss=65_000, stop_loss_mode=StopLossMode.USER_APPROVAL)
    monitor.add_position(position)
    config = monitor._watching["005930"]
    assert config.stop_loss_mode == StopLossMode.USER_APPROVAL, (
        "sanity: the WatchConfig snapshot must reflect the mode at "
        "add_position time"
    )

    # First hit, BEFORE the runtime flip: must alert, not execute.
    await monitor._handle_stop_loss("005930", config, 64_000)
    assert "order" not in captured, (
        "USER_APPROVAL must alert, not auto-execute"
    )
    assert any(a.alert_type == AlertType.STOP_LOSS_TRIGGERED for a in monitor._alerts)

    # Runtime change AFTER the position is already watched -- the
    # WatchConfig snapshot itself is deliberately left untouched.
    monitor.risk_params.stop_loss_mode = StopLossMode.AGENT_AUTO
    assert config.stop_loss_mode == StopLossMode.USER_APPROVAL, (
        "the snapshot must stay frozen -- only the live read changes"
    )

    # Second hit, AFTER the runtime flip: must now auto-execute, proving
    # _handle_stop_loss reads self.risk_params.stop_loss_mode live, not the
    # frozen WatchConfig snapshot (RED before the fix: this would still alert).
    await monitor._handle_stop_loss("005930", config, 64_000)
    assert "order" in captured
    assert captured["order"].order_type == OrderType.MARKET
    assert captured["order"].side == "sell"

