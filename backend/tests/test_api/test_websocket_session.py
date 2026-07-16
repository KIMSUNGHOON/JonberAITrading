"""P7 Phase 1: /ws/session/{id} push-first rewrite.

The session WebSocket must PREFER SessionManager pub/sub notifications (instant
push) and keep the legacy 0.3s dict-poll only as a per-session fallback. Reads
stay on the legacy dicts (source of truth for the un-migrated producers) with a
SessionManager fallback for sm-only sessions. Position frames are de-duplicated
via a cursor instead of being re-sent every poll cycle.

Headless: a fake WebSocket + a real SessionManager on a test SQLite db. The
endpoint coroutine is invoked directly (same pattern as the P6/P7 ledger notes:
"fake WebSocket + stubbed graph").
"""

import asyncio
import contextlib
import os

import pytest
from fastapi import WebSocketDisconnect

import services.session_manager as sm_module
from services.session_manager import MarketType, SessionManager, SessionStatus

import app.api.routes.websocket as ws_module
from app.api.routes.websocket import websocket_session

TEST_DB_PATH = "data/test_ws_push_sessions.db"

_DISCONNECT = object()


class FakeWebSocket:
    """Minimal stand-in for starlette's WebSocket used by websocket_session."""

    def __init__(self):
        self.sent: list[dict] = []
        self.sent_text: list[str] = []
        self.accepted = False
        self.closed_code: int | None = None
        self._incoming: asyncio.Queue = asyncio.Queue()

    async def accept(self):
        self.accepted = True

    async def send_json(self, message: dict):
        self.sent.append(message)

    async def send_text(self, text: str):
        self.sent_text.append(text)

    async def close(self, code: int = 1000):
        self.closed_code = code

    async def receive_text(self) -> str:
        item = await self._incoming.get()
        if item is _DISCONNECT:
            raise WebSocketDisconnect(code=1000)
        return item

    def client_send(self, text: str):
        self._incoming.put_nowait(text)

    def client_disconnect(self):
        self._incoming.put_nowait(_DISCONNECT)


async def wait_for_frame(ws: FakeWebSocket, predicate, timeout: float = 1.0) -> dict:
    """Poll the fake socket's outbox until a frame matches (or fail loudly)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        for frame in ws.sent:
            if predicate(frame):
                return frame
        await asyncio.sleep(0.02)
    raise AssertionError(f"expected frame not received within {timeout}s; sent={ws.sent}")


@contextlib.asynccontextmanager
async def running_ws(ws: FakeWebSocket, session_id: str):
    """Run the endpoint as a task; always tear it down."""
    task = asyncio.create_task(websocket_session(ws, session_id))
    try:
        yield task
    finally:
        if not task.done():
            ws.client_disconnect()
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except (asyncio.TimeoutError, Exception):
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task


@pytest.fixture
async def sm(monkeypatch):
    """Fresh SessionManager on a test db, installed as the process singleton."""
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    monkeypatch.setattr(sm_module, "DB_PATH", TEST_DB_PATH)
    manager = SessionManager()
    await manager.initialize()
    monkeypatch.setattr(sm_module, "_session_manager", manager)
    yield manager
    manager._sessions.clear()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture
def kr_sessions():
    """Isolated view of the legacy KR session dict."""
    from app.api.routes.kr_stocks.constants import kr_stock_sessions

    saved = dict(kr_stock_sessions)
    kr_stock_sessions.clear()
    yield kr_stock_sessions
    kr_stock_sessions.clear()
    kr_stock_sessions.update(saved)


@pytest.fixture
def fast_linger(monkeypatch):
    """Don't linger 2s after the complete frame in tests."""
    monkeypatch.setattr(ws_module, "COMPLETE_LINGER_SECONDS", 0.0)


@pytest.fixture
def slow_polls(monkeypatch):
    """Make the safety poll so slow that only push can deliver in time."""
    monkeypatch.setattr(ws_module, "SAFETY_POLL_SECONDS", 30.0)


