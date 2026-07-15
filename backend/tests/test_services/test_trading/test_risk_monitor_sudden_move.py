"""Risk Monitor — per-ticker sudden-move pause + auto-recovery (M1, C2 audit).

Before this fix, `RiskMonitor._handle_sudden_move` called the GLOBAL
`pause()`, which set `_trading_mode = PAUSED`. `_check_position` skipped
stop-loss/take-profit checks for EVERY watched ticker whenever that flag was
set — not just the ticker that actually moved. A single stock's dead-candle
froze stop-loss defense for the WHOLE book until a human called `resume()`.

This suite pins the fix: a sudden move pauses ONLY the ticker that moved
(`WatchConfig.sudden_move_cooldown_ticks`); every other watched ticker keeps
evaluating stop-loss/take-profit normally; and the paused ticker auto-recovers
after N monitor ticks OR once price stabilizes (volatility below threshold) —
no human RESUME required. The previously-untested sudden-move-detected branch
(M4) is exercised directly via `_check_position`/`_check_all_positions`.

The manual `pause()`/`resume()` API is kept as-is: it is a separate,
operator-driven kill-switch (ExecutionCoordinator.pause()/resume(), the
alert "RESUME" action) that still gates ALL tickers globally when invoked
explicitly — it is simply no longer what the sudden-move path uses.

T3 (MEDIUM finding B, review 2026-07-13) extends this: a ticker whose
tick-to-tick move keeps qualifying as "sudden" on EVERY tick re-enters
`_handle_sudden_move` every time and re-arms `sudden_move_cooldown_ticks`
before it can ever count down — under a perpetual move that ticker's
stop-loss/take-profit defense would never resume, and there is no manual
override (RESUME was removed). `WatchConfig.sudden_move_ticks_in_cooldown`
now counts consecutive re-arm ticks (NOT reset by re-arming) and forces
recovery once it exceeds an absolute cap
(`RiskMonitor.ABSOLUTE_COOLDOWN_CAP_MULTIPLIER` x `sudden_move_cooldown_ticks`)
— a circuit breaker for the circuit breaker: guaranteed recovery even if
the move never stabilizes.
"""

import pytest

from services.trading.models import ManagedPosition, RiskParameters, StopLossMode, TradingMode
from services.trading.risk_monitor import RiskMonitor


def _position(ticker, avg_price, stop_loss, quantity=10):
    return ManagedPosition(
        ticker=ticker,
        stock_name=ticker,
        quantity=quantity,
        avg_price=avg_price,
        current_price=avg_price,
        stop_loss=stop_loss,
        stop_loss_mode=StopLossMode.AGENT_AUTO,
    )


def _monitor(**risk_kwargs):
    defaults = dict(
        sudden_move_threshold_pct=10.0,
        sudden_move_cooldown_ticks=3,
        sudden_move_stabilization_pct=1.0,
    )
    defaults.update(risk_kwargs)
    return RiskMonitor(risk_params=RiskParameters(**defaults))


@pytest.mark.asyncio
async def test_sudden_move_pauses_only_that_ticker_other_still_fires():
    """(a) + M4: sudden move on AAAA must not block BBBB's stop-loss, and
    must not touch the global trading mode at all."""
    monitor = _monitor()
    executed = []

    async def executor(order):
        executed.append(order.ticker)

    monitor._execute_order = executor

    monitor.add_position(_position("AAAA", avg_price=70_000, stop_loss=65_000))
    monitor.add_position(_position("BBBB", avg_price=50_000, stop_loss=48_000))

    prices = {"AAAA": 55_000, "BBBB": 47_000}  # AAAA: -21.4% (sudden); BBBB: -6% (plain stop-loss)

    async def fetcher(ticker, ttl=None):
        return prices[ticker]

    monitor._get_price = fetcher

    await monitor._check_all_positions()

    # AAAA's own stop-loss (55_000 <= 65_000) must NOT have fired this tick —
    # the sudden-move branch pre-empts it and returns early, per-ticker.
    # BBBB's stop-loss must fire normally, proving the pause did not leak
    # to the rest of the book.
    assert executed == ["BBBB"]

    # Global mode was never touched by the sudden move.
    assert monitor.trading_mode != TradingMode.PAUSED
    assert not monitor.is_paused

    # Only AAAA is in cooldown; BBBB was never paused.
    assert monitor._watching["AAAA"].sudden_move_cooldown_ticks > 0
    assert monitor._watching["BBBB"].sudden_move_cooldown_ticks == 0


