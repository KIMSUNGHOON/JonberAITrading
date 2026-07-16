"""P4-2 (session-ssot Phase P4): ChatSession -> SessionManager (SM)
lifecycle registration.

Store A 병합의 본체 1/2: agent-chat 토론 세션(ChatSession)의 lifecycle을
services/session_manager.py's SessionManager(SM)에 기록하기 시작한다.

Additive by design -- this file verifies ONLY the new
`services.agent_chat.coordinator._register_sm_discussion` wiring (and its
two call sites, `_start_discussion` / `start_manual_discussion`). The
discussion's existing read path (`_session_history` / `_active_rooms`) and
its existing durable ledger (`decision_log.persist_session` ->
agent_chat_decisions) are completely untouched by P4-2 and are NOT
re-verified here (see test_coordinator.py / test_decision_log.py for that
coverage).

ChatRoom.start() runs 5 real (LLM-backed) discussion agents, so it is never
invoked here. Two lightweight ChatRoom doubles stand in instead:
  - `_FakeRoom`: exposes exactly the surface `_register_sm_discussion`
    touches (.session/.ticker/.stock_name/.on_message/.on_status_change)
    plus test-only `emit_message`/`emit_status` helpers that fire the
    captured callbacks directly -- used to unit-test the mirror wiring
    itself without any coordinator machinery.
  - `_ScriptedRoom`: mirrors ChatRoom's real constructor signature
    (ticker, stock_name, context, agent_weights) so it can be monkeypatched
    in as `coordinator.ChatRoom` itself; its `start()` fabricates a decided
    session synchronously instead of running real agents -- used to prove
    the wiring is actually reached from the two real coordinator call sites.

⚠️ Run ONLY this file (not the whole test_agent_chat dir -- some sibling
files touch real LLM/network paths and can hang):
    cd backend && python -m pytest tests/test_services/test_agent_chat/test_sm_registration.py -v
"""

import asyncio
import json
import os
from datetime import datetime
from unittest.mock import AsyncMock, patch

import aiosqlite
import numpy as np
import pytest

import services.session_manager as sm_module
from services.session_manager import (
    MarketType,
    SessionManager,
    SessionStatus as SmSessionStatus,
)

from services.agent_chat.coordinator import (
    ChatCoordinator,
    _register_sm_discussion,
)
from services.agent_chat.models import (
    AgentMessage,
    AgentType,
    AgentVote,
    ChatSession,
    DecisionAction,
    MarketContext,
    MessageType,
    SessionStatus,
    TradeDecision,
    VoteType,
)

from app.api.routes.kr_stocks.helpers import find_active_kr_session


TEST_DB_PATH = "data/test_agent_chat_sm_registration.db"


# -------------------------------------------
# Fixtures
# -------------------------------------------


@pytest.fixture
async def sm(monkeypatch):
    """Fresh SessionManager on an isolated test db, installed as the process
    singleton -- same pattern as test_api/test_analysis_dedup.py's `sm`
    fixture and test_services/test_session_kind.py's. coordinator.py's
    `_register_sm_discussion` resolves the singleton via
    `services.session_manager.get_session_manager()`, so patching
    `sm_module._session_manager` here is what actually redirects it."""
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    monkeypatch.setattr(sm_module, "DB_PATH", TEST_DB_PATH)
    manager = SessionManager()
    await manager.initialize()
    monkeypatch.setattr(sm_module, "_session_manager", manager)
    yield manager
    # Defensive flush-task cleanup (same as test_session_kind.py's `sm`) --
    # a debounced flush left pending past teardown leaks a task into a
    # closing event loop.
    task = manager._flush_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    manager._sessions.clear()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