@pytest.fixture
def fast_poll(monkeypatch):
    """Speed the safety poll up for tests that exercise poll-fallback mechanics
    (sessions without sm pub/sub, e.g. after a failed sm registration)."""
    monkeypatch.setattr(ws_module, "SAFETY_POLL_SECONDS", 0.1)


def _kr_state(**state_extra) -> dict:
    """Build the `state` sub-dict for a KR-shaped SM session (P1-2: these
    tests used to seed a legacy dict directly; now that legacy dicts are out
    of the read path under SESSION_SSOT_READS=True, they seed the SM session
    instead -- the state *shape* is unchanged, only where it lives)."""
    state = {"reasoning_log": [], "current_stage": "data_collection"}
    state.update(state_extra)
    return state


# -------------------------------------------
# Poll fallback (direct SM state writes, no notify) — existing contract
# preserved. P1-2: legacy dicts are out of the read path under
# SESSION_SSOT_READS=True, so what used to be "seed the legacy dict"
# (the old un-migrated-producer stand-in) is now "mutate the live SM
# session object without going through update_state()/update_status()",
# which is the only way left to simulate a write with no pub/sub notify.
# -------------------------------------------


async def test_sm_session_streams_reasoning_status_complete_via_poll(sm, kr_sessions, fast_linger, fast_poll):
    await sm.create_session(
        "legacy-1", MarketType.KIWOOM, "005930", "삼성전자",
        stk_cd="005930", stk_nm="삼성전자",
        state=_kr_state(reasoning_log=["[t] 시작", "[t] 기술 분석"]),
    )
    session = sm._sessions["legacy-1"]

    ws = FakeWebSocket()
    async with running_ws(ws, "legacy-1") as task:
        await wait_for_frame(ws, lambda f: f.get("type") == "reasoning" and f.get("data") == "[t] 기술 분석")
        status = await wait_for_frame(ws, lambda f: f.get("type") == "status")
        assert status["data"]["status"] == "running"

        # Un-notified write: mutate the live session object directly.
        session.state["reasoning_log"] = session.state["reasoning_log"] + ["[t] 종합"]
        await wait_for_frame(ws, lambda f: f.get("type") == "reasoning" and f.get("data") == "[t] 종합")

        session.status = SessionStatus.COMPLETED
        complete = await wait_for_frame(ws, lambda f: f.get("type") == "complete", timeout=4.0)
        assert complete["data"]["status"] == "completed"
        await asyncio.wait_for(task, timeout=4.0)

    reasoning_frames = [f for f in ws.sent if f.get("type") == "reasoning"]
    assert [f["data"] for f in reasoning_frames] == ["[t] 시작", "[t] 기술 분석", "[t] 종합"]


async def test_sm_ping_pong_and_on_demand_status(sm, kr_sessions, fast_linger, fast_poll):
    await sm.create_session(
        "legacy-2", MarketType.KIWOOM, "005930", "삼성전자",
        stk_cd="005930", stk_nm="삼성전자", state=_kr_state(),
    )

    ws = FakeWebSocket()
    async with running_ws(ws, "legacy-2"):
        await wait_for_frame(ws, lambda f: f.get("type") == "status")
        ws.client_send("ping")
        deadline = asyncio.get_running_loop().time() + 2.0
        while "pong" not in ws.sent_text and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
        assert "pong" in ws.sent_text

        # On-demand "status" command: a status frame with session_id nested in
        # data (distinct shape from change-driven status frames).
        ws.client_send("status")
        on_demand = await wait_for_frame(
            ws,
            lambda f: f.get("type") == "status" and f.get("data", {}).get("session_id") == "legacy-2",
            timeout=2.0,
        )
        assert on_demand["data"]["status"] == "running"
        assert on_demand["data"]["stage"] == "data_collection"
        assert on_demand["data"]["awaiting_approval"] is False


