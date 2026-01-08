"""
Tests for Agent Chat API Endpoints

Unit tests for the API routes in the Agent Group Chat system.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from services.agent_chat.models import (
    AgentType,
    MessageType,
    VoteType,
    SessionStatus,
    DecisionAction,
    MarketContext,
    ChatSession,
    TradeDecision,
    AgentMessage,
    AgentVote,
)


# -------------------------------------------
# Fixtures
# -------------------------------------------


@pytest.fixture
def mock_coordinator():
    """Create a mock ChatCoordinator."""
    coordinator = MagicMock()
    coordinator._running = False
    coordinator._active_rooms = {}
    coordinator._session_history = []
    coordinator.check_interval = 5
    coordinator.max_concurrent = 3
    coordinator.position_manager = None
    coordinator.start = AsyncMock()
    coordinator.stop = AsyncMock()
    coordinator.get_active_discussions = MagicMock(return_value=[])
    coordinator.get_session_history = MagicMock(return_value=[])
    coordinator.get_session_by_id = MagicMock(return_value=None)
    coordinator.start_manual_discussion = AsyncMock()
    return coordinator


@pytest.fixture
def mock_session():
    """Create a mock ChatSession."""
    context = MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=72500,
        price_change_pct=0.5,
    )
    session = ChatSession(
        ticker="005930",
        stock_name="삼성전자",
        context=context,
    )
    session.status = SessionStatus.DECIDED
    session.started_at = datetime.now()
    session.ended_at = datetime.now()
    session.decision = TradeDecision(
        action=DecisionAction.BUY,
        confidence=0.85,
        consensus_level=0.8,
        entry_price=72500,
        stop_loss=68875,
        take_profit=79750,
        rationale="Test decision",
    )
    return session


@pytest.fixture
def mock_position_manager():
    """Create a mock PositionManager."""
    pm = MagicMock()
    pm._running = True
    pm.get_all_positions = MagicMock(return_value=[])
    pm.get_position = MagicMock(return_value=None)
    pm.add_position = MagicMock()
    pm.update_position = MagicMock()
    pm.remove_position = MagicMock(return_value=True)
    pm.sync_from_account = AsyncMock()
    pm.get_summary = MagicMock(return_value={
        "is_running": True,
        "position_count": 0,
        "total_value": 0,
        "total_unrealized_pnl": 0,
        "total_unrealized_pnl_pct": 0,
        "event_count": 0,
        "positions": [],
    })
    pm.get_events = MagicMock(return_value=[])
    return pm


# -------------------------------------------
# Coordinator Status Tests
# -------------------------------------------


class TestCoordinatorStatusEndpoint:
    """Tests for coordinator status endpoint."""

    @pytest.mark.asyncio
    async def test_get_coordinator_status(self, mock_coordinator):
        """Test getting coordinator status."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/status")

            assert response.status_code == 200
            data = response.json()
            assert "is_running" in data
            assert "active_discussions" in data
            assert "total_sessions" in data

    @pytest.mark.asyncio
    async def test_get_coordinator_status_running(self, mock_coordinator):
        """Test getting coordinator status when running."""
        mock_coordinator._running = True
        mock_coordinator._active_rooms = {"005930": MagicMock()}
        mock_coordinator._session_history = [MagicMock(), MagicMock()]

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/status")

            assert response.status_code == 200
            data = response.json()
            assert data["is_running"] is True
            assert data["active_discussions"] == 1
            assert data["total_sessions"] == 2


# -------------------------------------------
# Coordinator Control Tests
# -------------------------------------------


