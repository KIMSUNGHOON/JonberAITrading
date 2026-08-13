"""P4-4 (session-ssot Phase P4): agent-chat session-history read merge.

Store A 병합의 본체 2/2: `_session_history` (the coordinator's in-memory,
100-capped list) is retired. `ChatCoordinator.get_session_history` and
`get_session_by_id` now read through the two durable/live sources P4-2
(SM kind="discussion" mirroring) and P4-3 (agent_chat_decisions/
agent_chat_transcripts ledger) already write:

  - `get_session_history`: SM (running discussions + any terminal one still
    within SM's TTL/reload window) merged with the ledger (permanent,
    survives restart), deduped by id -- SM wins -- sorted ascending by
    start/created time and truncated to the most recent `limit` (the exact
    `[-limit:]` semantics the retired list had). Returns summary dicts, not
    ChatSession objects (see coordinator.py's `_summary_from_ledger_row`
    docstring for why).
  - `get_session_by_id`: three-tier fallback -- `_active_rooms` (live,
    exact object) -> SM's `chat_snapshot` -> the ledger's persisted
    transcript.
  - `count_total_sessions`: the ledger's row count (`/status`'s
    `total_sessions`, replacing the retired list's `len()`).

Both read paths are failure-harmless per source (an SM or ledger outage
degrades to whatever the other source has, never a raise -- routes never
500).

⚠️ Run ONLY this file (mirrors test_sm_registration.py's isolation contract
-- some sibling files touch real LLM/network paths and can hang):
    cd backend && python -m pytest tests/test_services/test_agent_chat/test_history_merge.py -v
"""

import asyncio
import json
import os
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager

from services.agent_chat.coordinator import ChatCoordinator
from services.agent_chat.decision_log import serialize_session
from services.agent_chat.models import (
    ChatSession,
    DecisionAction,
    MarketContext,
    SessionStatus,
    TradeDecision,
)
from services.storage_service import StorageService


TEST_SM_DB_PATH = "data/test_agent_chat_history_merge_sm.db"


# -------------------------------------------
# Fixtures
# -------------------------------------------


@pytest.fixture
async def sm(monkeypatch):
    """Fresh SessionManager on an isolated test db, installed as the process
    singleton -- same pattern as test_sm_registration.py's `sm` fixture.
    coordinator.py resolves the singleton via
    `services.session_manager.get_session_manager()`, so patching
    `sm_module._session_manager` here is what actually redirects it."""
    if os.path.exists(TEST_SM_DB_PATH):
        os.remove(TEST_SM_DB_PATH)
    monkeypatch.setattr(sm_module, "DB_PATH", TEST_SM_DB_PATH)
    manager = SessionManager()
    await manager.initialize()
    monkeypatch.setattr(sm_module, "_session_manager", manager)
    yield manager
    task = manager._flush_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    manager._sessions.clear()
    if os.path.exists(TEST_SM_DB_PATH):
        os.remove(TEST_SM_DB_PATH)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Isolated StorageService on a tmp-file db, wired in as
    services.agent_chat.coordinator's get_storage_service -- same pattern
    test_transcript_persistence.py uses for decision_log.get_storage_service."""
    svc = StorageService(db_path=str(tmp_path / "storage.db"))
    monkeypatch.setattr(
        "services.agent_chat.coordinator.get_storage_service",
        AsyncMock(return_value=svc),
    )
    return svc


@pytest.fixture
def coordinator():
    return ChatCoordinator()


# -------------------------------------------
# Helpers
# -------------------------------------------


def _context(ticker: str = "005930", stock_name: str = "삼성전자") -> MarketContext:
    return MarketContext(
        ticker=ticker, stock_name=stock_name, current_price=72500.0, price_change_pct=0.5
    )


def _session(
    ticker: str = "005930",
    stock_name: str = "삼성전자",
    status: SessionStatus = SessionStatus.DECIDED,
    started_at=None,
    decision: TradeDecision = None,
) -> ChatSession:
    session = ChatSession(ticker=ticker, stock_name=stock_name, context=_context(ticker, stock_name))
    session.status = status
    session.started_at = started_at
    session.consensus_level = 0.8
    if decision is not None:
        session.decision = decision
    return session


async def _put_sm_discussion(sm: SessionManager, session: ChatSession, sub_status: str = None) -> None:
    """Register a raw SM discussion row -- the same call
    `_register_sm_discussion` makes, without needing a ChatRoom double."""
    state = {"chat_snapshot": session.model_dump(mode="json")}
    if sub_status is not None:
        state["sub_status"] = sub_status
    await sm.create_session(
        session_id=session.id,
        market_type=MarketType.KIWOOM,
        ticker=session.ticker,
        display_name=session.stock_name,
        kind="discussion",
        stk_cd=session.ticker,
        stk_nm=session.stock_name,
        state=state,
    )


async def _put_ledger_row(storage: StorageService, session: ChatSession) -> None:
    """Write a ledger row through the real serializer -- the same shape
    decision_log.persist_session produces."""
    decision, votes = serialize_session(session)
    await storage.save_agent_chat_decision(decision, votes)


async def _put_ledger_row_at(storage: StorageService, session: ChatSession, created_at: str) -> None:
    """Same as `_put_ledger_row`, but with an explicit `created_at` (the
    column production code lets SQLite CURRENT_TIMESTAMP-stamp) so ordering
    tests can control it deterministically."""
    await storage.initialize()
    decision, _votes = serialize_session(session)
    async with aiosqlite.connect(str(storage.db_path)) as conn:
        await conn.execute(
            """
            INSERT INTO agent_chat_decisions
            (id, ticker, stock_name, trade_date, status, action, confidence,
             consensus_level, total_messages, total_rounds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision["id"], decision["ticker"], decision["stock_name"],
                decision["trade_date"], decision["status"], decision["action"],
                decision["confidence"], decision["consensus_level"],
                decision["total_messages"], decision["total_rounds"], created_at,
            ),
        )
        await conn.commit()


