"""P6: SqliteCheckpointer durable-persistence round-trip.

A checkpoint (and its pending writes) must survive being written to storage and
read back by a BRAND-NEW checkpointer instance (simulating a process restart),
reconstructing the exact state via LangGraph's serde. This is what makes HITL
interrupt/resume durable across restarts (MemorySaver is in-process only).
"""

import json
from datetime import datetime, timezone

import pytest
from langgraph.checkpoint.base import CheckpointMetadata, empty_checkpoint

from agents.graph.sqlite_checkpointer import SqliteCheckpointer


class _FakeStorage:
    """In-memory stand-in that round-trips through JSON exactly like the SQLite
    store (which does json.dumps(default=str) on save)."""

    def __init__(self):
        self._rows = {}

    async def save_checkpoint(self, session_id, thread_id, data):
        self._rows[(session_id, thread_id)] = json.loads(json.dumps(data, default=str))

    async def get_checkpoint(self, session_id, thread_id):
        return self._rows.get((session_id, thread_id))


def _cp(storage, session_id="sess-1"):
    cp = SqliteCheckpointer(session_id)
    cp._storage_service = storage  # skip lazy get_storage_service()
    return cp


async def test_checkpoint_round_trips_losslessly_across_instances():
    storage = _FakeStorage()
    cp = _cp(storage)
    checkpoint = empty_checkpoint()
    # Include a datetime: the old ad-hoc json.dumps(default=str) mangles non-JSON
    # types to strings, so this asserts the serde path preserves types losslessly
    # (our real state channel values hold Pydantic models / datetimes).
    ts = datetime(2026, 7, 8, tzinfo=timezone.utc)
    checkpoint["channel_values"] = {"messages": ["hi"], "count": 3, "ts": ts}
    metadata = CheckpointMetadata(source="loop", step=2, writes={"node": {"x": 1}})

    out = await cp.aput({"configurable": {"thread_id": "t1"}}, checkpoint, metadata, {})
    assert out["configurable"]["checkpoint_id"] == checkpoint["id"]

    # Fresh instance (simulated restart), same storage.
    cp2 = _cp(storage)
    tup = await cp2.aget_tuple({"configurable": {"thread_id": "t1"}})
    assert tup is not None
    assert tup.checkpoint["id"] == checkpoint["id"]
    assert tup.checkpoint["channel_values"]["ts"] == ts  # datetime preserved, not str
    assert tup.checkpoint["channel_values"]["messages"] == ["hi"]
    assert tup.checkpoint["channel_values"]["count"] == 3
    assert tup.metadata["step"] == 2
    assert tup.metadata["source"] == "loop"


async def test_aput_writes_returned_as_pending_writes():
    storage = _FakeStorage()
    cp = _cp(storage)
    checkpoint = empty_checkpoint()
    await cp.aput({"configurable": {"thread_id": "t2"}}, checkpoint,
                  CheckpointMetadata(source="input", step=0), {})
    cfg = {"configurable": {"thread_id": "t2", "checkpoint_id": checkpoint["id"]}}
    await cp.aput_writes(cfg, [("channel_a", {"v": 1}), ("channel_b", [1, 2])], "task-1")

    tup = await _cp(storage).aget_tuple({"configurable": {"thread_id": "t2"}})
    assert tup is not None
    by_channel = {c: v for (_tid, c, v) in tup.pending_writes}
    assert by_channel == {"channel_a": {"v": 1}, "channel_b": [1, 2]}


async def test_aget_tuple_none_when_missing():
    tup = await _cp(_FakeStorage()).aget_tuple({"configurable": {"thread_id": "nope"}})
    assert tup is None


async def test_session_agnostic_keys_by_thread_id():
    # No session_id (the singleton-graph mode): partition by thread_id so one compiled
    # graph durably checkpoints every session.
    storage = _FakeStorage()
    cp = SqliteCheckpointer()
    cp._storage_service = storage
    checkpoint = empty_checkpoint()
    await cp.aput({"configurable": {"thread_id": "abc"}}, checkpoint,
                  CheckpointMetadata(source="input", step=0), {})
    assert ("abc", "abc") in storage._rows  # partitioned by thread_id
    tup = await cp.aget_tuple({"configurable": {"thread_id": "abc"}})
    assert tup is not None and tup.checkpoint["id"] == checkpoint["id"]


async def test_alist_is_async_generator_yielding_latest():
    storage = _FakeStorage()
    cp = _cp(storage)
    checkpoint = empty_checkpoint()
    await cp.aput({"configurable": {"thread_id": "t3"}}, checkpoint,
                  CheckpointMetadata(source="input", step=0), {})
    tuples = [t async for t in cp.alist({"configurable": {"thread_id": "t3"}})]
    assert len(tuples) == 1
    assert tuples[0].checkpoint["id"] == checkpoint["id"]
