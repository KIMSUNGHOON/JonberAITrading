"""P7 Phase 3: revive the agent-chat WebSocket.

Prior state (verified by exploration): the WS endpoint, ConnectionManager, and
ChatRoom callback system all existed but were never wired together — no producer
pushed a single frame — and /discuss ran the whole discussion SYNCHRONOUSLY, so
by the time the FE had a session_id there was nothing live to stream.

The fix: (a) start_manual_discussion launches the discussion as a background
task and returns the session immediately (⚠️ WITHOUT the auto path's
_handle_decision — manual discussions stay advisory-only, live trading FROZEN);
(b) a room-created hook lets the route layer wire ChatRoom's on_message /
on_status_change callbacks to the WS ConnectionManager, emitting the exact
frame shapes the existing FE hook (useAgentChatWebSocket) already expects:
'message' (+ derived 'vote' on VOTE messages) and 'status_change' (+ derived
'decision' when DECIDED).
"""

import asyncio

import pytest

import services.agent_chat.coordinator as coordinator_module
from services.agent_chat.coordinator import ChatCoordinator
from services.agent_chat.models import (
    AgentMessage,
    AgentType,
    AgentVote,
    ChatSession,
    DecisionAction,
    MessageType,
    SessionStatus,
    TradeDecision,
    VoteType,
)


class FakeRoom:
    """Stand-in for ChatRoom: real ChatSession + the same callback surface."""

    instances: list = []

    def __init__(self, ticker: str, stock_name: str, context=None):
        self.ticker = ticker
        self.stock_name = stock_name
        self.session = ChatSession(ticker=ticker, stock_name=stock_name)
        self._message_callbacks = []
        self._status_callbacks = []
        self.release = asyncio.Event()
        self.release.set()  # default: complete immediately
        FakeRoom.instances.append(self)

    def on_message(self, callback):
        self._message_callbacks.append(callback)

    def on_status_change(self, callback):
        self._status_callbacks.append(callback)

    async def start(self):
        await self.release.wait()
        self.session.status = SessionStatus.DECIDED
        return self.session

    async def emit_message(self, message):
        for cb in self._message_callbacks:
            await cb(message)

    async def emit_status(self, status):
        for cb in self._status_callbacks:
            await cb(status, self.session)


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, message: dict):
        self.sent.append(message)


@pytest.fixture
def coordinator(monkeypatch):
    coord = ChatCoordinator()

    async def fake_ctx(ticker, stock_name):
        return None

    monkeypatch.setattr(coord, "_fetch_market_context", fake_ctx)
    monkeypatch.setattr(coordinator_module, "ChatRoom", FakeRoom)
    FakeRoom.instances.clear()
    return coord


@pytest.fixture
def hook_registry():
    """Snapshot/restore the module-level room-created hook registry."""
    hooks = getattr(coordinator_module, "_room_created_hooks", None)
    saved = list(hooks) if hooks is not None else None
    yield
    if saved is not None:
        coordinator_module._room_created_hooks[:] = saved