async def test_sm_proposal_sent_once(sm, kr_sessions, fast_linger, fast_poll):
    await sm.create_session(
        "legacy-3", MarketType.KIWOOM, "005930", "삼성전자",
        stk_cd="005930", stk_nm="삼성전자",
        state=_kr_state(
            awaiting_approval=True,
            trade_proposal={
                "id": "p1",
                "stk_cd": "005930",
                "stk_nm": "삼성전자",
                "action": "BUY",
                "quantity": 10,
                "entry_price": 70000,
                "risk_score": 0.4,
                "rationale": "테스트",
            },
        ),
    )
    sm._sessions["legacy-3"].status = SessionStatus.AWAITING_APPROVAL

    ws = FakeWebSocket()
    async with running_ws(ws, "legacy-3"):
        await wait_for_frame(ws, lambda f: f.get("type") == "proposal")
        await asyncio.sleep(1.0)  # several poll cycles
        proposals = [f for f in ws.sent if f.get("type") == "proposal"]
        assert len(proposals) == 1
        assert proposals[0]["data"]["ticker"] == "005930"
        assert proposals[0]["data"]["action"] == "BUY"


async def test_position_frames_are_deduped(sm, kr_sessions, fast_linger, fast_poll):
    await sm.create_session(
        "pos-1", MarketType.KIWOOM, "005930", "삼성전자",
        stk_cd="005930", stk_nm="삼성전자",
        state=_kr_state(active_position={
            "ticker": "005930",
            "entry_price": 70000,
            "current_price": 71000,
            "quantity": 10,
        }),
    )
    session = sm._sessions["pos-1"]

    ws = FakeWebSocket()
    async with running_ws(ws, "pos-1") as task:
        await wait_for_frame(ws, lambda f: f.get("type") == "position")
        await asyncio.sleep(1.0)  # ~10 poll cycles at the patched 0.1s interval
        positions = [f for f in ws.sent if f.get("type") == "position"]
        assert len(positions) == 1, "unchanged position must not be re-sent every poll"

        session.state["active_position"]["current_price"] = 72000
        await wait_for_frame(
            ws, lambda f: f.get("type") == "position" and f["data"]["current_price"] == 72000
        )
        positions = [f for f in ws.sent if f.get("type") == "position"]
        assert len(positions) == 2

        session.status = SessionStatus.COMPLETED
        await asyncio.wait_for(task, timeout=4.0)


# -------------------------------------------
# Push mode (SessionManager sessions)
# -------------------------------------------


async def test_sm_only_session_streams_via_push(sm, kr_sessions, fast_linger, slow_polls):
    """A session living only in the SessionManager must stream via pub/sub push.

    Both poll timeouts are patched to 30s, so any frame arriving within a second
    can only have been delivered by a subscription wake-up — not by polling.
    """
    await sm.create_session(
        "push-1",
        MarketType.KIWOOM,
        "005930",
        "삼성전자",
        stk_cd="005930",
        stk_nm="삼성전자",
        state={"reasoning_log": [], "current_stage": "data_collection"},
    )

    ws = FakeWebSocket()
    async with running_ws(ws, "push-1") as task:
        # Initial status frame is emitted immediately on connect (no poll wait).
        status = await wait_for_frame(ws, lambda f: f.get("type") == "status", timeout=1.0)
        assert status["data"]["status"] == "running"

        await sm.update_state(
            "push-1",
            {"reasoning_log": ["[t] 푸시 엔트리"], "current_stage": "technical"},
            last_node="technical_analysis",
        )
        frame = await wait_for_frame(ws, lambda f: f.get("type") == "reasoning", timeout=1.0)
        assert frame["data"] == "[t] 푸시 엔트리"

        await sm.update_status("push-1", SessionStatus.COMPLETED)
        await wait_for_frame(ws, lambda f: f.get("type") == "complete", timeout=1.0)
        await asyncio.wait_for(task, timeout=2.0)

    # Inter-frame ordering: every reasoning frame precedes the complete frame.
    types = [f["type"] for f in ws.sent]
    assert max(i for i, t in enumerate(types) if t == "reasoning") < types.index("complete")


