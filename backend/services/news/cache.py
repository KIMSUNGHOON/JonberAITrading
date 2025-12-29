"""
News Cache Manager

Provides caching layer for news API responses and usage tracking.
Uses Redis for distributed caching.
"""

import logging
from datetime import datetime
from typing import Optional, Union

logger = logging.getLogger(__name__)


class NewsCacheManager:
    """
    Cache manager for news service.

    Handles:
    - Response caching (30 min default TTL)
    - Daily API usage tracking per provider
    - Rate limiting support
    """

    # Cache key prefixes
    PREFIX_CACHE = "news:cache"
    PREFIX_USAGE = "news:usage"
    PREFIX_RATE = "news:rate"

    def __init__(self, redis_client):
        """
        Initialize cache manager.

        Args:
            redis_client: Redis async client (redis.asyncio.Redis)
        """
        self.redis = redis_client

    async def get(self, key: str) -> Optional[str]:
        """
        Get cached value.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        try:
            full_key = f"{self.PREFIX_CACHE}:{key}"
            value = await self.redis.get(full_key)
            if value:
                logger.debug(f"[Cache] Hit: {key}")
            return value
        except Exception as e:
            logger.warning(f"[Cache] Get error: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Union[str, bytes],
        ttl: int = 1800
    ) -> bool:
        """
        Set cached value with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (default: 30 minutes)

        Returns:
            True if successful
        """
        try:
            full_key = f"{self.PREFIX_CACHE}:{key}"
            await self.redis.setex(full_key, ttl, value)
            logger.debug(f"[Cache] Set: {key} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.warning(f"[Cache] Set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete cached value."""
        try:
            full_key = f"{self.PREFIX_CACHE}:{key}"
            await self.redis.delete(full_key)
            return True
        except Exception as e:
            logger.warning(f"[Cache] Delete error: {e}")
            return False

    async def get_usage(self, provider: str) -> int:
        """
        Get today's API usage count for a provider.

        Args:
            provider: Provider name (e.g., "naver")

        Returns:
            Number of API calls made today
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            key = f"{self.PREFIX_USAGE}:{provider}:{today}"
            value = await self.redis.get(key)
            return int(value) if value else 0
        except Exception as e:
            logger.warning(f"[Cache] Get usage error: {e}")
            return 0

    async def increment_usage(self, provider: str) -> int:
        """
        Increment today's API usage count.

        Args:
            provider: Provider name

        Returns:
            New usage count
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            key = f"{self.PREFIX_USAGE}:{provider}:{today}"

            # Increment and set expiry (24 hours + buffer)
            count = await self.redis.incr(key)
            await self.redis.expire(key, 90000)  # 25 hours

            logger.debug(f"[Cache] Usage incremented: {provider} = {count}")
            return count
        except Exception as e:
            logger.warning(f"[Cache] Increment usage error: {e}")
            return 0

    async def get_all_usage(self) -> dict:
        """
        Get usage for all providers today.

        Returns:
            Dict mapping provider name to usage count
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            pattern = f"{self.PREFIX_USAGE}:*:{today}"

            usage = {}
            async for key in self.redis.scan_iter(match=pattern):
                # Extract provider name from key
                parts = key.decode() if isinstance(key, bytes) else key
                parts = parts.split(":")
                if len(parts) >= 3:
                    provider = parts[-2]
                    value = await self.redis.get(key)
                    usage[provider] = int(value) if value else 0

            return usage
        except Exception as e:
            logger.warning(f"[Cache] Get all usage error: {e}")
            return {}

    async def check_rate_limit(
        self,
        provider: str,
        limit_per_second: int
    ) -> bool:
        """
        Check if rate limit allows a request.

        Args:
            provider: Provider name
            limit_per_second: Max requests per second

        Returns:
            True if request is allowed
        """
        if limit_per_second <= 0:
            return True

        try:
            now = datetime.now()
            key = f"{self.PREFIX_RATE}:{provider}:{now.strftime('%Y%m%d%H%M%S')}"

            count = await self.redis.incr(key)
            await self.redis.expire(key, 2)  # 2 second window

            return count <= limit_per_second
        except Exception as e:
            logger.warning(f"[Cache] Rate limit check error: {e}")
            return True  # Allow on error

    async def clear_cache(self, pattern: str = "*") -> int:
        """
        Clear cached responses matching pattern.

        Args:
            pattern: Key pattern to match

        Returns:
            Number of keys deleted
        """
        try:
            full_pattern = f"{self.PREFIX_CACHE}:{pattern}"
            deleted = 0

            async for key in self.redis.scan_iter(match=full_pattern):
                await self.redis.delete(key)
                deleted += 1

            logger.info(f"[Cache] Cleared {deleted} keys matching '{pattern}'")
            return deleted
        except Exception as e:
            logger.warning(f"[Cache] Clear cache error: {e}")
            return 0


class InMemoryCacheManager:
    """
    Simple in-memory cache for development/testing.
    Not suitable for production (no persistence, no distribution).
    """

    def __init__(self):
        self._cache: dict = {}
        self._usage: dict = {}
        self._expiry: dict = {}

    async def get(self, key: str) -> Optional[str]:
        full_key = f"cache:{key}"
        if full_key in self._cache:
            if full_key in self._expiry:
                if datetime.now().timestamp() > self._expiry[full_key]:
                    del self._cache[full_key]
                    del self._expiry[full_key]
                    return None
            return self._cache[full_key]
        return None

    async def set(self, key: str, value: str, ttl: int = 1800) -> bool:
        full_key = f"cache:{key}"
        self._cache[full_key] = value
        self._expiry[full_key] = datetime.now().timestamp() + ttl
        return True

    async def delete(self, key: str) -> bool:
        full_key = f"cache:{key}"
        if full_key in self._cache:
            del self._cache[full_key]
        if full_key in self._expiry:
            del self._expiry[full_key]
        return True

    async def get_usage(self, provider: str) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        key = f"{provider}:{today}"
        return self._usage.get(key, 0)

    async def increment_usage(self, provider: str) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        key = f"{provider}:{today}"
        self._usage[key] = self._usage.get(key, 0) + 1
        return self._usage[key]

    async def get_all_usage(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            k.split(":")[0]: v
            for k, v in self._usage.items()
            if k.endswith(today)
        }

    async def check_rate_limit(self, provider: str, limit_per_second: int) -> bool:
        return True  # No rate limiting in memory cache

    async def clear_cache(self, pattern: str = "*") -> int:
        # Simple implementation: clear all cache
        count = len(self._cache)
        self._cache.clear()
        self._expiry.clear()
        return count