async def _wait_until(predicate, timeout: float = 2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


# -------------------------------------------
# /discuss must be non-blocking (a live window must exist for the WS)
# -------------------------------------------


async def test_manual_discussion_returns_before_completion(coordinator):
    room_gate = asyncio.Event()

    class SlowFakeRoom(FakeRoom):
        def __init__(self, ticker, stock_name, context=None):
            super().__init__(ticker, stock_name, context)
            self.release = room_gate  # don't finish until the test says so

    import services.agent_chat.coordinator as cm
    cm.ChatRoom = SlowFakeRoom

    # Must return while the discussion is still running — the old code awaited
    # room.start() here and would block until room_gate is set.
    session = await asyncio.wait_for(
        coordinator.start_manual_discussion("005930", "삼성전자"), timeout=1.0
    )

    assert session.status != SessionStatus.DECIDED
    assert "005930" in coordinator._active_rooms, "room must be visible as active"

    room_gate.set()
    await _wait_until(lambda: "005930" not in coordinator._active_rooms)
    assert coordinator._session_history and coordinator._session_history[-1] is session


async def test_manual_discussion_never_executes_decision(coordinator):
    """SAFETY pin: the manual path must never call _handle_decision (that is the
    watch-list auto path's job) — parity with the old synchronous behavior."""
    executed = []

    async def record_decision(ticker, decision):
        executed.append((ticker, decision))

    coordinator._handle_decision = record_decision

    class DecidingFakeRoom(FakeRoom):
        async def start(self):
            self.session.decision = TradeDecision(
                action=DecisionAction.BUY,
                confidence=0.9,
                consensus_level=0.9,
                rationale="테스트",
            )
            self.session.status = SessionStatus.DECIDED
            return self.session

    import services.agent_chat.coordinator as cm
    cm.ChatRoom = DecidingFakeRoom

    await coordinator.start_manual_discussion("005930", "삼성전자")
    await _wait_until(lambda: "005930" not in coordinator._active_rooms)

    assert executed == [], "manual discussions are advisory-only (live trading FROZEN)"


# -------------------------------------------
# Room-created hook: the route layer's wiring point
# -------------------------------------------


async def test_room_created_hook_fires_on_manual_start(coordinator, hook_registry):
    from services.agent_chat.coordinator import register_room_created_hook

    seen = []
    register_room_created_hook(seen.append)

    await coordinator.start_manual_discussion("005930", "삼성전자")
    await _wait_until(lambda: "005930" not in coordinator._active_rooms)

    assert len(seen) == 1
    assert seen[0] is FakeRoom.instances[-1]


# -------------------------------------------
# WS forwarding: ChatRoom callbacks → ConnectionManager frames
# -------------------------------------------


async def test_wire_room_forwards_message_vote_status_decision_frames():
    from app.api.routes.agent_chat import _wire_room_to_websocket, manager

    room = FakeRoom("005930", "삼성전자")
    session_id = room.session.id
    ws = FakeWS()
    manager.active_connections[session_id] = [ws]
    try:
        _wire_room_to_websocket(room)

        # 1. Plain analysis message → 'message' frame only
        msg = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술 분석가",
            message_type=MessageType.ANALYSIS,
            content="RSI 과매도",
            confidence=0.8,
        )
        room.session.add_message(msg)
        await room.emit_message(msg)

        assert [f["type"] for f in ws.sent] == ["message"]
        assert ws.sent[0]["session_id"] == session_id
        assert ws.sent[0]["message"]["content"] == "RSI 과매도"
        assert ws.sent[0]["message"]["message_type"] == "analysis"

        # 2. VOTE message → 'message' frame + derived 'vote' frame
        room.session.add_vote(
            AgentVote(
                agent_type=AgentType.TECHNICAL,
                vote=VoteType.BUY,
                confidence=0.8,
                reasoning="추세 상방",
            )
        )
        vote_msg = AgentMessage(
            agent_type=AgentType.TECHNICAL,
            agent_name="기술 분석가",
            message_type=MessageType.VOTE,
            content="투표: buy",
            confidence=0.8,
        )
        room.session.add_message(vote_msg)
        await room.emit_message(vote_msg)

        assert [f["type"] for f in ws.sent] == ["message", "message", "vote"]
        vote_frame = ws.sent[-1]
        assert vote_frame["vote"]["vote"] == "buy"
        assert vote_frame["vote"]["agent_type"] == "technical"
        assert "weight" in vote_frame["vote"] and "weighted_score" in vote_frame["vote"]

        # 3. Status change → 'status_change' frame with full session detail
        room.session.status = SessionStatus.DISCUSSING
        await room.emit_status(SessionStatus.DISCUSSING)
        status_frame = ws.sent[-1]
        assert status_frame["type"] == "status_change"
        assert status_frame["status"] == "discussing"
        assert status_frame["session"]["id"] == session_id
        assert status_frame["session"]["ticker"] == "005930"

        # 4. DECIDED with a decision → 'status_change' + derived 'decision' frame
        room.session.decision = TradeDecision(
            action=DecisionAction.HOLD,
            confidence=0.7,
            consensus_level=0.8,
            rationale="관망",
        )
        room.session.status = SessionStatus.DECIDED
        await room.emit_status(SessionStatus.DECIDED)

        assert [f["type"] for f in ws.sent[-2:]] == ["status_change", "decision"]
        decision_frame = ws.sent[-1]
        assert decision_frame["decision"]["action"] == "HOLD"
        assert decision_frame["decision"]["rationale"] == "관망"
    finally:
        manager.active_connections.pop(session_id, None)


async def test_route_module_registers_the_ws_wiring_hook(hook_registry):
    """Importing the routes must leave the WS forwarder registered so every new
    room (auto AND manual) gets wired."""
    import app.api.routes.agent_chat as route_module

    hooks = coordinator_module._room_created_hooks
    assert route_module._wire_room_to_websocket in hooks
