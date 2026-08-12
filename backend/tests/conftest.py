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

import services.background_scanner.scanner as scanner_module
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
# FI final-fix review Minor 2: scanner_results.db isolation (autouse)
# -------------------------------------------
#
# app.main's lifespan (FI-1, see BackgroundScanner.reconcile_orphan_scan_
# sessions) unconditionally runs an UPDATE against
# services.background_scanner.scanner.DB_PATH on every process startup --
# including every `with TestClient(app) as ...:` boot anywhere in the
# suite (module- or function-scoped `client` fixtures across
# tests/test_api/*.py all trigger FastAPI's lifespan). Left unpatched,
# this write silently touches the real backend/data/scanner_results.db
# from ordinary test runs -- the same tripwire-violating pattern the L-6
# incident below caught for storage.db, just for a different DB file.
#
# Session-scoped + autouse so it patches the module attribute once,
# before ANY test's own fixtures run: pytest instantiates higher-scoped
# fixtures first within a test request ("higher-scoped fixtures are
# instantiated first"), so this always wins the race against a
# module-scoped `client` fixture (e.g. tests/test_api/test_discovery_
# routes.py's) even on that module's very first test. Plain attribute
# reassignment rather than the `monkeypatch` fixture -- `monkeypatch` is
# function-scoped and cannot be requested from a session-scoped fixture.
# DB_PATH is read fresh off the module global at every call site inside
# scanner.py (never cached on the BackgroundScanner instance), so
# reassigning the attribute here is sufficient regardless of when
# scanner.py was first imported relative to this fixture running.


@pytest.fixture(scope="session", autouse=True)
def _isolate_scanner_db_path(tmp_path_factory):
    """Autouse: redirect scanner.DB_PATH at a throwaway sqlite file for the
    whole test session so no TestClient(app) boot's FI-1 orphan-reconcile
    (or any other scanner DB write) ever touches the real
    backend/data/scanner_results.db."""
    original = scanner_module.DB_PATH
    scanner_module.DB_PATH = tmp_path_factory.mktemp("scanner_db_isolation") / "scanner_results.db"
    yield
    scanner_module.DB_PATH = original


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


# -------------------------------------------
# 라이브 DB 가드 (2026-08-12) — 탐지가 아니라 **차단**
#
# 위 L-6 트립와이어는 `agent_chat_decisions`의 *행 수 증가*만 보고, 그것도
# 경고만 한다. 그래서 다음을 **구조적으로 놓친다**:
#
#   `app_settings` 오염은 UPDATE라 행 수가 변하지 않는다.
#
# 2026-08-03과 2026-08-11에 **같은 키가 두 번** 그렇게 덮였다 --
# `agent_chat:coordinator_state`가 테스트 픽스처 값
# `{"running": false, "check_interval": 5, "max_concurrent": 3}`으로. 08-11
# 오염은 **3거래일 뒤** 재기동에서야 발현해, 그동안 자율 토론 엔진이 꺼진
# 채로 돌았다(손절만 작동해 증상이 "주문이 안 나간다" 하나뿐이었다).
#
# 규칙("전체 스위트는 워크트리에서")이 메모리와 문서에만 있고 **명령 자체에
# 붙어 있지 않은 것**이 근본 원인이었다. 그래서 여기서 강제한다.
#
# **왜 실패가 아니라 리다이렉트인가**: 라이브 경로를 열려는 테스트를 즉시
# 실패시키면 격리가 없는 기존 파일 9개가 한꺼번에 깨진다. 리다이렉트는
# 메인 체크아웃을 **워크트리와 같은 상태**로 만들 뿐이라(워크트리에는
# `storage.db`가 없다) 동작 변화가 예측 가능하다. 대신 침묵하지 않는다 --
# 세션 끝에 리다이렉트된 테스트를 전부 이름으로 보고한다.
# -------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_LIVE_DB_FILES = {
    (_DATA_DIR / "storage.db").resolve(),
    (_DATA_DIR / "holidays.db").resolve(),
}
_live_db_offenders: set = set()


def _sandbox_target(original, sandbox: Path) -> Optional[Path]:
    """`original`이 라이브 DB면 샌드박스 안의 같은 이름 경로, 아니면 None."""
    if original is None:
        return None
    try:
        resolved = Path(original).resolve()
    except (OSError, ValueError, TypeError):
        return None
    return sandbox / resolved.name if resolved in _LIVE_DB_FILES else None


@pytest.fixture(autouse=True)
def guard_live_databases(request, tmp_path_factory, monkeypatch):
    """라이브 `storage.db`/`holidays.db`를 여는 시도를 tmp로 돌린다.

    `db_path=None`(기본 경로)까지 잡는 것이 핵심이다 -- 실제 사고 경로인
    `get_storage_service()` 싱글턴이 바로 그 형태로 만들어진다. 명시적
    경로만 막으면 정작 막아야 할 것을 놓친다.
    """
    import services.krx_holiday.storage as holiday_storage_module

    sandbox = tmp_path_factory.mktemp("live-db-guard")
    nodeid = request.node.nodeid

    real_storage_init = storage_service_module.StorageService.__init__
    real_holiday_init = holiday_storage_module.HolidayStorage.__init__

    def _storage_init(self, db_path=None):
        requested = db_path if db_path is not None else storage_service_module.DEFAULT_DB_PATH
        target = _sandbox_target(requested, sandbox)
        if target is not None:
            _live_db_offenders.add(nodeid)
            db_path = target
        real_storage_init(self, db_path)

    def _holiday_init(self, db_path=None):
        requested = db_path if db_path is not None else _DATA_DIR / "holidays.db"
        target = _sandbox_target(requested, sandbox)
        if target is not None:
            _live_db_offenders.add(nodeid)
            db_path = str(target)
        real_holiday_init(self, db_path)

    monkeypatch.setattr(
        storage_service_module.StorageService, "__init__", _storage_init
    )
    monkeypatch.setattr(
        holiday_storage_module.HolidayStorage, "__init__", _holiday_init
    )
    yield


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


def _report_live_db_redirects(session) -> None:
    """가드가 몇 번, 어떤 테스트에서 발동했는지 세션 끝에 알린다.

    리다이렉트는 사고를 **막지만** 원인을 고치지는 않는다. 조용히 넘어가면
    "격리 없이 라이브 경로를 여는 테스트"가 계속 늘어나고, 워크트리 밖에서
    돌릴 때만 가드에 의존하게 된다. 이름을 찍어 두면 점진적으로 고칠 수 있다.
    """
    if not _live_db_offenders:
        return
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    names = sorted(_live_db_offenders)
    shown = names[:15]
    lines = [
        "",
        "=" * 70,
        f"LIVE-DB GUARD: {len(names)}개 테스트가 라이브 DB 경로를 열려고 했고,",
        "모두 tmp 샌드박스로 돌렸다(라이브 파일은 안전하다).",
        "",
        "이 테스트들은 `isolated_storage_service` 픽스처를 쓰도록 고치는 것이",
        "근본 해결이다 -- 가드는 그물이지 설계가 아니다:",
        "",
    ]
    lines += [f"  - {n}" for n in shown]
    if len(names) > len(shown):
        lines.append(f"  ... 외 {len(names) - len(shown)}개")
    lines.append("=" * 70)
    message = "\n".join(lines)
    if terminal is not None:
        terminal.write_line(message, yellow=True, bold=True)
    else:
        print(message)


def pytest_sessionfinish(session, exitstatus):  # noqa: D103 - pytest hook
    _report_live_db_redirects(session)
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
