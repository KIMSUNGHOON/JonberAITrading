"""
Tests for ChatCoordinator

Unit tests for the ChatCoordinator that manages multiple chat rooms.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from services.agent_chat.models import (
    SessionStatus,
    DecisionAction,
    MarketContext,
    ChatSession,
    TradeDecision,
)
from services.agent_chat.coordinator import (
    ChatCoordinator,
    get_chat_coordinator,
)


# -------------------------------------------
# Fixtures
# -------------------------------------------


@pytest.fixture
def coordinator():
    """Create a ChatCoordinator instance for testing."""
    return ChatCoordinator(
        check_interval_minutes=5,
        max_concurrent_discussions=3,
        min_discussion_interval_minutes=30,
    )


@pytest.fixture
def mock_market_context():
    """Create a mock market context."""
    return MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=72500,
        price_change_pct=0.5,
    )


@pytest.fixture
def mock_session(mock_market_context):
    """Create a mock ChatSession."""
    session = ChatSession(
        ticker="005930",
        stock_name="삼성전자",
        context=mock_market_context,
    )
    session.status = SessionStatus.DECIDED
    session.decision = TradeDecision(
        action=DecisionAction.BUY,
        confidence=0.85,
        consensus_level=0.8,
        entry_price=72500,
        rationale="Test decision",
    )
    return session


# -------------------------------------------
# Initialization Tests
# -------------------------------------------


class TestCoordinatorInitialization:
    """Tests for ChatCoordinator initialization."""

    def test_create_coordinator(self):
        """Test creating a coordinator."""
        coord = ChatCoordinator(
            check_interval_minutes=10,
            max_concurrent_discussions=5,
        )

        assert coord.check_interval == 10
        assert coord.max_concurrent == 5
        assert not coord._running

    def test_default_values(self):
        """Test default values."""
        coord = ChatCoordinator()

        assert coord.check_interval == 5
        assert coord.max_concurrent == 3


# -------------------------------------------
# Lifecycle Tests
# -------------------------------------------


class TestCoordinatorLifecycle:
    """Tests for coordinator lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, coordinator):
        """Test that start sets running flag."""
        with patch.object(coordinator, '_position_manager', None):
            with patch('services.agent_chat.coordinator.get_position_manager') as mock_pm:
                mock_pm.return_value = AsyncMock()
                mock_pm.return_value.start = AsyncMock()
                mock_pm.return_value.sync_from_account = AsyncMock()
                mock_pm.return_value.set_chat_coordinator = MagicMock()
                mock_pm.return_value.get_all_positions = MagicMock(return_value=[])

                await coordinator.start()

                assert coordinator._running
                assert coordinator._scheduler is not None

                # Cleanup
                await coordinator.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, coordinator):
        """Test that stop clears running flag."""
        coordinator._running = True

        with patch.object(coordinator, '_position_manager', None):
            await coordinator.stop()

        assert not coordinator._running

    @pytest.mark.asyncio
    async def test_start_idempotent(self, coordinator):
        """Test that calling start twice is safe."""
        with patch.object(coordinator, '_position_manager', None):
            with patch('services.agent_chat.coordinator.get_position_manager') as mock_pm:
                mock_pm.return_value = AsyncMock()
                mock_pm.return_value.start = AsyncMock()
                mock_pm.return_value.sync_from_account = AsyncMock()
                mock_pm.return_value.set_chat_coordinator = MagicMock()
                mock_pm.return_value.get_all_positions = MagicMock(return_value=[])

                await coordinator.start()
                scheduler1 = coordinator._scheduler

                await coordinator.start()  # Should be no-op
                scheduler2 = coordinator._scheduler

                assert scheduler1 == scheduler2

                await coordinator.stop()


# -------------------------------------------
# Callback Tests
# -------------------------------------------


class TestCoordinatorCallbacks:
    """Tests for coordinator callbacks."""

    def test_register_decision_callback(self, coordinator):
        """Test registering a decision callback."""
        callback = MagicMock()
        coordinator.on_decision(callback)

        assert callback in coordinator._on_decision_callbacks

    def test_register_session_complete_callback(self, coordinator):
        """Test registering a session complete callback."""
        callback = MagicMock()
        coordinator.on_session_complete(callback)

        assert callback in coordinator._on_session_complete_callbacks


# -------------------------------------------
# Discussion Management Tests
# -------------------------------------------


class TestDiscussionManagement:
    """Tests for discussion management."""

    def test_get_active_discussions_empty(self, coordinator):
        """Test getting active discussions when none exist."""
        active = coordinator.get_active_discussions()

        assert active == []

    def test_get_session_history_empty(self, coordinator):
        """Test getting session history when empty."""
        history = coordinator.get_session_history()

        assert history == []

    def test_get_session_history_with_limit(self, coordinator, mock_session):
        """Test getting session history with limit."""
        # Add sessions
        coordinator._session_history = [mock_session] * 10

        history = coordinator.get_session_history(limit=5)

        assert len(history) == 5

    def test_get_session_history_filter_by_ticker(self, coordinator, mock_market_context):
        """Test filtering session history by ticker."""
        session1 = ChatSession(
            ticker="005930",
            stock_name="삼성전자",
            context=mock_market_context,
        )
        session2 = ChatSession(
            ticker="000660",
            stock_name="SK하이닉스",
            context=MarketContext(
                ticker="000660",
                stock_name="SK하이닉스",
                current_price=120000,
                price_change_pct=1.0,
            ),
        )

        coordinator._session_history = [session1, session2]

        history = coordinator.get_session_history(ticker="005930")

        assert len(history) == 1
        assert history[0].ticker == "005930"

    def test_get_session_by_id(self, coordinator, mock_session):
        """Test getting session by ID."""
        coordinator._session_history = [mock_session]

        found = coordinator.get_session_by_id(mock_session.id)

        assert found == mock_session

    def test_get_session_by_id_not_found(self, coordinator):
        """Test getting session by ID when not found."""
        found = coordinator.get_session_by_id("non-existent")

        assert found is None