async def test_push_mode_ping_pong(sm, kr_sessions, fast_linger, slow_polls):
    await sm.create_session(
        "push-2", MarketType.KIWOOM, "005930", "삼성전자", state={"reasoning_log": []}
    )

    ws = FakeWebSocket()
    async with running_ws(ws, "push-2"):
        await wait_for_frame(ws, lambda f: f.get("type") == "status", timeout=1.0)
        ws.client_send("ping")
        deadline = asyncio.get_running_loop().time() + 1.0
        while "pong" not in ws.sent_text and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
        assert "pong" in ws.sent_text


async def test_safety_poll_covers_unnotified_sm_writes(sm, kr_sessions, fast_linger):
    """P1-2: the safety poll covers writes that mutate the SM session object
    directly with NO pub/sub notification fired (the SM-only analogue of the
    old un-migrated legacy-dict-write path, now that legacy dicts are out of
    the read path): frames must still arrive within the poll interval.
    Disabling SAFETY_POLL_SECONDS would fail this test (runs at the real 1.0s
    default — no patching)."""
    await sm.create_session(
        "safety-1", MarketType.KIWOOM, "005930", "삼성전자", state={"reasoning_log": []}
    )

    ws = FakeWebSocket()
    async with running_ws(ws, "safety-1") as task:
        await wait_for_frame(ws, lambda f: f.get("type") == "status", timeout=1.0)

        # Un-notified write: mutate the live session object directly,
        # bypassing update_status()'s _notify_subscribers call.
        sm._sessions["safety-1"].status = SessionStatus.COMPLETED
        complete = await wait_for_frame(ws, lambda f: f.get("type") == "complete", timeout=3.0)
        assert complete["data"]["status"] == "completed"
        await asyncio.wait_for(task, timeout=2.0)


async def test_status_frame_carries_auto_approve_at_when_present(sm):
    """R3: the rail countdown rides the status frame (additive optional field)."""
    ws = FakeWebSocket()
    cursor = ws_module._SessionFrameCursor("auto-1")
    session = {
        "session_id": "auto-1",
        "status": "awaiting_approval",
        "error": None,
        "state": {
            "reasoning_log": [],
            "current_stage": "approval",
            "awaiting_approval": True,
            "auto_approve_at": "2026-07-12T10:00:00+00:00",
        },
    }

    await cursor.emit(ws, session)

    status_frames = [f for f in ws.sent if f["type"] == "status"]
    assert status_frames[0]["data"]["auto_approve_at"] == "2026-07-12T10:00:00+00:00"

    # Absent from sessions without it
    ws2 = FakeWebSocket()
    cursor2 = ws_module._SessionFrameCursor("auto-2")
    session2 = {
        "session_id": "auto-2", "status": "running", "error": None,
        "state": {"reasoning_log": [], "current_stage": "x"},
    }
    await cursor2.emit(ws2, session2)
    assert "auto_approve_at" not in [f for f in ws2.sent if f["type"] == "status"][0]["data"]


async def test_running_status_does_not_advertise_stale_proposal(sm):
    """P0-3 (F4a t2): a restart-stranded session whose legacy status is still
    "running" but whose state dict retained a stale awaiting_approval=True +
    trade_proposal (e.g. the process died mid-approval) must NOT re-advertise
    that proposal to a reconnecting tab. Only status == "awaiting_approval"
    may emit a proposal frame."""
    ws = FakeWebSocket()
    cursor = ws_module._SessionFrameCursor("stale-1")
    session = {
        "session_id": "stale-1",
        "status": "running",
        "error": None,
        "state": {
            "reasoning_log": [],
            "current_stage": "approval",
            "awaiting_approval": True,
            "trade_proposal": {
                "id": "p1",
                "stk_cd": "005930",
                "stk_nm": "삼성전자",
                "action": "BUY",
                "quantity": 10,
                "entry_price": 70000,
                "risk_score": 0.4,
                "rationale": "테스트",
            },
        },
    }

    await cursor.emit(ws, session)

    assert not [f for f in ws.sent if f["type"] == "proposal"], (
        "status=running must not emit a proposal frame even when state still "
        "carries a stale awaiting_approval=True + trade_proposal"
    )


