"""
Tests for Unified Session Manager Service
"""

import pytest
import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from services.session_manager import (
    SessionManager,
    AnalysisSession,
    MarketType,
    SessionStatus,
    get_session_manager,
    register_session,
    update_session_status,
    get_session,
    remove_session,
    get_all_sessions,
    get_sessions_by_market,
    acquire_analysis_slot,
    release_analysis_slot,
    get_analysis_stats,
    COMPLETED_SESSION_TTL,
    MAX_CONCURRENT_ANALYSES,
)


# Use a test database path
TEST_DB_PATH = "data/test_sessions.db"


@pytest.fixture
def clean_db():
    """Clean up test database before and after tests."""
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture
async def session_manager(clean_db):
    """Create a fresh SessionManager for testing."""
    with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
        manager = SessionManager()
        await manager.initialize()
        yield manager
        # Cleanup
        manager._sessions.clear()


class TestAnalysisSession:
    """Tests for AnalysisSession dataclass"""

    def test_session_creation(self):
        session = AnalysisSession(
            session_id="test-123",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자",
        )
        assert session.session_id == "test-123"
        assert session.market_type == MarketType.KIWOOM
        assert session.ticker == "005930"
        assert session.display_name == "삼성전자"
        assert session.status == SessionStatus.RUNNING

    def test_session_to_dict(self):
        session = AnalysisSession(
            session_id="test-123",
            market_type=MarketType.COIN,
            ticker="KRW-BTC",
            display_name="비트코인",
            market="KRW-BTC",
            korean_name="비트코인",
        )
        d = session.to_dict()
        assert d["session_id"] == "test-123"
        assert d["market_type"] == "coin"
        assert d["ticker"] == "KRW-BTC"
        assert d["korean_name"] == "비트코인"

    def test_session_to_legacy_dict_stock(self):
        session = AnalysisSession(
            session_id="test-123",
            market_type=MarketType.STOCK,
            ticker="AAPL",
            display_name="Apple Inc",
        )
        d = session.to_legacy_dict()
        assert d["ticker"] == "AAPL"
        assert "stk_cd" not in d
        assert "market" not in d

    def test_session_to_legacy_dict_kiwoom(self):
        session = AnalysisSession(
            session_id="test-123",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자",
            stk_cd="005930",
            stk_nm="삼성전자",
        )
        d = session.to_legacy_dict()
        assert d["stk_cd"] == "005930"
        assert d["stk_nm"] == "삼성전자"

    def test_session_to_legacy_dict_coin(self):
        session = AnalysisSession(
            session_id="test-123",
            market_type=MarketType.COIN,
            ticker="KRW-BTC",
            display_name="비트코인",
            market="KRW-BTC",
            korean_name="비트코인",
        )
        d = session.to_legacy_dict()
        assert d["market"] == "KRW-BTC"
        assert d["korean_name"] == "비트코인"


