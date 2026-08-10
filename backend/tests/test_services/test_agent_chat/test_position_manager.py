"""
Tests for PositionManager

Unit tests for the PositionManager that monitors positions in real-time.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
import structlog.testing
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

import services.storage_service as ss
import services.agent_chat.position_manager as pm_mod
from services.agent_chat.models import DecisionAction, TradeDecision
from services.agent_chat.position_manager import (
    PositionManager,
    PositionManagerConfig,
    PositionEventType,
    PositionAction,
    MonitoredPosition,
    PositionEvent,
    get_position_manager,
)


# -------------------------------------------
# Constants
# -------------------------------------------

# KRX regular session length in minutes: 09:00-15:30 KST (see
# services/trading/market_hours.py MarketHoursService, market_open=time(9,0)
# / market_close=time(15,30) -> 6.5h = 390min). Used to pin the invariant
# that PositionManagerConfig's daily strategic-re-eval budget
# (max_discussions_per_position) must not exhaust before the session ends
# -- see TestStrategicReevalConfig.test_daily_cap_cannot_exhaust_before_
# session_close.
KRX_SESSION_MINUTES = 390


# -------------------------------------------
# Fixtures
# -------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def temp_storage(tmp_path, monkeypatch):
    """Isolated SQLite storage wired into the get_storage_service() singleton
    (pattern from tests/test_services/test_r5_p1_execution_reliability.py).

    autouse: PositionManager's add/update/remove_position now fire a
    fire-and-forget persist task whenever a running event loop is present
    (every ``async def`` test in this file). Without this fixture those
    background writes would hit the REAL on-disk storage.db — the same file
    the live :8001 backend uses — so every test in this module gets an
    isolated DB whether or not it cares about persistence.
    """
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


@pytest.fixture
def config():
    """Create a test configuration."""
    return PositionManagerConfig(
        check_interval_seconds=30,
        stop_loss_warning_pct=2.0,
        take_profit_warning_pct=2.0,
        significant_gain_pct=10.0,
        significant_loss_pct=5.0,
        auto_execute_stop_loss=False,
        auto_execute_take_profit=False,
    )


@pytest.fixture
def position_manager(config):
    """Create a PositionManager instance."""
    return PositionManager(config=config)


@pytest.fixture
def sample_position():
    """Create a sample monitored position."""
    return MonitoredPosition(
        ticker="005930",
        stock_name="삼성전자",
        quantity=100,
        avg_price=72500,
        current_price=72500,
        stop_loss=68875,
        take_profit=79750,
    )


# -------------------------------------------
# MonitoredPosition Tests
# -------------------------------------------


class TestMonitoredPosition:
    """Tests for MonitoredPosition model."""

    def test_create_position(self):
        """Test creating a monitored position."""
        pos = MonitoredPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=73000,
        )

        assert pos.ticker == "005930"
        assert pos.quantity == 100
        assert pos.avg_price == 72500
        assert pos.current_price == 73000

    def test_unrealized_pnl(self):
        """Test unrealized P&L calculation."""
        pos = MonitoredPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=75000,
        )

        expected_pnl = (75000 - 72500) * 100  # 250,000
        assert pos.unrealized_pnl == expected_pnl

    def test_unrealized_pnl_pct(self):
        """Test unrealized P&L percentage calculation."""
        pos = MonitoredPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=75000,
        )

        expected_pct = ((75000 - 72500) / 72500) * 100  # ~3.45%
        assert abs(pos.unrealized_pnl_pct - expected_pct) < 0.01

    def test_position_value(self):
        """Test position value calculation."""
        pos = MonitoredPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=75000,
        )

        expected_value = 75000 * 100  # 7,500,000
        assert pos.position_value == expected_value

    def test_holding_days(self):
        """Test holding days calculation."""
        pos = MonitoredPosition(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=75000,
            entry_time=datetime.now() - timedelta(days=10),
        )

        assert pos.holding_days == 10


# -------------------------------------------
# PositionManager Initialization Tests
# -------------------------------------------


class TestPositionManagerInitialization:
    """Tests for PositionManager initialization."""

    def test_create_manager_default_config(self):
        """Test creating manager with default config."""
        pm = PositionManager()

        assert pm.config.check_interval_seconds == 30
        assert pm.config.stop_loss_warning_pct == 2.0

    def test_create_manager_custom_config(self, config):
        """Test creating manager with custom config."""
        pm = PositionManager(config=config)

        assert pm.config == config

    def test_initial_state(self, position_manager):
        """Test initial state of manager."""
        assert not position_manager._running
        assert len(position_manager._positions) == 0
        assert len(position_manager._events) == 0


# -------------------------------------------
# Position Management Tests
# -------------------------------------------


class TestPositionManagement:
    """Tests for position management."""

    def test_add_position(self, position_manager):
        """Test adding a position."""
        pos = position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            stop_loss=68875,
            take_profit=79750,
        )

        assert pos.ticker == "005930"
        assert "005930" in position_manager._positions
        assert position_manager._positions["005930"] == pos

    def test_update_position(self, position_manager):
        """Test updating a position."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
        )

        updated = position_manager.update_position(
            ticker="005930",
            current_price=75000,
            stop_loss=70000,
        )

        assert updated.current_price == 75000
        assert updated.stop_loss == 70000

    def test_update_nonexistent_position(self, position_manager):
        """Test updating a position that doesn't exist."""
        result = position_manager.update_position(
            ticker="000000",
            current_price=100,
        )

        assert result is None

    def test_remove_position(self, position_manager):
        """Test removing a position."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
        )

        result = position_manager.remove_position("005930")

        assert result is True
        assert "005930" not in position_manager._positions

    def test_remove_nonexistent_position(self, position_manager):
        """Test removing a position that doesn't exist."""
        result = position_manager.remove_position("000000")

        assert result is False

    def test_get_position(self, position_manager):
        """Test getting a specific position."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
        )

        pos = position_manager.get_position("005930")

        assert pos is not None
        assert pos.ticker == "005930"

    def test_get_all_positions(self, position_manager):
        """Test getting all positions."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
        )
        position_manager.add_position(
            ticker="000660",
            stock_name="SK하이닉스",
            quantity=50,
            avg_price=120000,
        )

        positions = position_manager.get_all_positions()

        assert len(positions) == 2


# -------------------------------------------
# Callback Tests
# -------------------------------------------


class TestPositionManagerCallbacks:
    """Tests for callback functionality."""

    def test_register_event_callback(self, position_manager):
        """Test registering an event callback."""
        callback = MagicMock()
        position_manager.on_event(callback)

        assert callback in position_manager._on_event_callbacks

    def test_register_decision_callback(self, position_manager):
        """Test registering a decision callback."""
        callback = MagicMock()
        position_manager.on_decision(callback)

        assert callback in position_manager._on_decision_callbacks


# -------------------------------------------
# Lifecycle Tests
# -------------------------------------------


class TestPositionManagerLifecycle:
    """Tests for manager lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, position_manager):
        """Test that start sets running flag."""
        await position_manager.start()

        assert position_manager._running
        assert position_manager._task is not None

        await position_manager.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, position_manager):
        """Test that stop clears running flag."""
        await position_manager.start()
        await position_manager.stop()

        assert not position_manager._running

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, position_manager):
        """Test that calling start twice is safe."""
        await position_manager.start()
        task1 = position_manager._task

        await position_manager.start()  # Should be no-op
        task2 = position_manager._task

        assert task1 == task2

        await position_manager.stop()


# -------------------------------------------
# Event Detection Tests
# -------------------------------------------


class TestEventDetection:
    """Tests for position event detection."""

    @pytest.mark.asyncio
    async def test_detect_stop_loss_hit(self, position_manager):
        """Test detecting stop-loss hit."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=68000,  # Below stop-loss
            stop_loss=68875,
        )

        events = []
        position_manager.on_event(lambda e: events.append(e))

        position = position_manager._positions["005930"]
        await position_manager._check_position(position)

        # Should have stop-loss hit event
        stop_loss_events = [e for e in events if e.event_type == PositionEventType.STOP_LOSS_HIT]
        assert len(stop_loss_events) >= 1

    @pytest.mark.asyncio
    async def test_detect_stop_loss_near(self, position_manager):
        """Test detecting near stop-loss."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=69500,  # Within 2% of stop-loss
            stop_loss=68875,
        )

        events = []
        position_manager.on_event(lambda e: events.append(e))

        position = position_manager._positions["005930"]
        await position_manager._check_position(position)

        # Should have stop-loss near event
        near_events = [e for e in events if e.event_type == PositionEventType.STOP_LOSS_NEAR]
        assert len(near_events) >= 1

    @pytest.mark.asyncio
    async def test_detect_take_profit_hit(self, position_manager):
        """Test detecting take-profit hit."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=80000,  # Above take-profit
            take_profit=79750,
        )

        events = []
        position_manager.on_event(lambda e: events.append(e))

        position = position_manager._positions["005930"]
        await position_manager._check_position(position)

        # Should have take-profit hit event
        tp_events = [e for e in events if e.event_type == PositionEventType.TAKE_PROFIT_HIT]
        assert len(tp_events) >= 1

    @pytest.mark.asyncio
    async def test_detect_significant_gain(self, position_manager):
        """Test detecting significant gain."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=80000,  # ~10.3% gain
        )

        events = []
        position_manager.on_event(lambda e: events.append(e))

        position = position_manager._positions["005930"]
        await position_manager._check_position(position)

        # Should have significant gain event
        gain_events = [e for e in events if e.event_type == PositionEventType.SIGNIFICANT_GAIN]
        assert len(gain_events) >= 1

    @pytest.mark.asyncio
    async def test_detect_significant_loss(self, position_manager):
        """Test detecting significant loss."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=68000,  # ~6.2% loss
        )

        events = []
        position_manager.on_event(lambda e: events.append(e))

        position = position_manager._positions["005930"]
        await position_manager._check_position(position)

        # Should have significant loss event
        loss_events = [e for e in events if e.event_type == PositionEventType.SIGNIFICANT_LOSS]
        assert len(loss_events) >= 1


# -------------------------------------------
# Stale-Price Guard Tests (CRITICAL safety fix, 2026-07-14)
# -------------------------------------------
#
# get_kr_stock_info now returns None on a real Kiwoom fetch failure instead
# of a fabricated np.random-seeded mock price. Before this fix, a transient
# Kiwoom hiccup would overwrite a HELD position's current_price with a
# random number, and _check_position would then evaluate the stop-loss
# distance against that fabricated price — potentially auto-executing a
# real sell on invented data. These tests pin the new contract: a None
# fetch must leave current_price untouched and skip this cycle's
# stop-loss/take-profit check for that ticker, using the LAZY in-node
# import convention (patch target is the source module
# agents.tools.kr_market_data, not position_manager's namespace).