async def test_countdown_arrival_triggers_a_status_frame(sm):
    """SAFETY-UX (review fix): the injector writes auto_approve_at AFTER the
    awaiting_approval transition — an already-connected client must still get
    a status frame when the countdown appears (and when it is cleared)."""
    ws = FakeWebSocket()
    cursor = ws_module._SessionFrameCursor("auto-3")
    session = {
        "session_id": "auto-3",
        "status": "awaiting_approval",
        "error": None,
        "state": {"reasoning_log": [], "current_stage": "approval", "awaiting_approval": True},
    }

    await cursor.emit(ws, session)  # awaiting transition frame (no countdown yet)
    session["state"]["auto_approve_at"] = "2026-07-12T10:00:00+00:00"
    await cursor.emit(ws, session)  # same status/stage — countdown appeared

    status_frames = [f for f in ws.sent if f["type"] == "status"]
    assert len(status_frames) == 2, "countdown appearance must emit a frame"
    assert status_frames[1]["data"]["auto_approve_at"] == "2026-07-12T10:00:00+00:00"

    session["state"].pop("auto_approve_at")
    await cursor.emit(ws, session)  # countdown cleared
    status_frames = [f for f in ws.sent if f["type"] == "status"]
    assert len(status_frames) == 3
    assert "auto_approve_at" not in status_frames[2]["data"]


async def test_cursor_emits_pending_frames_before_complete(sm):
    """Frame order within one wake: reasoning/status must precede the complete
    frame, so a client that stops reading at 'complete' misses nothing."""
    ws = FakeWebSocket()
    cursor = ws_module._SessionFrameCursor("cursor-1")
    session = {
        "session_id": "cursor-1",
        "status": "completed",
        "error": None,
        "state": {"reasoning_log": ["[t] a", "[t] b"], "current_stage": "done"},
    }

    completed = await cursor.emit(ws, session)

    assert completed is True
    types = [f["type"] for f in ws.sent]
    assert types == ["reasoning", "reasoning", "status", "complete"]


# -------------------------------------------
# Snapshot cap on initial connect replay
# -------------------------------------------
#
# LIVE-CONFIRMED bug: on every /ws/session/{id} connect, the full
# reasoning_log (hundreds of frames for a long session) was sent back-to-back
# with no yielding. That burst broke the vite dev proxy (EPIPE -> close 1006)
# ~2s after connect, the FE reconnected, and the full snapshot replayed again
# -> infinite churn, plus the repeated full-log json-encode froze the loop.
# _SessionFrameCursor.emit() now caps the *initial* replay (last_log_index
# still 0) at SNAPSHOT_MAX_REASONING entries with a leading truncation
# marker, while positioning the cursor at the true (uncapped) log length so
# live deltas after connect keep streaming with no gap/dup.


async def test_initial_snapshot_caps_reasoning_with_truncation_marker():
    """(a) 300 entries -> at most 100 + 1 truncation marker, newest 100 in order."""
    ws = FakeWebSocket()
    cursor = ws_module._SessionFrameCursor("snap-300")
    reasoning_log = [f"[t] entry {i}" for i in range(300)]
    session = {
        "session_id": "snap-300",
        "status": "running",
        "error": None,
        "state": {"reasoning_log": reasoning_log, "current_stage": "data_collection"},
    }

    await cursor.emit(ws, session)

    reasoning_frames = [f for f in ws.sent if f["type"] == "reasoning"]
    assert len(reasoning_frames) == ws_module.SNAPSHOT_MAX_REASONING + 1
    assert "생략" in reasoning_frames[0]["data"]
    assert [f["data"] for f in reasoning_frames[1:]] == reasoning_log[-100:]
    # Cursor tracks the true log length, not the capped send count.
    assert cursor.last_log_index == 300