@pytest.mark.asyncio
async def test_sudden_move_ticker_own_stop_loss_stays_gated_until_ticks_elapse():
    """(b) tick-count path: while AAAA cools down, repeated ticks below its
    stop-loss must NOT fire — until the Nth tick, when the cooldown expires
    and the (still-true) stop-loss condition fires with NO human action."""
    monitor = _monitor()  # cooldown_ticks=3, stabilization_pct=1.0
    executed = []

    async def executor(order):
        executed.append(order.ticker)

    monitor._execute_order = executor

    monitor.add_position(_position("AAAA", avg_price=70_000, stop_loss=65_000))
    config = monitor._watching["AAAA"]

    prices = [
        60_000,       # tick0: -14.3% from 70_000 -> sudden move, cooldown=3, no stop check
        61_200,       # tick1: +2.0% from 60_000 (above stabilization, below threshold) -> cooldown 3->2, gated
        62_424,       # tick2: +2.0% from 61_200 -> cooldown 2->1, gated
        63_672.48,    # tick3: +2.0% from 62_424 -> cooldown 1->0, RECOVERS, falls through to stop-loss check
    ]
    idx = {"i": 0}

    async def fetcher(ticker, ttl=None):
        price = prices[idx["i"]]
        idx["i"] += 1
        return price

    monitor._get_price = fetcher

    await monitor._check_position("AAAA", config)  # tick0: sudden move
    assert executed == []
    assert config.sudden_move_cooldown_ticks == 3

    await monitor._check_position("AAAA", config)  # tick1
    assert executed == []
    assert config.sudden_move_cooldown_ticks == 2

    await monitor._check_position("AAAA", config)  # tick2
    assert executed == []
    assert config.sudden_move_cooldown_ticks == 1

    await monitor._check_position("AAAA", config)  # tick3: recovers AND stop-loss fires, no human action
    assert executed == ["AAAA"]
    assert config.sudden_move_cooldown_ticks == 0


@pytest.mark.asyncio
async def test_sudden_move_auto_recovers_early_on_price_stabilization():
    """(b) stabilization path: if price stabilizes (tiny move) well before
    the N-tick cooldown would expire, the ticker recovers early — still with
    no human action."""
    monitor = _monitor(sudden_move_cooldown_ticks=10, sudden_move_stabilization_pct=1.0)
    executed = []

    async def executor(order):
        executed.append(order.ticker)

    monitor._execute_order = executor

    monitor.add_position(_position("AAAA", avg_price=70_000, stop_loss=65_000))
    config = monitor._watching["AAAA"]

    prices = [
        60_000,     # tick0: sudden move (-14.3%), cooldown=10
        60_050,     # tick1: +0.08% -> below stabilization_pct(1.0) -> recovers early, cooldown far from 0
    ]
    idx = {"i": 0}

    async def fetcher(ticker, ttl=None):
        price = prices[idx["i"]]
        idx["i"] += 1
        return price

    monitor._get_price = fetcher

    await monitor._check_position("AAAA", config)  # tick0
    assert config.sudden_move_cooldown_ticks == 10

    await monitor._check_position("AAAA", config)  # tick1: stabilized, well under 10 ticks
    # Recovered early (tick-count was nowhere near exhausted) and, since
    # price (60_050) is still <= stop_loss (65_000), the stop-loss fires
    # immediately upon recovery — no human RESUME needed.
    assert config.sudden_move_cooldown_ticks == 0
    assert executed == ["AAAA"]


