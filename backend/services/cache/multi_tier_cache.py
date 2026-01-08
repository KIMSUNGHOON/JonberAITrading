"""
Multi-Tier Cache Implementation

A unified caching layer with three tiers:
- L1 (Memory): Fast, process-local, limited size
- L2 (Redis): Distributed, shared across processes
- L3 (SQLite): Persistent, fallback storage

Usage:
    cache = await get_cache_service()

    # Set with automatic tier management
    await cache.set("key", {"data": "value"}, ttl=60)

    # Get with tier promotion (Redis -> Memory)
    value = await cache.get("key")

    # Get statistics
    stats = cache.get_stats()
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    """Configuration for multi-tier cache."""

    # L1 Memory settings
    memory_max_size: int = 1000
    memory_default_ttl: float = 60.0

    # L2 Redis settings
    redis_url: Optional[str] = None
    redis_default_ttl: int = 300
    redis_key_prefix: str = "cache"

    # L3 SQLite settings
    sqlite_path: str = "data/cache.db"
    sqlite_default_ttl: int = 3600

    # Behavior
    write_through: bool = True  # Write to all tiers
    promote_on_hit: bool = True  # Promote L2/L3 hits to L1


@dataclass
class CacheStats:
    """Cache statistics."""
    l1_hits: int = 0
    l1_misses: int = 0
    l2_hits: int = 0
    l2_misses: int = 0
    l3_hits: int = 0
    l3_misses: int = 0
    l1_size: int = 0
    redis_available: bool = False
    sqlite_available: bool = False

    @property
    def total_hits(self) -> int:
        return self.l1_hits + self.l2_hits + self.l3_hits

    @property
    def total_misses(self) -> int:
        return self.l1_misses + self.l2_misses + self.l3_misses

    @property
    def hit_rate(self) -> float:
        total = self.total_hits + self.total_misses
        return (self.total_hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "l1": {"hits": self.l1_hits, "misses": self.l1_misses, "size": self.l1_size},
            "l2": {"hits": self.l2_hits, "misses": self.l2_misses, "available": self.redis_available},
            "l3": {"hits": self.l3_hits, "misses": self.l3_misses, "available": self.sqlite_available},
            "total": {"hits": self.total_hits, "misses": self.total_misses, "hit_rate": f"{self.hit_rate:.1f}%"},
        }


@dataclass
class MemoryCacheEntry:
    """L1 memory cache entry."""
    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class MultiTierCache:
    """
    Multi-tier caching with L1 (Memory), L2 (Redis), L3 (SQLite).

    Provides:
    - Fast reads from memory cache
    - Distributed caching via Redis
    - Persistent fallback via SQLite
    - Automatic tier promotion on cache hits
    - Write-through for consistency
    """

    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or CacheConfig()

        # L1: Memory cache
        self._memory_cache: Dict[str, MemoryCacheEntry] = {}

        # L2: Redis client (lazy initialized)
        self._redis = None
        self._redis_available = False

        # L3: SQLite connection (lazy initialized)
        self._sqlite_path = self.config.sqlite_path
        self._sqlite_initialized = False

        # Statistics
        self._stats = CacheStats()

        # Lock for thread safety
        self._lock = asyncio.Lock()

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize cache backends."""
        # Initialize Redis
        await self._init_redis()

        # Initialize SQLite
        await self._init_sqlite()

        # Start periodic cleanup task
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

        logger.info(
            "multi_tier_cache_initialized",
            extra={
                "redis": self._redis_available,
                "sqlite": self._sqlite_initialized,
            }
        )

    async def _periodic_cleanup(self) -> None:
        """Periodically clean up expired entries (every 5 minutes)."""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                cleaned = await self.cleanup_expired()
                if cleaned > 0:
                    logger.info("cache_auto_cleanup", extra={"cleaned": cleaned})
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("cache_cleanup_task_failed", extra={"error": str(e)})

    async def _init_redis(self) -> None:
        """Initialize Redis connection."""
        if not self.config.redis_url:
            return

        try:
            import redis.asyncio as redis
            self._redis = redis.from_url(
                self.config.redis_url,
                decode_responses=True,
            )
            # Test connection
            await self._redis.ping()
            self._redis_available = True
            self._stats.redis_available = True
            logger.info("redis_cache_connected", extra={"url": self.config.redis_url})
        except ImportError:
            logger.warning("redis_package_not_installed")
        except Exception as e:
            logger.warning("redis_connection_failed", extra={"error": str(e)})

    async def _init_sqlite(self) -> None:
        """Initialize SQLite cache table."""
        try:
            import os
            os.makedirs(os.path.dirname(self._sqlite_path), exist_ok=True)

            async with aiosqlite.connect(self._sqlite_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS cache (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        created_at REAL DEFAULT (strftime('%s', 'now'))
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cache_expires
                    ON cache(expires_at)
                """)
                await db.commit()

            self._sqlite_initialized = True
            self._stats.sqlite_available = True
            logger.info("sqlite_cache_initialized", extra={"path": self._sqlite_path})
        except Exception as e:
            logger.warning("sqlite_cache_init_failed", extra={"error": str(e)})

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache, checking tiers in order.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        # L1: Check memory cache first (with lock protection)
        async with self._lock:
            value = self._get_from_memory(key)
            if value is not None:
                self._stats.l1_hits += 1
                return value
            self._stats.l1_misses += 1

        # L2: Check Redis
        if self._redis_available:
            value = await self._get_from_redis(key)
            if value is not None:
                self._stats.l2_hits += 1
                # Promote to L1 (with lock protection)
                if self.config.promote_on_hit:
                    async with self._lock:
                        self._set_to_memory(key, value, self.config.memory_default_ttl)
                return value
            self._stats.l2_misses += 1

        # L3: Check SQLite
        if self._sqlite_initialized:
            value = await self._get_from_sqlite(key)
            if value is not None:
                self._stats.l3_hits += 1
                # Promote to L1 and L2 (with lock protection)
                if self.config.promote_on_hit:
                    async with self._lock:
                        self._set_to_memory(key, value, self.config.memory_default_ttl)
                    if self._redis_available:
                        await self._set_to_redis(key, value, self.config.redis_default_ttl)
                return value
            self._stats.l3_misses += 1

        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        memory_only: bool = False,
    ) -> bool:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache (must be JSON serializable)
            ttl: Time-to-live in seconds
            memory_only: Only write to L1 memory cache

        Returns:
            True if successful
        """
        ttl = ttl or self.config.memory_default_ttl

        # L1: Always write to memory (with lock protection)
        async with self._lock:
            self._set_to_memory(key, value, ttl)

        if memory_only:
            return True

        # L2: Write to Redis (write-through)
        if self.config.write_through and self._redis_available:
            await self._set_to_redis(key, value, int(ttl))

        # L3: Write to SQLite (write-through for persistence)
        if self.config.write_through and self._sqlite_initialized:
            await self._set_to_sqlite(key, value, ttl)

        return True

    async def delete(self, key: str) -> bool:
        """
        Delete key from all cache tiers.

        Args:
            key: Cache key to delete

        Returns:
            True if deleted from any tier
        """
        deleted = False

        # L1: Delete from memory (with lock protection)
        async with self._lock:
            if key in self._memory_cache:
                del self._memory_cache[key]
                deleted = True

        # L2: Delete from Redis
        if self._redis_available:
            try:
                full_key = f"{self.config.redis_key_prefix}:{key}"
                await self._redis.delete(full_key)
                deleted = True
            except Exception as e:
                logger.warning("redis_delete_failed", extra={"key": key, "error": str(e)})

        # L3: Delete from SQLite
        if self._sqlite_initialized:
            try:
                async with aiosqlite.connect(self._sqlite_path) as db:
                    await db.execute("DELETE FROM cache WHERE key = ?", (key,))
                    await db.commit()
                deleted = True
            except Exception as e:
                logger.warning("sqlite_delete_failed", extra={"key": key, "error": str(e)})

        return deleted

    async def clear(self, pattern: str = "*") -> int:
        """
        Clear cache entries matching pattern.

        Args:
            pattern: Key pattern (supports * wildcard)

        Returns:
            Number of entries cleared
        """
        cleared = 0

        # L1: Clear memory cache (with lock protection)
        async with self._lock:
            if pattern == "*":
                cleared += len(self._memory_cache)
                self._memory_cache.clear()
            else:
                # Simple pattern matching
                import fnmatch
                keys_to_delete = [k for k in self._memory_cache if fnmatch.fnmatch(k, pattern)]
                for k in keys_to_delete:
                    del self._memory_cache[k]
                    cleared += 1

        # L2: Clear Redis
        if self._redis_available:
            try:
                full_pattern = f"{self.config.redis_key_prefix}:{pattern}"
                async for key in self._redis.scan_iter(match=full_pattern):
                    await self._redis.delete(key)
                    cleared += 1
            except Exception as e:
                logger.warning("redis_clear_failed", extra={"error": str(e)})

        # L3: Clear SQLite
        if self._sqlite_initialized:
            try:
                async with aiosqlite.connect(self._sqlite_path) as db:
                    if pattern == "*":
                        cursor = await db.execute("DELETE FROM cache")
                        cleared += cursor.rowcount
                    else:
                        # SQLite LIKE pattern
                        like_pattern = pattern.replace("*", "%")
                        cursor = await db.execute(
                            "DELETE FROM cache WHERE key LIKE ?",
                            (like_pattern,)
                        )
                        cleared += cursor.rowcount
                    await db.commit()
            except Exception as e:
                logger.warning("sqlite_clear_failed", extra={"error": str(e)})

        logger.info("cache_cleared", extra={"pattern": pattern, "cleared": cleared})
        return cleared

    async def invalidate_by_prefix(self, prefix: str) -> int:
        """
        Invalidate all keys with given prefix.

        Args:
            prefix: Key prefix to match

        Returns:
            Number of entries invalidated
        """
        return await self.clear(f"{prefix}*")

    # -------------------------------------------
    # L1 Memory Cache Operations
    # -------------------------------------------

    def _get_from_memory(self, key: str) -> Optional[Any]:
        """Get value from memory cache."""
        entry = self._memory_cache.get(key)
        if entry is None:
            return None

        if entry.is_expired:
            del self._memory_cache[key]
            return None

        return entry.value

    def _set_to_memory(self, key: str, value: Any, ttl: float) -> None:
        """Set value in memory cache."""
        # Evict if at capacity
        if len(self._memory_cache) >= self.config.memory_max_size:
            self._evict_memory()

        self._memory_cache[key] = MemoryCacheEntry(
            value=value,
            expires_at=time.time() + ttl,
        )
        self._stats.l1_size = len(self._memory_cache)

    def _evict_memory(self) -> None:
        """Evict expired or oldest entries from memory cache."""
        # First, remove expired entries
        now = time.time()
        expired = [k for k, v in self._memory_cache.items() if v.expires_at < now]
        for k in expired:
            del self._memory_cache[k]

        # If still at capacity, remove oldest 20% to create headroom
        if len(self._memory_cache) >= self.config.memory_max_size:
            target_size = int(self.config.memory_max_size * 0.8)
            num_to_remove = len(self._memory_cache) - target_size

            if num_to_remove > 0:
                sorted_keys = sorted(
                    self._memory_cache.keys(),
                    key=lambda k: self._memory_cache[k].created_at
                )
                for k in sorted_keys[:num_to_remove]:
                    del self._memory_cache[k]

    # -------------------------------------------
    # L2 Redis Cache Operations
    # -------------------------------------------

    async def _get_from_redis(self, key: str) -> Optional[Any]:
        """Get value from Redis cache."""
        if not self._redis_available:
            return None

        try:
            full_key = f"{self.config.redis_key_prefix}:{key}"
            value = await self._redis.get(full_key)
            if value is not None:
                return json.loads(value)
        except Exception as e:
            logger.warning("redis_get_failed", extra={"key": key, "error": str(e)})

        return None

    async def _set_to_redis(self, key: str, value: Any, ttl: int) -> bool:
        """Set value in Redis cache."""
        if not self._redis_available:
            return False

        try:
            full_key = f"{self.config.redis_key_prefix}:{key}"
            serialized = json.dumps(value, default=str)
            await self._redis.setex(full_key, ttl, serialized)
            return True
        except Exception as e:
            logger.warning("redis_set_failed", extra={"key": key, "error": str(e)})
            return False

    # -------------------------------------------
    # L3 SQLite Cache Operations
    # -------------------------------------------

    async def _get_from_sqlite(self, key: str) -> Optional[Any]:
        """Get value from SQLite cache."""
        if not self._sqlite_initialized:
            return None

        try:
            async with aiosqlite.connect(self._sqlite_path) as db:
                async with db.execute(
                    "SELECT value, expires_at FROM cache WHERE key = ?",
                    (key,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        value, expires_at = row
                        if time.time() < expires_at:
                            return json.loads(value)
                        # Expired, delete it
                        await db.execute("DELETE FROM cache WHERE key = ?", (key,))
                        await db.commit()
        except Exception as e:
            logger.warning("sqlite_get_failed", extra={"key": key, "error": str(e)})

        return None

    async def _set_to_sqlite(self, key: str, value: Any, ttl: float) -> bool:
        """Set value in SQLite cache."""
        if not self._sqlite_initialized:
            return False

        try:
            async with aiosqlite.connect(self._sqlite_path) as db:
                serialized = json.dumps(value, default=str)
                expires_at = time.time() + ttl
                await db.execute(
                    """
                    INSERT OR REPLACE INTO cache (key, value, expires_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, serialized, expires_at)
                )
                await db.commit()
            return True
        except Exception as e:
            logger.warning("sqlite_set_failed", extra={"key": key, "error": str(e)})
            return False

    # -------------------------------------------
    # Maintenance
    # -------------------------------------------

    async def cleanup_expired(self) -> int:
        """
        Clean up expired entries from all tiers.

        Returns:
            Number of entries cleaned
        """
        cleaned = 0

        # L1: Clean memory (with lock protection)
        async with self._lock:
            now = time.time()
            expired = [k for k, v in self._memory_cache.items() if v.expires_at < now]
            for k in expired:
                del self._memory_cache[k]
                cleaned += 1

        # L3: Clean SQLite
        if self._sqlite_initialized:
            try:
                async with aiosqlite.connect(self._sqlite_path) as db:
                    cursor = await db.execute(
                        "DELETE FROM cache WHERE expires_at < ?",
                        (time.time(),)
                    )
                    cleaned += cursor.rowcount
                    await db.commit()
            except Exception as e:
                logger.warning("sqlite_cleanup_failed", extra={"error": str(e)})

        self._stats.l1_size = len(self._memory_cache)
        return cleaned

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        self._stats.l1_size = len(self._memory_cache)
        self._stats.redis_available = self._redis_available
        self._stats.sqlite_available = self._sqlite_initialized
        return self._stats

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self._stats = CacheStats(
            l1_size=len(self._memory_cache),
            redis_available=self._redis_available,
            sqlite_available=self._sqlite_initialized,
        )

    async def close(self) -> None:
        """Close cache connections."""
        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Close Redis
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._redis_available = False


# -------------------------------------------
# Singleton Instance
# -------------------------------------------

_cache_instance: Optional[MultiTierCache] = None
_cache_lock = asyncio.Lock()


async def get_cache_service(config: Optional[CacheConfig] = None) -> MultiTierCache:
    """
    Get or create the singleton cache service.

    Args:
        config: Optional cache configuration

    Returns:
        MultiTierCache instance
    """
    global _cache_instance

    async with _cache_lock:
        if _cache_instance is None:
            from app.config import get_settings
            settings = get_settings()

            if config is None:
                config = CacheConfig(
                    redis_url=settings.REDIS_URL,
                    sqlite_path="data/cache.db",
                )

            _cache_instance = MultiTierCache(config)
            await _cache_instance.initialize()

        return _cache_instance
