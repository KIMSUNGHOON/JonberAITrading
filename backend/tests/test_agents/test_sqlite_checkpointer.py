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


async def test_real_graph_interrupt_survives_restart_and_resumes():
    """End-to-end durable HITL: a graph interrupts, a BRAND-NEW checkpointer instance
    (simulated restart) resumes from the SQLite-persisted state and completes — the
    pre-interrupt work must survive (MemorySaver would lose it)."""
    from typing import Annotated, TypedDict

    from langgraph.graph import END, StateGraph

    from agents.graph.state_base import append_list

    class S(TypedDict, total=False):
        steps: Annotated[list, append_list]
        approved: bool

    def node_a(state):
        return {"steps": ["a"]}

    def gate(state):
        return {}

    def node_b(state):
        return {"steps": ["b"]}

    def build():
        g = StateGraph(S)
        g.add_node("a", node_a)
        g.add_node("gate", gate)
        g.add_node("b", node_b)
        g.set_entry_point("a")
        g.add_edge("a", "gate")
        g.add_edge("gate", "b")
        g.add_edge("b", END)
        return g

    storage = _FakeStorage()
    config = {"configurable": {"thread_id": "run-1"}}

    cp1 = SqliteCheckpointer()
    cp1._storage_service = storage
    graph1 = build().compile(checkpointer=cp1, interrupt_before=["gate"])
    async for _ in graph1.astream({"steps": []}, config):
        pass  # runs "a", then pauses before "gate"

    # Simulated restart: fresh checkpointer + freshly-compiled graph, SAME storage.
    cp2 = SqliteCheckpointer()
    cp2._storage_service = storage
    graph2 = build().compile(checkpointer=cp2, interrupt_before=["gate"])
    # Correct resume: inject the decision into the (persisted) checkpoint, then
    # continue with astream(None). Passing a dict to astream would RESTART the graph.
    await graph2.aupdate_state(config, {"approved": True})
    async for _ in graph2.astream(None, config):
        pass  # resumes from the interrupt, runs "gate" then "b"

    snap = await graph2.aget_state(config)
    # "a" (pre-interrupt, durably persisted) + "b" (post-resume) both present.
    assert snap.values.get("steps") == ["a", "b"]
    assert snap.values.get("approved") is True


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