class TestUpdatePricesStaleGuard:
    """Tests for _update_prices / _check_all_positions handling of a None
    (failed) price fetch."""

    @pytest.fixture(autouse=True)
    def _market_open(self, monkeypatch):
        """E2-1: _check_all_positions is now gated on KRX hours (완전
        idle). These tests exercise the defensive stop-loss logic
        independent of real wall-clock market state, so pin the gate
        open rather than depend on whatever time the suite happens to
        run at."""
        monkeypatch.setattr(pm_mod, "is_krx_open_cached", lambda: True)

    @pytest.mark.asyncio
    async def test_update_prices_none_leaves_current_price_unchanged(
        self, position_manager
    ):
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=72500,
        )

        with patch(
            "agents.tools.kr_market_data.get_kr_stock_info",
            AsyncMock(return_value=None),
        ):
            stale = await position_manager._update_prices()

        position = position_manager._positions["005930"]
        assert position.current_price == 72500  # unchanged, not fabricated
        assert "005930" in stale

    @pytest.mark.asyncio
    async def test_update_prices_success_still_updates_price(
        self, position_manager
    ):
        """Happy path: a real fetch must still update current_price exactly
        as before this fix."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=72500,
        )

        with patch(
            "agents.tools.kr_market_data.get_kr_stock_info",
            AsyncMock(return_value={"stk_cd": "005930", "cur_prc": 73000}),
        ):
            stale = await position_manager._update_prices()

        position = position_manager._positions["005930"]
        assert position.current_price == 73000
        assert stale == set()

    @pytest.mark.asyncio
    async def test_check_all_positions_skips_stop_loss_on_stale_price(
        self, position_manager
    ):
        """A position whose current_price is already below its stop_loss
        (from the last successful fetch) must NOT re-fire STOP_LOSS_HIT
        this cycle when the price refresh fails — the check itself must be
        skipped, not merely the price update."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=68000,  # already below stop_loss
            stop_loss=68875,
        )

        events = []
        position_manager.on_event(lambda e: events.append(e))

        with patch(
            "agents.tools.kr_market_data.get_kr_stock_info",
            AsyncMock(return_value=None),
        ):
            await position_manager._check_all_positions()

        stop_loss_events = [
            e for e in events if e.event_type == PositionEventType.STOP_LOSS_HIT
        ]
        assert stop_loss_events == []

        position = position_manager._positions["005930"]
        assert position.current_price == 68000  # unchanged

    @pytest.mark.asyncio
    async def test_check_all_positions_still_checks_fresh_price(
        self, position_manager
    ):
        """Happy path: when the fetch succeeds, the stop-loss check must
        still run exactly as before."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=72500,
            stop_loss=68875,
        )

        events = []
        position_manager.on_event(lambda e: events.append(e))

        with patch(
            "agents.tools.kr_market_data.get_kr_stock_info",
            AsyncMock(return_value={"stk_cd": "005930", "cur_prc": 68000}),
        ):
            await position_manager._check_all_positions()

        stop_loss_events = [
            e for e in events if e.event_type == PositionEventType.STOP_LOSS_HIT
        ]
        assert len(stop_loss_events) >= 1


# -------------------------------------------
# Trailing Stop Tests
# -------------------------------------------


class TestTrailingStop:
    """Tests for trailing stop functionality."""

    @pytest.mark.asyncio
    async def test_trailing_stop_activation(self, position_manager):
        """Test automatic trailing stop activation."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=76500,  # 5.5% gain - should activate trailing
        )

        position = position_manager._positions["005930"]

        # Update highest price
        position.highest_price = 76500

        await position_manager._check_position(position)

        # Should activate trailing stop
        if position_manager.config.auto_update_trailing:
            assert position.trailing_stop_pct is not None

    @pytest.mark.asyncio
    async def test_trailing_stop_update(self, position_manager):
        """Test trailing stop price update."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=76500,
            trailing_stop_pct=5.0,
        )

        position = position_manager._positions["005930"]
        position.highest_price = 76500

        events = []
        position_manager.on_event(lambda e: events.append(e))

        await position_manager._check_trailing_stop(position, events)

        # Should update trailing stop price
        expected_trailing = 76500 * 0.95  # 5% below highest
        if position.trailing_stop_price:
            assert abs(position.trailing_stop_price - expected_trailing) < 1


# -------------------------------------------
# Take-Profit Lock-In Tests (S-5, survival discipline)
# -------------------------------------------
#
# docs/superpowers/specs/2026-07-19-survival-discipline-design.md §2 D2/S-5:
# take-profit EXECUTION stays discussion-gated (auto_execute_take_profit
# stays False), but once price has reached take_profit at least once, a
# retracement back below it should ratchet the stop-loss up toward
# breakeven+lock_in_ratio*(gain) -- protecting the profit even though
# nothing gets sold automatically.


class TestTakeProfitLockIn:
    """S-5: take_profit_reached_at fire-once marking + the breakeven+alpha
    stop ratchet it drives on a post-TP retracement."""

    @pytest.mark.asyncio
    async def test_take_profit_hit_records_once_and_does_not_auto_sell(
        self, position_manager
    ):
        """(1) TP reached -> take_profit_reached_at recorded exactly once;
        auto_execute_take_profit stays False so nothing gets sold, and a
        refire on the next tick (existing TAKE_PROFIT_HIT semantics -- it
        intentionally keeps firing every tick it's still true) must NOT move
        the recorded timestamp."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=70000,
            current_price=70000,
            take_profit=77000,
        )
        position = position_manager._positions["005930"]
        assert position.take_profit_reached_at is None
        assert position_manager.config.auto_execute_take_profit is False

        position.current_price = 77000  # TP hit
        events = []
        position_manager.on_event(lambda e: events.append(e))
        await position_manager._check_position(position)

        first_recorded = position.take_profit_reached_at
        assert first_recorded is not None
        assert position.quantity == 100, "no auto-sell -- take-profit execution stays OFF"
        tp_events = [e for e in events if e.event_type == PositionEventType.TAKE_PROFIT_HIT]
        assert len(tp_events) >= 1
        assert tp_events[0].auto_execute is False

        # Refire: the *_HIT event fires again every tick (unchanged, existing
        # semantics) but the fire-once mark must not move.
        await position_manager._check_position(position)
        assert position.take_profit_reached_at == first_recorded
        assert position.quantity == 100

    @pytest.mark.asyncio
    async def test_retracement_locks_in_stop_at_breakeven_plus_alpha(
        self, position_manager
    ):
        """(2) After TP is reached, a retracement below it raises stop_loss
        to entry*(1 + lock_in_ratio*(tp-entry)/entry) -- hand-computed here
        -- and a further retracement never lowers it again.

        take_profit is deliberately only a 4% target (avg 70,000 -> TP
        72,800) -- comfortably below the position manager's OWN unrelated
        `trailing_activation_pct` default (5.0%, auto-activates the
        pre-existing highest-price trailing stop on a big enough gain). A
        10%+ target would also auto-activate that feature and its own
        (legitimately higher, since both mechanisms only ever raise the
        stop) ratchet would confound this test's hand-computed lock-in
        number -- so this keeps the two ratchet mechanisms cleanly
        separated."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=70000,
            current_price=72800,
            take_profit=72800,
        )
        position = position_manager._positions["005930"]
        await position_manager._check_position(position)  # records TP reached
        assert position.take_profit_reached_at is not None

        # Retrace below take_profit.
        position.current_price = 71500
        await position_manager._check_position(position)

        lock_in_ratio = position_manager.config.trailing_lock_in_ratio
        expected_stop = 70000 * (1 + lock_in_ratio * (72800 - 70000) / 70000)
        assert expected_stop == pytest.approx(70840.0)
        assert position.stop_loss == pytest.approx(expected_stop)

        # Further retracement (still above the lock-in level) must NOT lower
        # the already-raised stop.
        position.current_price = 71000
        await position_manager._check_position(position)
        assert position.stop_loss == pytest.approx(expected_stop)

    @pytest.mark.asyncio
    async def test_lock_in_never_lowers_an_already_higher_stop(self, position_manager):
        """(2b) If the existing stop is already above what lock-in alone
        would compute, the hook must leave it untouched (the `max`)."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=70000,
            current_price=72800,  # 4% target, below trailing_activation_pct
            take_profit=72800,
            stop_loss=71500,  # already above the 70,840 lock-in level
        )
        position = position_manager._positions["005930"]
        await position_manager._check_position(position)  # records TP reached

        position.current_price = 72000
        await position_manager._check_position(position)

        assert position.stop_loss == 71500, "an already-higher stop must never be lowered"

    def test_lock_in_rejects_when_sanity_check_fails(self, position_manager):
        """(4) A lock-in candidate that fails `_stops_sane` against the
        CURRENT price (e.g. price has already fallen through it) is rejected
        outright, exactly like the decision-path and restore-path
        rejections -- `_stops_sane` is shared across all three call sites."""
        position = position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=70000,
            current_price=71000,
            take_profit=77000,
        )
        position.take_profit_reached_at = datetime.now()  # reached earlier

        # lock_in_price = 70000 * (1 + 0.3 * (77000-70000)/70000) = 72,100.
        # current_price 71,000 < 72,100 -> _stops_sane must reject it.
        events = []
        position_manager._apply_take_profit_lock_in(position, events)

        assert position.stop_loss is None, "insane candidate must be rejected, not applied"
        assert events == [], "a rejected candidate must not emit an observability event"

    @pytest.mark.asyncio
    async def test_lock_in_applied_logs_and_emits_event(self, position_manager):
        """G-3 (spec docs/superpowers/specs/2026-07-20-gap-discipline-
        design.md §2): a successful lock-in ratchet must be observable the
        same way the pre-existing %-trailing-stop ratchet already is
        (`_check_trailing_stop` fires TRAILING_STOP_UPDATE) -- before this
        fix a lock-in raise was silent (no log, no event)."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=70000,
            current_price=72800,
            take_profit=72800,
        )
        position = position_manager._positions["005930"]
        await position_manager._check_position(position)  # records TP reached

        events = []
        position_manager.on_event(lambda e: events.append(e))

        # Retrace below take_profit -- triggers the lock-in ratchet.
        position.current_price = 71500
        with structlog.testing.capture_logs() as logs:
            await position_manager._check_position(position)

        lock_in_ratio = position_manager.config.trailing_lock_in_ratio
        expected_stop = 70000 * (1 + lock_in_ratio * (72800 - 70000) / 70000)
        assert position.stop_loss == pytest.approx(expected_stop)

        applied_logs = [
            e for e in logs if e.get("event") == "take_profit_lock_in_applied"
        ]
        assert len(applied_logs) == 1
        assert applied_logs[0]["ticker"] == "005930"
        assert applied_logs[0]["old_stop"] == 0.0  # no prior stop_loss was set
        assert applied_logs[0]["new_stop"] == pytest.approx(expected_stop)

        lock_in_events = [
            e for e in events
            if e.event_type == PositionEventType.TRAILING_STOP_UPDATE
            and e.trigger_value == pytest.approx(expected_stop)
        ]
        assert len(lock_in_events) == 1, (
            "a successful lock-in ratchet must emit a TRAILING_STOP_UPDATE "
            "event, symmetric with the existing %-trailing-stop raise"
        )
        assert lock_in_events[0].requires_discussion is False


# -------------------------------------------
# Summary Tests
# -------------------------------------------


class TestPositionManagerSummary:
    """Tests for summary functionality."""

    def test_get_summary_empty(self, position_manager):
        """Test getting summary with no positions."""
        summary = position_manager.get_summary()

        assert summary["is_running"] is False
        assert summary["position_count"] == 0
        assert summary["total_value"] == 0

    def test_get_summary_with_positions(self, position_manager):
        """Test getting summary with positions."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=75000,
        )
        position_manager.add_position(
            ticker="000660",
            stock_name="SK하이닉스",
            quantity=50,
            avg_price=120000,
            current_price=125000,
        )

        summary = position_manager.get_summary()

        assert summary["position_count"] == 2
        assert summary["total_value"] == 75000 * 100 + 125000 * 50
        assert len(summary["positions"]) == 2


# -------------------------------------------
# Event History Tests
# -------------------------------------------


class TestEventHistory:
    """Tests for event history."""

    def test_get_events_empty(self, position_manager):
        """Test getting events when empty."""
        events = position_manager.get_events()

        assert events == []

    def test_get_events_with_filter(self, position_manager):
        """Test getting events with ticker filter."""
        # Add some events manually
        event1 = PositionEvent(
            ticker="005930",
            event_type=PositionEventType.SIGNIFICANT_GAIN,
            current_price=75000,
            trigger_value=10.0,
            message="Test event 1",
        )
        event2 = PositionEvent(
            ticker="000660",
            event_type=PositionEventType.SIGNIFICANT_LOSS,
            current_price=115000,
            trigger_value=-5.0,
            message="Test event 2",
        )

        position_manager._events = [event1, event2]

        filtered = position_manager.get_events(ticker="005930")

        assert len(filtered) == 1
        assert filtered[0].ticker == "005930"

    def test_get_events_with_limit(self, position_manager):
        """Test getting events with limit."""
        # Add many events
        for i in range(20):
            position_manager._events.append(PositionEvent(
                ticker="005930",
                event_type=PositionEventType.TRAILING_STOP_UPDATE,
                current_price=75000 + i * 100,
                trigger_value=72000,
                message=f"Event {i}",
            ))

        events = position_manager.get_events(limit=5)

        assert len(events) == 5


# -------------------------------------------
# Stop-Level Persistence Tests (F3 Task 7)
# -------------------------------------------
#
# PositionManager stop levels (stop_loss/take_profit/trailing_stop_pct) lived
# only in memory — a backend restart silently dropped every stop, requiring
# manual re-registration. These pin the persist -> restart-simulation ->
# restore round trip via SQLite (app_settings blob), mirroring
# tests/test_services/test_r5_p1_execution_reliability.py's coordinator tests.

_STOPS_KEY = "agent_chat:position_manager_state"


def _fake_holding(ticker: str, name: str, qty: int, avg_price: int, cur_price: int):
    """Minimal stand-in for services.kiwoom.models.Holding — sync_from_account
    only reads these five attributes."""
    return SimpleNamespace(
        stk_cd=ticker,
        stk_nm=name,
        hldg_qty=qty,
        avg_buy_prc=avg_price,
        cur_prc=cur_price,
    )


def _fake_kiwoom_client(holdings):
    account = SimpleNamespace(holdings=holdings)
    client = AsyncMock()
    client.get_account_balance = AsyncMock(return_value=account)
    return client


class TestSyncFromAccountCostBasis:
    """최종 리뷰 item2: `sync_from_account`의 "기존 갱신" 분기가 브로커의
    quantity/current_price만 밀어넣고 avg_price는 넘기지 않아 148주 원가가
    185주에 그대로 적용되는 정확히 그 결함(reconciler.py 모듈독스트링이 드리프트
    원인으로 지목하는 함수) — POST /api/agent-chat/positions/sync로 라이브
    도달 가능하고, 그 원가가 `_apply_take_profit_lock_in`의 락인 스탑 계산에도
    쓰인다."""

    @pytest.mark.asyncio
    async def test_sync_updates_existing_position_avg_price_to_broker_value(self, config):
        pm = PositionManager(config=config)
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=148,
            avg_price=37_950.0,
        )

        holdings = [_fake_holding("005930", "삼성전자", 185, 38_091, 38_750)]
        with patch(
            "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
            AsyncMock(return_value=_fake_kiwoom_client(holdings)),
        ):
            await pm.sync_from_account()

        position = pm.get_position("005930")
        assert position.quantity == 185
        assert position.avg_price == 38_091, (
            "브로커 원가가 반영돼야 한다 — 이전엔 37,950(148주 원가)에 "
            "동결된 채 수량만 185주로 커졌다"
        )
        assert position.current_price == 38_750


class TestStopLevelPersistence:
    """Tests for stop-level persist/restore across a simulated restart."""

    @pytest.mark.asyncio
    async def test_update_position_persists_stops(self, position_manager, temp_storage):
        """(a) update_position(stop_loss=...) is reflected in the storage blob
        once explicitly persisted."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
        )

        position_manager.update_position(
            ticker="005930",
            stop_loss=68875,
            take_profit=79750,
            trailing_stop_pct=5.0,
        )
        await position_manager._persist_stops()

        blob = await temp_storage.get_app_setting(_STOPS_KEY)
        assert blob is not None
        data = json.loads(blob)
        assert data["stops"]["005930"] == {
            "stop_loss": 68875,
            "take_profit": 79750,
            "trailing_stop_pct": 5.0,
            "take_profit_reached_at": None,  # S-5 schema extension
        }

    @pytest.mark.asyncio
    async def test_restore_stop_overlay_restores_synced_tickers(self, config, temp_storage):
        """(b) restart simulation: a fresh PM instance syncs two tickers from
        the broker, then restore_stop_overlay() brings back their stops."""
        pm1 = PositionManager(config=config)
        pm1.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            stop_loss=68875,
            take_profit=79750,
        )
        pm1.add_position(
            ticker="000660",
            stock_name="SK하이닉스",
            quantity=10,
            avg_price=115000,
            stop_loss=110000,
        )
        await pm1._persist_stops()

        # Simulate a restart: brand-new PM instance with nothing in memory.
        pm2 = PositionManager(config=config)
        holdings = [
            _fake_holding("005930", "삼성전자", 100, 72500, 73000),
            _fake_holding("000660", "SK하이닉스", 10, 115000, 116000),
        ]
        with patch(
            "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
            AsyncMock(return_value=_fake_kiwoom_client(holdings)),
        ):
            await pm2.sync_from_account()

        assert pm2.get_position("005930").stop_loss is None  # not yet restored

        restored = await pm2.restore_stop_overlay()

        assert restored == 2
        pos_1 = pm2.get_position("005930")
        assert pos_1.stop_loss == 68875
        assert pos_1.take_profit == 79750
        pos_2 = pm2.get_position("000660")
        assert pos_2.stop_loss == 110000

    @pytest.mark.asyncio
    async def test_restore_stop_overlay_session_value_wins(self, config, temp_storage):
        """Restore must NOT clobber a stop already set this session (e.g. by a
        fresher broker sync or a manual update) — only None fields are filled."""
        pm1 = PositionManager(config=config)
        pm1.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            stop_loss=68875,
        )
        await pm1._persist_stops()

        pm2 = PositionManager(config=config)
        holdings = [_fake_holding("005930", "삼성전자", 100, 72500, 73000)]
        with patch(
            "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
            AsyncMock(return_value=_fake_kiwoom_client(holdings)),
        ):
            await pm2.sync_from_account()

        # Session already set a different stop-loss before restore runs.
        pm2.update_position(ticker="005930", stop_loss=70000)

        restored = await pm2.restore_stop_overlay()

        assert restored == 0
        assert pm2.get_position("005930").stop_loss == 70000

    @pytest.mark.asyncio
    async def test_restore_stop_overlay_drops_stale_ticker_from_blob(
        self, config, temp_storage
    ):
        """(c) a blob entry for a ticker the broker no longer confirms held is
        discarded — both from the live overlay and from the blob itself."""
        pm1 = PositionManager(config=config)
        pm1.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            stop_loss=68875,
        )
        pm1.add_position(
            ticker="999999",
            stock_name="청산됨",
            quantity=10,
            avg_price=10000,
            stop_loss=9000,
        )
        await pm1._persist_stops()

        # Restart: broker sync only confirms 005930 — 999999 was fully sold.
        pm2 = PositionManager(config=config)
        holdings = [_fake_holding("005930", "삼성전자", 100, 72500, 73000)]
        with patch(
            "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
            AsyncMock(return_value=_fake_kiwoom_client(holdings)),
        ):
            await pm2.sync_from_account()

        restored = await pm2.restore_stop_overlay()

        assert restored == 1
        assert pm2.get_position("999999") is None

        blob = await temp_storage.get_app_setting(_STOPS_KEY)
        data = json.loads(blob)
        assert "999999" not in data["stops"]
        assert data["stops"]["005930"]["stop_loss"] == 68875

    @pytest.mark.asyncio
    async def test_remove_position_removes_from_blob(self, position_manager, temp_storage):
        """(d) remove_position drops the ticker from the persisted blob too."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            stop_loss=68875,
        )
        await position_manager._persist_stops()

        blob = await temp_storage.get_app_setting(_STOPS_KEY)
        assert "005930" in json.loads(blob)["stops"]

        position_manager.remove_position("005930")
        await position_manager._persist_stops()

        blob = await temp_storage.get_app_setting(_STOPS_KEY)
        data = json.loads(blob)
        assert "005930" not in data.get("stops", {})

    @pytest.mark.asyncio
    async def test_restore_stop_overlay_no_blob_is_noop(self, position_manager, temp_storage):
        """No persisted blob at all (fresh install) -> 0 restored, no crash."""
        restored = await position_manager.restore_stop_overlay()
        assert restored == 0

    def test_schedule_persist_stops_without_running_loop_is_safe(self, position_manager):
        """Sync caller with no running event loop: the fire-and-forget hook
        must not raise (mutators call it unconditionally)."""
        position_manager.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            stop_loss=68875,
        )
        position_manager.update_position(ticker="005930", stop_loss=70000)
        assert position_manager.remove_position("005930") is True


# -------------------------------------------
# Trailing-stop persistence bugfix (S-5, survival discipline)
# -------------------------------------------
#
# Pre-S-5, _check_trailing_stop raised position.stop_loss via a direct
# attribute assignment that never called _schedule_persist_stops -- so a
# raised trailing stop-loss lived only in memory and silently vanished on the
# next restart. These pin the fix: the raise now goes through
# update_position (same fire-and-forget persist hook every other stop-level
# mutator already relies on), so it actually lands in the blob and survives
# a simulated restart.