class _FakeRoom:
    """Minimal ChatRoom double exposing exactly the surface
    `_register_sm_discussion` touches, plus test-only emit_* helpers that
    fire the callbacks it registered -- drives the mirror wiring without
    ever invoking the real (LLM-backed) ChatRoom.start()."""

    def __init__(self, session: ChatSession):
        self.session = session
        self.ticker = session.ticker
        self.stock_name = session.stock_name
        self._message_cbs = []
        self._status_cbs = []

    def on_message(self, cb) -> None:
        self._message_cbs.append(cb)

    def on_status_change(self, cb) -> None:
        self._status_cbs.append(cb)

    async def emit_message(self, message: AgentMessage) -> None:
        self.session.add_message(message)
        for cb in self._message_cbs:
            await cb(message)

    async def emit_status(self, status: SessionStatus) -> None:
        self.session.status = status
        for cb in self._status_cbs:
            await cb(status, self.session)


class _ScriptedRoom:
    """Stand-in for the real ChatRoom class in coordinator-level tests:
    mirrors ChatRoom's real constructor signature and on_message/
    on_status_change registration, but `start()` fabricates a HOLD-decided
    session synchronously (HOLD deliberately -- it skips
    ChatCoordinator._handle_decision's BUY/SELL/ADD/REDUCE execution branch,
    so no autonomy-gate/trading-coordinator mocking is needed here)."""

    def __init__(self, ticker, stock_name, context, agent_weights=None):
        self.ticker = ticker
        self.stock_name = stock_name
        self.session = ChatSession(ticker=ticker, stock_name=stock_name, context=context)
        self._message_cbs = []
        self._status_cbs = []

    def on_message(self, cb) -> None:
        self._message_cbs.append(cb)

    def on_status_change(self, cb) -> None:
        self._status_cbs.append(cb)

    async def start(self) -> ChatSession:
        decision = TradeDecision(
            action=DecisionAction.HOLD,
            confidence=0.6,
            consensus_level=0.8,
            rationale="관망",
        )
        self.session.finalize(decision)  # sets status = DECIDED
        for cb in self._status_cbs:
            await cb(SessionStatus.DECIDED, self.session)
        return self.session


def _context(ticker: str = "005930", stock_name: str = "삼성전자") -> MarketContext:
    return MarketContext(
        ticker=ticker,
        stock_name=stock_name,
        current_price=72500.0,
        price_change_pct=0.5,
    )


def _session(ticker: str = "005930", stock_name: str = "삼성전자") -> ChatSession:
    return ChatSession(ticker=ticker, stock_name=stock_name, context=_context(ticker, stock_name))


# -------------------------------------------
# 1) 토론 시작 -> SM에 kind=discussion RUNNING 행 + sub_status 전이
# -------------------------------------------


class TestRegistrationAndSubStatusTransitions:
    @pytest.mark.asyncio
    async def test_register_creates_discussion_kind_running_row(self, sm):
        session = _session()
        room = _FakeRoom(session)

        await _register_sm_discussion(room)

        fetched = await sm.get_session(session.id)
        assert fetched is not None
        assert fetched.kind == "discussion"
        assert fetched.status == SmSessionStatus.RUNNING
        assert fetched.market_type == MarketType.KIWOOM
        assert fetched.ticker == "005930"
        assert fetched.stk_cd == "005930"
        assert fetched.stk_nm == "삼성전자"
        assert fetched.state["sub_status"] == "initializing"
        assert fetched.state["chat_snapshot"]["id"] == session.id

    @pytest.mark.asyncio
    async def test_status_change_updates_sub_status_stays_running(self, sm):
        session = _session()
        room = _FakeRoom(session)
        await _register_sm_discussion(room)

        for status in (SessionStatus.ANALYZING, SessionStatus.DISCUSSING, SessionStatus.VOTING):
            await room.emit_status(status)
            fetched = await sm.get_session(session.id)
            assert fetched.status == SmSessionStatus.RUNNING
            assert fetched.state["sub_status"] == status.value

    @pytest.mark.asyncio
    async def test_message_event_refreshes_chat_snapshot(self, sm):
        session = _session()
        room = _FakeRoom(session)
        await _register_sm_discussion(room)

        msg = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술 분석가",
            message_type=MessageType.ANALYSIS,
            content="상승 추세",
            confidence=0.7,
        )
        await room.emit_message(msg)

        fetched = await sm.get_session(session.id)
        snapshot_messages = fetched.state["chat_snapshot"]["all_messages"]
        assert len(snapshot_messages) == 1
        assert snapshot_messages[0]["content"] == "상승 추세"


