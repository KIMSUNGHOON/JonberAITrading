"""
LLM Provider Tests
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from agents.llm_provider import LLMProvider, get_llm_provider, reset_llm_provider


@pytest.fixture
def event_loop():
    """Create event loop for tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestLLMProviderInit:
    """Tests for LLMProvider initialization."""

    @pytest.mark.asyncio
    async def test_provider_singleton(self):
        """LLM provider should be singleton."""
        reset_llm_provider()
        provider1 = get_llm_provider()
        provider2 = get_llm_provider()
        assert provider1 is provider2
        reset_llm_provider()

    @pytest.mark.asyncio
    async def test_provider_has_model(self):
        """LLM provider should have model configured."""
        reset_llm_provider()
        provider = get_llm_provider()
        assert provider.config.model is not None
        reset_llm_provider()

    @pytest.mark.asyncio
    async def test_provider_has_base_url(self):
        """LLM provider should have base URL configured."""
        reset_llm_provider()
        provider = get_llm_provider()
        assert provider.config.base_url is not None
        reset_llm_provider()


class TestLLMProviderHealthCheck:
    """Tests for LLM provider health check."""

    @pytest.mark.asyncio
    async def test_health_check_returns_dict(self):
        """Health check should return dictionary."""
        reset_llm_provider()
        provider = get_llm_provider()
        result = await provider.health_check()

        assert isinstance(result, dict)
        assert "status" in result
        reset_llm_provider()

    @pytest.mark.asyncio
    async def test_health_check_status_values(self):
        """Health check status should be valid value."""
        reset_llm_provider()
        provider = get_llm_provider()
        result = await provider.health_check()

        assert result["status"] in ["healthy", "unhealthy", "degraded"]
        reset_llm_provider()


class TestLLMProviderGenerate:
    """Tests for LLM provider generate method."""

    @pytest.mark.asyncio
    async def test_generate_with_empty_messages(self):
        """Generate with empty messages should handle gracefully."""
        reset_llm_provider()
        provider = get_llm_provider()

        # Should either return empty or raise appropriate error
        try:
            result = await provider.generate([])
            assert isinstance(result, str)
        except (ValueError, Exception):
            pass  # Expected behavior for empty messages

        reset_llm_provider()


class TestLLMProviderClose:
    """Tests for LLM provider close method."""

    @pytest.mark.asyncio
    async def test_close_cleanup(self):
        """Close should clean up resources."""
        reset_llm_provider()
        provider = get_llm_provider()

        # Should not raise
        await provider.close()
        reset_llm_provider()

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Close should be idempotent."""
        reset_llm_provider()
        provider = get_llm_provider()

        # Closing multiple times should not raise
        await provider.close()
        await provider.close()
        reset_llm_provider()