class TestTrailingStopPersistenceBugfix:
    @pytest.mark.asyncio
    async def test_trailing_stop_raise_survives_restart(self, config, temp_storage):
        """(3) Round trip: raise a trailing stop via _check_trailing_stop
        (NOT via a manual _persist_stops() call after the raise -- only the
        fire-and-forget hook inside update_position may persist it), then
        simulate a full restart and confirm restore_stop_overlay brings the
        raised value back. Deliberately RED pre-fix: the old direct
        attribute assignment never scheduled a persist, so the blob would
        still hold the pre-trailing (no-stop) baseline and restore would
        find nothing for this ticker."""
        pm1 = PositionManager(config=config)
        position = pm1.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=70000,
            current_price=76500,
            trailing_stop_pct=5.0,
        )
        position.highest_price = 76500
        # Flush the pre-trailing (no-stop) baseline deterministically, so
        # the assertions below can only pass if _check_trailing_stop's OWN
        # raise triggers a NEW persist -- not an accidental race with
        # add_position's own fire-and-forget write landing late.
        await pm1._persist_stops()

        events = []
        pm1.on_event(lambda e: events.append(e))
        await pm1._check_trailing_stop(position, events)

        raised_stop = position.stop_loss
        assert raised_stop == pytest.approx(76500 * 0.95)

        # No manual _persist_stops() call here -- only the scheduled
        # fire-and-forget hook (invoked by update_position, if and only if
        # the fix routes the raise through it) may persist the raise. Give
        # it a chance to land.
        await asyncio.sleep(0.05)

        # Simulate a restart: brand-new PM instance, nothing in memory.
        pm2 = PositionManager(config=config)
        holdings = [_fake_holding("005930", "삼성전자", 100, 70000, 76500)]
        with patch(
            "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
            AsyncMock(return_value=_fake_kiwoom_client(holdings)),
        ):
            await pm2.sync_from_account()

        assert pm2.get_position("005930").stop_loss is None  # not yet restored

        restored = await pm2.restore_stop_overlay()

        assert restored == 1, (
            "the raised trailing stop must have made it into the persisted "
            "blob via update_position -> _schedule_persist_stops"
        )
        assert pm2.get_position("005930").stop_loss == pytest.approx(raised_stop)

    @pytest.mark.asyncio
    async def test_trailing_stop_raise_rejected_by_sanity_check(self, config):
        """The new sanity gate on the trailing-stop raise: if the computed
        level is not sane against the CURRENT price, the stop_loss raise is
        skipped (kept at its prior value) while trailing_stop_price -- a
        pure internal tracking field, not a live order level -- still
        updates as before."""
        pm = PositionManager(config=config)
        position = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=90,
            current_price=97,
            trailing_stop_pct=1.0,
        )
        position.highest_price = 100  # new_trailing_price = 100*0.99 = 99 > current 97

        events = []
        await pm._check_trailing_stop(position, events)

        assert position.stop_loss is None, "insane trailing raise must be rejected"
        assert position.trailing_stop_price == pytest.approx(99.0), (
            "the internal trailing tracking value still updates independent "
            "of the stop_loss sanity gate"
        )


# -------------------------------------------
# Persist single-writer / race (T7 review CRITICAL 1)
# -------------------------------------------


class TestPersistSingleWriter:
    """A stale fire-and-forget persist — scheduled by sync_from_account's
    add_position BEFORE restore_stop_overlay ran, carrying a None-stops payload
    — must never clobber restore's corrective save. Each set_app_setting opens
    its own aiosqlite connection, so without a single-writer discipline the DB
    landing order is unguaranteed and the blob can silently revert to null
    stops right after they were restored."""

    @pytest.mark.asyncio
    async def test_delayed_stale_write_cannot_clobber_restore(
        self, config, temp_storage, monkeypatch
    ):
        # A previous session persisted a stop for 005930.
        await temp_storage.set_app_setting(
            _STOPS_KEY,
            json.dumps({"stops": {"005930": {
                "stop_loss": 68875.0,
                "take_profit": None,
                "trailing_stop_pct": None,
            }}}),
        )

        # Delay-inject the FIRST PM-originated write (the None-stops persist
        # scheduled by add_position) so its DB landing happens after restore's
        # corrective save would land — the reviewer's adversarial interleaving.
        real_set = temp_storage.set_app_setting
        calls = {"n": 0}

        async def delayed_set(key, value):
            calls["n"] += 1
            if calls["n"] == 1:
                await asyncio.sleep(0.15)
            await real_set(key, value)

        monkeypatch.setattr(temp_storage, "set_app_setting", delayed_set)

        pm = PositionManager(config=config)
        # sync_from_account shape: broker holding arrives with NO stops →
        # schedules a fire-and-forget persist of a None-stops blob.
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=73000,
        )
        await asyncio.sleep(0.05)  # let the scheduled task reach the delayed write

        restored = await pm.restore_stop_overlay()
        assert restored == 1
        assert pm.get_position("005930").stop_loss == 68875.0

        await asyncio.sleep(0.3)  # let the delayed stale write land / drain

        blob = await temp_storage.get_app_setting(_STOPS_KEY)
        data = json.loads(blob)
        assert data["stops"]["005930"]["stop_loss"] == 68875.0, (
            "stale None-stops write landed after restore's corrective save — "
            "the persisted stops silently reverted to null"
        )

    @pytest.mark.asyncio
    async def test_pending_write_cannot_land_before_restore_read(
        self, config, temp_storage, monkeypatch
    ):
        """Final-review CRITICAL (C1) — the INVERSE interleaving of
        test_delayed_stale_write_cannot_clobber_restore above.

        In production, ChatCoordinator.start() awaits
        sync_from_account() then immediately awaits restore_stop_overlay()
        with no yield in between. sync_from_account's add_position calls
        schedule a fire-and-forget None-stops persist synchronously; that
        pending writer gets its FIRST chance to run at restore's own first
        await. If it reaches the DB before restore's read, restore reads an
        all-None blob, "restores" nothing, and its own unconditional
        corrective re-save then cements the loss — the good stop is gone for
        good, with no delayed-write window for the OTHER test to catch.

        Delay-inject the READ (not the write, as above) so the pending write
        gets a chance to land while restore's read is in flight."""
        # A previous session persisted a good stop for 005930.
        await temp_storage.set_app_setting(
            _STOPS_KEY,
            json.dumps({"stops": {"005930": {
                "stop_loss": 68875.0,
                "take_profit": None,
                "trailing_stop_pct": None,
            }}}),
        )

        real_get = temp_storage.get_app_setting

        async def delayed_get(key, default=None):
            # Yield BEFORE actually reading, so the pending None-stops write
            # (already scheduled by add_position below) gets a window to
            # land in the DB first — the adversarial ordering C1 describes.
            await asyncio.sleep(0.15)
            return await real_get(key, default)

        monkeypatch.setattr(temp_storage, "get_app_setting", delayed_get)

        pm = PositionManager(config=config)
        # sync_from_account shape: broker holding arrives with NO stops →
        # schedules a fire-and-forget persist of a None-stops blob. No sleep
        # follows — mirrors "no yield occurs before restore_stop_overlay
        # entry" from the finding.
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=73000,
        )

        restored = await pm.restore_stop_overlay()

        assert restored == 1, (
            "the pending None-stops write landed before restore's read — "
            "restore saw an all-None blob and restored nothing"
        )
        assert pm.get_position("005930").stop_loss == 68875.0

        blob = await temp_storage.get_app_setting(_STOPS_KEY)
        data = json.loads(blob)
        assert data["stops"]["005930"]["stop_loss"] == 68875.0, (
            "restore's corrective re-save cemented the race's data loss "
            "into the blob"
        )


# -------------------------------------------
# Stop sanity validation (P0-2)
# -------------------------------------------