async def _put_transcript(storage: StorageService, session: ChatSession) -> None:
    await storage.save_agent_chat_transcript(
        session.id, json.dumps(session.model_dump(mode="json"), default=str)
    )


# -------------------------------------------
# ① 진행중(SM)+종료(원장) 병합 목록·시간 정렬·limit
# -------------------------------------------


class TestMergedHistoryOrderingAndLimit:
    @pytest.mark.asyncio
    async def test_running_and_completed_merge_sorted_and_limited(self, sm, storage, coordinator):
        session_a = _session(
            ticker="005930", stock_name="삼성전자", status=SessionStatus.DECIDED,
            decision=TradeDecision(
                action=DecisionAction.HOLD, confidence=0.5, consensus_level=0.6, rationale="r",
            ),
        )
        session_c = _session(
            ticker="000660", stock_name="SK하이닉스", status=SessionStatus.DECIDED,
            decision=TradeDecision(
                action=DecisionAction.BUY, confidence=0.9, consensus_level=0.85, rationale="r",
            ),
        )
        session_b = _session(
            ticker="035420", stock_name="NAVER", status=SessionStatus.VOTING,
            started_at=datetime.now(),
        )

        await _put_ledger_row_at(storage, session_a, "2026-07-10 09:00:00")
        await _put_ledger_row_at(storage, session_c, "2026-07-16 08:00:00")
        await _put_sm_discussion(sm, session_b, sub_status="voting")

        limited = await coordinator.get_session_history(limit=2)
        assert [h["id"] for h in limited] == [session_c.id, session_b.id]

        full = await coordinator.get_session_history(limit=10)
        assert [h["id"] for h in full] == [session_a.id, session_c.id, session_b.id]
        # SM-sourced entry carries live discussion fields the ledger alone
        # never would (no decision yet).
        b_entry = next(h for h in full if h["id"] == session_b.id)
        assert b_entry["status"] == "voting"
        assert b_entry["decision_action"] is None

    @pytest.mark.asyncio
    async def test_ticker_filter_applies_across_both_sources(self, sm, storage, coordinator):
        target = _session(
            ticker="005930", status=SessionStatus.DECIDED,
            decision=TradeDecision(action=DecisionAction.BUY, confidence=0.7, consensus_level=0.8, rationale="r"),
        )
        other_ledger = _session(
            ticker="000660", status=SessionStatus.DECIDED,
            decision=TradeDecision(action=DecisionAction.SELL, confidence=0.6, consensus_level=0.7, rationale="r"),
        )
        other_sm = _session(ticker="035420", status=SessionStatus.VOTING, started_at=datetime.now())

        await _put_ledger_row(storage, target)
        await _put_ledger_row(storage, other_ledger)
        await _put_sm_discussion(sm, other_sm)

        history = await coordinator.get_session_history(ticker="005930")

        assert [h["id"] for h in history] == [target.id]


# -------------------------------------------
# ② dedup: 동일 id 양쪽 존재 -> 1건, SM 우선
# -------------------------------------------


