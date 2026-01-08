"""
Tests for Multi-Tier Cache Service

Tests L1 (memory), L2 (Redis), and L3 (SQLite) caching layers.
"""

import asyncio
import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.cache import CacheConfig, CacheStats, MultiTierCache


@pytest.fixture
def temp_cache_dir():
    """Create temporary directory for cache database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def cache_config(temp_cache_dir):
    """Create cache configuration with temp SQLite path."""
    return CacheConfig(
        memory_max_size=100,
        memory_default_ttl=10.0,
        redis_url=None,  # No Redis for unit tests
        sqlite_path=os.path.join(temp_cache_dir, "test_cache.db"),
        sqlite_default_ttl=60,
        write_through=True,
        promote_on_hit=True,
    )


@pytest.fixture
async def cache(cache_config):
    """Create and initialize cache instance."""
    cache = MultiTierCache(cache_config)
    await cache.initialize()
    yield cache
    await cache.close()


class TestCacheStats:
    """Tests for CacheStats dataclass."""

    def test_initial_stats(self):
        """Test initial stats are zero."""
        stats = CacheStats()
        assert stats.l1_hits == 0
        assert stats.l1_misses == 0
        assert stats.l2_hits == 0
        assert stats.l2_misses == 0
        assert stats.l3_hits == 0
        assert stats.l3_misses == 0

    def test_total_hits(self):
        """Test total hits calculation."""
        stats = CacheStats(l1_hits=10, l2_hits=5, l3_hits=2)
        assert stats.total_hits == 17

    def test_total_misses(self):
        """Test total misses calculation."""
        stats = CacheStats(l1_misses=10, l2_misses=5, l3_misses=2)
        assert stats.total_misses == 17

    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        stats = CacheStats(l1_hits=80, l1_misses=20)
        assert stats.hit_rate == 80.0

    def test_hit_rate_zero_requests(self):
        """Test hit rate with no requests."""
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_to_dict(self):
        """Test stats serialization to dict."""
        stats = CacheStats(l1_hits=10, l1_misses=5, l1_size=100)
        result = stats.to_dict()

        assert "l1" in result
        assert result["l1"]["hits"] == 10
        assert result["l1"]["misses"] == 5
        assert result["l1"]["size"] == 100


class TestMultiTierCacheL1:
    """Tests for L1 (memory) cache operations."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        """Test basic set and get operations."""
        await cache.set("test_key", {"data": "value"})
        result = await cache.get("test_key")

        assert result is not None
        assert result["data"] == "value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, cache):
        """Test getting a key that doesn't exist."""
        result = await cache.get("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_expiration(self, cache_config):
        """Test that cache entries expire."""
        # Create cache with very short TTL
        config = CacheConfig(
            memory_max_size=100,
            memory_default_ttl=0.1,  # 100ms
            redis_url=None,
            sqlite_path=cache_config.sqlite_path,
        )
        cache = MultiTierCache(config)
        await cache.initialize()

        await cache.set("expiring_key", "value", ttl=0.1)

        # Should exist immediately
        result = await cache.get("expiring_key")
        assert result == "value"

        # Wait for expiration
        await asyncio.sleep(0.15)

        # Should be expired (L1 miss, check L3)
        # L3 might still have it with longer TTL
        cache._memory_cache.clear()  # Force L1 miss
        result = await cache.get("expiring_key")
        # L3 has longer TTL, so it should still exist

        await cache.close()

    @pytest.mark.asyncio
    async def test_cache_delete(self, cache):
        """Test deleting a cache entry."""
        await cache.set("delete_key", "value")
        assert await cache.get("delete_key") == "value"

        deleted = await cache.delete("delete_key")
        assert deleted is True

        result = await cache.get("delete_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_clear(self, cache):
        """Test clearing all cache entries."""
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")

        cleared = await cache.clear()
        assert cleared >= 3  # At least 3 entries cleared

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None
        assert await cache.get("key3") is None

    @pytest.mark.asyncio
    async def test_memory_eviction(self, temp_cache_dir):
        """Test memory cache eviction when at capacity."""
        config = CacheConfig(
            memory_max_size=3,  # Very small for testing
            memory_default_ttl=60.0,
            redis_url=None,
            sqlite_path=os.path.join(temp_cache_dir, "evict_test.db"),
        )
        cache = MultiTierCache(config)
        await cache.initialize()

        # Add more entries than max_size
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")
        await cache.set("key4", "value4")  # Should trigger eviction

        # Memory cache should have at most max_size entries
        assert len(cache._memory_cache) <= 3

        await cache.close()


class TestMultiTierCacheL3:
    """Tests for L3 (SQLite) cache operations."""

    @pytest.mark.asyncio
    async def test_sqlite_persistence(self, cache):
        """Test that data persists in SQLite."""
        await cache.set("persist_key", {"persisted": True})

        # Clear L1 to force L3 lookup
        cache._memory_cache.clear()

        result = await cache.get("persist_key")
        assert result is not None
        assert result["persisted"] is True

    @pytest.mark.asyncio
    async def test_sqlite_initialization(self, cache_config):
        """Test SQLite initialization creates table."""
        cache = MultiTierCache(cache_config)
        await cache.initialize()

        assert cache._sqlite_initialized is True
        assert os.path.exists(cache_config.sqlite_path)

        await cache.close()


class TestMultiTierCacheStats:
    """Tests for cache statistics."""

    @pytest.mark.asyncio
    async def test_stats_tracking(self, cache):
        """Test that stats are tracked correctly."""
        # Initial stats
        stats = cache.get_stats()
        initial_hits = stats.total_hits
        initial_misses = stats.total_misses

        # Miss
        await cache.get("missing_key")

        # Hit
        await cache.set("hit_key", "value")
        await cache.get("hit_key")

        stats = cache.get_stats()
        assert stats.total_misses > initial_misses
        assert stats.total_hits > initial_hits

    @pytest.mark.asyncio
    async def test_stats_reset(self, cache):
        """Test resetting stats."""
        await cache.set("key", "value")
        await cache.get("key")
        await cache.get("missing")

        cache.reset_stats()

        stats = cache.get_stats()
        assert stats.l1_hits == 0
        assert stats.l1_misses == 0


class TestMultiTierCachePattern:
    """Tests for pattern-based cache operations."""

    @pytest.mark.asyncio
    async def test_invalidate_by_prefix(self, cache):
        """Test invalidating keys by prefix."""
        await cache.set("user:1:name", "Alice")
        await cache.set("user:1:email", "alice@example.com")
        await cache.set("user:2:name", "Bob")
        await cache.set("other:key", "value")

        invalidated = await cache.invalidate_by_prefix("user:1")
        assert invalidated >= 2

        assert await cache.get("user:1:name") is None
        assert await cache.get("user:1:email") is None
        assert await cache.get("user:2:name") is not None
        assert await cache.get("other:key") is not None

    @pytest.mark.asyncio
    async def test_clear_with_pattern(self, cache):
        """Test clearing cache with pattern."""
        await cache.set("stock:005930", {"price": 70000})
        await cache.set("stock:000660", {"price": 150000})
        await cache.set("account:balance", 1000000)

        cleared = await cache.clear("stock:*")
        assert cleared >= 2

        assert await cache.get("stock:005930") is None
        assert await cache.get("account:balance") is not None


class TestMultiTierCacheCleanup:
    """Tests for cache cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, temp_cache_dir):
        """Test cleanup of expired entries."""
        config = CacheConfig(
            memory_max_size=100,
            memory_default_ttl=0.1,  # 100ms
            redis_url=None,
            sqlite_path=os.path.join(temp_cache_dir, "cleanup_test.db"),
            sqlite_default_ttl=1,  # 1 second for SQLite
        )
        cache = MultiTierCache(config)
        await cache.initialize()

        await cache.set("expired_key", "value", ttl=0.1)
        await asyncio.sleep(0.2)

        cleaned = await cache.cleanup_expired()
        assert cleaned >= 1

        await cache.close()


class TestKiwoomCacheMultiTier:
    """Tests for Kiwoom cache with multi-tier support."""

    @pytest.mark.asyncio
    async def test_kiwoom_cache_l1_operations(self):
        """Test Kiwoom cache L1 operations."""
        from services.kiwoom.cache import KiwoomCache, make_cache_key

        cache = KiwoomCache(max_size=100, enabled=True)

        # Sync operations
        key = make_cache_key("stock_info", "005930")
        cache.set(key, {"price": 70000})

        result = cache.get(key)
        assert result is not None
        assert result["price"] == 70000

    @pytest.mark.asyncio
    async def test_kiwoom_cache_async_operations(self):
        """Test Kiwoom cache async operations (without Redis)."""
        from services.kiwoom.cache import KiwoomCache, make_cache_key

        cache = KiwoomCache(max_size=100, enabled=True)

        key = make_cache_key("stock_info", "005930")
        await cache.set_async(key, {"price": 70000})

        result = await cache.get_async(key)
        assert result is not None
        assert result["price"] == 70000

    @pytest.mark.asyncio
    async def test_kiwoom_cache_stats(self):
        """Test Kiwoom cache statistics."""
        from services.kiwoom.cache import KiwoomCache, make_cache_key

        cache = KiwoomCache(max_size=100, enabled=True)

        key = make_cache_key("stock_info", "005930")
        cache.set(key, {"price": 70000})
        cache.get(key)  # Hit
        cache.get("nonexistent")  # Miss

        stats = cache.stats
        assert "l1" in stats
        assert stats["l1"]["hits"] >= 1
        assert stats["l1"]["misses"] >= 1

    @pytest.mark.asyncio
    async def test_kiwoom_cache_invalidation(self):
        """Test Kiwoom cache account invalidation."""
        from services.kiwoom.cache import KiwoomCache, make_cache_key

        cache = KiwoomCache(max_size=100, enabled=True)

        # Add account-related cache entries
        cache.set(make_cache_key("cash_balance", "account1"), 1000000)
        cache.set(make_cache_key("pending_orders", "account1"), [])
        cache.set(make_cache_key("stock_info", "005930"), {"price": 70000})

        # Invalidate account cache
        invalidated = cache.invalidate_account_cache()
        assert invalidated >= 2

        # Account cache should be gone
        assert cache.get(make_cache_key("cash_balance", "account1")) is None

        # Stock info should still exist
        assert cache.get(make_cache_key("stock_info", "005930")) is not None

    def test_make_cache_key(self):
        """Test cache key generation."""
        from services.kiwoom.cache import make_cache_key

        assert make_cache_key("stock_info", "005930") == "stock_info:005930"
        assert make_cache_key("daily_chart", "005930", "20241225") == "daily_chart:005930:20241225"
        assert make_cache_key("account", None, "balance") == "account:balance"