class TestStopSanity:
    """_stops_sane guards BOTH stop-setting paths — agent-decision stops
    (_apply_decision) and blob restore (restore_stop_overlay).

    Root cause pinned here: the 2026-07-12 15:40 hang — a discussion decision
    set stop_loss 1,993,680 ABOVE the price 1,845,000, so stop_loss_hit fired
    on every monitor cycle → infinite event loop → CPU spin."""

    def test_stops_sane_contract(self, position_manager):
        sane = position_manager._stops_sane
        assert sane(70000, 68000, 75000) is True
        assert sane(70000, None, None) is True
        assert sane(70000, 70000, None) is False    # stop >= price
        assert sane(70000, 71000, None) is False
        assert sane(70000, None, 70000) is False    # take <= price
        assert sane(70000, None, 69000) is False
        assert sane(0, 68000, None) is False        # unknown price → fail-closed
        assert sane(-1, None, None) is False

    # ---- decision path (_apply_decision HOLD/ADD) ----

    def _pm_and_position(self, config, current_price=1_845_000.0):
        pm = PositionManager(config=config)
        pos = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=1_800_000,
            current_price=current_price,
            stop_loss=1_700_000,
        )
        return pm, pos

    @staticmethod
    def _decision(stop_loss=None, take_profit=None):
        return SimpleNamespace(
            action=DecisionAction.HOLD,
            quantity=None,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    @staticmethod
    def _notifier():
        notifier = MagicMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock()
        return notifier

    @pytest.mark.asyncio
    async def test_decision_stop_above_price_rejected(self, config):
        """(i) The 15:40-hang shape: decision stop 1,993,680 >= price 1,845,000
        → rejected, existing stop kept, human notified."""
        pm, pos = self._pm_and_position(config)
        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, self._decision(stop_loss=1_993_680))

        assert pos.stop_loss == 1_700_000, "insane decision stop must be rejected"
        notifier.send_message.assert_awaited_once()
        assert "결정 스탑 기각" in notifier.send_message.await_args.args[0]

    # ---- 손절 단조성 (2026-07-28) ----

    @pytest.mark.asyncio
    async def test_decision_stop_cannot_be_lowered(self, config):
        """에이전트 결정은 손절을 **낮추지 못한다**.

        라이브 사고(094840, 2026-07-28): 30분 주기 전략 재평가마다 LLM이
        현재가 기준으로 손절을 새로 제안했고, 주가가 빠지자 손절이 따라
        내려갔다(12,492 → 12,238 → 12,173). 포지션 수량은 그대로인데 손절만
        넓어져 리스크가 +56%, 손익비가 2.36 → 1.19로 붕괴했다.

        `_stops_sane`은 "손절이 현재가보다 위"인 명백한 오류만 잡을 뿐
        하향은 검사하지 않았다. 익절 락인(`max(...)`)과 트레일링
        (`raise_stop`) 경로는 이미 상향만 허용하므로, 결정 경로도 같은
        규율을 따르게 한다.
        """
        pm, pos = self._pm_and_position(config)      # stop 1,700,000, price 1,845,000
        await pm._apply_decision(pos, self._decision(stop_loss=1_600_000))
        assert pos.stop_loss == 1_700_000, "손절 하향은 무시되어야 한다"

    @pytest.mark.asyncio
    async def test_decision_stop_can_be_raised(self, config):
        """상향은 허용된다 — 이익 보호(트레일링)와 같은 방향이다."""
        pm, pos = self._pm_and_position(config)
        await pm._apply_decision(pos, self._decision(stop_loss=1_750_000))
        assert pos.stop_loss == 1_750_000

    @pytest.mark.asyncio
    async def test_decision_stop_set_when_none(self, config):
        """기존 손절이 없으면 값을 설정한다(하향 판정 대상이 아니다)."""
        pm, pos = self._pm_and_position(config)
        pm.update_position(pos.ticker, stop_loss=None)
        pos.stop_loss = None
        await pm._apply_decision(pos, self._decision(stop_loss=1_600_000))
        assert pos.stop_loss == 1_600_000

    @pytest.mark.asyncio
    async def test_take_profit_still_free_to_move_down(self, config):
        """익절은 단조성 대상이 아니다 — 손절만 고정하면 손익비는 보호된다.

        익절 하향은 "빨리 팔자"라 손실 위험을 키우지 않으므로 기존 동작을
        유지한다(과도한 제약은 YAGNI)."""
        pm, pos = self._pm_and_position(config)
        pm.update_position(pos.ticker, take_profit=2_000_000)
        await pm._apply_decision(pos, self._decision(take_profit=1_900_000))
        assert pos.take_profit == 1_900_000

    @pytest.mark.asyncio
    async def test_decision_take_below_price_rejected(self, config):
        """(ii) take_profit <= current price → instant take-profit → rejected."""
        pm, pos = self._pm_and_position(config)
        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, self._decision(take_profit=1_500_000))

        assert pos.take_profit is None, "insane decision take-profit must be rejected"
        notifier.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_decision_valid_stops_applied(self, config):
        """(iii) Sane stops from a decision are applied normally."""
        pm, pos = self._pm_and_position(config)
        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(
                pos, self._decision(stop_loss=1_750_000, take_profit=1_950_000)
            )

        assert pos.stop_loss == 1_750_000
        assert pos.take_profit == 1_950_000
        notifier.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_decision_rejected_when_price_unknown(self, config):
        """(iv) current_price == 0 → cannot validate → fail-closed reject."""
        pm, pos = self._pm_and_position(config)
        pos.current_price = 0
        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, self._decision(stop_loss=1_750_000))

        assert pos.stop_loss == 1_700_000
        notifier.send_message.assert_awaited_once()

    # ---- restore path (restore_stop_overlay) ----

    @pytest.mark.asyncio
    async def test_restore_drops_insane_blob_entries(self, config, temp_storage):
        """(b) The live-pollution shape: fixture stops 85000/80000 persisted
        for 005930 while the stock now trades at 90,000 — stop_loss 85,000 >=
        take_profit 80,000 is a self-contradictory pair independent of the
        current price (D1b: `take_profit <= current_price` ALONE is no
        longer this test's drop reason — that shape now restores/preserves,
        see `test_restore_preserves_gap_through_tp_and_logs` below, which
        reuses this test's PRE-D1b fixture values 68875/79750/90000 to pin
        the inversion explicitly). The polluted entry must be skipped AND
        its values dropped from the blob; the sane entry restores normally."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "005930": {
                "stop_loss": 85000.0,
                "take_profit": 80000.0,
                "trailing_stop_pct": None,
            },
            "000660": {
                "stop_loss": 110000.0,
                "take_profit": 130000.0,
                "trailing_stop_pct": None,
            },
        }}))

        pm = PositionManager(config=config)
        pm.add_position(
            ticker="005930", stock_name="삼성전자", quantity=100,
            avg_price=72500, current_price=90000,
        )
        pm.add_position(
            ticker="000660", stock_name="SK하이닉스", quantity=10,
            avg_price=115000, current_price=116000,
        )

        restored = await pm.restore_stop_overlay()

        assert restored == 1, "only the sane entry may restore"
        polluted = pm.get_position("005930")
        assert polluted.stop_loss is None
        assert polluted.take_profit is None
        valid = pm.get_position("000660")
        assert valid.stop_loss == 110000.0
        assert valid.take_profit == 130000.0

        # Polluted values dropped from the blob too (re-save reflects positions).
        data = json.loads(await temp_storage.get_app_setting(_STOPS_KEY))
        assert data["stops"]["005930"]["stop_loss"] is None
        assert data["stops"]["005930"]["take_profit"] is None
        assert data["stops"]["000660"]["stop_loss"] == 110000.0

    @pytest.mark.asyncio
    async def test_restore_drop_notifies(self, config, temp_storage):
        """(M1, final-review) A restore-drop was previously Telegram-silent —
        the human had no way to learn a position came back up from a restart
        with NO stop-loss/take-profit protection. The drop path must fire the
        same best-effort notifier the decision-path rejection uses.

        Fixture (D1b, 2026-07-20 follow-up): stop_loss(85000) >=
        take_profit(80000) is a genuinely still-insane structural violation
        post-D1b (contradictory levels, independent of current price) —
        the original 68875/79750/90000 fixture used here no longer drops
        (that shape is a preserved tp gap-up now, see
        `test_restore_preserves_gap_through_tp_and_logs`)."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "005930": {
                "stop_loss": 85000.0,
                "take_profit": 80000.0,
                "trailing_stop_pct": None,
            },
        }}))

        pm = PositionManager(config=config)
        pm.add_position(
            ticker="005930", stock_name="삼성전자", quantity=100,
            avg_price=72500, current_price=90000,
        )

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            restored = await pm.restore_stop_overlay()

        assert restored == 0
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "복원 스탑 기각" in msg
        assert "005930" in msg

    # ---- restore path: gap-through preservation (G-1, 2026-07-20) ----
    #
    # 2026-07-20 00:02 재시작 실전 사례: PM이 인상해둔 스탑(1,807,923)이
    # 프리오픈 갭 가격(1,782,000)에 뚫린 채 복원되면서 (구)`_stops_sane`
    # (스탑>=현재가 => insane)에 걸려 통째로 드롭됐다 --
    # restore_stops_insane_dropped ticker=000660. D1(사용자 결정,
    # docs/superpowers/specs/2026-07-20-gap-discipline-design.md): 갭 관통은
    # "위법"이 아니라 규율의 정상 형태다 -- 스탑을 원본 그대로 보존하고,
    # 발동 판정은 장중 감시 루프(`_check_position`)의 정상 STOP_LOSS_HIT
    # 로직에 위임한다. `_stops_sane` 자체는 장중 신규 설정 경로
    # (결정/락인/트레일링)에서 계속 그대로 쓰인다(byte-불변) -- 아래
    # 테스트들은 restore 전용 분류만 다룬다.

    @pytest.mark.asyncio
    async def test_restore_preserves_gap_through_stop_and_logs(self, config, temp_storage):
        """① 오늘 실사례 그대로 재현: stop_loss 1,807,923 >= current_price
        1,782,000 (프리오픈 갭 관통). 드롭 대신 보존 +
        gap_through_stop_restored info 로그(티커·스탑·현재가). 드롭이
        아니므로 기각 통지는 발사되지 않는다. Pre-fix RED: 공유
        `_stops_sane`이 이 엔트리를 통째로 드롭했다."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "000660": {
                "stop_loss": 1_807_923,
                "take_profit": None,
                "trailing_stop_pct": None,
            },
        }}))

        pm = PositionManager(config=config)
        pm.add_position(
            ticker="000660", stock_name="SK하이닉스", quantity=10,
            avg_price=1_800_000, current_price=1_782_000,
        )

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ), patch.object(pm_mod, "logger") as mock_logger:
            restored = await pm.restore_stop_overlay()

        assert restored == 1
        pos = pm.get_position("000660")
        assert pos.stop_loss == 1_807_923, "gap-through stop must be preserved, not dropped"
        notifier.send_message.assert_not_awaited()

        gap_logs = [
            c for c in mock_logger.info.call_args_list
            if c.args and c.args[0] == "gap_through_stop_restored"
        ]
        assert len(gap_logs) == 1
        _, kwargs = gap_logs[0]
        assert kwargs["ticker"] == "000660"
        assert kwargs["stop_loss"] == 1_807_923
        assert kwargs["current_price"] == 1_782_000

        drop_warnings = [
            c for c in mock_logger.warning.call_args_list
            if c.args and c.args[0] == "restore_stops_insane_dropped"
        ]
        assert drop_warnings == []

    @pytest.mark.asyncio
    async def test_restore_preserved_gap_through_stop_fires_stop_loss_hit_next_tick(
        self, config, temp_storage
    ):
        """② 보존된 갭 관통 스탑이 다음 감시 틱에서 정상적으로
        STOP_LOSS_HIT을 발화하는 체인 확인 -- D1 "발동은 감시 루프 위임"의
        실질 증거. 발동 코드(`_check_position`) 자체는 무변경이어야 한다."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "000660": {
                "stop_loss": 1_807_923,
                "take_profit": None,
                "trailing_stop_pct": None,
            },
        }}))

        pm = PositionManager(config=config)
        pm.add_position(
            ticker="000660", stock_name="SK하이닉스", quantity=10,
            avg_price=1_800_000, current_price=1_782_000,
        )

        restored = await pm.restore_stop_overlay()
        assert restored == 1

        events = []
        pm.on_event(lambda e: events.append(e))
        position = pm.get_position("000660")
        await pm._check_position(position)

        stop_loss_events = [
            e for e in events if e.event_type == PositionEventType.STOP_LOSS_HIT
        ]
        assert len(stop_loss_events) >= 1, (
            "the preserved gap-through stop must fire a normal STOP_LOSS_HIT "
            "on the next monitor tick, exactly like any other price crossing"
        )

    @pytest.mark.asyncio
    async def test_restore_drops_structurally_insane_stop_gte_take_profit(
        self, config, temp_storage
    ):
        """③ 구조적 위법: stop_loss(1,807,923) >= take_profit(1,800,000) --
        두 저장 레벨 자체가 현재가와 무관하게 논리적으로 모순된다. 갭 관통
        모양(stop >= current_price)을 동시에 띠어도 구조적 위법이 우선해
        여전히 드롭되어야 한다(신뢰할 수 없는 데이터 우선 기각)."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "000660": {
                "stop_loss": 1_807_923,
                "take_profit": 1_800_000,
                "trailing_stop_pct": None,
            },
        }}))

        pm = PositionManager(config=config)
        pm.add_position(
            ticker="000660", stock_name="SK하이닉스", quantity=10,
            avg_price=1_800_000, current_price=1_782_000,
        )

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            restored = await pm.restore_stop_overlay()

        assert restored == 0
        pos = pm.get_position("000660")
        assert pos.stop_loss is None
        assert pos.take_profit is None
        notifier.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_reached_at_restored_independently_of_structural_violation(
        self, config, temp_storage
    ):
        """④ take_profit_reached_at은 스탑 필드의 sanity 판정과 무관하게
        독립 복원되어야 한다 -- 구조적 위법으로 stop/take가 드롭되는
        엔트리에서도 reached_at은 살아야 한다(단순 부기 타임스탬프, 라이브
        주문 레벨이 아니므로 위법 개념 자체가 없다)."""
        reached_at = datetime(2026, 7, 19, 14, 30, 0)
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "000660": {
                "stop_loss": 1_807_923,
                "take_profit": 1_800_000,  # stop >= take -> structural drop
                "trailing_stop_pct": None,
                "take_profit_reached_at": reached_at.isoformat(),
            },
        }}))

        pm = PositionManager(config=config)
        pm.add_position(
            ticker="000660", stock_name="SK하이닉스", quantity=10,
            avg_price=1_800_000, current_price=1_782_000,
        )

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            restored = await pm.restore_stop_overlay()

        pos = pm.get_position("000660")
        assert pos.stop_loss is None, "structural violation must still drop the stop"
        assert pos.take_profit is None
        assert pos.take_profit_reached_at == reached_at, (
            "reached_at must restore independently of the stop/take structural drop"
        )
        assert restored == 1, "reached_at restore alone must still count as a restore"

    @pytest.mark.asyncio
    async def test_decision_gap_through_stop_still_rejected_unlike_restore(self, config):
        """⑤ 회귀 핀: 장중 신규 설정 경로(_apply_decision -> _stops_sane)는
        G-1로 byte-불변이어야 한다 -- 오늘 실사례와 동일한 값(stop
        1,807,923 >= price 1,782,000)이 "결정"으로 들어오면 여전히
        기각되어야 한다(락인/토론발 스탑의 즉시 발동 방지). restore
        전용 경로만 갭 관통을 보존하고, 장중 신규 설정 경로는 그대로
        거부한다는 비대칭을 고정하는 핀."""
        pm, pos = self._pm_and_position(config, current_price=1_782_000.0)
        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, self._decision(stop_loss=1_807_923))

        assert pos.stop_loss == 1_700_000, (
            "decision-path gap-through stop must still be rejected -- _stops_sane "
            "is unchanged by G-1"
        )
        notifier.send_message.assert_awaited_once()

    # ---- restore path: gap-through preservation, take_profit side (D1b,
    # 2026-07-20 follow-up) ----
    #
    # 결정 D1b (spec docs/superpowers/specs/2026-07-20-gap-discipline-design.md
    # §0, commit 614ded1): G-1이 stop_loss 갭 관통은 보존하면서 take_profit
    # 갭업(take_profit <= current_price)은 여전히 "구조적 위법"으로 분류해
    # 엔트리 전체(동반 스탑 + S-5 락인 트리거 포함)를 드롭하던 비대칭을
    # 해소한다. 무해 근거: 익절은 토론 트리거일 뿐 자동 매도가 없다
    # (auto_execute_take_profit=False, take_profit_mode=user_approval) --
    # 보존해도 즉시 청산이 발생하지 않고, 오히려 보존해야 S-5 락인 트리거와
    # 동반 스탑이 살아남는다. 잔존 구조적 위법은 가격 <= 0과 stop >= tp
    # 두 가지뿐이다.

    @pytest.mark.asyncio
    async def test_restore_preserves_gap_through_tp_and_logs(self, config, temp_storage):
        """⑥ D1b 반전 핀: 이 픽스처(stop_loss 68875 / take_profit 79750 /
        current_price 90000)는 `test_restore_drops_insane_blob_entries`가
        D1b 이전에 "폴루션(insane)"으로 드롭하던 정확히 그 값이다 --
        take_profit(79750) <= current_price(90000)라는 이유만으로는 더 이상
        구조적 위법이 아니다(stop(68875) < take(79750)이므로 stop>=take
        모순도 아니다). D1b 이후에는 드롭 대신 보존 + 동반 스탑도 함께
        생존 + `gap_through_tp_restored` info 로그(티커·익절가·현재가).
        드롭이 아니므로 기각 통지는 발사되지 않는다. Pre-fix RED: 구
        `_restore_stop_is_structurally_insane`가 이 엔트리를 통째로
        드롭했다(스탑까지 함께)."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "005930": {
                "stop_loss": 68875.0,
                "take_profit": 79750.0,
                "trailing_stop_pct": None,
            },
        }}))

        pm = PositionManager(config=config)
        pm.add_position(
            ticker="005930", stock_name="삼성전자", quantity=100,
            avg_price=72500, current_price=90000,
        )

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ), patch.object(pm_mod, "logger") as mock_logger:
            restored = await pm.restore_stop_overlay()

        assert restored == 1
        pos = pm.get_position("005930")
        assert pos.take_profit == 79750.0, (
            "gap-up take_profit must be preserved, not dropped (D1b)"
        )
        assert pos.stop_loss == 68875.0, (
            "the accompanying stop_loss must survive alongside the preserved tp "
            "-- D1b's whole point is the entry is no longer dropped wholesale"
        )
        notifier.send_message.assert_not_awaited()

        gap_logs = [
            c for c in mock_logger.info.call_args_list
            if c.args and c.args[0] == "gap_through_tp_restored"
        ]
        assert len(gap_logs) == 1
        _, kwargs = gap_logs[0]
        assert kwargs["ticker"] == "005930"
        assert kwargs["take_profit"] == 79750.0
        assert kwargs["current_price"] == 90000

        drop_warnings = [
            c for c in mock_logger.warning.call_args_list
            if c.args and c.args[0] == "restore_stops_insane_dropped"
        ]
        assert drop_warnings == []

    @pytest.mark.asyncio
    async def test_restore_preserved_gap_through_tp_chain_no_sell_then_lock_in(
        self, config, temp_storage, monkeypatch
    ):
        """⑦ D1b 체인 (무해성 + 락인 훅 생존의 실 경로 증거): 보존된 tp
        갭업 엔트리가 실 경로(`_check_position`)에서 (a) TAKE_PROFIT_HIT을
        발화해도 매도가 전혀 없고(quantity 불변, auto_execute=False) --
        토론/기록 트리거일 뿐 -- take_profit_reached_at만 기록하며, (b) 그
        후 가격이 되돌림하면 S-5 락인 훅(`_apply_take_profit_lock_in`)이
        `TestTakeProfitLockIn.test_retracement_locks_in_stop_at_breakeven_plus_alpha`와
        동일한 손계산으로 stop_loss를 정상 ratchet한다 -- 같은 세션에서 tp에
        도달한 것과 완전히 동일한 체인이 restore로 보존된 엔트리에서도
        그대로 작동함을 증명한다."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "005930": {
                "stop_loss": 68000.0,
                "take_profit": 72800.0,
                "trailing_stop_pct": None,
            },
        }}))

        pm = PositionManager(config=config)
        # regression-guard(D1b 리뷰 Minor): 분류 로직이 되돌아가 이 픽스처가
        # 드롭 경로를 타더라도 실 Telegram으로 새지 않게 — 형제 테스트와
        # 동일 타깃 목킹(리뷰 검증 중 실발송 사고의 재발 방지).
        monkeypatch.setattr(
            "services.telegram.get_telegram_notifier", lambda: self._notifier()
        )
        pm.add_position(
            ticker="005930", stock_name="삼성전자", quantity=100,
            avg_price=70000, current_price=72800,
        )

        restored = await pm.restore_stop_overlay()
        assert restored == 1
        position = pm.get_position("005930")
        assert position.take_profit == 72800.0, "gap-up tp preserved by restore"
        assert position.stop_loss == 68000.0, (
            "accompanying stop preserved alongside the preserved tp"
        )
        assert position.take_profit_reached_at is None, (
            "not yet marked -- only a real monitor tick marks it, not restore itself"
        )

        # Tick 1: real _check_position path -- TAKE_PROFIT_HIT fires, no sell.
        events = []
        pm.on_event(lambda e: events.append(e))
        await pm._check_position(position)

        tp_events = [e for e in events if e.event_type == PositionEventType.TAKE_PROFIT_HIT]
        assert len(tp_events) >= 1
        assert tp_events[0].auto_execute is False
        assert position.quantity == 100, (
            "no auto-sell on a restore-preserved gap-through tp -- take-profit "
            "execution stays discussion-gated exactly like a same-session hit"
        )
        assert position.take_profit_reached_at is not None

        # Tick 2: retrace below tp -- the S-5 lock-in ratchet must fire
        # normally, chained off the restore-preserved tp/reached_at exactly
        # like a same-session take-profit hit would.
        position.current_price = 71500
        await pm._check_position(position)

        lock_in_ratio = pm.config.trailing_lock_in_ratio
        expected_stop = 70000 * (1 + lock_in_ratio * (72800 - 70000) / 70000)
        assert expected_stop == pytest.approx(70840.0)
        assert position.stop_loss == pytest.approx(expected_stop), (
            "S-5 lock-in must ratchet the stop off a restore-preserved "
            "gap-through tp, same as a same-session take-profit hit"
        )

    @pytest.mark.asyncio
    async def test_restore_drops_when_current_price_invalid(self, config, temp_storage):
        """⑧ 구조적 위법 잔존 (2종 중 하나): current_price가 알수없음
        (<=0)이면 스탑/익절 필드가 어떤 값이든 검증 자체가 불가능하다 --
        D1b로도 바뀌지 않는 fail-closed 드롭. 두 저장 값 모두 통째로 드롭
        + 사람에게 통지되어야 한다."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "005930": {
                "stop_loss": 65000.0,
                "take_profit": 80000.0,
                "trailing_stop_pct": None,
            },
        }}))

        pm = PositionManager(config=config)
        pm.add_position(
            ticker="005930", stock_name="삼성전자", quantity=100,
            avg_price=70000, current_price=72000,
        )
        pm.get_position("005930").current_price = 0

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            restored = await pm.restore_stop_overlay()

        assert restored == 0
        pos = pm.get_position("005930")
        assert pos.stop_loss is None
        assert pos.take_profit is None
        notifier.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_decision_take_profit_gap_through_still_rejected_unlike_restore(
        self, config
    ):
        """⑨ 회귀 핀 (⑤의 대칭): 장중 신규 설정 경로(_apply_decision ->
        `_stops_sane`)는 D1b로도 byte-불변이어야 한다 -- take_profit이
        현재가 이하로 "결정"에 들어오면(즉시 익절 폭주 방지) 여전히
        기각되어야 한다. restore 전용 경로만 tp 갭업을 보존하고, 장중
        신규 설정 경로는 그대로 거부한다는 비대칭을 고정하는 핀."""
        pm, pos = self._pm_and_position(config, current_price=72800.0)
        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, self._decision(take_profit=72800.0))

        assert pos.take_profit is None, (
            "decision-path gap-through take_profit must still be rejected -- "
            "_stops_sane is unchanged by D1b"
        )
        notifier.send_message.assert_awaited_once()


# -------------------------------------------
# Apply-Decision Honesty (P0, 2026-07-15)
# -------------------------------------------
#
# _apply_decision previously (a) let a partial REDUCE decision silently
# decrement the monitored quantity via update_position(quantity=...) with NO
# broker sell order behind it — a shadow-ledger lie that desynced from the
# real account until the next sync_from_account overwrote it; and (b) let an
# ADD decision fall into the exact same branch as HOLD, discarding the "add"
# intent in silence. These tests pin the P0 honesty fix: no more silent
# quantity mutation for an unexecuted partial reduce, plus an explicit
# not-executed notice for both partial REDUCE and ADD. The full-close REDUCE
# path (new_quantity <= 0) and plain SELL are real execution and must keep
# working exactly as before (regression).
#
# Audit: docs/superpowers/audits/2026-07-14-autonomous-position-mgmt-audit.md
# Plan: docs/superpowers/plans/2026-07-15-position-mgmt-execution.md (Task P0)

import services.autonomy as autonomy_pkg
from services.autonomy import GateDecision


