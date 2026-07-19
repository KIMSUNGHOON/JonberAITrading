"""
Pytest Configuration and Fixtures

Provides shared fixtures for all tests.
"""

import asyncio
import sqlite3
from pathlib import Path
from typing import AsyncGenerator, Generator, Optional

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app

import services.storage_service as storage_service_module


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
        "decision": "approved",
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


# -------------------------------------------
# L-6: real-storage.db isolation (opt-in) + session tripwire
# -------------------------------------------
#
# Incident (2026-07-19 05:43~06:12 UTC): an unisolated test file
# (tests/test_api/test_agent_chat_ws_push.py) ran real
# ChatCoordinator.start_manual_discussion() completions against the
# process-wide get_storage_service() singleton, which defaults to the LIVE
# backend/data/storage.db when nothing has swapped it out. Every completed
# discussion (DECIDED or CANCELLED) calls
# services.agent_chat.decision_log.persist_session(), which writes a real
# row into agent_chat_decisions (+ agent_chat_votes) -- silently
# contaminating the measurement DB this lineage-restoration arc depends on.
#
# `isolated_storage_service` below is the fix: an OPT-IN (NOT autouse)
# fixture any test file can request explicitly (directly as a fixture arg,
# or via `pytestmark = pytest.mark.usefixtures("isolated_storage_service")`
# at module scope) to redirect get_storage_service() at its tmp-path SQLite
# instance for the duration of that file's tests. It is deliberately NOT
# autouse here -- making it blanket every test under tests/ would be a much
# larger blast radius than this task's remit, and would silently change the
# behavior of tests that intentionally exercise the real singleton (e.g.
# get_storage_service failure-path tests). Apply it file-by-file, the same
# way test_r5_p1_execution_reliability.py / test_afterhours_gate.py already
# hand-roll the identical pattern locally.
#
# `pytest_sessionstart`/`pytest_sessionfinish` add a tripwire: the real
# storage.db's agent_chat_decisions row count is snapshotted at session
# start and compared at session end. A net increase means some test,
# somewhere, wrote to the live DB without isolation -- this only WARNS
# (never fails the run) so it can't break the existing suite, but it makes
# any future regression impossible to miss in the test output.
#
# See .superpowers/sdd/task-L-6-report.md for the full incident writeup,
# the confirmed culprit, and the cleanup SQL for the rows already landed.


@pytest_asyncio.fixture
async def isolated_storage_service(tmp_path, monkeypatch):
    """Opt-in: swap services.storage_service's module-level singleton for a
    tmp-path-backed StorageService so get_storage_service() -- however it
    was imported by the calling module -- never touches the live
    backend/data/storage.db for the duration of the requesting test."""
    storage = storage_service_module.StorageService(
        db_path=tmp_path / "test_storage_isolated.db"
    )
    await storage.initialize()
    monkeypatch.setattr(storage_service_module, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(storage_service_module, "_storage_service", None)


_LINEAGE_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "storage.db"
_lineage_decisions_baseline: Optional[int] = None


def _count_live_agent_chat_decisions() -> Optional[int]:
    """Read-only row count of the LIVE agent_chat_decisions table. Never
    opens the db for write; returns None (tripwire no-ops) if the file or
    table doesn't exist yet (fresh checkout / CI)."""
    if not _LINEAGE_DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{_LINEAGE_DB_PATH}?mode=ro", uri=True)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM agent_chat_decisions")
            return cur.fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def pytest_sessionstart(session):  # noqa: D103 - pytest hook, not a fixture
    global _lineage_decisions_baseline
    _lineage_decisions_baseline = _count_live_agent_chat_decisions()


def pytest_sessionfinish(session, exitstatus):  # noqa: D103 - pytest hook
    if _lineage_decisions_baseline is None:
        return
    after = _count_live_agent_chat_decisions()
    if after is None or after <= _lineage_decisions_baseline:
        return
    delta = after - _lineage_decisions_baseline
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    message = (
        f"\n{'=' * 70}\n"
        f"L-6 TRIPWIRE WARNING: backend/data/storage.db agent_chat_decisions "
        f"grew by {delta} row(s) during this test session "
        f"({_lineage_decisions_baseline} -> {after}).\n"
        f"Some test wrote to the LIVE measurement DB instead of an isolated "
        f"tmp storage -- see .superpowers/sdd/task-L-6-report.md for the "
        f"isolation pattern (isolated_storage_service in tests/conftest.py) "
        f"and the cleanup SQL.\n"
        f"{'=' * 70}"
    )
    if terminal is not None:
        terminal.write_line(message, red=True, bold=True)
    else:
        print(message)
