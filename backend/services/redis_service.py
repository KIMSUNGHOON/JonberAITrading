"""
Redis Service for Session Persistence

Provides:
- Session state storage
- LangGraph checkpointing
- Cache management
"""

import json
from datetime import timedelta
from typing import Any, Optional

import redis.asyncio as redis
import structlog

from app.config import settings

logger = structlog.get_logger()

# -------------------------------------------
# Redis Client Singleton
# -------------------------------------------

_redis_client: Optional[redis.Redis] = None


async def get_redis_client() -> redis.Redis:
    """Get or create Redis client singleton."""
    global _redis_client

    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            db=settings.REDIS_DB,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("redis_client_created", url=settings.REDIS_URL)

    return _redis_client


async def close_redis_client():
    """Close Redis connection."""
    global _redis_client

    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
        logger.info("redis_client_closed")


# -------------------------------------------
# Redis Service Class
# -------------------------------------------


class RedisService:
    """
    Redis service for session and state management.

    Provides high-level methods for:
    - Session storage
    - State checkpointing
    - Cache operations
    """

    # Key prefixes for namespace separation
    PREFIX_SESSION = "session:"
    PREFIX_STATE = "state:"
    PREFIX_CHECKPOINT = "checkpoint:"
    PREFIX_CACHE = "cache:"

    # Default TTLs
    DEFAULT_SESSION_TTL = timedelta(hours=24)
    DEFAULT_CACHE_TTL = timedelta(minutes=30)

    def __init__(self, client: redis.Redis):
        self.client = client

    # -------------------------------------------
    # Session Management
    # -------------------------------------------

    async def save_session(
        self,
        session_id: str,
        data: dict[str, Any],
        ttl: Optional[timedelta] = None,
    ) -> bool:
        """
        Save session data to Redis.

        Args:
            session_id: Unique session identifier
            data: Session data dictionary
            ttl: Time to live (default: 24 hours)

        Returns:
            True if saved successfully
        """
        key = f"{self.PREFIX_SESSION}{session_id}"
        ttl = ttl or self.DEFAULT_SESSION_TTL

        try:
            await self.client.setex(
                key,
                ttl,
                json.dumps(data, default=str),
            )
            logger.debug("session_saved", session_id=session_id)
            return True
        except Exception as e:
            logger.error("session_save_failed", session_id=session_id, error=str(e))
            return False

    async def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve session data from Redis.

        Args:
            session_id: Unique session identifier

        Returns:
            Session data dictionary or None if not found
        """
        key = f"{self.PREFIX_SESSION}{session_id}"

        try:
            data = await self.client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error("session_get_failed", session_id=session_id, error=str(e))
            return None

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session from Redis."""
        key = f"{self.PREFIX_SESSION}{session_id}"

        try:
            await self.client.delete(key)
            logger.debug("session_deleted", session_id=session_id)
            return True
        except Exception as e:
            logger.error("session_delete_failed", session_id=session_id, error=str(e))
            return False

    async def list_sessions(self, pattern: str = "*") -> list[str]:
        """
        List all session IDs matching pattern.

        Args:
            pattern: Glob pattern for matching (default: all)

        Returns:
            List of session IDs
        """
        key_pattern = f"{self.PREFIX_SESSION}{pattern}"

        try:
            keys = await self.client.keys(key_pattern)
            # Remove prefix from keys
            prefix_len = len(self.PREFIX_SESSION)
            return [key[prefix_len:] for key in keys]
        except Exception as e:
            logger.error("session_list_failed", error=str(e))
            return []

    # -------------------------------------------
    # State Checkpointing (for LangGraph)
    # -------------------------------------------

    async def save_checkpoint(
        self,
        session_id: str,
        thread_id: str,
        checkpoint_data: dict[str, Any],
    ) -> bool:
        """
        Save LangGraph checkpoint for a session.

        Args:
            session_id: Session identifier
            thread_id: LangGraph thread ID
            checkpoint_data: Checkpoint state data

        Returns:
            True if saved successfully
        """
        key = f"{self.PREFIX_CHECKPOINT}{session_id}:{thread_id}"

        try:
            await self.client.setex(
                key,
                self.DEFAULT_SESSION_TTL,
                json.dumps(checkpoint_data, default=str),
            )
            logger.debug(
                "checkpoint_saved",
                session_id=session_id,
                thread_id=thread_id,
            )
            return True
        except Exception as e:
            logger.error(
                "checkpoint_save_failed",
                session_id=session_id,
                thread_id=thread_id,
                error=str(e),
            )
            return False

    async def get_checkpoint(
        self,
        session_id: str,
        thread_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Retrieve LangGraph checkpoint.

        Args:
            session_id: Session identifier
            thread_id: LangGraph thread ID

        Returns:
            Checkpoint data or None
        """
        key = f"{self.PREFIX_CHECKPOINT}{session_id}:{thread_id}"

        try:
            data = await self.client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(
                "checkpoint_get_failed",
                session_id=session_id,
                thread_id=thread_id,
                error=str(e),
            )
            return None

    async def list_checkpoints(self, session_id: str) -> list[str]:
        """List all checkpoints for a session."""
        key_pattern = f"{self.PREFIX_CHECKPOINT}{session_id}:*"

        try:
            keys = await self.client.keys(key_pattern)
            prefix_len = len(f"{self.PREFIX_CHECKPOINT}{session_id}:")
            return [key[prefix_len:] for key in keys]
        except Exception as e:
            logger.error("checkpoint_list_failed", session_id=session_id, error=str(e))
            return []

    # -------------------------------------------
    # Cache Operations
    # -------------------------------------------

    async def cache_set(
        self,
        key: str,
        value: Any,
        ttl: Optional[timedelta] = None,
    ) -> bool:
        """
        Set a cache value.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live (default: 30 minutes)
        """
        cache_key = f"{self.PREFIX_CACHE}{key}"
        ttl = ttl or self.DEFAULT_CACHE_TTL

        try:
            await self.client.setex(
                cache_key,
                ttl,
                json.dumps(value, default=str),
            )
            return True
        except Exception as e:
            logger.error("cache_set_failed", key=key, error=str(e))
            return False

    async def cache_get(self, key: str) -> Optional[Any]:
        """Get a cached value."""
        cache_key = f"{self.PREFIX_CACHE}{key}"

        try:
            data = await self.client.get(cache_key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error("cache_get_failed", key=key, error=str(e))
            return None

    async def cache_delete(self, key: str) -> bool:
        """Delete a cached value."""
        cache_key = f"{self.PREFIX_CACHE}{key}"

        try:
            await self.client.delete(cache_key)
            return True
        except Exception as e:
            logger.error("cache_delete_failed", key=key, error=str(e))
            return False

    # -------------------------------------------
    # Health Check
    # -------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """
        Check Redis connection health.

        Returns:
            Health status dictionary
        """
        try:
            # Ping Redis
            await self.client.ping()

            # Get some stats
            info = await self.client.info("memory")

            return {
                "status": "healthy",
                "connected": True,
                "memory_used": info.get("used_memory_human", "unknown"),
            }
        except Exception as e:
            logger.error("redis_health_check_failed", error=str(e))
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
            }


# -------------------------------------------
# Service Factory
# -------------------------------------------

_redis_service: Optional[RedisService] = None


async def get_redis_service() -> RedisService:
    """Get or create RedisService singleton."""
    global _redis_service

    if _redis_service is None:
        client = await get_redis_client()
        _redis_service = RedisService(client)

    return _redis_service


async def reset_redis_service():
    """Reset Redis service (for testing)."""
    global _redis_service
    _redis_service = None
    await close_redis_client()