async def test_initial_snapshot_cursor_continuity_no_gap_no_dup():
    """(b) live entries appended after a capped connect still stream: no
    duplicate of the last snapshot line, no gap."""
    ws = FakeWebSocket()
    cursor = ws_module._SessionFrameCursor("snap-cont")
    reasoning_log = [f"[t] entry {i}" for i in range(300)]
    session = {
        "session_id": "snap-cont",
        "status": "running",
        "error": None,
        "state": {"reasoning_log": reasoning_log, "current_stage": "data_collection"},
    }

    await cursor.emit(ws, session)  # capped initial snapshot

    session["state"]["reasoning_log"] = reasoning_log + ["[t] live entry"]
    await cursor.emit(ws, session)  # live delta after connect

    reasoning_frames = [f for f in ws.sent if f["type"] == "reasoning"]
    data = [f["data"] for f in reasoning_frames]
    assert data[-1] == "[t] live entry"
    assert data.count("[t] live entry") == 1
    assert data.count("[t] entry 299") == 1, "last pre-connect line must not be re-sent"
    assert data.count("[t] entry 0") == 0, "omitted lines never appear"


async def test_short_session_under_cap_gets_no_marker():
    """(c) 50 entries -> all 50 delivered, no truncation marker."""
    ws = FakeWebSocket()
    cursor = ws_module._SessionFrameCursor("snap-50")
    reasoning_log = [f"[t] entry {i}" for i in range(50)]
    session = {
        "session_id": "snap-50",
        "status": "running",
        "error": None,
        "state": {"reasoning_log": reasoning_log, "current_stage": "data_collection"},
    }

    await cursor.emit(ws, session)

    reasoning_frames = [f for f in ws.sent if f["type"] == "reasoning"]
    assert len(reasoning_frames) == 50
    assert [f["data"] for f in reasoning_frames] == reasoning_log


async def test_snapshot_replay_is_paced(monkeypatch):
    """Snapshot replay yields every frame (sleep(0)) and takes a longer
    breather every SNAPSHOT_PACE_SLEEP_EVERY frames, so the proxy can flush
    instead of getting hit with hundreds of frames in one scheduler tick."""
    sleep_calls: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        await real_sleep(0)  # keep the test itself fast

    monkeypatch.setattr(ws_module.asyncio, "sleep", fake_sleep)

    ws = FakeWebSocket()
    cursor = ws_module._SessionFrameCursor("snap-pace")
    reasoning_log = [f"[t] entry {i}" for i in range(300)]
    session = {
        "session_id": "snap-pace",
        "status": "running",
        "error": None,
        "state": {"reasoning_log": reasoning_log, "current_stage": "data_collection"},
    }

    await cursor.emit(ws, session)

    total_frames = ws_module.SNAPSHOT_MAX_REASONING + 1  # 100 entries + marker
    yield_calls = [c for c in sleep_calls if c == 0]
    assert len(yield_calls) == total_frames
    throttle_calls = [c for c in sleep_calls if c == ws_module.SNAPSHOT_PACE_SLEEP_SECONDS]
    assert len(throttle_calls) == total_frames // ws_module.SNAPSHOT_PACE_SLEEP_EVERY