@pytest.mark.asyncio
async def test_manual_global_pause_still_gates_all_tickers():
    """The manual pause()/resume() API is kept as a separate operator
    kill-switch (used by ExecutionCoordinator.pause()/resume() and the
    RESUME alert action elsewhere) — unlike the sudden-move path, an
    explicit global pause() legitimately gates every ticker."""
    monitor = _monitor()
    executed = []

    async def executor(order):
        executed.append(order.ticker)

    monitor._execute_order = executor

    monitor.add_position(_position("AAAA", avg_price=70_000, stop_loss=65_000))
    config = monitor._watching["AAAA"]

    await monitor.pause("manual kill-switch test")
    assert monitor.is_paused

    # Seed last_price close to the test price so the tick-to-tick move stays
    # well under the sudden-move threshold — this test isolates the GLOBAL
    # gate specifically, not the per-ticker sudden-move path.
    config.last_price = 66_000

    async def fetcher(_ticker, ttl=None):
        return 64_000  # -3.0% tick move (not sudden), but <= stop_loss

    monitor._get_price = fetcher

    await monitor._check_position("AAAA", config)
    assert executed == []  # gated by the manual global pause

    await monitor.resume()
    assert not monitor.is_paused

    await monitor._check_position("AAAA", config)
    assert executed == ["AAAA"]  # fires once resumed


@pytest.mark.asyncio
async def test_sudden_move_perpetual_re_arm_force_recovers_after_absolute_cap():
    """T3 (MEDIUM finding B): a ticker that re-qualifies as "sudden" on
    EVERY tick would re-arm `sudden_move_cooldown_ticks` forever and never
    reach the normal N-tick recovery path (it always returns early from the
    sudden-move branch, never falling into the decrement branch). The
    absolute cap on consecutive re-arms forces recovery regardless —
    stop-loss/take-profit resumes (take-profit fires here, proving the
    check actually ran) even though the move never stabilized."""
    monitor = _monitor(
        sudden_move_cooldown_ticks=3,
        sudden_move_stabilization_pct=1.0,
        take_profit_mode=StopLossMode.AGENT_AUTO,
    )
    executed = []

    async def executor(order):
        executed.append(order.ticker)

    monitor._execute_order = executor

    position = ManagedPosition(
        ticker="AAAA",
        stock_name="AAAA",
        quantity=10,
        avg_price=70_000,
        current_price=70_000,
        take_profit=75_000,
        stop_loss_mode=StopLossMode.AGENT_AUTO,
    )
    monitor.add_position(position)
    config = monitor._watching["AAAA"]

    # Every tick is a +15% move from the previous tick — always >= the 10%
    # sudden-move threshold, so this ticker NEVER falls into the ordinary
    # decrement/recovery branch on its own.
    price = 70_000.0
    prices = []
    for _ in range(12):
        price *= 1.15
        prices.append(price)
    idx = {"i": 0}

    async def fetcher(_ticker, ttl=None):
        p = prices[idx["i"]]
        idx["i"] += 1
        return p

    monitor._get_price = fetcher

    absolute_cap = (
        monitor.risk_params.sudden_move_cooldown_ticks
        * monitor.ABSOLUTE_COOLDOWN_CAP_MULTIPLIER
    )

    for _ in range(absolute_cap):
        await monitor._check_position("AAAA", config)
        assert executed == [], "still gated — re-arming every tick, under the cap"
    assert config.sudden_move_ticks_in_cooldown == absolute_cap
    assert config.sudden_move_cooldown_ticks == monitor.risk_params.sudden_move_cooldown_ticks

    # One more consecutive "sudden" tick exceeds the absolute cap -> forced
    # recovery THIS tick; take-profit (long since crossed) fires immediately.
    await monitor._check_position("AAAA", config)
    assert config.sudden_move_ticks_in_cooldown == 0
    assert config.sudden_move_cooldown_ticks == 0
    assert executed == ["AAAA"]