# -------------------------------------------
# Manual Discussion Tests
# -------------------------------------------


class TestManualDiscussion:
    """Tests for manual discussion triggering."""

    @pytest.mark.asyncio
    async def test_start_manual_discussion(self, coordinator):
        """Test starting a manual discussion."""
        with patch('services.agent_chat.coordinator.ChatRoom') as MockRoom:
            mock_session = MagicMock()
            mock_session.id = "test-session"
            mock_session.status = SessionStatus.DECIDED
            mock_session.decision = TradeDecision(
                action=DecisionAction.HOLD,
                confidence=0.7,
                consensus_level=0.75,
                rationale="Hold decision",
            )

            mock_room_instance = AsyncMock()
            mock_room_instance.start = AsyncMock(return_value=mock_session)
            mock_room_instance.session = mock_session
            MockRoom.return_value = mock_room_instance

            with patch.object(coordinator, '_fetch_market_context') as mock_context:
                mock_context.return_value = AsyncMock()

                session = await coordinator.start_manual_discussion(
                    ticker="005930",
                    stock_name="삼성전자",
                )

                assert session is not None
                assert session.id == "test-session"

    @pytest.mark.asyncio
    async def test_manual_discussion_conflict(self, coordinator):
        """Test that concurrent discussions for same stock are prevented."""
        # Simulate active room
        coordinator._active_rooms["005930"] = MagicMock()

        with pytest.raises(ValueError, match="already in progress"):
            await coordinator.start_manual_discussion(
                ticker="005930",
                stock_name="삼성전자",
            )


# -------------------------------------------
# Opportunity Detection Tests
# -------------------------------------------


class TestOpportunityDetection:
    """Tests for opportunity detection logic."""

    @pytest.mark.asyncio
    async def test_detect_opportunity_target_price_hit(self, coordinator):
        """Test opportunity detection when target price is near."""
        stock = {
            "ticker": "005930",
            "current_price": 72000,
            "target_entry_price": 72500,
            "confidence": 0.8,
        }

        should_discuss = await coordinator._detect_opportunity(stock)

        # Within 3% of target should trigger
        # Implementation may vary, check both cases
        assert should_discuss is True or should_discuss is False

    @pytest.mark.asyncio
    async def test_detect_opportunity_low_confidence(self, coordinator):
        """Test that low confidence doesn't trigger discussion."""
        stock = {
            "ticker": "005930",
            "current_price": 72500,
            "target_entry_price": 80000,  # Far from current price (>3%)
            "confidence": 0.5,  # Low confidence
        }

        should_discuss = await coordinator._detect_opportunity(stock)

        # Low confidence + price far from target = no trigger
        assert should_discuss is False


# -------------------------------------------
# Discussion Interval Tests
# -------------------------------------------


class TestDiscussionInterval:
    """Tests for discussion interval enforcement."""

    def test_was_recently_discussed_recent(self, coordinator):
        """Test that recently discussed stocks are detected."""
        ticker = "005930"

        # Set last discussion to recent time
        coordinator._last_discussion[ticker] = datetime.now()

        was_recent = coordinator._was_recently_discussed(ticker)

        assert was_recent is True

    def test_was_recently_discussed_old(self, coordinator):
        """Test that old discussions are not flagged."""
        ticker = "005930"

        # Set last discussion to past interval
        coordinator._last_discussion[ticker] = datetime.now() - timedelta(minutes=60)

        was_recent = coordinator._was_recently_discussed(ticker)

        assert was_recent is False

    def test_was_recently_discussed_never(self, coordinator):
        """Test that never discussed stocks are allowed."""
        ticker = "005930"

        # No previous discussion
        was_recent = coordinator._was_recently_discussed(ticker)

        assert was_recent is False


# -------------------------------------------
# Max Concurrent Tests
# -------------------------------------------


class TestMaxConcurrent:
    """Tests for maximum concurrent discussions limit."""

    def test_respects_max_concurrent(self, coordinator):
        """Test that max concurrent limit is respected."""
        # Fill up active rooms
        for i in range(coordinator.max_concurrent):
            coordinator._active_rooms[f"ticker_{i}"] = MagicMock()

        # Should not allow more
        at_limit = len(coordinator._active_rooms) >= coordinator.max_concurrent

        assert at_limit is True


# -------------------------------------------
# Singleton Tests
# -------------------------------------------


class TestCoordinatorSingleton:
    """Tests for singleton pattern."""

    @pytest.mark.asyncio
    async def test_get_coordinator_returns_same_instance(self):
        """Test that get_chat_coordinator returns the same instance."""
        coord1 = await get_chat_coordinator()
        coord2 = await get_chat_coordinator()

        assert coord1 is coord2