class TestDedupSmWins:
    @pytest.mark.asyncio
    async def test_same_id_in_sm_and_ledger_collapses_to_one_sm_wins(self, sm, storage, coordinator):
        shared_id = str(uuid.uuid4())

        sm_session = _session(status=SessionStatus.VOTING)
        sm_session.id = shared_id
        ledger_session = _session(
            status=SessionStatus.DECIDED,
            decision=TradeDecision(action=DecisionAction.BUY, confidence=0.8, consensus_level=0.9, rationale="r"),
        )
        ledger_session.id = shared_id

        await _put_sm_discussion(sm, sm_session, sub_status="voting")
        await _put_ledger_row(storage, ledger_session)

        history = await coordinator.get_session_history()

        matches = [h for h in history if h["id"] == shared_id]
        assert len(matches) == 1
        assert matches[0]["status"] == "voting"  # SM's value, not the ledger's "decided"
        assert matches[0]["decision_action"] is None  # SM snapshot has no decision yet


# -------------------------------------------
# state["sub_status"] precedence (brief requirement #4)
# -------------------------------------------


class TestSubStatusPrecedence:
    @pytest.mark.asyncio
    async def test_sub_status_preferred_over_embedded_snapshot_status(self, sm, storage, coordinator):
        session = _session(status=SessionStatus.DISCUSSING)
        await _put_sm_discussion(sm, session, sub_status="voting")  # deliberately diverges

        history = await coordinator.get_session_history()

        assert history[0]["status"] == "voting"

    @pytest.mark.asyncio
    async def test_sm_status_fallback_when_sub_status_missing(self, sm, storage, coordinator):
        """A row with no sub_status key (an SM row written before the mirror
        existed) falls back to the RUNNING -> 'discussing' vocabulary
        mapping instead of crashing or leaking a raw SM word."""
        session = _session(status=SessionStatus.DISCUSSING)
        await _put_sm_discussion(sm, session)  # no sub_status kwarg -> key absent

        history = await coordinator.get_session_history()

        assert history[0]["status"] == "discussing"


# -------------------------------------------
# ③ 레거시 원장 행 NULL -> 0 폴백 + 어휘
# -------------------------------------------