class TestSessionManager:
    """Tests for SessionManager class"""

    @pytest.mark.asyncio
    async def test_initialize(self, session_manager):
        """Test manager initialization."""
        assert session_manager._initialized is True
        assert session_manager._analysis_semaphore is not None

    @pytest.mark.asyncio
    async def test_create_session(self, session_manager):
        """Test session creation."""
        session = await session_manager.create_session(
            session_id="test-001",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자",
            stk_cd="005930",
            stk_nm="삼성전자",
        )
        assert session.session_id == "test-001"
        assert session.market_type == MarketType.KIWOOM
        assert session.status == SessionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_get_session(self, session_manager):
        """Test session retrieval."""
        await session_manager.create_session(
            session_id="test-002",
            market_type=MarketType.COIN,
            ticker="KRW-BTC",
            display_name="비트코인",
        )
        session = await session_manager.get_session("test-002")
        assert session is not None
        assert session.ticker == "KRW-BTC"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, session_manager):
        """Test session not found."""
        session = await session_manager.get_session("nonexistent")
        assert session is None

    @pytest.mark.asyncio
    async def test_update_status(self, session_manager):
        """Test status update."""
        await session_manager.create_session(
            session_id="test-003",
            market_type=MarketType.STOCK,
            ticker="AAPL",
            display_name="Apple",
        )
        await session_manager.update_status("test-003", SessionStatus.COMPLETED)
        session = await session_manager.get_session("test-003")
        assert session.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, session_manager):
        """Test status update with error."""
        await session_manager.create_session(
            session_id="test-004",
            market_type=MarketType.STOCK,
            ticker="AAPL",
            display_name="Apple",
        )
        await session_manager.update_status("test-004", SessionStatus.ERROR, error="Test error")
        session = await session_manager.get_session("test-004")
        assert session.status == SessionStatus.ERROR
        assert session.error == "Test error"

    @pytest.mark.asyncio
    async def test_update_state(self, session_manager):
        """Test state update."""
        await session_manager.create_session(
            session_id="test-005",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자",
        )
        await session_manager.update_state(
            "test-005",
            {"technical_analysis": {"signal": "BUY"}},
            last_node="technical"
        )
        session = await session_manager.get_session("test-005")
        assert session.state.get("technical_analysis", {}).get("signal") == "BUY"
        assert session.last_node == "technical"

    @pytest.mark.asyncio
    async def test_get_all_sessions(self, session_manager):
        """Test getting all sessions."""
        await session_manager.create_session(
            session_id="test-010",
            market_type=MarketType.STOCK,
            ticker="AAPL",
            display_name="Apple",
        )
        await session_manager.create_session(
            session_id="test-011",
            market_type=MarketType.COIN,
            ticker="KRW-BTC",
            display_name="비트코인",
        )
        sessions = await session_manager.get_all_sessions()
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_get_all_sessions_filtered_by_market(self, session_manager):
        """Test getting sessions filtered by market type."""
        await session_manager.create_session(
            session_id="test-020",
            market_type=MarketType.STOCK,
            ticker="AAPL",
            display_name="Apple",
        )
        await session_manager.create_session(
            session_id="test-021",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자",
        )
        await session_manager.create_session(
            session_id="test-022",
            market_type=MarketType.KIWOOM,
            ticker="000660",
            display_name="SK하이닉스",
        )
        kiwoom_sessions = await session_manager.get_all_sessions(market_type=MarketType.KIWOOM)
        assert len(kiwoom_sessions) == 2

    @pytest.mark.asyncio
    async def test_remove_session(self, session_manager):
        """Test session removal."""
        await session_manager.create_session(
            session_id="test-030",
            market_type=MarketType.STOCK,
            ticker="AAPL",
            display_name="Apple",
        )
        result = await session_manager.remove_session("test-030")
        assert result is True
        session = await session_manager.get_session("test-030")
        assert session is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_session(self, session_manager):
        """Test removing nonexistent session."""
        result = await session_manager.remove_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, session_manager):
        """Test cleanup of expired sessions."""
        # Create a completed session with old timestamp
        session = await session_manager.create_session(
            session_id="test-040",
            market_type=MarketType.STOCK,
            ticker="AAPL",
            display_name="Apple",
        )
        # Manually set old created_at and completed status
        session.created_at = datetime.now(timezone.utc) - COMPLETED_SESSION_TTL - timedelta(hours=1)
        session.status = SessionStatus.COMPLETED

        # Create a running session (should not be removed)
        await session_manager.create_session(
            session_id="test-041",
            market_type=MarketType.STOCK,
            ticker="MSFT",
            display_name="Microsoft",
        )

        removed = await session_manager.cleanup_expired_sessions()
        assert removed == 1
        assert await session_manager.get_session("test-040") is None
        assert await session_manager.get_session("test-041") is not None

    @pytest.mark.asyncio
    async def test_get_stats(self, session_manager):
        """Test getting statistics."""
        await session_manager.create_session(
            session_id="test-050",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자",
        )
        await session_manager.create_session(
            session_id="test-051",
            market_type=MarketType.COIN,
            ticker="KRW-BTC",
            display_name="비트코인",
        )
        await session_manager.update_status("test-051", SessionStatus.COMPLETED)

        stats = await session_manager.get_stats()
        assert stats["total_sessions"] == 2
        assert stats["session_counts"]["running"] == 1
        assert stats["session_counts"]["completed"] == 1
        assert stats["market_counts"]["kiwoom"] == 1
        assert stats["market_counts"]["coin"] == 1


class TestConcurrencyControl:
    """Tests for semaphore-based concurrency control"""

    @pytest.mark.asyncio
    async def test_acquire_and_release_slot(self, session_manager):
        """Test acquiring and releasing analysis slots."""
        initial_available = session_manager.get_available_slots()
        assert initial_available == MAX_CONCURRENT_ANALYSES

        acquired = await session_manager.acquire_analysis_slot()
        assert acquired is True
        assert session_manager.get_available_slots() == initial_available - 1
        assert session_manager.get_active_analysis_count() == 1

        session_manager.release_analysis_slot()
        assert session_manager.get_available_slots() == initial_available

    @pytest.mark.asyncio
    async def test_acquire_slot_timeout(self, session_manager):
        """Test slot acquisition timeout."""
        # Acquire all slots
        for _ in range(MAX_CONCURRENT_ANALYSES):
            await session_manager.acquire_analysis_slot()

        # Try to acquire one more with short timeout
        acquired = await session_manager.acquire_analysis_slot(timeout=0.1)
        assert acquired is False

        # Release all slots
        for _ in range(MAX_CONCURRENT_ANALYSES):
            session_manager.release_analysis_slot()


