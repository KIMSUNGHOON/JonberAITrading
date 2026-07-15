"""
Tests for PositionManager

Unit tests for the PositionManager that monitors positions in real-time.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

import services.storage_service as ss
from services.agent_chat.models import DecisionAction
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
        """(b) The live-pollution shape: fixture stops 68875/79750 persisted for
        005930 while the stock now trades at 90,000 — take_profit 79,750 <=
        price would fire an instant take-profit storm on the first monitor
        cycle after restore. The polluted entry must be skipped AND its values
        dropped from the blob; the sane entry restores normally."""
        await temp_storage.set_app_setting(_STOPS_KEY, json.dumps({"stops": {
            "005930": {
                "stop_loss": 68875.0,
                "take_profit": 79750.0,
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
        same best-effort notifier the decision-path rejection uses."""
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
        ):
            restored = await pm.restore_stop_overlay()

        assert restored == 0
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "복원 스탑 기각" in msg
        assert "005930" in msg


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
    """P0: partial REDUCE must not desync the shadow ledger; ADD must not be
    silently demoted to HOLD."""

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
    async def test_partial_reduce_leaves_quantity_unchanged_and_notifies(self, config):
        """The core bug: a partial REDUCE (new_quantity > 0) must NOT mutate
        the monitored quantity — there is no broker order behind it yet — and
        must emit an explicit not-executed notice instead of quiet drift."""
        pm, pos = self._position(config, quantity=100)
        notifier = self._notifier()

        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(
                pos, _honesty_decision(DecisionAction.REDUCE, quantity=30)
            )

        assert pos.quantity == 100, (
            "partial REDUCE must not silently decrement the shadow ledger"
        )
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "부분청산" in msg
        assert "005930" in msg

    @pytest.mark.asyncio
    async def test_add_decision_notifies_not_executed(self, config):
        """ADD must not be silently swallowed into HOLD — it must emit an
        explicit not-executed notice, and must not touch quantity (no buy
        execution path exists yet)."""
        pm, pos = self._position(config, quantity=100)
        notifier = self._notifier()

        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(pos, _honesty_decision(DecisionAction.ADD))

        assert pos.quantity == 100, "ADD has no buy execution path yet"
        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.await_args.args[0]
        assert "추가매수" in msg
        assert "005930" in msg

    @pytest.mark.asyncio
    async def test_add_decision_still_applies_sane_stop_adjustment(self, config):
        """The not-executed notice for ADD must not swallow the stop/take
        adjustment behavior it shares with the HOLD branch."""
        pm, pos = self._position(config, quantity=100, current_price=72500)
        notifier = self._notifier()

        with patch(
            "services.telegram.get_telegram_notifier",
            AsyncMock(return_value=notifier),
        ):
            await pm._apply_decision(
                pos,
                _honesty_decision(
                    DecisionAction.ADD, stop_loss=70000, take_profit=80000
                ),
            )

        assert pos.stop_loss == 70000
        assert pos.take_profit == 80000

    # ---- Regression: real execution paths must be unaffected ----

    @pytest.mark.asyncio
    async def test_full_close_reduce_still_executes(self, config, monkeypatch):
        """A REDUCE decision whose quantity closes the whole position
        (new_quantity <= 0) is real execution and must be unaffected."""
        pm, pos = self._position(config, quantity=100)

        closed = []
        fake_coord = MagicMock()

        async def _close(ticker):
            closed.append(ticker)

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

        async def _close(ticker):
            closed.append(ticker)

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