def _honesty_decision(action, quantity=None, stop_loss=None, take_profit=None):
    return SimpleNamespace(
        action=action,
        quantity=quantity,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


class TestApplyDecisionHonestyP0:
    """P0: no silent quantity mutation / demotion to a no-op.

    (Partial REDUCE's P0 "must not desync the shadow ledger / notify only"
    behavior was superseded by P1's real execution path — see
    TestApplyDecisionReducePartialP1 below. ADD's P0 "no execution path"
    behavior was likewise superseded by P2's real execution path — see
    TestApplyDecisionAddP2 below, including the sizing-computes-to-zero
    not-executed notice that replaces this class's old "no execution path"
    one.)"""

    @staticmethod
    def _position(config, quantity=100, current_price=72500):
        pm = PositionManager(config=config)
        pos = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=quantity,
            avg_price=72500,
            current_price=current_price,
        )
        return pm, pos

    @staticmethod
    def _notifier():
        notifier = MagicMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock()
        return notifier

    # ---- Regression: real execution paths must be unaffected ----

    @pytest.mark.asyncio
    async def test_full_close_reduce_still_executes(self, config, monkeypatch):
        """A REDUCE decision whose quantity closes the whole position
        (new_quantity <= 0) is real execution and must be unaffected."""
        pm, pos = self._position(config, quantity=100)

        closed = []
        fake_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            closed.append(ticker)
            return MagicMock()  # non-None -- coordinator proceeded (N3)

        fake_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(
            pos, _honesty_decision(DecisionAction.REDUCE, quantity=100)
        )

        assert closed == ["005930"]
        assert pm.get_position("005930") is None

    @pytest.mark.asyncio
    async def test_sell_still_executes(self, config, monkeypatch):
        """A plain SELL decision is real execution and must be unaffected."""
        pm, pos = self._position(config, quantity=100)

        closed = []
        fake_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            closed.append(ticker)
            return MagicMock()  # non-None -- coordinator proceeded (N3)

        fake_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(pos, _honesty_decision(DecisionAction.SELL))

        assert closed == ["005930"]
        assert pm.get_position("005930") is None


# -------------------------------------------
# Partial REDUCE Real Execution (P1, 2026-07-15)
# -------------------------------------------
#
# P1 replaces P0's notify-only "부분청산 미지원" stand-in with a real,
# quantity-specified SELL through `ExecutionCoordinator._reduce_position`,
# gated the same way the full-close path is gated: check_autonomy(SELL).
#
# Audit: docs/superpowers/audits/2026-07-14-autonomous-position-mgmt-audit.md
# Plan: docs/superpowers/plans/2026-07-15-position-mgmt-execution.md (Task P1)

from services.trading.models import OrderResult, OrderSide, RiskParameters


def _order_result(filled_quantity: int, requested_quantity: int = None) -> OrderResult:
    return OrderResult(
        order_id="o1",
        ticker="005930",
        side=OrderSide.SELL,
        requested_quantity=(
            requested_quantity if requested_quantity is not None else filled_quantity
        ),
        filled_quantity=filled_quantity,
        avg_price=72_500,
        status="filled" if filled_quantity > 0 else "rejected",
    )


class TestApplyDecisionReducePartialP1:
    """Partial REDUCE (new_quantity > 0) now places a real, quantity-specified
    SELL order via the SAME autonomy gate the full-close path uses, and
    decrements the monitored quantity by the ACTUAL filled amount."""

    @staticmethod
    def _position(config, quantity=100, current_price=72500):
        pm = PositionManager(config=config)
        pos = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=quantity,
            avg_price=72500,
            current_price=current_price,
        )
        return pm, pos

    @staticmethod
    def _notifier():
        notifier = MagicMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock()
        return notifier

    @pytest.mark.asyncio
    async def test_partial_reduce_places_sell_for_specified_quantity_not_full(
        self, config, monkeypatch
    ):
        """The gate-allowed happy path: a REDUCE for 30 of 100 places a SELL
        for exactly 30 (not the full 100), and the monitored quantity
        decrements by the ACTUAL fill."""
        pm, pos = self._position(config, quantity=100)

        reduce_calls = []
        fake_coord = MagicMock()

        async def _reduce(ticker, quantity, decision_id=None, reason=None, **kwargs):
            reduce_calls.append((ticker, quantity))
            return _order_result(filled_quantity=quantity)

        fake_coord._reduce_position = _reduce
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        gate_calls = []

        async def allow_gate(market, **kwargs):
            gate_calls.append(kwargs)
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(
            pos, _honesty_decision(DecisionAction.REDUCE, quantity=30)
        )

        assert reduce_calls == [("005930", 30)], (
            "must place a SELL for the SPECIFIED (clamped) quantity, not the "
            "full position"
        )
        assert gate_calls and gate_calls[0]["quantity"] == 30, (
            "check_autonomy must be called with the intended sell quantity"
        )
        assert pm.get_position("005930").quantity == 70, (
            "monitored quantity must decrement by the ACTUAL executed amount"
        )

    @pytest.mark.asyncio
    async def test_partial_reduce_gate_denied_leaves_quantity_unchanged(
        self, config, monkeypatch
    ):
        """check_autonomy(SELL) denied → no order placed, position quantity
        unchanged, human notified (P0's behavior for the genuine
        can't-execute case, preserved for gate denial)."""
        pm, pos = self._position(config, quantity=100)

        reduce_calls = []
        fake_coord = MagicMock()

        async def _reduce(ticker, quantity, decision_id=None, reason=None, **kwargs):
            reduce_calls.append((ticker, quantity))
            return _order_result(filled_quantity=quantity)

        fake_coord._reduce_position = _reduce
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def deny_gate(market, **kwargs):
            return GateDecision(
                allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode"
            )

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(
                pos, _honesty_decision(DecisionAction.REDUCE, quantity=30)
            )

        assert reduce_calls == [], "gate-denied reduce must not place an order"
        assert pm.get_position("005930").quantity == 100, (
            "gate-denied reduce must leave the position unchanged"
        )
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "005930" in msg
        assert "hitl" in msg

    @pytest.mark.asyncio
    async def test_partial_reduce_unfilled_leaves_quantity_unchanged(
        self, config, monkeypatch
    ):
        """A gate-allowed reduce whose order does not fill at all must leave
        the monitored quantity untouched (no phantom decrement), and the
        operator must be notified — an accepted-but-unfilled order is not
        something that should only show up in logs (P1/P2 review MEDIUM)."""
        pm, pos = self._position(config, quantity=100)

        fake_coord = MagicMock()

        async def _reduce(ticker, quantity, decision_id=None, reason=None, **kwargs):
            return _order_result(filled_quantity=0, requested_quantity=quantity)

        fake_coord._reduce_position = _reduce
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(
                pos, _honesty_decision(DecisionAction.REDUCE, quantity=30)
            )

        assert pm.get_position("005930").quantity == 100
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "005930" in msg

    @pytest.mark.asyncio
    async def test_partial_reduce_no_coordinator_position_notifies_desync(
        self, config, monkeypatch
    ):
        """A gate-allowed reduce whose coordinator lookup returns None (no
        matching position on the coordinator's OWN ledger) is a genuine
        ledger desync between this manager and the coordinator — the
        operator must be notified, not just logged (P1/P2 review MEDIUM)."""
        pm, pos = self._position(config, quantity=100)

        fake_coord = MagicMock()
        fake_coord._reduce_position = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(
                pos, _honesty_decision(DecisionAction.REDUCE, quantity=30)
            )

        assert pm.get_position("005930").quantity == 100, (
            "no coordinator position means nothing was placed — this "
            "manager's quantity must stay untouched"
        )
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "005930" in msg

    @pytest.mark.asyncio
    async def test_partial_reduce_coordinator_clamp_collapses_to_full_close(
        self, config, monkeypatch
    ):
        """Oversell/divergence clamp: PositionManager's own ledger considers
        this a partial reduce (new_quantity=70 > 0), but the coordinator's
        SEPARATE ledger only actually holds — and sells — up to its own
        quantity. When the ACTUAL fill consumes this manager's entire
        tracked quantity, the position must be fully removed from
        monitoring, not left at a negative/zero quantity."""
        pm, pos = self._position(config, quantity=100)

        fake_coord = MagicMock()

        async def _reduce(ticker, quantity, decision_id=None, reason=None, **kwargs):
            # Simulate the coordinator's own clamp/ledger actually selling
            # the full 100 (e.g. its ManagedPosition only held 100 too, and
            # the clamp there collapsed the request into a full close).
            return _order_result(filled_quantity=100, requested_quantity=quantity)

        fake_coord._reduce_position = _reduce
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(
            pos, _honesty_decision(DecisionAction.REDUCE, quantity=30)
        )

        assert pm.get_position("005930") is None, (
            "a real fill that consumes the whole tracked quantity must "
            "remove the position, not just decrement it"
        )

    @pytest.mark.asyncio
    async def test_reduce_zero_clamped_quantity_notifies_not_executed(
        self, config, monkeypatch
    ):
        """Direct-call edge case: if the requested quantity clamps to zero or
        less against the currently monitored quantity (e.g. already fully
        reduced by a concurrent path), no order is placed and the human is
        notified — distinct from a gate denial."""
        pm, pos = self._position(config, quantity=0)

        fake_coord = MagicMock()
        fake_coord._reduce_position = AsyncMock()
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        gate_called = []

        async def allow_gate(market, **kwargs):
            gate_called.append(kwargs)
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._execute_reduce_position(pos, 30, "agent_decision_reduce_partial")

        assert gate_called == [], "a zero-clamp request must short-circuit before the gate"
        fake_coord._reduce_position.assert_not_awaited()
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "005930" in msg


# -------------------------------------------
# ADD Real Execution + Percentage-of-Holding Sizing (P2, 2026-07-15)
# -------------------------------------------
#
# P2 replaces P0's notify-only "추가매수 미실행 — 보류" stand-in with a real,
# quantity-specified BUY through `ExecutionCoordinator._add_to_position`,
# gated the same way the REDUCE/SELL paths are gated: check_autonomy(BUY).
# The buy quantity is sized as a configurable percentage of the CURRENTLY
# held quantity (add_position_pct), not any free-text quantity the
# discussion itself proposed.
#
# Audit: docs/superpowers/audits/2026-07-14-autonomous-position-mgmt-audit.md
# Plan: docs/superpowers/plans/2026-07-15-position-mgmt-execution.md (Task P2)


def _buy_order_result(filled_quantity: int, avg_price: float = 74_000) -> OrderResult:
    return OrderResult(
        order_id="o-add-1",
        ticker="005930",
        side=OrderSide.BUY,
        requested_quantity=filled_quantity,
        filled_quantity=filled_quantity,
        avg_price=avg_price,
        status="filled" if filled_quantity > 0 else "rejected",
    )


class TestApplyDecisionAddP2:
    """ADD now places a real, percentage-of-holding BUY order via the SAME
    autonomy gate the SELL/REDUCE paths use, and updates the monitored
    quantity/avg_price by the ACTUAL fill (weighted-average merge)."""

    @staticmethod
    def _position(config, quantity=100, current_price=72500):
        pm = PositionManager(config=config)
        pos = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=quantity,
            avg_price=72500,
            current_price=current_price,
        )
        return pm, pos

    @staticmethod
    def _notifier():
        notifier = MagicMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock()
        return notifier

    @pytest.mark.asyncio
    async def test_add_gate_allowed_places_buy_sized_as_pct_of_held_and_merges_avg(
        self, config, monkeypatch
    ):
        """Happy path: 100 held, default add_position_pct=0.25 → a BUY for
        25 is placed via check_autonomy(BUY), and the monitored
        quantity/avg_price merge to the weighted average of the ACTUAL
        fill."""
        pm, pos = self._position(config, quantity=100, current_price=72500)

        add_calls = []
        fake_coord = MagicMock()

        async def _add(ticker, quantity, decision_id=None):
            add_calls.append((ticker, quantity))
            return _buy_order_result(filled_quantity=quantity, avg_price=74_000)

        fake_coord._add_to_position = _add
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        gate_calls = []

        async def allow_gate(market, **kwargs):
            gate_calls.append(kwargs)
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert add_calls == [("005930", 25)], (
            "must place a BUY for round(held * add_position_pct) = "
            "round(100 * 0.25) = 25"
        )
        assert gate_calls and gate_calls[0]["action"] == "BUY"
        assert gate_calls[0]["quantity"] == 25
        assert gate_calls[0]["entry_price"] == 72500

        merged = pm.get_position("005930")
        assert merged.quantity == 125, "monitored quantity must increment by the ACTUAL fill"
        expected_avg = (100 * 72500 + 25 * 74_000) / 125
        assert merged.avg_price == expected_avg, "avg_entry_price must be the cost-weighted average"

    @pytest.mark.asyncio
    async def test_add_passes_ticker_so_gate_can_exempt_the_slot_cap(
        self, config, monkeypatch
    ):
        """게이트에 ticker를 넘겨야 max_open_positions 면제가 성립한다.

        추가매수는 보유 티커 집합에 원소를 더하지 않으므로 슬롯 상한의
        대상이 아니다. 게이트(check 6)는 그 면제를 **자신이 조회한 보유
        목록**으로 판정하는데, 판정 대상 티커를 모르면 면제할 수가 없다.

        라이브 사고(2026-08-05): 316140의 ADD 7건이 전부
        `check=max_positions`("open positions 5 >= limit 5")로 거절돼 체결
        0건이었다. 게이트 쪽 면제만 고치고 이 배선을 빠뜨리면 라이브는
        한 톨도 달라지지 않는다.
        """
        pm, pos = self._position(config, quantity=100, current_price=72500)

        fake_coord = MagicMock()

        async def _add(ticker, quantity, decision_id=None):
            return _buy_order_result(filled_quantity=quantity, avg_price=74_000)

        fake_coord._add_to_position = _add
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        gate_calls = []

        async def allow_gate(market, **kwargs):
            gate_calls.append(kwargs)
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert gate_calls, "게이트가 호출되지 않았다"
        assert gate_calls[0].get("ticker") == "005930", (
            "추가매수 대상 티커를 게이트에 넘겨야 슬롯 상한을 면제할 수 있다"
        )
        assert gate_calls[0]["action"] == "BUY", (
            "action은 계속 BUY여야 한다 — 진입 BUY와 동일한 안전(브레이커·"
            "명목캡·코디네이터 활성)을 그대로 받겠다는 의도가 여기 걸려 있다. "
            "ADD로 바꾸면 이 테스트가 아니라 게이트 쪽 분기가 조용히 달라진다"
        )

    @pytest.mark.asyncio
    async def test_add_position_pct_is_configurable(self, monkeypatch):
        """A custom add_position_pct changes the sized quantity — proves the
        sizing policy is a config field, not a hardcoded constant."""
        custom_config = PositionManagerConfig(add_position_pct=0.5)
        pm, pos = self._position(custom_config, quantity=100, current_price=72500)

        add_calls = []
        fake_coord = MagicMock()

        async def _add(ticker, quantity, decision_id=None):
            add_calls.append((ticker, quantity))
            return _buy_order_result(filled_quantity=quantity)

        fake_coord._add_to_position = _add
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert add_calls == [("005930", 50)], "0.5 * 100 held = 50"

    @pytest.mark.asyncio
    async def test_add_qty_rounds_correctly(self, monkeypatch):
        """round(held * add_position_pct) must round, not truncate/floor."""
        custom_config = PositionManagerConfig(add_position_pct=0.25)
        pm, pos = self._position(custom_config, quantity=33, current_price=72500)

        add_calls = []
        fake_coord = MagicMock()

        async def _add(ticker, quantity, decision_id=None):
            add_calls.append((ticker, quantity))
            return _buy_order_result(filled_quantity=quantity)

        fake_coord._add_to_position = _add
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert add_calls == [("005930", round(33 * 0.25))]
        assert add_calls[0][1] == 8

    @pytest.mark.asyncio
    async def test_add_zero_computed_quantity_notifies_not_executed(self, config):
        """A sizing result of zero (e.g. a very small existing holding)
        keeps the not-executed notice and never calls the gate/coordinator
        at all — distinct from a gate denial."""
        pm, pos = self._position(config, quantity=1, current_price=72500)
        # round(1 * 0.25) == 0
        notifier = self._notifier()

        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert pos.quantity == 1, "sizing-clamped-to-zero must not touch quantity"
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "추가매수" in msg
        assert "005930" in msg

    @pytest.mark.asyncio
    async def test_add_gate_denied_leaves_quantity_unchanged(self, config, monkeypatch):
        """check_autonomy(BUY) denied → no order placed, position quantity
        unchanged, human notified."""
        pm, pos = self._position(config, quantity=100, current_price=72500)

        add_calls = []
        fake_coord = MagicMock()

        async def _add(ticker, quantity, decision_id=None):
            add_calls.append((ticker, quantity))
            return _buy_order_result(filled_quantity=quantity)

        fake_coord._add_to_position = _add
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def deny_gate(market, **kwargs):
            return GateDecision(
                allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode"
            )

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert add_calls == [], "gate-denied add must not place an order"
        assert pm.get_position("005930").quantity == 100
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "005930" in msg
        assert "hitl" in msg

    @pytest.mark.asyncio
    async def test_add_unfilled_leaves_quantity_unchanged(self, config, monkeypatch):
        """A gate-allowed add whose order does not fill at all must leave the
        monitored quantity/avg_price untouched (no phantom merge), and the
        operator must be notified — an accepted-but-unfilled order is not
        something that should only show up in logs (P1/P2 review MEDIUM)."""
        pm, pos = self._position(config, quantity=100, current_price=72500)

        fake_coord = MagicMock()

        async def _add(ticker, quantity, decision_id=None):
            return _buy_order_result(filled_quantity=0)

        fake_coord._add_to_position = _add
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert pm.get_position("005930").quantity == 100
        assert pm.get_position("005930").avg_price == 72500
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "005930" in msg

    @pytest.mark.asyncio
    async def test_add_no_coordinator_position_leaves_quantity_unchanged(
        self, config, monkeypatch
    ):
        """The coordinator's own ledger has no matching position (a
        divergent/desynced ledger) — nothing was placed, so this manager's
        quantity/avg_price must stay untouched rather than guess. The
        operator must be notified of the desync, not just logged (P1/P2
        review MEDIUM — this is the real ledger-desync red flag)."""
        pm, pos = self._position(config, quantity=100, current_price=72500)

        fake_coord = MagicMock()
        fake_coord._add_to_position = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert pm.get_position("005930").quantity == 100
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "005930" in msg

    @pytest.mark.asyncio
    async def test_add_decision_still_applies_sane_stop_adjustment(self, config, monkeypatch):
        """The ADD execution attempt must not swallow the stop/take
        adjustment behavior it shares with the HOLD branch."""
        pm, pos = self._position(config, quantity=100, current_price=72500)

        fake_coord = MagicMock()

        async def _add(ticker, quantity, decision_id=None):
            return _buy_order_result(filled_quantity=quantity)

        fake_coord._add_to_position = _add
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._apply_decision(
            pos,
            _honesty_decision(
                DecisionAction.ADD, stop_loss=70000, take_profit=80000
            ),
        )

        assert pos.stop_loss == 70000
        assert pos.take_profit == 80000

    @pytest.mark.asyncio
    async def test_add_notional_cap_denies_oversized_add(self, config, monkeypatch):
        """The REAL autonomy gate's per-trade notional cap — the same one
        the entry BUY path enforces — denies an ADD whose notional exceeds
        it. Proves identical safety level to entry, not just that SOME gate
        function gets called."""
        from app.config import settings as app_settings
        from services.autonomy.gate import check_autonomy as real_check_autonomy

        pm, pos = self._position(config, quantity=100, current_price=72500)
        # add_qty = round(100 * 0.25) = 25; notional = 25 * 72500 = 1,812,500

        monkeypatch.setattr(app_settings, "AUTONOMY_ENABLED", True)

        # pct-based cap (T1): notional cap = equity x pct. 0.5% is the field's
        # own lower bound, so a ~100M equity account still caps far below the
        # ADD's notional (25 * 72500 = 1,812,500) -- same "tiny cap" intent as
        # the old fixed-krw field, expressed in the new equity-relative unit.
        tiny_cap_params = RiskParameters(max_trade_notional_pct=0.5)

        async def permissive_mode(market):
            return "autonomous"

        async def permissive_paper(market):
            return True

        async def permissive_loss(market):
            return 0.0

        async def permissive_positions(market):
            return 0

        async def permissive_coordinator_active(market):
            return True

        async def permissive_equity(market):
            return 100_000_000

        async def gate_with_tiny_notional_cap(market, **kwargs):
            return await real_check_autonomy(
                market,
                action=kwargs["action"],
                quantity=kwargs["quantity"],
                entry_price=kwargs["entry_price"],
                mode_provider=permissive_mode,
                paper_provider=permissive_paper,
                daily_loss_provider=permissive_loss,
                positions_count_provider=permissive_positions,
                risk_params_provider=lambda: tiny_cap_params,
                coordinator_active_provider=permissive_coordinator_active,
                account_equity_provider=permissive_equity,
            )

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", gate_with_tiny_notional_cap)

        fake_coord = MagicMock()
        fake_coord._add_to_position = AsyncMock()
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        fake_coord._add_to_position.assert_not_awaited()
        assert pm.get_position("005930").quantity == 100, (
            "a cap-exceeding ADD must not execute"
        )
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "005930" in msg


