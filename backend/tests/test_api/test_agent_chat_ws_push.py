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
# R3: coordinator execution must pass the shared autonomy gate
# -------------------------------------------


async def test_coordinator_execution_gated(monkeypatch):
    """The watch-list auto path executed with NO gate before R3 — every
    execution now needs the shared autonomy gate's approval."""
    from services.autonomy import GateDecision
    import services.agent_chat.coordinator as cm

    coord = ChatCoordinator()
    executed = []

    async def record_execute(ticker, decision, session):
        executed.append(ticker)

    async def noop(*args, **kwargs):
        return None

    coord._execute_trade = record_execute
    coord._notify_decision = noop

    decision = TradeDecision(
        action=DecisionAction.BUY, confidence=0.9, consensus_level=0.9,
        rationale="테스트", quantity=10, entry_price=50_000,
    )
    session = ChatSession(ticker="005930", stock_name="테스트")

    # Gate denies → no execution
    async def deny_gate(market, **kwargs):
        return GateDecision(allowed=False, reason="AUTONOMY_ENABLED is off", check="master_gate")

    monkeypatch.setattr(cm, "check_autonomy", deny_gate)
    await coord._handle_decision("005930", decision, session)
    assert executed == []

    # Gate allows → existing execution path runs
    async def allow_gate(market, **kwargs):
        return GateDecision(allowed=True, reason="ok", check="all")

    monkeypatch.setattr(cm, "check_autonomy", allow_gate)
    await coord._handle_decision("005930", decision, session)
    assert executed == ["005930"]


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
# wait=True: the blocking contract PositionManager depends on
# -------------------------------------------


class DecidingFakeRoom(FakeRoom):
    async def start(self):
        self.session.decision = TradeDecision(
            action=DecisionAction.SELL,
            confidence=0.85,
            consensus_level=0.9,
            rationale="손절 근접",
        )
        self.session.status = SessionStatus.DECIDED
        return self.session


class FailingFakeRoom(FakeRoom):
    async def start(self):
        # Mirrors ChatRoom.start: sets CANCELLED, then re-raises.
        self.session.status = SessionStatus.CANCELLED
        raise RuntimeError("discussion blew up")


async def test_wait_true_blocks_until_decided(coordinator):
    """PositionManager awaits the completed session (old synchronous contract) —
    wait=True must return a DECIDED session with the decision populated."""
    import services.agent_chat.coordinator as cm
    cm.ChatRoom = DecidingFakeRoom

    session = await coordinator.start_manual_discussion("005930", "삼성전자", wait=True)

    assert session.status == SessionStatus.DECIDED
    assert session.decision is not None
    assert "005930" not in coordinator._active_rooms
    assert coordinator._session_history[-1] is session


async def test_wait_true_propagates_failure(coordinator):
    """Old contract: a failed discussion RAISES to the caller (PositionManager
    catches it and skips the discussion-budget increment)."""
    import services.agent_chat.coordinator as cm
    cm.ChatRoom = FailingFakeRoom

    with pytest.raises(RuntimeError):
        await coordinator.start_manual_discussion("005930", "삼성전자", wait=True)

    assert "005930" not in coordinator._active_rooms


async def test_position_manager_calls_with_wait(monkeypatch):
    """PositionManager._trigger_discussion must use wait=True — with the async
    default it would read session.decision before the debate even starts and
    _apply_decision would be dead code."""
    from services.agent_chat.position_manager import (
        MonitoredPosition,
        PositionEvent,
        PositionEventType,
        PositionManager,
    )

    calls = []

    class FakeCoordinator:
        async def start_manual_discussion(self, ticker, stock_name, wait=False):
            calls.append(wait)
            return ChatSession(ticker=ticker, stock_name=stock_name)

    pm = PositionManager()
    pm.set_chat_coordinator(FakeCoordinator())

    position = MonitoredPosition(
        ticker="005930", stock_name="삼성전자", quantity=10, avg_price=70000,
        current_price=66000, stop_loss=65000,
    )
    event = PositionEvent(
        ticker="005930",
        event_type=PositionEventType.STOP_LOSS_NEAR,
        current_price=66000,
        trigger_value=65000,
        message="손절가 근접",
    )

    await pm._trigger_discussion(event, position)

    assert calls == [True], "PositionManager must await the COMPLETED session"


async def test_failed_async_discussion_recorded_as_cancelled(coordinator):
    """A /discuss session id must never dangle: if the background run fails,
    the CANCELLED session still lands in history (REST detail keeps working)."""
    import services.agent_chat.coordinator as cm
    cm.ChatRoom = FailingFakeRoom

    session = await coordinator.start_manual_discussion("005930", "삼성전자")
    await _wait_until(lambda: "005930" not in coordinator._active_rooms)

    stored = coordinator.get_session_by_id(session.id)
    assert stored is not None, "failed session must remain queryable (was a 404 dangle)"
    assert stored.status == SessionStatus.CANCELLED


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


async def test_send_message_prunes_dead_connections():
    """A dead socket must be pruned and must not stop delivery to healthy ones
    (send_message is now the delivery path for every agent-chat frame)."""
    from app.api.routes.agent_chat import ConnectionManager

    class DeadWS:
        async def send_json(self, message):
            raise RuntimeError("socket closed")

    mgr = ConnectionManager()
    dead, healthy = DeadWS(), FakeWS()
    mgr.active_connections["s1"] = [dead, healthy]

    await mgr.send_message("s1", {"type": "message", "session_id": "s1"})

    assert healthy.sent == [{"type": "message", "session_id": "s1"}]
    assert dead not in mgr.active_connections.get("s1", []), "dead socket must be pruned"


async def test_ws_endpoint_sends_snapshot_on_connect(monkeypatch):
    """A client connecting mid-discussion (or just after the last frame) must
    receive an immediate status_change snapshot — otherwise the FE suppresses
    its poll while 'live' and stays stale forever."""
    import contextlib
    from fastapi import WebSocketDisconnect

    import app.api.routes.agent_chat as route_module

    session = ChatSession(ticker="005930", stock_name="삼성전자")
    session.status = SessionStatus.DISCUSSING

    class FakeCoordinator:
        def get_session_by_id(self, session_id):
            return session if session_id == session.id else None

    async def fake_get_coordinator():
        return FakeCoordinator()

    monkeypatch.setattr(route_module, "get_chat_coordinator", fake_get_coordinator)

    disconnect = object()

    class EndpointFakeWS(FakeWS):
        def __init__(self):
            super().__init__()
            self.accepted = False
            self._incoming: asyncio.Queue = asyncio.Queue()

        async def accept(self):
            self.accepted = True

        async def receive_text(self):
            item = await self._incoming.get()
            if item is disconnect:
                raise WebSocketDisconnect(code=1000)
            return item

    ws = EndpointFakeWS()
    task = asyncio.create_task(route_module.websocket_endpoint(ws, session.id))
    try:
        await _wait_until(lambda: len(ws.sent) >= 1)
        snapshot = ws.sent[0]
        assert snapshot["type"] == "status_change"
        assert snapshot["status"] == "discussing"
        assert snapshot["session"]["id"] == session.id
    finally:
        ws._incoming.put_nowait(disconnect)
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(task, timeout=2.0)