# -------------------------------------------
# 2) 종료: DECIDED -> COMPLETED / 취소·타임아웃 -> CANCELLED
# -------------------------------------------


class TestTerminalStatusMapping:
    @pytest.mark.asyncio
    async def test_decided_maps_to_completed(self, sm):
        session = _session()
        room = _FakeRoom(session)
        await _register_sm_discussion(room)

        decision = TradeDecision(
            action=DecisionAction.BUY,
            confidence=0.8,
            consensus_level=0.9,
            rationale="합의",
            entry_price=72500.0,
        )
        session.finalize(decision)
        await room.emit_status(SessionStatus.DECIDED)

        fetched = await sm.get_session(session.id)
        assert fetched.status == SmSessionStatus.COMPLETED
        assert fetched.state["sub_status"] == "decided"
        assert fetched.state["chat_snapshot"]["decision"]["action"] == "BUY"

    @pytest.mark.asyncio
    async def test_cancelled_maps_to_cancelled(self, sm):
        session = _session()
        room = _FakeRoom(session)
        await _register_sm_discussion(room)

        await room.emit_status(SessionStatus.CANCELLED)

        fetched = await sm.get_session(session.id)
        assert fetched.status == SmSessionStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_timeout_maps_to_cancelled(self, sm):
        session = _session()
        room = _FakeRoom(session)
        await _register_sm_discussion(room)

        await room.emit_status(SessionStatus.TIMEOUT)

        fetched = await sm.get_session(session.id)
        assert fetched.status == SmSessionStatus.CANCELLED


# -------------------------------------------
# 3) 왕복 lossless: ChatSession.model_dump(mode="json") 직렬화 경계
# -------------------------------------------


