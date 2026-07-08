"""
SQLite-based Checkpointer for LangGraph (P6 durable persistence).

Persists LangGraph workflow state to SQLite so HITL (Human-in-the-Loop)
interrupt/resume survives a process restart — MemorySaver is in-process only and
loses everything between propose and approve on a restart.

Checkpoints and pending writes are serialized with LangGraph's own serde
(JsonPlusSerializer), so complex channel values (Pydantic models, tuples,
datetimes, ...) round-trip losslessly. The serde bytes are base64-encoded so they
fit the storage layer's JSON blob. No external server required.
"""

import base64
from typing import Any, AsyncIterator, Optional, Sequence

import structlog
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from services.storage_service import get_storage_service

logger = structlog.get_logger()


class SqliteCheckpointer(BaseCheckpointSaver):
    """SQLite-backed checkpoint saver for durable HITL interrupt/resume.

    The storage layer keeps the latest checkpoint per (session_id, thread_id) as a
    single JSON blob; this class encodes the serde-serialized checkpoint, metadata,
    and pending writes into that blob.
    """

    def __init__(self, session_id: Optional[str] = None):
        """
        Args:
            session_id: optional storage partition. When None (the recommended mode
                for a graph singleton shared across sessions), the LangGraph
                thread_id is used as the partition, so one compiled graph durably
                checkpoints every session by its thread_id.
        """
        super().__init__()
        self.session_id = session_id
        self._storage_service = None

    async def _get_service(self):
        """Lazy load storage service."""
        if self._storage_service is None:
            self._storage_service = await get_storage_service()
        return self._storage_service

    def _sid(self, thread_id: str) -> str:
        """Storage partition key: an explicit session_id, else the thread_id."""
        return self.session_id or thread_id

    # -------------------------------------------
    # serde <-> JSON-safe helpers
    # -------------------------------------------

    def _encode(self, obj: Any) -> dict[str, str]:
        """serde-serialize an object to a JSON-safe {"t": type, "b": base64} dict."""
        type_, blob = self.serde.dumps_typed(obj)
        return {"t": type_, "b": base64.b64encode(blob).decode("ascii")}

    def _decode(self, enc: dict[str, str]) -> Any:
        """Inverse of _encode."""
        return self.serde.loads_typed((enc["t"], base64.b64decode(enc["b"])))

    # -------------------------------------------
    # Async API (LangGraph calls these)
    # -------------------------------------------

    async def aget_tuple(self, config: dict[str, Any]) -> Optional[CheckpointTuple]:
        """Load the checkpoint + its pending writes for a thread."""
        thread_id = config["configurable"].get("thread_id", "default")
        requested_id = config["configurable"].get("checkpoint_id")

        service = await self._get_service()
        try:
            data = await service.get_checkpoint(self._sid(thread_id), thread_id)
        except Exception as e:
            logger.error(
                "checkpoint_get_failed",
                session_id=self.session_id, thread_id=thread_id, error=str(e),
            )
            return None

        if not data or "checkpoint" not in data:
            return None

        stored_id = data.get("checkpoint_id")
        if requested_id and stored_id != requested_id:
            return None

        try:
            checkpoint = self._decode(data["checkpoint"])
            metadata = self._decode(data["metadata"])
        except Exception as e:
            logger.error(
                "checkpoint_deserialize_failed",
                session_id=self.session_id, thread_id=thread_id, error=str(e),
            )
            return None

        pending_writes = []
        for w in data.get("writes", []):
            if w.get("checkpoint_id") != stored_id:
                continue
            try:
                value = self._decode(w)
            except Exception:
                continue
            pending_writes.append((w["task_id"], w["channel"], value))

        parent_id = data.get("parent_checkpoint_id")
        parent_config = (
            {"configurable": {"thread_id": thread_id, "checkpoint_id": parent_id}}
            if parent_id else None
        )

        return CheckpointTuple(
            config={"configurable": {"thread_id": thread_id, "checkpoint_id": stored_id}},
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    async def alist(
        self,
        config: Optional[dict[str, Any]] = None,
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Yield checkpoints for a thread.

        The storage keeps only the latest checkpoint per (session, thread), so this
        yields at most one tuple — sufficient for HITL resume (history/time-travel
        would require a per-checkpoint-id schema).
        """
        if config is None:
            return
        tup = await self.aget_tuple(config)
        if tup is not None:
            yield tup

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Persist a checkpoint (serde-serialized), preserving writes recorded
        against this checkpoint id."""
        thread_id = config["configurable"].get("thread_id", "default")
        checkpoint_id = checkpoint["id"]
        parent_id = config["configurable"].get("checkpoint_id")

        service = await self._get_service()
        try:
            existing = await service.get_checkpoint(self._sid(thread_id), thread_id) or {}
        except Exception:
            existing = {}
        writes = [
            w for w in existing.get("writes", [])
            if w.get("checkpoint_id") == checkpoint_id
        ]

        blob = {
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_id,
            "checkpoint": self._encode(checkpoint),
            "metadata": self._encode(dict(metadata)),
            "writes": writes,
        }

        try:
            await service.save_checkpoint(self._sid(thread_id), thread_id, blob)
            logger.debug(
                "checkpoint_saved",
                session_id=self.session_id, thread_id=thread_id, checkpoint_id=checkpoint_id,
            )
        except Exception as e:
            logger.error(
                "checkpoint_save_failed",
                session_id=self.session_id, thread_id=thread_id, error=str(e),
            )
            raise

        return {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Persist a task's pending writes against the current checkpoint id, so
        aget_tuple can return them as pending_writes on resume."""
        thread_id = config["configurable"].get("thread_id", "default")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        service = await self._get_service()
        try:
            data = await service.get_checkpoint(self._sid(thread_id), thread_id) or {}
        except Exception:
            data = {}

        stored = data.get("writes", [])
        for idx, (channel, value) in enumerate(writes):
            enc = self._encode(value)
            stored.append({
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "task_path": task_path,
                "idx": idx,
                "channel": channel,
                "t": enc["t"],
                "b": enc["b"],
            })
        data["writes"] = stored
        data.setdefault("checkpoint_id", checkpoint_id)

        try:
            await service.save_checkpoint(self._sid(thread_id), thread_id, data)
        except Exception as e:
            logger.error(
                "checkpoint_writes_save_failed",
                session_id=self.session_id, thread_id=thread_id, error=str(e),
            )

    # -------------------------------------------
    # Synchronous methods (required by base class; this checkpointer is async-only)
    # -------------------------------------------

    def get_tuple(self, config: dict[str, Any]) -> Optional[CheckpointTuple]:
        raise NotImplementedError("Use aget_tuple for async operations")

    def list(
        self,
        config: Optional[dict[str, Any]] = None,
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        limit: Optional[int] = None,
    ):
        raise NotImplementedError("Use alist for async operations")

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        raise NotImplementedError("Use aput for async operations")

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        raise NotImplementedError("Use aput_writes for async operations")


# -------------------------------------------
# Factory Function
# -------------------------------------------


def create_checkpointer(session_id: str) -> SqliteCheckpointer:
    """Create a SQLite checkpointer for a session."""
    return SqliteCheckpointer(session_id)