# -------------------------------------------
# Strategic Re-Evaluation Trigger (P3, 2026-07-15)
# -------------------------------------------
#
# The 30s _check_position loop previously only reacted to DEFENSIVE events
# (stop/take proximity, big P&L swings, long holding). It never proactively
# re-judged a held position for ADD/REDUCE/HOLD/SELL. P3 adds a hybrid
# INTERVAL + PRICE-CHANGE trigger (STRATEGIC_REEVAL) that fires
# _check_position's SAME _handle_event -> _should_trigger_discussion ->
# _trigger_discussion -> _apply_decision chain the defensive events already
# use, so the resulting decision reaches the SAME real, gated execution
# (P0/P1/P2) — no duplicated execution logic.
#
# Audit: docs/superpowers/audits/2026-07-14-autonomous-position-mgmt-audit.md §C P3
# Plan: docs/superpowers/plans/2026-07-15-position-mgmt-execution.md Task P3


class TestStrategicReevalConfig:
    """PositionManagerConfig gets two new, conservative-by-default fields."""

    @pytest.fixture(autouse=True)
    def _market_open(self, monkeypatch):
        """E2-1: _check_strategic_reeval is now gated on KRX hours. Pin
        the gate open — see TestUpdatePricesStaleGuard._market_open."""
        monkeypatch.setattr(pm_mod, "is_krx_open_cached", lambda: True)

    def test_defaults(self):
        cfg = PositionManagerConfig()
        # 49: 8 (max_discussions_per_position) x 49 = 392min covers the
        # 390min KRX session -- see the field's docstring for the full
        # incident and test_daily_cap_cannot_exhaust_before_session_close
        # below for the invariant this pins.
        assert cfg.reeval_interval_minutes == 49
        assert cfg.reeval_price_change_pct == 2.0
        assert cfg.min_discussion_interval_minutes == 15
        assert cfg.max_discussions_per_position == 8

    def test_interval_minutes_rejects_non_positive(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PositionManagerConfig(reeval_interval_minutes=0)

    def test_price_change_pct_rejects_negative(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PositionManagerConfig(reeval_price_change_pct=-1.0)

    def test_default_config_2pct_move_is_price_due(self):
        """Behavior proof for the tightened default: at DEFAULT config (no
        explicit overrides), a +2.0% move from the last re-eval price
        baseline crosses the new reeval_price_change_pct=2.0 threshold (was
        3.0) and _check_strategic_reeval reports the position as due,
        purely on the price-change leg (the interval leg is kept far from
        due via a fresh last_reeval_at)."""
        pm = PositionManager(config=PositionManagerConfig())
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=10000,
            current_price=10000,
        )
        position = pm.get_position("005930")
        # Isolate the price-change leg: fresh last_reeval_at means the
        # (new, tighter) interval leg is nowhere near due.
        position.last_reeval_at = datetime.now()
        position.last_reeval_price = 10000
        position.current_price = 10200  # +2.0% vs. the 10000 baseline

        event = pm._check_strategic_reeval(position)

        assert event is not None, (
            "a +2.0% move must be price_due under the new default "
            "reeval_price_change_pct=2.0"
        )
        assert event.event_type == PositionEventType.STRATEGIC_REEVAL

    def test_daily_cap_cannot_exhaust_before_session_close(self):
        """Invariant, not a number pin: max_discussions_per_position *
        reeval_interval_minutes must cover the full KRX_SESSION_MINUTES
        session. If it doesn't, a held position burns its entire daily
        strategic-re-eval budget before the market closes and then goes
        completely dark for the rest of the day -- exactly what happened
        live on 2026-08-04 (4/5 positions, cap hit ~12:53) and again on
        2026-08-05 (all 5 positions, cap hit by 12:55:50, zero re-eval for
        the remaining 2h35m to close). The watch-list control group (not
        subject to this per-position cap) kept being discussed all
        afternoon on 2026-08-05, which is what isolates this as a
        cap/interval interaction rather than an LLM or market-conditions
        problem.

        Deliberately derives both operands from the config object instead
        of hard-coding 8 or 49, so this also fires if a future change
        raises the cap or shortens the interval without checking the
        interaction -- unlike a bare `reeval_interval_minutes == 49`
        assertion, which would only restate the current value."""
        cfg = PositionManagerConfig()
        total_reeval_minutes = (
            cfg.max_discussions_per_position * cfg.reeval_interval_minutes
        )
        assert total_reeval_minutes >= KRX_SESSION_MINUTES, (
            f"max_discussions_per_position ({cfg.max_discussions_per_position}) "
            f"* reeval_interval_minutes ({cfg.reeval_interval_minutes}) = "
            f"{total_reeval_minutes} minutes, which is LESS than the "
            f"{KRX_SESSION_MINUTES}-minute KRX session (09:00-15:30 KST). "
            "The daily strategic-re-eval cap will exhaust before the "
            "session closes, leaving held positions with zero strategic "
            "re-evaluation for the remainder of the day (see the "
            "2026-08-04 and 2026-08-05 live incidents referenced on "
            "PositionManagerConfig.reeval_interval_minutes)."
        )


class TestStrategicReevalTriggerP3:
    """_check_position: STRATEGIC_REEVAL fires the SAME discussion path as
    defensive events, but only when no defensive event fired this cycle."""

    @pytest.fixture(autouse=True)
    def _market_open(self, monkeypatch):
        """E2-1: _check_strategic_reeval is now gated on KRX hours. Pin
        the gate open — see TestUpdatePricesStaleGuard._market_open."""
        monkeypatch.setattr(pm_mod, "is_krx_open_cached", lambda: True)

    @staticmethod
    def _position_manager(**config_overrides):
        cfg = PositionManagerConfig(
            check_interval_seconds=30,
            stop_loss_warning_pct=2.0,
            take_profit_warning_pct=2.0,
            significant_gain_pct=10.0,
            significant_loss_pct=5.0,
            **config_overrides,
        )
        return PositionManager(config=cfg)

    @staticmethod
    def _fresh_no_defensive_position(pm, current_price=72500, avg_price=72500):
        """A position with no stop/take-profit set and current_price ==
        avg_price (0% P&L) — no defensive event of any kind can fire for
        it, isolating the strategic-reeval branch."""
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=avg_price,
            current_price=current_price,
        )
        return pm.get_position("005930")

    # ---- 1. Interval-elapsed fires ----

    @pytest.mark.asyncio
    async def test_interval_elapsed_triggers_strategic_reeval(self):
        """No defensive event, price baseline unchanged, but the configured
        interval has elapsed since the last re-eval -> STRATEGIC_REEVAL
        fires and _trigger_discussion is called (strategically, not from a
        defensive event)."""
        pm = self._position_manager(reeval_interval_minutes=60, reeval_price_change_pct=3.0)
        position = self._fresh_no_defensive_position(pm)
        # Backdate past the 60-minute interval; price baseline untouched
        # (0% change) so ONLY the interval condition is due.
        position.last_reeval_at = datetime.now() - timedelta(minutes=61)

        pm._trigger_discussion = AsyncMock()

        await pm._check_position(position)

        pm._trigger_discussion.assert_awaited_once()
        fired_event = pm._trigger_discussion.await_args.args[0]
        assert fired_event.event_type == PositionEventType.STRATEGIC_REEVAL

    # ---- 2. Price-change threshold crossed (no interval) fires ----

    @pytest.mark.asyncio
    async def test_price_change_triggers_strategic_reeval_without_interval(self):
        """No interval elapsed, but the price has moved >= the configured
        threshold since the last re-eval baseline -> STRATEGIC_REEVAL fires
        purely on the price-change leg of the OR."""
        pm = self._position_manager(reeval_interval_minutes=60, reeval_price_change_pct=3.0)
        position = self._fresh_no_defensive_position(pm, current_price=72500, avg_price=72500)
        # last_reeval_at is fresh (just seeded by add_position) -> interval
        # NOT due. Move price +4% (> 3% threshold, < 5% trailing-activation,
        # < 10% significant-gain) so no OTHER event branch fires either.
        pm.update_position("005930", current_price=72500 * 1.04)

        pm._trigger_discussion = AsyncMock()

        await pm._check_position(position)

        pm._trigger_discussion.assert_awaited_once()
        fired_event = pm._trigger_discussion.await_args.args[0]
        assert fired_event.event_type == PositionEventType.STRATEGIC_REEVAL

    # ---- 3. Neither condition met -> no spurious firing ----

    @pytest.mark.asyncio
    async def test_neither_interval_nor_change_no_spurious_firing(self):
        """Freshly-monitored position, checked immediately: neither the
        interval nor the price-change condition is met -> no strategic
        re-eval, no discussion, baseline untouched."""
        pm = self._position_manager(reeval_interval_minutes=60, reeval_price_change_pct=3.0)
        position = self._fresh_no_defensive_position(pm)
        baseline_at = position.last_reeval_at
        baseline_price = position.last_reeval_price

        pm._trigger_discussion = AsyncMock()

        await pm._check_position(position)

        pm._trigger_discussion.assert_not_awaited()
        assert position.last_reeval_at == baseline_at, "baseline must not reset without a fire"
        assert position.last_reeval_price == baseline_price

    # ---- 4. Throttle: min_discussion_interval_minutes blocks it ----

    @pytest.mark.asyncio
    async def test_min_discussion_interval_throttle_blocks_strategic_reeval(self):
        """Due by interval, but a discussion for this position happened very
        recently (within min_discussion_interval_minutes) -> the SAME
        _should_trigger_discussion throttle defensive events use blocks the
        strategic discussion too."""
        pm = self._position_manager(
            reeval_interval_minutes=60,
            reeval_price_change_pct=3.0,
            min_discussion_interval_minutes=30,
        )
        position = self._fresh_no_defensive_position(pm)
        position.last_reeval_at = datetime.now() - timedelta(minutes=61)
        position.last_discussion = datetime.now() - timedelta(minutes=5)  # within 30-min throttle

        pm._trigger_discussion = AsyncMock()

        await pm._check_position(position)

        pm._trigger_discussion.assert_not_awaited()

    # ---- 5. Throttle: max_discussions_per_position blocks it ----

    @pytest.mark.asyncio
    async def test_max_discussions_throttle_blocks_strategic_reeval(self):
        """Due by interval, but this position already hit
        max_discussions_per_position -> throttled, no discussion."""
        pm = self._position_manager(
            reeval_interval_minutes=60,
            reeval_price_change_pct=3.0,
            max_discussions_per_position=5,
        )
        position = self._fresh_no_defensive_position(pm)
        position.last_reeval_at = datetime.now() - timedelta(minutes=61)
        position.discussion_count = 5

        pm._trigger_discussion = AsyncMock()

        await pm._check_position(position)

        pm._trigger_discussion.assert_not_awaited()

    # ---- 6. last_reeval_at/price updates on fire; prevents immediate refire ----

    @pytest.mark.asyncio
    async def test_last_reeval_fields_update_on_fire_and_prevent_immediate_refire(self):
        """Once a strategic re-eval fires, both baseline fields reset to
        "now"/current price, so an immediate second check does NOT re-fire
        even though nothing else changed."""
        pm = self._position_manager(reeval_interval_minutes=60, reeval_price_change_pct=3.0)
        position = self._fresh_no_defensive_position(pm, current_price=72500, avg_price=72500)
        old_reeval_at = datetime.now() - timedelta(minutes=61)
        position.last_reeval_at = old_reeval_at

        pm._trigger_discussion = AsyncMock()

        await pm._check_position(position)

        pm._trigger_discussion.assert_awaited_once()
        assert position.last_reeval_at > old_reeval_at, "baseline must reset to ~now on fire"
        assert position.last_reeval_price == position.current_price

        # Second check, same tick conditions: must NOT re-fire.
        await pm._check_position(position)
        pm._trigger_discussion.assert_awaited_once()  # still only the one call

    # ---- 7. Defensive event present -> dedup, no double-trigger ----

    @pytest.mark.asyncio
    async def test_defensive_event_present_skips_strategic_check_same_tick(self):
        """A defensive event (SIGNIFICANT_LOSS here) fires this cycle AND the
        strategic-reeval interval is independently due -> only the
        defensive discussion fires (exactly once), and the strategic
        baseline is left untouched (the strategic branch never even ran)."""
        pm = self._position_manager(reeval_interval_minutes=60, reeval_price_change_pct=3.0)
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=68000,  # ~6.2% loss -> SIGNIFICANT_LOSS (> 5% default)
        )
        position = pm.get_position("005930")
        stale_reeval_at = datetime.now() - timedelta(minutes=61)
        position.last_reeval_at = stale_reeval_at

        pm._trigger_discussion = AsyncMock()

        await pm._check_position(position)

        pm._trigger_discussion.assert_awaited_once()
        fired_event = pm._trigger_discussion.await_args.args[0]
        assert fired_event.event_type == PositionEventType.SIGNIFICANT_LOSS, (
            "the defensive event must win this tick, not STRATEGIC_REEVAL"
        )
        assert position.last_reeval_at == stale_reeval_at, (
            "strategic branch must not even run (and thus not reset the "
            "baseline) when a defensive event already fired this tick"
        )

    # ---- 8. End-to-end: strategic reeval decision flows to real _apply_decision ----

    @pytest.mark.asyncio
    async def test_strategic_reeval_decision_flows_to_apply_decision(self, monkeypatch):
        """Full chain, no shortcuts: STRATEGIC_REEVAL -> _trigger_discussion
        (real) -> a manual discussion whose session.decision is SELL ->
        _apply_decision (real) -> the SAME gated close path defensive SELLs
        already use. Proves P3 reuses the existing chain end-to-end rather
        than duplicating execution.

        L3 (spec docs/superpowers/specs/2026-07-19-decision-lineage-
        design.md): also pins that session.id -- the REAL, persisted
        agent_chat_decisions.id -- reaches the coordinator's _close_position
        call as decision_id, closing 끊김 B (the discussion knows the real
        decision id but _apply_decision used to drop it on the floor)."""
        pm = self._position_manager(reeval_interval_minutes=60, reeval_price_change_pct=3.0)
        position = self._fresh_no_defensive_position(pm)
        position.last_reeval_at = datetime.now() - timedelta(minutes=61)

        decision = SimpleNamespace(
            action=DecisionAction.SELL,
            quantity=None,
            stop_loss=None,
            take_profit=None,
        )
        session = SimpleNamespace(id="reeval-decision-1", decision=decision)

        fake_coordinator = MagicMock()
        fake_coordinator.start_manual_discussion = AsyncMock(return_value=session)
        pm.set_chat_coordinator(fake_coordinator)

        closed = []
        fake_trading_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            closed.append((ticker, decision_id))
            return MagicMock()  # non-None -- coordinator proceeded (N3)

        fake_trading_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_trading_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        await pm._check_position(position)

        fake_coordinator.start_manual_discussion.assert_awaited_once()
        call_kwargs = fake_coordinator.start_manual_discussion.await_args.kwargs
        assert call_kwargs["ticker"] == "005930"
        assert call_kwargs["wait"] is True
        assert closed == [("005930", "reeval-decision-1")], (
            "the SELL decision must reach the REAL gated close path WITH "
            "the discussion's real decision id threaded as decision_id"
        )
        assert pm.get_position("005930") is None

    # ---- 9. Regression: existing defensive-event detection unaffected ----

    @pytest.mark.asyncio
    async def test_regression_stop_loss_hit_still_detected_with_reeval_present(self):
        """A defensive STOP_LOSS_HIT must still fire exactly as before, even
        though a strategic-reeval config is now active by default."""
        pm = self._position_manager()
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=68000,  # Below stop-loss
            stop_loss=68875,
        )

        events = []
        pm.on_event(lambda e: events.append(e))

        position = pm.get_position("005930")
        await pm._check_position(position)

        stop_loss_events = [e for e in events if e.event_type == PositionEventType.STOP_LOSS_HIT]
        assert len(stop_loss_events) >= 1
        strategic_events = [
            e for e in events if e.event_type == PositionEventType.STRATEGIC_REEVAL
        ]
        assert strategic_events == [], "defensive event must suppress strategic reeval this tick"


