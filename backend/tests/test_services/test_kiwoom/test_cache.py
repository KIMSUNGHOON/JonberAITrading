"""
Kiwoom Cache Unit Tests

Tests for in-memory TTL cache functionality.
"""

import time

import pytest

from services.kiwoom.cache import CacheEntry, KiwoomCache, make_cache_key


class TestCacheEntry:
    """CacheEntry unit tests"""

    def test_cache_entry_creation(self):
        """Test creating a cache entry"""
        entry = CacheEntry(value="test", expires_at=time.time() + 10)

        assert entry.value == "test"
        assert not entry.is_expired
        assert entry.ttl_remaining > 0

    def test_cache_entry_expired(self):
        """Test expired cache entry"""
        entry = CacheEntry(value="test", expires_at=time.time() - 1)

        assert entry.is_expired
        assert entry.ttl_remaining == 0

    def test_cache_entry_ttl_remaining(self):
        """Test ttl_remaining calculation"""
        entry = CacheEntry(value="test", expires_at=time.time() + 5)

        ttl = entry.ttl_remaining
        assert 4 < ttl <= 5


class TestKiwoomCache:
    """KiwoomCache unit tests"""

    def test_cache_initialization(self):
        """Test cache initializes correctly"""
        cache = KiwoomCache(max_size=100, enabled=True)

        assert cache.enabled is True
        assert cache.size == 0
        assert cache._max_size == 100

    def test_cache_disabled(self):
        """Test disabled cache returns None"""
        cache = KiwoomCache(enabled=False)

        cache.set("key", "value")
        result = cache.get("key")

        assert result is None
        assert cache.size == 0

    def test_cache_set_and_get(self):
        """Test setting and getting cache values"""
        cache = KiwoomCache()

        cache.set("test_key", "test_value", ttl=10.0)
        result = cache.get("test_key")

        assert result == "test_value"

    def test_cache_miss(self):
        """Test cache miss returns None"""
        cache = KiwoomCache()

        result = cache.get("nonexistent_key")

        assert result is None

    def test_cache_expiration(self):
        """Test cache entry expiration"""
        cache = KiwoomCache()

        cache.set("test_key", "test_value", ttl=0.05)  # 50ms TTL
        time.sleep(0.1)  # Wait 100ms

        result = cache.get("test_key")

        assert result is None

    def test_cache_delete(self):
        """Test deleting cache entry"""
        cache = KiwoomCache()

        cache.set("test_key", "test_value", ttl=10.0)
        assert cache.get("test_key") == "test_value"

        deleted = cache.delete("test_key")

        assert deleted is True
        assert cache.get("test_key") is None

    def test_cache_delete_nonexistent(self):
        """Test deleting nonexistent entry"""
        cache = KiwoomCache()

        deleted = cache.delete("nonexistent_key")

        assert deleted is False

    def test_cache_clear(self):
        """Test clearing all cache entries"""
        cache = KiwoomCache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        cleared = cache.clear()

        assert cleared == 3
        assert cache.size == 0

    def test_default_ttl_stock_info(self):
        """Test default TTL for stock_info prefix"""
        cache = KiwoomCache()

        cache.set("stock_info:005930", "data")
        entry = cache._cache.get("stock_info:005930")

        assert entry is not None
        # stock_info TTL is 3 seconds
        assert 2.5 < entry.ttl_remaining <= 3.0

    def test_default_ttl_orderbook(self):
        """Test default TTL for orderbook prefix"""
        cache = KiwoomCache()

        cache.set("orderbook:005930", "data")
        entry = cache._cache.get("orderbook:005930")

        assert entry is not None
        # orderbook TTL is 2 seconds
        assert 1.5 < entry.ttl_remaining <= 2.0

    def test_default_ttl_daily_chart(self):
        """Test default TTL for daily_chart prefix"""
        cache = KiwoomCache()

        cache.set("daily_chart:005930:20241225", "data")
        entry = cache._cache.get("daily_chart:005930:20241225")

        assert entry is not None
        # daily_chart TTL is 3600 seconds (1 hour)
        assert 3599 < entry.ttl_remaining <= 3600

    def test_default_ttl_account_balance(self):
        """Test default TTL for account_balance prefix"""
        cache = KiwoomCache()

        cache.set("account_balance", "data")
        entry = cache._cache.get("account_balance")

        assert entry is not None
        # account_balance TTL is 30 seconds
        assert 29 < entry.ttl_remaining <= 30

    def test_invalidate_account_cache(self):
        """Test invalidating account-related cache"""
        cache = KiwoomCache()

        # Set various cache entries
        cache.set("stock_info:005930", "stock_data")
        cache.set("cash_balance", "cash_data")
        cache.set("account_balance", "account_data")
        cache.set("pending_orders", "pending_data")
        cache.set("filled_orders", "filled_data")

        assert cache.size == 5

        # Invalidate account cache
        invalidated = cache.invalidate_account_cache()

        # Should invalidate 4 entries (cash_balance, account_balance, pending_orders, filled_orders)
        assert invalidated == 4
        assert cache.size == 1
        assert cache.get("stock_info:005930") == "stock_data"
        assert cache.get("cash_balance") is None
        assert cache.get("account_balance") is None

    def test_cache_stats(self):
        """Test cache statistics"""
        cache = KiwoomCache()

        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("key1")  # hit
        cache.get("nonexistent")  # miss

        stats = cache.stats

        assert stats["enabled"] is True
        assert stats["size"] == 1
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert "hit_rate" in stats

    def test_cache_max_size_eviction(self):
        """Test cache evicts oldest entries when max size reached"""
        cache = KiwoomCache(max_size=3)

        cache.set("key1", "value1", ttl=100)
        time.sleep(0.01)
        cache.set("key2", "value2", ttl=100)
        time.sleep(0.01)
        cache.set("key3", "value3", ttl=100)
        time.sleep(0.01)

        assert cache.size == 3

        # Adding 4th item should evict oldest (key1)
        cache.set("key4", "value4", ttl=100)

        assert cache.size == 3
        assert cache.get("key1") is None  # evicted
        assert cache.get("key4") == "value4"

    def test_cache_expired_eviction(self):
        """Test expired entries are evicted first"""
        cache = KiwoomCache(max_size=3)

        cache.set("key1", "value1", ttl=0.01)  # Will expire quickly
        cache.set("key2", "value2", ttl=100)
        cache.set("key3", "value3", ttl=100)

        time.sleep(0.02)  # Wait for key1 to expire

        # Adding 4th item should evict expired key1 first
        cache.set("key4", "value4", ttl=100)

        assert cache.size == 3
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_reset_stats(self):
        """Test resetting cache statistics"""
        cache = KiwoomCache()

        cache.set("key", "value")
        cache.get("key")
        cache.get("nonexistent")

        assert cache.stats["hits"] > 0

        cache.reset_stats()

        assert cache.stats["hits"] == 0
        assert cache.stats["misses"] == 0

    def test_enabled_setter(self):
        """Test enabling/disabling cache via property"""
        cache = KiwoomCache(enabled=True)

        cache.set("key", "value")
        assert cache.get("key") == "value"

        # Disable cache (should clear all entries)
        cache.enabled = False

        assert cache.enabled is False
        assert cache.size == 0
        assert cache.get("key") is None