class TestCoordinatorControlEndpoints:
    """Tests for coordinator control endpoints."""

    @pytest.mark.asyncio
    async def test_start_coordinator(self, mock_coordinator):
        """Test starting the coordinator."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/agent-chat/start")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"
            mock_coordinator.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_coordinator_with_config(self, mock_coordinator):
        """Test starting the coordinator with custom config."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/agent-chat/start",
                    json={
                        "check_interval_minutes": 10,
                        "max_concurrent_discussions": 5,
                    }
                )

            assert response.status_code == 200
            assert mock_coordinator.check_interval == 10
            assert mock_coordinator.max_concurrent == 5

    @pytest.mark.asyncio
    async def test_stop_coordinator(self, mock_coordinator):
        """Test stopping the coordinator."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/agent-chat/stop")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "stopped"
            mock_coordinator.stop.assert_awaited_once()


# -------------------------------------------
# Discussion Endpoints Tests
# -------------------------------------------


class TestDiscussionEndpoints:
    """Tests for discussion endpoints."""

    @pytest.mark.asyncio
    async def test_start_discussion(self, mock_coordinator, mock_session):
        """Test starting a manual discussion."""
        mock_coordinator.start_manual_discussion.return_value = mock_session

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/agent-chat/discuss",
                    json={
                        "ticker": "005930",
                        "stock_name": "삼성전자",
                    }
                )

            assert response.status_code == 200
            data = response.json()
            assert data["ticker"] == "005930"
            assert data["stock_name"] == "삼성전자"
            assert "session_id" in data

    @pytest.mark.asyncio
    async def test_start_discussion_conflict(self, mock_coordinator):
        """Test starting discussion when one is already in progress."""
        mock_coordinator.start_manual_discussion.side_effect = ValueError(
            "Discussion already in progress"
        )

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/agent-chat/discuss",
                    json={
                        "ticker": "005930",
                        "stock_name": "삼성전자",
                    }
                )

            assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_get_active_discussions(self, mock_coordinator):
        """Test getting active discussions."""
        mock_coordinator.get_active_discussions.return_value = [
            {
                "ticker": "005930",
                "stock_name": "삼성전자",
                "status": "analyzing",
            }
        ]

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/active")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            assert len(data["discussions"]) == 1


# -------------------------------------------
# Session History Tests
# -------------------------------------------


class TestSessionHistoryEndpoints:
    """Tests for session history endpoints."""

    @pytest.mark.asyncio
    async def test_get_sessions_empty(self, mock_coordinator):
        """Test getting sessions when empty."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/sessions")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
            assert data["sessions"] == []

    @pytest.mark.asyncio
    async def test_get_sessions_with_data(self, mock_coordinator, mock_session):
        """Test getting sessions with data."""
        mock_coordinator.get_session_history.return_value = [mock_session]

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/sessions")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            assert data["sessions"][0]["ticker"] == "005930"

    @pytest.mark.asyncio
    async def test_get_sessions_with_filter(self, mock_coordinator):
        """Test getting sessions with ticker filter."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/sessions?ticker=005930&limit=10")

            assert response.status_code == 200
            mock_coordinator.get_session_history.assert_called_once_with(
                limit=10,
                ticker="005930",
            )

    @pytest.mark.asyncio
    async def test_get_session_detail(self, mock_coordinator, mock_session):
        """Test getting session detail."""
        mock_coordinator.get_session_by_id.return_value = mock_session

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/agent-chat/sessions/{mock_session.id}")

            assert response.status_code == 200
            data = response.json()
            assert data["ticker"] == "005930"
            assert "decision" in data

    @pytest.mark.asyncio
    async def test_get_session_detail_not_found(self, mock_coordinator):
        """Test getting session detail when not found."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/sessions/non-existent")

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_session_messages(self, mock_coordinator, mock_session):
        """Test getting session messages."""
        msg = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술적 분석가",
            message_type=MessageType.ANALYSIS,
            content="분석 결과",
        )
        mock_session.start_round("analysis")
        mock_session.add_message(msg)
        mock_coordinator.get_session_by_id.return_value = mock_session

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/agent-chat/sessions/{mock_session.id}/messages")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_get_session_decision(self, mock_coordinator, mock_session):
        """Test getting session decision."""
        mock_coordinator.get_session_by_id.return_value = mock_session

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/agent-chat/sessions/{mock_session.id}/decision")

            assert response.status_code == 200
            data = response.json()
            assert data["action"] == "BUY"
            assert data["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_get_session_decision_no_decision(self, mock_coordinator, mock_session):
        """Test getting decision when none exists."""
        mock_session.decision = None
        mock_coordinator.get_session_by_id.return_value = mock_session

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/agent-chat/sessions/{mock_session.id}/decision")

            assert response.status_code == 404


# -------------------------------------------
# Agent Info Tests
# -------------------------------------------


class TestAgentInfoEndpoints:
    """Tests for agent info endpoints."""

    @pytest.mark.asyncio
    async def test_get_agent_info(self):
        """Test getting agent info."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/agent-chat/agents")

        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 5
        assert data["total_weight"] == 1.0

    @pytest.mark.asyncio
    async def test_get_decision_actions(self):
        """Test getting decision actions."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/agent-chat/decision-actions")

        assert response.status_code == 200
        data = response.json()
        assert "actions" in data
        actions = [a["action"] for a in data["actions"]]
        assert "BUY" in actions
        assert "SELL" in actions
        assert "HOLD" in actions


# -------------------------------------------
# Position Management Tests
# -------------------------------------------