# -------------------------------------------
# Decision-Id Provenance (L3, 2026-07-19)
# -------------------------------------------
#
# 끊김 B: MonitoredPosition carried no provenance at all, and
# _trigger_discussion held session.id (the REAL, persisted
# agent_chat_decisions.id) but dropped it before _apply_decision ever
# reached the coordinator. The discussion-issued exit -> coordinator
# decision_id chain (Step 1 test 1) is pinned end-to-end by
# TestPositionManagerStrategicReeval::test_strategic_reeval_decision_flows_to_apply_decision
# above (real _trigger_discussion -> real _apply_decision -> real
# _execute_close_position). These tests cover the remaining three: the
# non-discussion auto-execute path staying decision_id=None (spec D2), the
# entry_decision_id field round trip, and existing add_position call sites
# staying unaffected.
#
# Spec: docs/superpowers/specs/2026-07-19-decision-lineage-design.md (L3)
# Brief: .superpowers/sdd/task-L-3-brief.md


class TestDecisionIdLineageL3:
    @staticmethod
    def _position(config, quantity=100, current_price=68000, stop_loss=68875):
        pm = PositionManager(config=config)
        pos = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=quantity,
            avg_price=72500,
            current_price=current_price,
            stop_loss=stop_loss,
        )
        return pm, pos

    # ---- Step 1 test 2: auto-execute (non-discussion) close = decision_id=None ----

    @pytest.mark.asyncio
    async def test_auto_execute_stop_loss_close_has_no_decision_id(
        self, config, monkeypatch
    ):
        """D2 (spec): a mechanical stop-loss auto-execute close has no
        upstream discussion decision to cite -- decision_id must reach the
        coordinator as explicit None, not be silently omitted or invented."""
        pm, pos = self._position(config)

        close_calls = []
        fake_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            close_calls.append((ticker, decision_id))

        fake_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        event = PositionEvent(
            ticker="005930",
            event_type=PositionEventType.STOP_LOSS_HIT,
            current_price=68000,
            trigger_value=68875,
            message="손절가 도달",
            auto_execute=True,
        )
        await pm._auto_execute_event(event, pos)

        assert close_calls == [("005930", None)], (
            "auto-execute (non-discussion) close must pass decision_id=None explicitly"
        )

    # ---- Step 1 test 4: existing add_position call sites unaffected (default None) ----

    def test_add_position_default_entry_decision_id_is_none(self, config):
        """Every existing add_position call site (direct test calls,
        sync_from_account) omits entry_decision_id -- must default to None,
        byte-for-byte unchanged behavior."""
        pm = PositionManager(config=config)
        pos = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=72500,
        )
        assert pos.entry_decision_id is None

    def test_add_position_accepts_explicit_entry_decision_id(self, config):
        """New optional param: when a caller HAS a durable decision id, it
        lands on the created position."""
        pm = PositionManager(config=config)
        pos = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=72500,
            entry_decision_id="dec-entry-1",
        )
        assert pos.entry_decision_id == "dec-entry-1"

    def test_update_position_sets_entry_decision_id_when_passed(self, config):
        pm = PositionManager(config=config)
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=72500,
        )
        pm.update_position("005930", entry_decision_id="dec-backfill-1")
        assert pm.get_position("005930").entry_decision_id == "dec-backfill-1"

    def test_update_position_omitted_entry_decision_id_leaves_field_unchanged(
        self, config
    ):
        """update_position's default None must NOT clobber an already-set
        entry_decision_id -- the same coalesce discipline every other
        optional field in this method already follows."""
        pm = PositionManager(config=config)
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=72500,
            entry_decision_id="dec-entry-1",
        )
        pm.update_position("005930", current_price=73000)
        assert pm.get_position("005930").entry_decision_id == "dec-entry-1"


# -------------------------------------------
# S-2: Autonomous Stop-Loss Default ON + HITL Discussion Fallback
# (survival discipline, 2026-07-19)
# -------------------------------------------
#
# auto_execute_stop_loss now defaults to True (D1) -- an autonomous account
# must never sit at a breached stop waiting for a human click. This is safe
# for a HITL account too because the autonomy gate is re-checked inside
# _execute_close_position/_execute_reduce_position on every attempt: a
# market_mode denial (account not actually autonomous) now falls back to
# the SAME agent-discussion path any other position event uses, instead of
# silently leaving the position monitored with only a one-time notice.
#
# Spec: docs/superpowers/specs/2026-07-19-survival-discipline-design.md §2 S-2
# Brief: .superpowers/sdd/task-S-2-brief.md


class TestS2AutoStopLossDefaultAndHitlFallback:
    @staticmethod
    def _position_manager(**config_overrides):
        cfg = PositionManagerConfig(
            check_interval_seconds=30,
            stop_loss_warning_pct=2.0,
            take_profit_warning_pct=2.0,
            significant_gain_pct=10.0,
            significant_loss_pct=5.0,
            **config_overrides,
        )  # auto_execute_stop_loss intentionally left at the model DEFAULT
        return PositionManager(config=cfg)

    @staticmethod
    def _stopped_out_position(pm):
        """A position whose current_price is already at/through its
        stop-loss -- the very next _check_position must detect STOP_LOSS_HIT
        -- and ONLY STOP_LOSS_HIT (isolating the event under test): -3.4%
        unrealized P&L stays well clear of the config's 5.0%
        significant_loss_pct threshold, so no second SIGNIFICANT_LOSS event
        fires in the same tick and confounds the discussion-call
        assertions below."""
        pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=70000,  # <= stop_loss below, -3.4% P&L
            stop_loss=71000,
        )
        return pm.get_position("005930")

    @staticmethod
    def _notifier():
        notifier = MagicMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock()
        return notifier

    # ---- ① Default ON pin (new config, no override) ----

    def test_default_config_auto_execute_stop_loss_is_true(self):
        cfg = PositionManagerConfig()
        assert cfg.auto_execute_stop_loss is True

    # ---- ⑥ Take-profit auto-execution remains OFF ----

    def test_default_config_auto_execute_take_profit_still_false(self):
        cfg = PositionManagerConfig()
        assert cfg.auto_execute_take_profit is False

    # ---- ② STOP_LOSS_HIT + gate allow (autonomous) = immediate execution,
    # discussion never fires ----

    @pytest.mark.asyncio
    async def test_stop_loss_hit_gate_allowed_executes_immediately_no_discussion(
        self, monkeypatch
    ):
        pm = self._position_manager()
        position = self._stopped_out_position(pm)

        closed = []
        fake_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            closed.append(ticker)
            return MagicMock()  # non-None -- coordinator proceeded (N3)

        fake_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        pm._trigger_discussion = AsyncMock()

        await pm._check_position(position)

        assert closed == ["005930"], (
            "auto_execute_stop_loss defaults to True -- a gate-allowed "
            "STOP_LOSS_HIT must close immediately without a discussion"
        )
        pm._trigger_discussion.assert_not_awaited()
        assert pm.get_position("005930") is None

    # ---- ③ Same event + gate deny(market_mode) = discussion fallback
    # fires, zero orders placed ----

    @pytest.mark.asyncio
    async def test_stop_loss_hit_market_mode_deny_falls_back_to_discussion(
        self, monkeypatch
    ):
        pm = self._position_manager()
        position = self._stopped_out_position(pm)

        closed = []
        fake_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            closed.append(ticker)

        fake_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def deny_gate(market, **kwargs):
            return GateDecision(
                allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode"
            )

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

        pm._trigger_discussion = AsyncMock()

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._check_position(position)

        assert closed == [], "a market_mode-denied close must not place an order"
        pm._trigger_discussion.assert_awaited_once()
        fired_event = pm._trigger_discussion.await_args.args[0]
        assert fired_event.event_type == PositionEventType.STOP_LOSS_HIT
        assert position.ticker in pm._positions, (
            "the position must remain monitored while denied/under discussion"
        )

    # ---- ④ gate deny(paper) = no fallback (notify-only, unchanged) ----

    @pytest.mark.asyncio
    async def test_stop_loss_hit_paper_only_deny_does_not_fall_back(
        self, monkeypatch
    ):
        pm = self._position_manager()
        position = self._stopped_out_position(pm)

        closed = []
        fake_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            closed.append(ticker)

        fake_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def deny_gate(market, **kwargs):
            return GateDecision(allowed=False, reason="paper mode only", check="paper_only")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

        pm._trigger_discussion = AsyncMock()

        notifier = self._notifier()
        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._check_position(position)

        assert closed == []
        # a non-market_mode denial (paper_only here) must NOT escalate to a
        # discussion -- notify-only, unchanged pre-S-2 behavior.
        pm._trigger_discussion.assert_not_awaited()
        notifier.send_message.assert_awaited_once()



# -------------------------------------------
# S-2 review fix: recursion-safety permanent regression (real chain)
# -------------------------------------------
#
# The reviewer probed this exact scenario: a HITL-denied STOP_LOSS_HIT falls
# back to a discussion (`_fallback_to_discussion_on_hitl_deny` ->
# `_trigger_discussion`); the discussion re-decides SELL; `_apply_decision`
# routes that SELL back into `_execute_close_position`; the SAME market_mode
# gate denies it again; the SECOND `_fallback_to_discussion_on_hitl_deny`
# call must NOT spawn a second discussion, because `_trigger_discussion` sets
# `position.last_discussion` to "now" BEFORE `_apply_decision` even runs --
# so the re-entry is blocked by `_should_trigger_discussion`'s cooldown
# interval, not by call depth. This test exercises the REAL method chain
# (`_execute_close_position` -> `_fallback_to_discussion_on_hitl_deny` ->
# `_trigger_discussion` -> `_apply_decision` -> `_execute_close_position`
# again) with nothing mocked except the autonomy gate and the chat-
# coordinator boundary (`start_manual_discussion`, which would otherwise
# spin up a real LLM discussion) -- unlike the existing S-2 tests above,
# which stub `_trigger_discussion` itself and so cannot catch a recursion
# regression.


class TestS2RecursionSafetyRealChain:
    @staticmethod
    def _position_manager():
        cfg = PositionManagerConfig(
            check_interval_seconds=30,
            stop_loss_warning_pct=2.0,
            take_profit_warning_pct=2.0,
            significant_gain_pct=10.0,
            significant_loss_pct=5.0,
        )
        return PositionManager(config=cfg)

    @pytest.mark.asyncio
    async def test_hitl_fallback_sell_redecision_does_not_recurse(self, monkeypatch):
        pm = self._position_manager()
        position = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=70000,  # already through stop_loss
            stop_loss=71000,
        )

        # The gate ALWAYS denies with market_mode -- both the original
        # mechanical STOP_LOSS_HIT attempt AND the discussion's re-decided
        # SELL hit the SAME live check on every call.
        async def deny_gate(market, **kwargs):
            return GateDecision(
                allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode"
            )

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", deny_gate)

        # Chat-coordinator boundary only: a real discussion would call an
        # LLM, so start_manual_discussion is stubbed to return a re-decided
        # SELL -- but _trigger_discussion/_apply_decision/
        # _fallback_to_discussion_on_hitl_deny/_execute_close_position all
        # run for real (no mocking of PositionManager's own methods).
        sell_decision = TradeDecision(
            action=DecisionAction.SELL,
            confidence=0.8,
            consensus_level=0.8,
            rationale="re-decided SELL",
        )
        fake_session = SimpleNamespace(decision=sell_decision, id="sess-1")

        start_calls = []

        async def fake_start_manual_discussion(ticker, stock_name, wait=False):
            start_calls.append((ticker, stock_name, wait))
            return fake_session

        fake_coordinator = MagicMock()
        fake_coordinator.start_manual_discussion = fake_start_manual_discussion
        pm.set_chat_coordinator(fake_coordinator)

        notifier = MagicMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock()

        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            # The original mechanical STOP_LOSS_HIT auto-execution attempt --
            # the entry point a real RiskMonitor-triggered auto-execute would
            # use (mirrors _auto_execute_event's own call shape).
            await pm._execute_close_position(position, "stop_loss")

        assert start_calls == [("005930", "삼성전자", True)], (
            "start_manual_discussion must fire EXACTLY once -- the "
            "re-decided SELL's own re-denial must be blocked by the "
            "discussion cooldown (_should_trigger_discussion), not spawn a "
            "second discussion"
        )
        assert position.discussion_count == 1
        assert position.ticker in pm._positions, (
            "the position must remain monitored -- denied both times, never "
            "executed"
        )