class TestChatSnapshotRoundTrip:
    """The brief's serialization-boundary requirement: state must only ever
    receive `ChatSession.model_dump(mode='json')`'s own output. Proven with
    a fixture close to what a real discussion actually produces --
    MarketContext.indicators holding a numpy float64 the way a pandas
    rolling-window computation naturally would (np.float64 subclasses
    Python float, so it's the one numpy scalar type that survives
    model_dump(mode='json') -- np.int64/np.float32 do NOT and raise
    PydanticSerializationError; the real kr_market_data.py boundary already
    coerces everything to plain int/float before it reaches MarketContext,
    so a raw numpy int never actually reaches this path in production),
    AgentMessage.data as a nested dict, and multiple datetime fields
    throughout."""

    @pytest.mark.asyncio
    async def test_chat_snapshot_round_trips_losslessly(self, sm):
        context = MarketContext(
            ticker="005930",
            stock_name="삼성전자",
            current_price=72500.0,
            price_change_pct=0.5,
            chart_data=[
                {"date": "2026-07-16", "open": 72000, "high": 73000,
                 "low": 71500, "close": 72500, "volume": 1_000_000},
            ],
            indicators={
                "rsi": np.float64(55.3),
                "sma_20": 71800.0,
                "trend": "bullish",
                "macd": {"line": np.float64(120.5), "signal": 110.2},
            },
            per=12.5, pbr=1.3, eps=5000.0,
            has_position=True, position_quantity=10, position_avg_price=70000.0,
            available_cash=1_000_000.0, total_portfolio_value=5_000_000.0,
        )
        session = ChatSession(
            ticker="005930", stock_name="삼성전자", context=context,
            started_at=datetime.now(),
        )
        session.start_round("voting")
        vote_msg = AgentMessage(
            agent_type=AgentType.TECHNICAL, agent_name="기술 분석가",
            message_type=MessageType.VOTE, content="투표: buy",
            confidence=0.8, data={"vote": "buy", "score": np.float64(0.82)},
        )
        session.add_message(vote_msg)
        session.add_vote(AgentVote(
            agent_type=AgentType.TECHNICAL, vote=VoteType.BUY, confidence=0.8,
            reasoning="호재", key_factors=["a", "b"],
        ))
        session.end_round()
        session.finalize(TradeDecision(
            action=DecisionAction.BUY, confidence=0.8, consensus_level=0.9,
            quantity=10, entry_price=72500.0, stop_loss=70000.0,
            take_profit=76000.0, rationale="r", votes={"technical": "buy"},
        ))

        room = _FakeRoom(session)
        await _register_sm_discussion(room)  # create_session flushes synchronously

        # (a) pure pydantic-level assertion, exactly as the brief specifies.
        dump = session.model_dump(mode="json")
        round_tripped = ChatSession.model_validate(json.loads(json.dumps(dump)))
        assert round_tripped == session

        # (b) the SAME dump, read back through SM's actual SQLite layer
        # (_save_session's `json.dumps(state, default=str)`) -- confirms the
        # serialization boundary really is JSON-native end to end: the
        # `default=str` fallback never fires because there was never a
        # non-JSON-native value left in `state` by the time it got there.
        async with aiosqlite.connect(TEST_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT state_json FROM analysis_sessions WHERE session_id = ?",
                (session.id,),
            ) as cursor:
                row = await cursor.fetchone()
        persisted_state = json.loads(row["state_json"])
        persisted_snapshot = ChatSession.model_validate(persisted_state["chat_snapshot"])
        assert persisted_snapshot == session


# -------------------------------------------
# 4) 실패-무해: SM 쓰기 실패가 토론을 죽이지 않는다
# -------------------------------------------


class TestSmFailureIsHarmless:
    @pytest.mark.asyncio
    async def test_events_after_failed_create_are_harmlessly_swallowed(self, sm, monkeypatch):
        """create_session failing must not prevent later message/
        status_change events from safely no-op'ing -- P2-1's fail-loud
        KeyError on an untracked session_id must be swallowed by the mirror
        callbacks, not propagated up through ChatRoom's emit machinery."""
        session = _session()
        room = _FakeRoom(session)

        async def _broken_create_session(*a, **kw):
            raise RuntimeError("create failed")

        monkeypatch.setattr(sm, "create_session", _broken_create_session)

        await _register_sm_discussion(room)  # registration itself must not raise

        # Subsequent events must not raise either.
        await room.emit_status(SessionStatus.ANALYZING)
        await room.emit_message(AgentMessage(
            agent_type=AgentType.TECHNICAL, agent_name="기술 분석가",
            message_type=MessageType.ANALYSIS, content="상승", confidence=0.6,
        ))
        await room.emit_status(SessionStatus.DECIDED)

        # And the session genuinely never got tracked by SM.
        assert await sm.get_session(session.id) is None

    @pytest.mark.asyncio
    async def test_manual_wait_discussion_completes_and_persists_when_sm_unavailable(
        self, monkeypatch
    ):
        """SM being entirely unreachable (get_session_manager itself fails)
        must not stop a manual wait=True discussion from completing, and
        the durable ledger (decision_log.persist_session) must still run --
        SM is an additive mirror, never a dependency of the existing path."""
        coordinator = ChatCoordinator()
        persisted = []

        async def _fake_persist(session):
            persisted.append(session)

        async def _broken_get_session_manager():
            raise RuntimeError("sm unavailable")

        monkeypatch.setattr("services.agent_chat.coordinator.ChatRoom", _ScriptedRoom)
        monkeypatch.setattr("services.agent_chat.coordinator.persist_session", _fake_persist)
        monkeypatch.setattr(
            "services.agent_chat.coordinator.get_session_manager",
            _broken_get_session_manager,
        )

        with (
            patch.object(coordinator, "_fetch_market_context", AsyncMock(return_value=_context())),
            patch.object(coordinator, "_compute_agent_weights", AsyncMock(return_value=None)),
        ):
            session = await coordinator.start_manual_discussion(
                ticker="005930", stock_name="삼성전자", wait=True,
            )

        assert session.status == SessionStatus.DECIDED
        assert len(persisted) == 1
        assert persisted[0] is session
        assert "005930" not in coordinator._active_rooms