class TestBackwardCompatibility:
    """Tests for backward compatibility wrapper functions"""

    @pytest.mark.asyncio
    async def test_register_session_wrapper(self, clean_db):
        """Test register_session wrapper."""
        with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
            # Reset singleton
            import services.session_manager as sm
            sm._session_manager = None

            result = await register_session(
                session_id="compat-001",
                market_type="kiwoom",
                ticker="005930",
                display_name="삼성전자",
            )
            assert result["session_id"] == "compat-001"
            assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_update_session_status_wrapper(self, clean_db):
        """Test update_session_status wrapper."""
        with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
            import services.session_manager as sm
            sm._session_manager = None

            await register_session(
                session_id="compat-002",
                market_type="coin",
                ticker="KRW-BTC",
                display_name="비트코인",
            )
            await update_session_status("compat-002", "completed")

            session = await get_session("compat-002")
            assert session["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_session_wrapper(self, clean_db):
        """Test get_session wrapper."""
        with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
            import services.session_manager as sm
            sm._session_manager = None

            await register_session(
                session_id="compat-003",
                market_type="stock",
                ticker="AAPL",
                display_name="Apple",
            )
            session = await get_session("compat-003")
            assert session is not None
            assert session["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_remove_session_wrapper(self, clean_db):
        """Test remove_session wrapper."""
        with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
            import services.session_manager as sm
            sm._session_manager = None

            await register_session(
                session_id="compat-004",
                market_type="kiwoom",
                ticker="005930",
                display_name="삼성전자",
            )
            await remove_session("compat-004")
            session = await get_session("compat-004")
            assert session is None

    @pytest.mark.asyncio
    async def test_get_all_sessions_wrapper(self, clean_db):
        """Test get_all_sessions wrapper."""
        with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
            import services.session_manager as sm
            sm._session_manager = None

            await register_session(
                session_id="compat-005",
                market_type="stock",
                ticker="AAPL",
                display_name="Apple",
            )
            await register_session(
                session_id="compat-006",
                market_type="kiwoom",
                ticker="005930",
                display_name="삼성전자",
            )
            sessions = await get_all_sessions()
            assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_get_sessions_by_market_wrapper(self, clean_db):
        """Test get_sessions_by_market wrapper."""
        with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
            import services.session_manager as sm
            sm._session_manager = None

            await register_session(
                session_id="compat-007",
                market_type="stock",
                ticker="AAPL",
                display_name="Apple",
            )
            await register_session(
                session_id="compat-008",
                market_type="kiwoom",
                ticker="005930",
                display_name="삼성전자",
            )
            kiwoom_sessions = await get_sessions_by_market("kiwoom")
            assert len(kiwoom_sessions) == 1
            assert "compat-008" in kiwoom_sessions

    @pytest.mark.asyncio
    async def test_get_analysis_stats_wrapper(self, clean_db):
        """Test get_analysis_stats wrapper."""
        with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
            import services.session_manager as sm
            sm._session_manager = None

            await register_session(
                session_id="compat-009",
                market_type="kiwoom",
                ticker="005930",
                display_name="삼성전자",
            )
            stats = await get_analysis_stats()
            assert "total_sessions" in stats
            assert "session_counts" in stats
            assert "market_counts" in stats


class TestSubscription:
    """Tests for WebSocket subscription support"""

    @pytest.mark.asyncio
    async def test_subscribe_and_notify(self, session_manager):
        """Test subscribing and receiving notifications."""
        await session_manager.create_session(
            session_id="sub-001",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자",
        )

        queue = await session_manager.subscribe("sub-001")

        # Update status should trigger notification
        await session_manager.update_status("sub-001", SessionStatus.COMPLETED)

        # Check queue received message
        message = queue.get_nowait()
        assert message["type"] == "status"
        assert message["status"] == "completed"

    @pytest.mark.asyncio
    async def test_unsubscribe(self, session_manager):
        """Test unsubscribing from notifications."""
        await session_manager.create_session(
            session_id="sub-002",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자",
        )

        queue = await session_manager.subscribe("sub-002")
        await session_manager.unsubscribe("sub-002", queue)

        assert "sub-002" not in session_manager._subscribers
