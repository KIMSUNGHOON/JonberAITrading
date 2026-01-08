"""
SQLite-based Checkpointer for LangGraph

Provides persistent state storage for LangGraph workflows,
enabling HITL (Human-in-the-Loop) interrupt/resume functionality.

No external server required - uses embedded SQLite database.
"""

import json
from typing import Any, Optional, Sequence

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata, CheckpointTuple

from services.storage_service import get_storage_service

logger = structlog.get_logger()


class SqliteCheckpointer(BaseCheckpointSaver):
    """
    SQLite-based checkpoint saver for LangGraph.

    Stores workflow state in SQLite for:
    - HITL interrupts (awaiting approval)
    - Session resumption
    - Crash recovery

    No external server required!
    """

    def __init__(self, session_id: str):
        """
        Initialize SQLite checkpointer.

        Args:
            session_id: Session identifier for this workflow
        """
        super().__init__()
        self.session_id = session_id
        self._storage_service = None

    async def _get_service(self):
        """Lazy load storage service."""
        if self._storage_service is None:
            self._storage_service = await get_storage_service()
        return self._storage_service

    async def aget_tuple(self, config: dict[str, Any]) -> Optional[CheckpointTuple]:
        """
        Get a checkpoint tuple by config.

        Args:
            config: Configuration dict with thread_id and optional checkpoint_id

        Returns:
            CheckpointTuple if found, None otherwise
        """
        thread_id = config["configurable"].get("thread_id", "default")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        service = await self._get_service()

        try:
            data = await service.get_checkpoint(self.session_id, thread_id)

            if data is None:
                return None

            # If specific checkpoint requested, verify it matches
            if checkpoint_id and data.get("id") != checkpoint_id:
                return None

            checkpoint = Checkpoint(
                v=data.get("v", 1),
                id=data.get("id", ""),
                ts=data.get("ts", ""),
                channel_values=data.get("channel_values", {}),
                channel_versions=data.get("channel_versions", {}),
                versions_seen=data.get("versions_seen", {}),
                pending_sends=data.get("pending_sends", []),
            )

            metadata = CheckpointMetadata(
                source=data.get("metadata", {}).get("source", "input"),
                step=data.get("metadata", {}).get("step", 0),
                writes=data.get("metadata", {}).get("writes"),
            )

            return CheckpointTuple(
                config=config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=data.get("parent_config"),
            )

        except Exception as e:
            logger.error(
                "checkpoint_get_failed",
                session_id=self.session_id,
                thread_id=thread_id,
                error=str(e),
            )
            return None

    async def alist(
        self,
        config: Optional[dict[str, Any]] = None,
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> list[CheckpointTuple]:
        """
        List checkpoints for a thread.

        Note: Simplified implementation - returns latest checkpoint only.
        """
        if config is None:
            return []

        result = await self.aget_tuple(config)
        if result:
            return [result]
        return []

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Save a checkpoint to SQLite.

        Args:
            config: Configuration dict
            checkpoint: Checkpoint data
            metadata: Checkpoint metadata
            new_versions: New version info

        Returns:
            Updated config with checkpoint_id
        """
        thread_id = config["configurable"].get("thread_id", "default")

        service = await self._get_service()

        # Prepare checkpoint data for storage
        checkpoint_data = {
            "v": checkpoint["v"],
            "id": checkpoint["id"],
            "ts": checkpoint["ts"],
            "channel_values": self._serialize_channel_values(checkpoint.get("channel_values", {})),
            "channel_versions": checkpoint.get("channel_versions", {}),
            "versions_seen": checkpoint.get("versions_seen", {}),
            "pending_sends": checkpoint.get("pending_sends", []),
            "metadata": {
                "source": metadata.get("source", "input"),
                "step": metadata.get("step", 0),
                "writes": metadata.get("writes"),
            },
            "parent_config": config.get("configurable", {}).get("checkpoint_id"),
        }

        try:
            await service.save_checkpoint(
                self.session_id,
                thread_id,
                checkpoint_data,
            )

            logger.debug(
                "checkpoint_saved",
                session_id=self.session_id,
                thread_id=thread_id,
                checkpoint_id=checkpoint["id"],
            )

            return {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint["id"],
                }
            }

        except Exception as e:
            logger.error(
                "checkpoint_save_failed",
                session_id=self.session_id,
                thread_id=thread_id,
                error=str(e),
            )
            raise

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """
        Store intermediate writes.

        Note: Simplified implementation - writes are stored with checkpoint.
        """
        pass

    def _serialize_channel_values(self, values: dict[str, Any]) -> dict[str, Any]:
        """
        Serialize channel values for JSON storage.

        Handles complex objects by converting to string representation.
        """
        serialized = {}

        for key, value in values.items():
            try:
                # Try JSON serialization
                json.dumps(value, default=str)
                serialized[key] = value
            except (TypeError, ValueError):
                # Fall back to string representation
                serialized[key] = str(value)

        return serialized

    # -------------------------------------------
    # Synchronous methods (required by base class)
    # -------------------------------------------

    def get_tuple(self, config: dict[str, Any]) -> Optional[CheckpointTuple]:
        """Sync version - raises NotImplementedError."""
        raise NotImplementedError("Use aget_tuple for async operations")

    def list(
        self,
        config: Optional[dict[str, Any]] = None,
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> list[CheckpointTuple]:
        """Sync version - raises NotImplementedError."""
        raise NotImplementedError("Use alist for async operations")

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Sync version - raises NotImplementedError."""
        raise NotImplementedError("Use aput for async operations")

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Sync version - raises NotImplementedError."""
        raise NotImplementedError("Use aput_writes for async operations")


# -------------------------------------------
# Factory Function
# -------------------------------------------


def create_checkpointer(session_id: str) -> SqliteCheckpointer:
    """
    Create a SQLite checkpointer for a session.

    Args:
        session_id: Unique session identifier

    Returns:
        SqliteCheckpointer instance
    """
    return SqliteCheckpointer(session_id)