class TestMakeCacheKey:
    """make_cache_key function tests"""

    def test_single_arg(self):
        """Test cache key with single argument"""
        key = make_cache_key("stock_info", "005930")
        assert key == "stock_info:005930"

    def test_multiple_args(self):
        """Test cache key with multiple arguments"""
        key = make_cache_key("daily_chart", "005930", "20241225")
        assert key == "daily_chart:005930:20241225"

    def test_no_args(self):
        """Test cache key with no arguments"""
        key = make_cache_key("cash_balance")
        assert key == "cash_balance"

    def test_none_args_filtered(self):
        """Test None arguments are filtered out"""
        key = make_cache_key("test", "arg1", None, "arg2")
        assert key == "test:arg1:arg2"

    def test_numeric_args(self):
        """Test numeric arguments are converted to strings"""
        key = make_cache_key("test", 123, 456)
        assert key == "test:123:456"


class TestCacheIntegration:
    """Integration tests for cache with client behavior simulation"""

    def test_cache_workflow(self):
        """Test typical cache workflow"""
        cache = KiwoomCache()

        # First call - cache miss, store result
        cache_key = make_cache_key("stock_info", "005930")
        cached = cache.get(cache_key)
        assert cached is None

        # Simulate API response and cache it
        api_result = {"stk_cd": "005930", "cur_prc": 50000}
        cache.set(cache_key, api_result)

        # Second call - cache hit
        cached = cache.get(cache_key)
        assert cached == api_result

        # After order - invalidate account cache
        cache.set("account_balance", {"total": 1000000})
        cache.invalidate_account_cache()

        # Stock info should still be cached
        assert cache.get(cache_key) == api_result
        # Account balance should be invalidated
        assert cache.get("account_balance") is None
