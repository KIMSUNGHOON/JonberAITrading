"""
Redis Service Tests
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import timedelta


class TestRedisServiceInit:
    """Tests for Redis service initialization."""

    @pytest.mark.asyncio
    async def test_get_redis_service_returns_instance(self):
        """get_redis_service should return RedisService instance."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.ping = AsyncMock()

            from services.redis_service import get_redis_service, reset_redis_service

            await reset_redis_service()
            service = await get_redis_service()

            assert service is not None
            await reset_redis_service()


class TestRedisServiceSession:
    """Tests for Redis service session operations."""

    @pytest.mark.asyncio
    async def test_save_session_success(self):
        """save_session should store session data."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.setex = AsyncMock(return_value=True)

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            result = await service.save_session("test-session", {"key": "value"})

            assert result is True
            mock_client.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session_returns_data(self):
        """get_session should return stored data."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.get = AsyncMock(return_value='{"key": "value"}')

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            result = await service.get_session("test-session")

            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_session_returns_none_for_missing(self):
        """get_session should return None for non-existent session."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.get = AsyncMock(return_value=None)

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            result = await service.get_session("non-existent")

            assert result is None

    @pytest.mark.asyncio
    async def test_delete_session_success(self):
        """delete_session should remove session data."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.delete = AsyncMock(return_value=1)

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            result = await service.delete_session("test-session")

            assert result is True


class TestRedisServiceCache:
    """Tests for Redis service cache operations."""

    @pytest.mark.asyncio
    async def test_cache_set_success(self):
        """cache_set should store cached value."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.setex = AsyncMock(return_value=True)

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            result = await service.cache_set("test-key", {"data": "value"})

            assert result is True

    @pytest.mark.asyncio
    async def test_cache_get_returns_data(self):
        """cache_get should return cached value."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.get = AsyncMock(return_value='{"data": "value"}')

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            result = await service.cache_get("test-key")

            assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_cache_with_custom_ttl(self):
        """cache_set should accept custom TTL."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.setex = AsyncMock(return_value=True)

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            custom_ttl = timedelta(hours=1)
            result = await service.cache_set("test-key", "value", ttl=custom_ttl)

            assert result is True


class TestRedisServiceHealthCheck:
    """Tests for Redis service health check."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """health_check should return healthy status."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.info = AsyncMock(return_value={"used_memory_human": "1M"})

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            result = await service.health_check()

            assert result["status"] == "healthy"
            assert result["connected"] is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        """health_check should return unhealthy on connection error."""
        with patch("services.redis_service.redis") as mock_redis:
            mock_client = AsyncMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.ping = AsyncMock(side_effect=ConnectionError("Connection refused"))

            from services.redis_service import RedisService

            service = RedisService(mock_client)
            result = await service.health_check()

            assert result["status"] == "unhealthy"
            assert result["connected"] is False
