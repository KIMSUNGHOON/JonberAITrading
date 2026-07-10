"""P7 Phase 0: SessionManager pub/sub primitive — bounded queue, drop-oldest
coalescing, and a reasoning-log delta in the state_update notification.

These harden the (currently dormant) WebSocket subscription primitive so the P7
session-push rewrite can stream per reasoning entry and a slow/dead socket cannot
grow the queue unboundedly. Headless — a real asyncio.Queue + a fake consumer.
"""

import asyncio
import os

import pytest
from unittest.mock import AsyncMock, patch

from services.session_manager import (
    SessionManager,
    MarketType,
    SessionStatus,
    SUBSCRIBER_QUEUE_MAXSIZE,
)

TEST_DB_PATH = "data/test_pubsub_sessions.db"


@pytest.fixture
def clean_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    yield
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture
async def sm(clean_db):
    with patch("services.session_manager.DB_PATH", TEST_DB_PATH):
        m = SessionManager()
        await m.initialize()
        yield m
        m._sessions.clear()


async def test_state_update_carries_reasoning_delta_and_last_node(sm):
    await sm.create_session("s1", MarketType.KIWOOM, "005930", "삼성전자")
    q = await sm.subscribe("s1")
    await sm.update_state(
        "s1", {"reasoning_log": ["a"], "current_stage": "technical"}, last_node="technical"
    )
    msg = await asyncio.wait_for(q.get(), timeout=1)
    assert msg["type"] == "state_update"
    assert "current_stage" in msg["updates"]
    assert msg["reasoning_delta"] == ["a"]  # only the appended entry
    assert msg["last_node"] == "technical"


async def test_reasoning_delta_is_only_the_new_entries(sm):
    await sm.create_session("s2", MarketType.KIWOOM, "005930", "삼성")
    q = await sm.subscribe("s2")
    await sm.update_state("s2", {"reasoning_log": ["a"]})
    await asyncio.wait_for(q.get(), 1)
    await sm.update_state("s2", {"reasoning_log": ["a", "b", "c"]})
    msg = await asyncio.wait_for(q.get(), 1)
    assert msg["reasoning_delta"] == ["b", "c"]  # delta, not the whole log


async def test_status_update_notifies_subscribers(sm):
    await sm.create_session("s3", MarketType.KIWOOM, "005930", "삼성")
    q = await sm.subscribe("s3")
    await sm.update_status("s3", SessionStatus.COMPLETED)
    msg = await asyncio.wait_for(q.get(), 1)
    assert msg["type"] == "status"
    assert msg["status"] == "completed"


async def test_unsubscribe_stops_delivery(sm):
    await sm.create_session("s4", MarketType.KIWOOM, "005930", "삼성")
    q = await sm.subscribe("s4")
    await sm.unsubscribe("s4", q)
    await sm.update_state("s4", {"current_stage": "x"})
    assert q.empty()


async def test_bounded_queue_drops_oldest_keeping_latest(sm):
    await sm.create_session("s5", MarketType.KIWOOM, "005930", "삼성")
    q = await sm.subscribe("s5")
    assert q.maxsize == SUBSCRIBER_QUEUE_MAXSIZE
    sm._save_session = AsyncMock()  # isolate the queue behavior from SQLite I/O

    # Slow/dead consumer: overflow the queue with distinguishable messages.
    total = SUBSCRIBER_QUEUE_MAXSIZE + 10
    log = []
    for i in range(total):
        log.append(f"e{i}")
        await sm.update_state("s5", {"reasoning_log": list(log)})

    assert q.qsize() == SUBSCRIBER_QUEUE_MAXSIZE  # bounded, not unbounded
    drained = []
    while not q.empty():
        drained.append(q.get_nowait())
    # drop-oldest: the newest notification is retained, the oldest were dropped.
    assert drained[-1]["reasoning_delta"] == [f"e{total - 1}"]
    assert drained[0]["reasoning_delta"] == [f"e{total - SUBSCRIBER_QUEUE_MAXSIZE}"]
