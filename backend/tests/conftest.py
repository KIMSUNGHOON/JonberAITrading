"""
Pytest Configuration and Fixtures

Provides shared fixtures for all tests.
"""

import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app


# -------------------------------------------
# Event Loop Configuration
# -------------------------------------------


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# -------------------------------------------
# FastAPI Test Client Fixtures
# -------------------------------------------


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """
    Synchronous test client for FastAPI.

    Usage:
        def test_endpoint(client):
            response = client.get("/health")
            assert response.status_code == 200
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """
    Asynchronous test client for FastAPI.

    Usage:
        async def test_endpoint(async_client):
            response = await async_client.get("/health")
            assert response.status_code == 200
    """
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# -------------------------------------------
# Mock Fixtures
# -------------------------------------------


@pytest.fixture
def mock_ticker() -> str:
    """Sample ticker for testing."""
    return "AAPL"


@pytest.fixture
def mock_analysis_request() -> dict:
    """Sample analysis request payload."""
    return {
        "ticker": "AAPL",
        "analysis_types": ["technical", "fundamental"],
    }


@pytest.fixture
def mock_approval_request() -> dict:
    """Sample approval request payload."""
    return {
        "session_id": "test-session-123",
        "proposal_id": "test-proposal-456",
        "approved": True,
        "feedback": "Looks good",
    }


@pytest.fixture
def mock_trade_proposal() -> dict:
    """Sample trade proposal."""
    return {
        "id": "test-proposal-456",
        "ticker": "AAPL",
        "action": "buy",
        "quantity": 100,
        "entry_price": 150.00,
        "stop_loss": 145.00,
        "take_profit": 160.00,
        "risk_score": 5,
        "rationale": "Strong technical indicators",
    }


@pytest.fixture
def mock_session_state() -> dict:
    """Sample session state."""
    return {
        "ticker": "AAPL",
        "current_stage": "analysis",
        "analyses": [],
        "reasoning_log": [],
        "trade_proposal": None,
        "awaiting_approval": False,
        "active_position": None,
    }


# -------------------------------------------
# Environment Configuration for Tests
# -------------------------------------------


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    """Set environment variables for testing."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("MARKET_DATA_MODE", "mock")
