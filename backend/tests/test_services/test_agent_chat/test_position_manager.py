"""
Tests for PositionManager

Unit tests for the PositionManager that monitors positions in real-time.
"""

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

import services.storage_service as ss
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