class TestLegacyLedgerRowNullSafety:
    @pytest.mark.asyncio
    async def test_preexisting_row_without_count_columns_zero_falls_back(self, storage, coordinator, sm):
        """A row written before P4-3's total_messages/total_rounds columns
        existed (NULL) must 0-fallback, and the ledger's own status
        vocabulary passes through unchanged (FE vocab unaffected)."""
        await storage.initialize()
        legacy_id = str(uuid.uuid4())
        async with aiosqlite.connect(str(storage.db_path)) as conn:
            await conn.execute(
                """
                INSERT INTO agent_chat_decisions
                (id, ticker, stock_name, trade_date, status, action)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (legacy_id, "005930", "삼성전자", "2026-07-01", "decided", "BUY"),
            )
            await conn.commit()

        history = await coordinator.get_session_history()

        assert len(history) == 1
        row = history[0]
        assert row["id"] == legacy_id
        assert row["status"] == "decided"
        assert row["total_messages"] == 0
        assert row["total_rounds"] == 0
        assert row["started_at"] is None


# -------------------------------------------
# ④ get_session_by_id 3계층 폴백
# -------------------------------------------


class TestGetSessionByIdThreeTiers:
    @pytest.mark.asyncio
    async def test_tier1_active_room_returns_exact_object(self, coordinator):
        live_session = _session(status=SessionStatus.DISCUSSING)
        coordinator._active_rooms[live_session.ticker] = SimpleNamespace(session=live_session)

        found = await coordinator.get_session_by_id(live_session.id)

        assert found is live_session

    @pytest.mark.asyncio
    async def test_tier2_sm_chat_snapshot_reconstructs_chat_session(self, sm, coordinator):
        session = _session(status=SessionStatus.VOTING)
        await _put_sm_discussion(sm, session)

        found = await coordinator.get_session_by_id(session.id)

        assert found is not None
        assert found == session  # full pydantic round-trip equality
        assert found.status == SessionStatus.VOTING

    @pytest.mark.asyncio
    async def test_tier3_ledger_transcript_reconstructs_chat_session(self, sm, storage, coordinator):
        session = _session(
            status=SessionStatus.DECIDED,
            decision=TradeDecision(action=DecisionAction.BUY, confidence=0.8, consensus_level=0.9, rationale="r"),
        )
        await _put_transcript(storage, session)

        found = await coordinator.get_session_by_id(session.id)

        assert found is not None
        assert found.id == session.id
        assert found.status == SessionStatus.DECIDED
        assert found.decision.action == DecisionAction.BUY

    @pytest.mark.asyncio
    async def test_not_found_anywhere_returns_none(self, sm, storage, coordinator):
        found = await coordinator.get_session_by_id("nonexistent-id")

        assert found is None


# -------------------------------------------
# ⑤ 재시작 시뮬(인메모리 비움, SM/원장만) -> 히스토리 비지 않음
# -------------------------------------------


class TestRestartSurvival:
    @pytest.mark.asyncio
    async def test_history_survives_restart_via_ledger_when_sm_has_nothing(self, sm, storage, coordinator):
        """SM freshly initialized with nothing registered simulates the
        post-restart state (only RUNNING/AWAITING_APPROVAL rows would ever
        survive a reload, and this discussion had already finished before
        the process died -- see services/session_manager.py's
        _load_active_sessions). The ledger alone must still populate
        history; a fresh ChatCoordinator() (no _active_rooms either) must
        still resolve the session by id."""
        assert await sm.get_all_sessions(kind="discussion") == {}  # sanity: genuinely empty

        session = _session(
            status=SessionStatus.DECIDED,
            decision=TradeDecision(action=DecisionAction.HOLD, confidence=0.6, consensus_level=0.7, rationale="r"),
        )
        await _put_ledger_row(storage, session)
        await _put_transcript(storage, session)

        history = await coordinator.get_session_history()
        assert len(history) == 1
        assert history[0]["id"] == session.id
        assert history[0]["decision_action"] == "HOLD"

        found = await coordinator.get_session_by_id(session.id)
        assert found is not None
        assert found.id == session.id


# -------------------------------------------
# ⑥ /status total_sessions = 원장 카운트
# -------------------------------------------


class TestTotalSessionsCount:
    @pytest.mark.asyncio
    async def test_count_total_sessions_matches_ledger_row_count(self, storage, coordinator):
        for _ in range(3):
            await _put_ledger_row(storage, _session())

        assert await storage.count_agent_chat_decisions() == 3
        assert await coordinator.count_total_sessions() == 3

    @pytest.mark.asyncio
    async def test_count_total_sessions_zero_when_empty(self, storage, coordinator):
        assert await coordinator.count_total_sessions() == 0


# -------------------------------------------
# ⑦ 조회 실패 폴백 무예외
# -------------------------------------------


class TestFailureHarmless:
    @pytest.mark.asyncio
    async def test_get_session_history_survives_total_outage(self, coordinator, monkeypatch):
        async def broken_sm():
            raise RuntimeError("sm down")

        async def broken_storage():
            raise RuntimeError("storage down")

        monkeypatch.setattr("services.agent_chat.coordinator.get_session_manager", broken_sm)
        monkeypatch.setattr("services.agent_chat.coordinator.get_storage_service", broken_storage)

        history = await coordinator.get_session_history()

        assert history == []

    @pytest.mark.asyncio
    async def test_get_session_by_id_survives_total_outage(self, coordinator, monkeypatch):
        async def broken_sm():
            raise RuntimeError("sm down")

        async def broken_storage():
            raise RuntimeError("storage down")

        monkeypatch.setattr("services.agent_chat.coordinator.get_session_manager", broken_sm)
        monkeypatch.setattr("services.agent_chat.coordinator.get_storage_service", broken_storage)

        found = await coordinator.get_session_by_id("whatever")

        assert found is None

    @pytest.mark.asyncio
    async def test_get_session_history_degrades_to_ledger_when_sm_down(self, storage, coordinator, monkeypatch):
        session = _session(
            status=SessionStatus.DECIDED,
            decision=TradeDecision(action=DecisionAction.BUY, confidence=0.7, consensus_level=0.8, rationale="r"),
        )
        await _put_ledger_row(storage, session)

        async def broken_sm():
            raise RuntimeError("sm down")

        monkeypatch.setattr("services.agent_chat.coordinator.get_session_manager", broken_sm)

        history = await coordinator.get_session_history()

        assert len(history) == 1
        assert history[0]["id"] == session.id

    @pytest.mark.asyncio
    async def test_get_session_history_degrades_to_sm_when_ledger_down(self, sm, coordinator, monkeypatch):
        session = _session(status=SessionStatus.VOTING)
        await _put_sm_discussion(sm, session)

        async def broken_storage():
            raise RuntimeError("storage down")

        monkeypatch.setattr("services.agent_chat.coordinator.get_storage_service", broken_storage)

        history = await coordinator.get_session_history()

        assert len(history) == 1
        assert history[0]["id"] == session.id

    @pytest.mark.asyncio
    async def test_count_total_sessions_survives_storage_outage(self, coordinator, monkeypatch):
        async def broken_storage():
            raise RuntimeError("storage down")

        monkeypatch.setattr("services.agent_chat.coordinator.get_storage_service", broken_storage)

        assert await coordinator.count_total_sessions() == 0