async def test_subscriber_registered_and_cleaned_up(sm, kr_sessions, fast_linger):
    await sm.create_session(
        "push-3", MarketType.KIWOOM, "005930", "삼성전자", state={"reasoning_log": []}
    )

    ws = FakeWebSocket()
    async with running_ws(ws, "push-3") as task:
        await wait_for_frame(ws, lambda f: f.get("type") == "status", timeout=1.0)
        assert sm._subscribers.get("push-3"), "endpoint must subscribe to sm pub/sub"

        ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2.0)

    assert not sm._subscribers.get("push-3"), "subscription must be cleaned up on disconnect"


# -------------------------------------------
# Not-found close (P0-2)
# -------------------------------------------


async def test_ws_unknown_session_not_found_close(sm, kr_sessions, monkeypatch):
    """A session id with no snapshot anywhere (legacy dicts or SessionManager)
    must not be safety-polled forever: after NOT_FOUND_GRACE_SECONDS of
    consecutive None snapshots, the server sends a not_found frame and closes
    with code 4404 (P0-2). P0-3's FE consumes this frame/code to drop the
    card instead of reconnecting."""
    monkeypatch.setattr(ws_module, "NOT_FOUND_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(ws_module, "SAFETY_POLL_SECONDS", 0.05)

    ws = FakeWebSocket()
    async with running_ws(ws, "no-such-session-id") as task:
        await wait_for_frame(ws, lambda f: f.get("type") == "not_found", timeout=1.0)
        await asyncio.wait_for(task, timeout=1.0)

    not_found_frames = [f for f in ws.sent if f["type"] == "not_found"]
    assert len(not_found_frames) == 1
    assert not_found_frames[0]["data"]["session_id"] == "no-such-session-id"
    assert ws.closed_code == 4404


# -------------------------------------------
# Session-SSOT reads (P1-2): SM is the sole snapshot source
# -------------------------------------------


async def test_ws_snapshot_sm_only(sm, kr_sessions):
    """SESSION_SSOT_READS=True (default): _get_session_snapshot reads the
    SessionManager exclusively. A session that exists only in the legacy dict
    is no longer served -- it now falls into P0-2's not-found path instead
    of being served from the legacy dict fallback."""
    await sm.create_session(
        "ssot-p12", MarketType.KIWOOM, "005930", "삼성전자",
        state={"reasoning_log": ["a"]},
    )
    snap = await ws_module._get_session_snapshot("ssot-p12")
    assert snap is not None and snap["session_id"] == "ssot-p12"

    # legacy-only 세션은 더 이상 서빙되지 않는다
    kr_sessions["legacy-only-p12"] = {
        "session_id": "legacy-only-p12", "status": "running",
        "state": {"reasoning_log": []}, "created_at": None, "error": None,
    }
    assert await ws_module._get_session_snapshot("legacy-only-p12") is None


async def test_ws_snapshot_kill_switch_reads_legacy_when_false(sm, kr_sessions, monkeypatch):
    """SESSION_SSOT_READS=False: legacy-first behavior is fully restored --
    a legacy-dict-only session is served again, and an sm-only session still
    falls back to sm (kill-switch regression guard, same pattern as
    tests/test_api/test_approval_pending_ssot.py's False-branch tests)."""
    import types

    monkeypatch.setattr(
        ws_module, "get_settings",
        lambda: types.SimpleNamespace(SESSION_SSOT_READS=False),
    )

    await sm.create_session(
        "ssot-p12-ks-sm-only", MarketType.KIWOOM, "005930", "삼성전자",
        state={"reasoning_log": []},
    )
    snap = await ws_module._get_session_snapshot("ssot-p12-ks-sm-only")
    assert snap is not None and snap["session_id"] == "ssot-p12-ks-sm-only"

    kr_sessions["ssot-p12-ks-legacy"] = {
        "session_id": "ssot-p12-ks-legacy", "status": "running",
        "state": {"reasoning_log": []}, "created_at": None, "error": None,
    }
    snap2 = await ws_module._get_session_snapshot("ssot-p12-ks-legacy")
    assert snap2 is not None and snap2["session_id"] == "ssot-p12-ks-legacy"