# -------------------------------------------
# 5) 분석 표면 비오염: find_active_kr_session이 진행 중 토론을 무시(P4-1 필터)
# -------------------------------------------


class TestAnalysisSurfaceNotPolluted:
    @pytest.mark.asyncio
    async def test_find_active_kr_session_ignores_running_discussion(self, sm):
        session = _session(ticker="005930")
        room = _FakeRoom(session)

        await _register_sm_discussion(room)  # RUNNING, kind="discussion"

        active = await find_active_kr_session("005930")

        assert active is None


# -------------------------------------------
# 6) 실제 코디네이터 호출부 배선 확인 (choke-point 자체가 아니라 그 사용처)
# -------------------------------------------


class TestCoordinatorCallSitesRegisterWithSm:
    """Proves `_register_sm_discussion` is actually wired at BOTH real
    room-construction choke points in coordinator.py -- `_start_discussion`
    (auto watch-list path) and `start_manual_discussion` (covers wait=True
    inline AND the wait=False background task, since both branch from the
    exact same construction point) -- not merely callable in isolation."""

    @pytest.mark.asyncio
    async def test_start_discussion_auto_path_registers_with_sm(self, sm, monkeypatch):
        coordinator = ChatCoordinator()
        monkeypatch.setattr("services.agent_chat.coordinator.ChatRoom", _ScriptedRoom)
        monkeypatch.setattr("services.agent_chat.coordinator.persist_session", AsyncMock())

        with (
            patch.object(coordinator, "_fetch_market_context", AsyncMock(return_value=_context())),
            patch.object(coordinator, "_compute_agent_weights", AsyncMock(return_value=None)),
        ):
            before = asyncio.all_tasks()
            await coordinator._start_discussion({"ticker": "005930", "stock_name": "삼성전자"})
            new_tasks = asyncio.all_tasks() - before
            assert len(new_tasks) == 1
            await asyncio.wait_for(next(iter(new_tasks)), timeout=5)

        sessions = await sm.get_all_sessions(kind="discussion")
        assert len(sessions) == 1
        session = next(iter(sessions.values()))
        assert session.stk_cd == "005930"
        assert session.status == SmSessionStatus.COMPLETED  # _ScriptedRoom.start() decides HOLD

    @pytest.mark.asyncio
    async def test_start_manual_discussion_wait_true_registers_with_sm(self, sm, monkeypatch):
        coordinator = ChatCoordinator()
        monkeypatch.setattr("services.agent_chat.coordinator.ChatRoom", _ScriptedRoom)
        monkeypatch.setattr("services.agent_chat.coordinator.persist_session", AsyncMock())

        with (
            patch.object(coordinator, "_fetch_market_context", AsyncMock(return_value=_context())),
            patch.object(coordinator, "_compute_agent_weights", AsyncMock(return_value=None)),
        ):
            session = await coordinator.start_manual_discussion(
                ticker="005930", stock_name="삼성전자", wait=True,
            )

        assert session.status == SessionStatus.DECIDED
        fetched = await sm.get_session(session.id)
        assert fetched is not None
        assert fetched.kind == "discussion"
        assert fetched.status == SmSessionStatus.COMPLETED