# -------------------------------------------
# N3: coordinator-skipped close must NOT drop PM's own watch
# -------------------------------------------
#
# `coordinator._close_position` returns None when it SKIPPED the close
# outright (S-2's in-flight guard: a concurrent defensive exit for the SAME
# ticker already owns it, or the position was already gone broker-side) --
# NOT when an order was placed and merely unfilled/rejected (that path still
# returns an OrderResult). Before this fix `_execute_close_position` called
# `remove_position` unconditionally, ignoring the return value entirely --
# a skipped close silently dropped PM's watch, leaving the position
# undefended until the next add_position/reconciler pass (up to ~60s).
#
# Spec: docs/superpowers/specs/2026-07-20-gap-discipline-design.md §1/§2 N3
# Brief: .superpowers/sdd/task-G-3-brief.md


class TestN3CoordinatorSkipKeepsMonitoring:
    @staticmethod
    def _position(config, quantity=100, current_price=68000, stop_loss=68875):
        pm = PositionManager(config=config)
        pos = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=quantity,
            avg_price=72500,
            current_price=current_price,
            stop_loss=stop_loss,
        )
        return pm, pos

    @pytest.mark.asyncio
    async def test_coordinator_none_return_keeps_position_monitored_and_warns(
        self, config, monkeypatch
    ):
        """RED (pre-fix): the position used to be removed from monitoring
        unconditionally, even though the coordinator reported it skipped the
        close. GREEN: the position stays monitored and a warning is logged
        instead."""
        pm, pos = self._position(config)

        fake_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            return None  # coordinator skipped: in-flight guard / not found

        fake_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        with structlog.testing.capture_logs() as logs:
            await pm._execute_close_position(pos, "stop_loss")

        assert pm.get_position("005930") is not None, (
            "a coordinator-skipped close must NOT drop PM's own watch -- "
            "that would leave a monitoring gap until the next "
            "add_position/reconciler pass"
        )

        warnings = [
            e for e in logs
            if e.get("event") == "close_position_skipped_kept_monitored"
        ]
        assert len(warnings) == 1
        assert warnings[0]["ticker"] == "005930"
        assert warnings[0]["reason"] == "stop_loss"

        # The "position_closed" success log must NOT fire on a skip.
        closed_logs = [e for e in logs if e.get("event") == "position_closed"]
        assert closed_logs == []

    @pytest.mark.asyncio
    async def test_coordinator_non_none_return_still_removes_as_before(
        self, config, monkeypatch
    ):
        """Byte-invariant: a normal completion (coordinator returns an
        actual OrderResult, non-None) keeps removing the position from
        monitoring exactly as before -- this guard only changes the
        None/skip branch."""
        pm, pos = self._position(config)

        fake_coord = MagicMock()

        async def _close(ticker, decision_id=None, reason=None, **kwargs):
            return MagicMock()  # a real OrderResult stand-in -- non-None

        fake_coord._close_position = _close
        monkeypatch.setattr(
            "app.dependencies.get_trading_coordinator",
            AsyncMock(return_value=fake_coord),
        )

        async def allow_gate(market, **kwargs):
            return GateDecision(allowed=True, reason="ok", check="all")

        monkeypatch.setattr(autonomy_pkg, "check_autonomy", allow_gate)

        with structlog.testing.capture_logs() as logs:
            await pm._execute_close_position(pos, "stop_loss")

        assert pm.get_position("005930") is None

        closed_logs = [e for e in logs if e.get("event") == "position_closed"]
        assert len(closed_logs) == 1
        assert closed_logs[0]["ticker"] == "005930"


# -------------------------------------------
# S-2 review fix: fallback event reason -> event_type label mapping (Minor)
# -------------------------------------------
#
# `_fallback_to_discussion_on_hitl_deny`'s reconstructed event previously
# labeled EVERY non-"take_profit" reason as STOP_LOSS_HIT, including
# "agent_decision"/"agent_decision_reduce"/"agent_decision_reduce_partial"
# (a plain discussion SELL/REDUCE, not a mechanical stop trigger) -- a log/
# notification accuracy bug, not a functional one (event_type here only
# feeds logging/history, never auto_execute).


class TestFallbackEventReasonLabelMapping:
    @staticmethod
    def _position_manager():
        return PositionManager(config=PositionManagerConfig())

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reason,expected_event_type",
        [
            ("stop_loss", PositionEventType.STOP_LOSS_HIT),
            ("take_profit", PositionEventType.TAKE_PROFIT_HIT),
            ("agent_decision", PositionEventType.STRATEGIC_REEVAL),
            ("agent_decision_reduce", PositionEventType.STRATEGIC_REEVAL),
            ("agent_decision_reduce_partial", PositionEventType.STRATEGIC_REEVAL),
        ],
    )
    async def test_fallback_event_type_matches_reason(self, reason, expected_event_type):
        pm = self._position_manager()
        position = pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=70000,
            stop_loss=71000,
        )
        pm._trigger_discussion = AsyncMock()

        gate = GateDecision(
            allowed=False, reason="trading_mode:kiwoom is 'hitl'", check="market_mode"
        )

        await pm._fallback_to_discussion_on_hitl_deny(position, reason, gate)

        pm._trigger_discussion.assert_awaited_once()
        fired_event = pm._trigger_discussion.await_args.args[0]
        assert fired_event.event_type == expected_event_type, (
            f"reason={reason!r} must label the reconstructed event as "
            f"{expected_event_type}, not default to STOP_LOSS_HIT"
        )


# -------------------------------------------
# Discussion timeout bound (2026-08-04)
# -------------------------------------------
#
# `_trigger_discussion`'s `await self._chat_coordinator
# .start_manual_discussion(..., wait=True)` was unbounded -- measured live,
# discussions averaged 262s (median 217s, max 651s), and the 30s monitor
# loop was blocked ~40% of a session because this await is the ONLY thing
# between `_monitor_loop` and the next check cycle for EVERY position, not
# just the one being discussed. Both engines hold stop-losses for the same
# live positions and PositionManager's are the TIGHTER ones, so the
# effective stop for every position lived in the loop that kept stalling.
#
# Fixed with `asyncio.wait_for` at a configurable
# `discussion_timeout_seconds` (default 600). Not 900: 900 ==
# min_discussion_interval_minutes (15min) in seconds, so it would collide
# with that cooldown boundary, AND today's observed maximum was 651s -- 900
# would never have fired against real data.
#
# asyncio.TimeoutError is a plain Exception subclass, so the pre-existing
# bare `except Exception` at the bottom of `_trigger_discussion` already
# kept a timeout from propagating into the monitor loop -- the NEW risk
# this introduces is SILENCE (no `_alert_llm_failure`-style notice existed
# for a plain timeout, only for `LLMAllBackendsFailed` inside
# coordinator.py). `_alert_discussion_timeout` closes that gap, mirroring
# `coordinator._alert_llm_failure`'s claim-then-back-out latch (TOCTOU fix,
# 2026-08-03) but instance-scoped and ticker-keyed rather than
# module-global and cause-keyed (see the method's docstring for why).


class _SlowCoordinator:
    """`start_manual_discussion(wait=True)` sleeps past the configured
    timeout. Deterministic and fast: the SLEEP is real asyncio time but the
    configured TIMEOUT is tiny (0.05s in these tests), so `asyncio.wait_for`
    cancels the sleep almost immediately -- these tests never wait anywhere
    near production's 600s."""

    def __init__(self, sleep_seconds: float, session=None):
        self._sleep_seconds = sleep_seconds
        self._session = session
        self.call_count = 0

    async def start_manual_discussion(self, ticker, stock_name, wait=False):
        self.call_count += 1
        await asyncio.sleep(self._sleep_seconds)
        return self._session


class TestDiscussionTimeoutBound:
    @staticmethod
    def _position_manager(discussion_timeout_seconds=0.05, **overrides):
        cfg = PositionManagerConfig(
            discussion_timeout_seconds=discussion_timeout_seconds,
            min_discussion_interval_minutes=0,
            **overrides,
        )
        return PositionManager(config=cfg)

    @staticmethod
    def _position(pm):
        return pm.add_position(
            ticker="005930",
            stock_name="삼성전자",
            quantity=100,
            avg_price=72500,
            current_price=70000,
            stop_loss=71000,
        )

    @staticmethod
    def _event():
        return PositionEvent(
            ticker="005930",
            event_type=PositionEventType.STRATEGIC_REEVAL,
            current_price=70000,
            trigger_value=0,
            message="test",
        )

    # ---- config field ----

    def test_config_default_is_600_not_900(self):
        """900 == min_discussion_interval_minutes (15min) in seconds -- it
        would collide with the cooldown boundary AND never have fired
        against today's observed 651s max discussion."""
        cfg = PositionManagerConfig()
        assert cfg.discussion_timeout_seconds == 600

    def test_config_field_is_tunable(self):
        cfg = PositionManagerConfig(discussion_timeout_seconds=120)
        assert cfg.discussion_timeout_seconds == 120

    # ---- bounding ----

    @pytest.mark.asyncio
    async def test_timeout_is_cut_and_does_not_propagate(self):
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)
        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))

        # Must return promptly (well under the 5s sleep), not hang, and not
        # raise out of the monitoring path.
        await asyncio.wait_for(
            pm._trigger_discussion(self._event(), position), timeout=2.0
        )

    @pytest.mark.asyncio
    async def test_timeout_does_not_bump_discussion_count(self):
        """A timeout must NOT consume the daily discussion budget
        (max_discussions_per_position) -- only a discussion that actually
        completed should count against it."""
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)
        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))
        assert position.discussion_count == 0

        await pm._trigger_discussion(self._event(), position)

        assert position.discussion_count == 0

    @pytest.mark.asyncio
    async def test_timeout_sets_last_discussion_for_backoff(self):
        """Review fix (2026-08-04, final branch review): a timeout used to
        leave `last_discussion` untouched too, which meant
        `_should_trigger_discussion` kept returning True every 30s monitor
        tick -- a chronically slow position retried with NO backoff (stall
        600s, cancel, stall 600s again, forever), and this loop carries the
        TIGHTER of the two stop-loss engines. `last_discussion` must now be
        set on timeout so the existing min_discussion_interval_minutes
        cooldown actually throttles the retry."""
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)
        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))
        assert position.last_discussion is None

        await pm._trigger_discussion(self._event(), position)

        assert position.last_discussion is not None

    @pytest.mark.asyncio
    async def test_timeout_throttles_immediate_retrigger_via_should_trigger_discussion(self):
        """Pins the actual behaviour the backoff exists for: after a
        timeout, `_should_trigger_discussion` must return False until
        min_discussion_interval_minutes elapses -- NOT true again on the
        very next 30s monitor tick."""
        cfg = PositionManagerConfig(
            discussion_timeout_seconds=0.05, min_discussion_interval_minutes=15
        )
        pm = PositionManager(config=cfg)
        position = self._position(pm)
        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))

        await pm._trigger_discussion(self._event(), position)

        assert not pm._should_trigger_discussion(position), (
            "a timed-out discussion must be throttled by the interval "
            "cooldown, exactly like a completed one -- otherwise the next "
            "30s monitor tick immediately retries, burning ~15 paid LLM "
            "calls per attempt with no backoff"
        )

    @pytest.mark.asyncio
    async def test_under_timeout_discussion_untouched(self):
        """A discussion that finishes inside the budget must behave exactly
        as before the wrap: count bumped, last_discussion set, decision
        applied."""
        pm = self._position_manager(discussion_timeout_seconds=5.0)
        position = self._position(pm)
        decision = SimpleNamespace(
            action=DecisionAction.HOLD, quantity=None, stop_loss=None, take_profit=None,
        )
        session = SimpleNamespace(id="fast-1", decision=decision)
        fast_coord = _SlowCoordinator(sleep_seconds=0.01, session=session)
        pm.set_chat_coordinator(fast_coord)
        pm._apply_decision = AsyncMock()

        await pm._trigger_discussion(self._event(), position)

        assert fast_coord.call_count == 1
        assert position.discussion_count == 1
        assert position.last_discussion is not None
        pm._apply_decision.assert_awaited_once()

    # ---- notification ----

    @pytest.mark.asyncio
    async def test_timeout_fires_notification(self, monkeypatch):
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)
        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))

        notifier = AsyncMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)
        )

        await pm._trigger_discussion(self._event(), position)

        notifier.send_message.assert_awaited_once()
        text = str(notifier.send_message.await_args.args[0])
        assert "005930" in text or "삼성전자" in text

    @pytest.mark.asyncio
    async def test_notification_dedup_no_spam_same_ticker(self, monkeypatch):
        """Two timeouts in a row for the SAME ticker (interval throttle
        disabled in the fixture) must only alert once until the latch
        clears."""
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)
        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))

        notifier = AsyncMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)
        )

        await pm._trigger_discussion(self._event(), position)
        await pm._trigger_discussion(self._event(), position)

        assert notifier.send_message.await_count == 1

    @pytest.mark.asyncio
    async def test_notification_reclears_after_a_successful_discussion(self, monkeypatch):
        """Timeout, then a discussion that completes in-budget, then another
        timeout: must alert twice -- the latch clears on recovery, exactly
        like coordinator._alert_llm_failure's clear-on-success."""
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)

        notifier = AsyncMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)
        )

        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))
        await pm._trigger_discussion(self._event(), position)  # times out, alerts

        decision = SimpleNamespace(
            action=DecisionAction.HOLD, quantity=None, stop_loss=None, take_profit=None,
        )
        session = SimpleNamespace(id="fast-1", decision=decision)
        pm._apply_decision = AsyncMock()
        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=0.01, session=session))
        await pm._trigger_discussion(self._event(), position)  # succeeds, clears latch

        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))
        await pm._trigger_discussion(self._event(), position)  # times out again -> re-alert

        assert notifier.send_message.await_count == 2

    @pytest.mark.asyncio
    async def test_notification_latch_cleared_on_position_removal(self, monkeypatch):
        """Review fix (2026-08-04, final branch review): the latch was only
        ever cleared by that SAME ticker's next successful discussion.
        Without clearing it on remove_position, a sell -> re-buy of the same
        ticker would inherit stale latch state, and the NEW position's first
        timeout would be silently deduped against an alert that was really
        about the old, already-closed position -- a silent-notification
        failure, the exact family this whole fix exists to close."""
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)

        notifier = AsyncMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)
        )

        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))
        await pm._trigger_discussion(self._event(), position)  # times out, alerts, latches
        assert notifier.send_message.await_count == 1

        # Sell, then re-buy the SAME ticker -- a fresh position.
        pm.remove_position("005930")
        new_position = self._position(pm)

        await pm._trigger_discussion(self._event(), new_position)  # times out again

        assert notifier.send_message.await_count == 2, (
            "the new position's timeout must alert -- it must not be "
            "silently deduped against the old (now-closed) position's latch"
        )

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_break_the_loop(self, monkeypatch):
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)
        pm.set_chat_coordinator(_SlowCoordinator(sleep_seconds=5.0))

        monkeypatch.setattr(
            "services.telegram.get_telegram_notifier",
            AsyncMock(side_effect=RuntimeError("telegram down")),
        )

        # Must not raise out of the monitoring path.
        await asyncio.wait_for(
            pm._trigger_discussion(self._event(), position), timeout=2.0
        )

    @pytest.mark.asyncio
    async def test_no_race_between_dedup_check_and_claim(self, monkeypatch):
        """TOCTOU regression, mirrored from coordinator's
        test_concurrent_calls_with_same_cause_send_once: two coroutines
        racing the SAME ticker's timeout latch must not both pass the dedup
        check before either commits the claim."""
        pm = self._position_manager(discussion_timeout_seconds=0.05)
        position = self._position(pm)

        async def _yielding_send(*args, **kwargs):
            await asyncio.sleep(0)
            return True

        notifier = AsyncMock()
        notifier.is_ready = True
        notifier.send_message = AsyncMock(side_effect=_yielding_send)
        monkeypatch.setattr(
            "services.telegram.get_telegram_notifier", AsyncMock(return_value=notifier)
        )

        await asyncio.gather(
            pm._alert_discussion_timeout(position, 0.05),
            pm._alert_discussion_timeout(position, 0.05),
        )

        assert notifier.send_message.await_count == 1