class TestPositionEndpoints:
    """Tests for position management endpoints."""

    @pytest.mark.asyncio
    async def test_get_positions_no_manager(self, mock_coordinator):
        """Test getting positions when manager not running."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/positions")

            assert response.status_code == 200
            data = response.json()
            assert data["is_running"] is False
            assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_get_positions_with_manager(self, mock_coordinator, mock_position_manager):
        """Test getting positions with manager running."""
        mock_coordinator.position_manager = mock_position_manager

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/positions")

            assert response.status_code == 200
            data = response.json()
            assert data["is_running"] is True

    @pytest.mark.asyncio
    async def test_get_position_not_found(self, mock_coordinator, mock_position_manager):
        """Test getting a specific position that doesn't exist."""
        mock_coordinator.position_manager = mock_position_manager

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/positions/000000")

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_add_position(self, mock_coordinator, mock_position_manager):
        """Test adding a position."""
        mock_coordinator.position_manager = mock_position_manager
        mock_position = MagicMock()
        mock_position.ticker = "005930"
        mock_position_manager.add_position.return_value = mock_position

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/agent-chat/positions",
                    json={
                        "ticker": "005930",
                        "stock_name": "삼성전자",
                        "quantity": 100,
                        "avg_price": 72500,
                    }
                )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "added"
            assert data["ticker"] == "005930"

    @pytest.mark.asyncio
    async def test_add_position_no_manager(self, mock_coordinator):
        """Test adding position when manager not running."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/agent-chat/positions",
                    json={
                        "ticker": "005930",
                        "stock_name": "삼성전자",
                        "quantity": 100,
                        "avg_price": 72500,
                    }
                )

            assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_update_position(self, mock_coordinator, mock_position_manager):
        """Test updating a position."""
        mock_coordinator.position_manager = mock_position_manager
        mock_position = MagicMock()
        mock_position.stop_loss = 68000
        mock_position.take_profit = 80000
        mock_position.trailing_stop_pct = 5.0
        mock_position_manager.update_position.return_value = mock_position

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.put(
                    "/api/agent-chat/positions/005930",
                    json={
                        "stop_loss": 68000,
                        "take_profit": 80000,
                    }
                )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "updated"

    @pytest.mark.asyncio
    async def test_delete_position(self, mock_coordinator, mock_position_manager):
        """Test deleting a position."""
        mock_coordinator.position_manager = mock_position_manager

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.delete("/api/agent-chat/positions/005930")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "removed"

    @pytest.mark.asyncio
    async def test_sync_positions(self, mock_coordinator, mock_position_manager):
        """Test syncing positions from account."""
        mock_coordinator.position_manager = mock_position_manager

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/agent-chat/positions/sync")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "synced"
            mock_position_manager.sync_from_account.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_position_summary(self, mock_coordinator, mock_position_manager):
        """Test getting position summary."""
        mock_coordinator.position_manager = mock_position_manager

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/positions/summary")

            assert response.status_code == 200
            data = response.json()
            assert "is_running" in data
            assert "position_count" in data

    @pytest.mark.asyncio
    async def test_get_position_events(self, mock_coordinator, mock_position_manager):
        """Test getting position events."""
        mock_coordinator.position_manager = mock_position_manager

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agent-chat/positions/events")

            assert response.status_code == 200
            data = response.json()
            assert "events" in data
            assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_get_position_event_types(self):
        """Test getting position event types."""
        from app.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/agent-chat/positions/event-types")

        assert response.status_code == 200
        data = response.json()
        assert "event_types" in data
        event_types = [e["type"] for e in data["event_types"]]
        assert "stop_loss_hit" in event_types
        assert "take_profit_hit" in event_types


# -------------------------------------------
# Validation Tests
# -------------------------------------------


class TestRequestValidation:
    """Tests for request validation."""

    @pytest.mark.asyncio
    async def test_start_discussion_missing_ticker(self, mock_coordinator):
        """Test starting discussion with missing ticker."""
        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/agent-chat/discuss",
                    json={
                        "stock_name": "삼성전자",
                    }
                )

            assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_add_position_invalid_quantity(self, mock_coordinator, mock_position_manager):
        """Test adding position with invalid quantity."""
        mock_coordinator.position_manager = mock_position_manager

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/agent-chat/positions",
                    json={
                        "ticker": "005930",
                        "stock_name": "삼성전자",
                        "quantity": 0,  # Invalid
                        "avg_price": 72500,
                    }
                )

            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_add_position_negative_price(self, mock_coordinator, mock_position_manager):
        """Test adding position with negative price."""
        mock_coordinator.position_manager = mock_position_manager

        with patch('app.api.routes.agent_chat.get_chat_coordinator') as mock_get:
            mock_get.return_value = mock_coordinator

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/agent-chat/positions",
                    json={
                        "ticker": "005930",
                        "stock_name": "삼성전자",
                        "quantity": 100,
                        "avg_price": -100,  # Invalid
                    }
                )

            assert response.status_code == 422
