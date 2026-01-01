"""
Tests for GPU Monitor Service
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from services.gpu_monitor import (
    GPUStats,
    GPUMonitor,
    get_gpu_monitor,
    get_gpu_optimal_concurrency,
    get_gpu_optimal_batch_size,
    should_throttle_gpu_tasks,
)


class TestGPUStats:
    """Tests for GPUStats dataclass"""

    def test_memory_usage_pct_normal(self):
        stats = GPUStats(
            memory_used_mb=12000,
            memory_total_mb=24000,
        )
        assert stats.memory_usage_pct == 50.0

    def test_memory_usage_pct_zero_total(self):
        stats = GPUStats(memory_total_mb=0)
        assert stats.memory_usage_pct == 0.0

    def test_is_high_memory_pressure(self):
        # Not high pressure (50%)
        stats_low = GPUStats(memory_used_mb=12000, memory_total_mb=24000)
        assert not stats_low.is_high_memory_pressure

        # High pressure (86%)
        stats_high = GPUStats(memory_used_mb=20640, memory_total_mb=24000)
        assert stats_high.is_high_memory_pressure

    def test_is_critical_memory(self):
        # Not critical (80%)
        stats_ok = GPUStats(memory_used_mb=19200, memory_total_mb=24000)
        assert not stats_ok.is_critical_memory

        # Critical (96%)
        stats_critical = GPUStats(memory_used_mb=23040, memory_total_mb=24000)
        assert stats_critical.is_critical_memory

    def test_is_overheating(self):
        # Normal temperature
        stats_normal = GPUStats(temperature_c=65)
        assert not stats_normal.is_overheating

        # Overheating
        stats_hot = GPUStats(temperature_c=90)
        assert stats_hot.is_overheating


class TestGPUMonitor:
    """Tests for GPUMonitor class"""

    @pytest.fixture
    def monitor(self):
        return GPUMonitor()

    @pytest.mark.asyncio
    async def test_is_available_cached(self, monitor):
        """Test that availability is cached"""
        monitor._available = True
        result = await monitor.is_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_get_stats_caching(self, monitor):
        """Test stats caching"""
        monitor._available = True
        mock_stats = GPUStats(
            gpu_id=0,
            name="RTX 3090",
            memory_used_mb=8000,
            memory_total_mb=24000,
            memory_free_mb=16000,
            utilization_pct=50.0,
            temperature_c=60,
        )
        monitor._last_stats = mock_stats
        monitor._last_stats_time = float("inf")  # Far future to ensure cache hit

        # Should return cached stats
        result = await monitor.get_stats()
        assert result == mock_stats

    @pytest.mark.asyncio
    async def test_get_optimal_concurrency_default(self, monitor):
        """Test default concurrency when GPU not available"""
        monitor._available = False

        result = await monitor.get_optimal_concurrency()
        assert result == GPUMonitor.DEFAULT_CONCURRENT

    @pytest.mark.asyncio
    async def test_get_optimal_concurrency_low_usage(self, monitor):
        """Test concurrency with low GPU usage"""
        monitor._available = True
        # Set last concurrency to high so oscillation prevention doesn't limit
        monitor._last_concurrency = 8
        monitor._last_stats = GPUStats(
            memory_used_mb=7200,  # 30% of 24GB
            memory_total_mb=24000,
            memory_free_mb=16800,
            temperature_c=50,
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.get_optimal_concurrency()
        # With 30% usage, should recommend high concurrency (7-8)
        assert result >= 7

    @pytest.mark.asyncio
    async def test_get_optimal_concurrency_high_usage(self, monitor):
        """Test concurrency with high GPU usage"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=21600,  # 90% of 24GB
            memory_total_mb=24000,
            memory_free_mb=2400,
            temperature_c=70,
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.get_optimal_concurrency()
        # With 90% usage, should recommend low concurrency
        assert result <= 2

    @pytest.mark.asyncio
    async def test_get_optimal_concurrency_overheating(self, monitor):
        """Test concurrency reduction when overheating"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=8000,  # Low memory usage but
            memory_total_mb=24000,
            memory_free_mb=16000,
            temperature_c=90,  # Overheating!
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.get_optimal_concurrency()
        assert result == 1  # Should throttle to minimum

    @pytest.mark.asyncio
    async def test_get_optimal_concurrency_critical_memory(self, monitor):
        """Test concurrency reduction at critical memory"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=23500,  # 97.9% usage
            memory_total_mb=24000,
            memory_free_mb=500,
            temperature_c=60,
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.get_optimal_concurrency()
        assert result == 1  # Should throttle to minimum

    @pytest.mark.asyncio
    async def test_get_optimal_batch_size_high_memory(self, monitor):
        """Test batch size with high free memory"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=6000,
            memory_total_mb=24000,
            memory_free_mb=18000,  # 18GB free
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.get_optimal_batch_size()
        assert result >= 15  # Should allow large batch

    @pytest.mark.asyncio
    async def test_get_optimal_batch_size_low_memory(self, monitor):
        """Test batch size with low free memory"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=21000,
            memory_total_mb=24000,
            memory_free_mb=3000,  # 3GB free
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.get_optimal_batch_size()
        assert result <= 5  # Should use small batch

    def test_get_memory_trend_stable(self, monitor):
        """Test memory trend detection - stable"""
        monitor._memory_history.extend([50, 51, 50])
        assert monitor.get_memory_trend() == "stable"

    def test_get_memory_trend_increasing(self, monitor):
        """Test memory trend detection - increasing"""
        monitor._memory_history.extend([50, 55, 60])
        assert monitor.get_memory_trend() == "increasing"

    def test_get_memory_trend_decreasing(self, monitor):
        """Test memory trend detection - decreasing"""
        monitor._memory_history.extend([60, 55, 50])
        assert monitor.get_memory_trend() == "decreasing"

    def test_get_memory_trend_insufficient_data(self, monitor):
        """Test memory trend with insufficient data"""
        monitor._memory_history.extend([50, 55])  # Only 2 data points
        assert monitor.get_memory_trend() == "stable"

    @pytest.mark.asyncio
    async def test_should_throttle_critical(self, monitor):
        """Test throttle on critical memory"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=23500,  # >95%
            memory_total_mb=24000,
            memory_free_mb=500,
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.should_throttle()
        assert result is True

    @pytest.mark.asyncio
    async def test_should_throttle_overheating(self, monitor):
        """Test throttle on overheating"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=12000,
            memory_total_mb=24000,
            memory_free_mb=12000,
            temperature_c=90,  # Overheating
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.should_throttle()
        assert result is True

    @pytest.mark.asyncio
    async def test_should_throttle_false_normal(self, monitor):
        """Test no throttle in normal conditions"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=12000,  # 50%
            memory_total_mb=24000,
            memory_free_mb=12000,
            temperature_c=60,
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.should_throttle()
        assert result is False

    @pytest.mark.asyncio
    async def test_can_start_task_enough_memory(self, monitor):
        """Test can_start_task with enough memory"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=8000,
            memory_total_mb=24000,
            memory_free_mb=16000,
        )
        monitor._last_stats_time = float("inf")

        result = await monitor.can_start_task(estimated_memory_mb=2000)
        assert result is True

    @pytest.mark.asyncio
    async def test_can_start_task_insufficient_memory(self, monitor):
        """Test can_start_task with insufficient memory"""
        monitor._available = True
        monitor._last_stats = GPUStats(
            memory_used_mb=22000,
            memory_total_mb=24000,
            memory_free_mb=2000,  # Only 2GB free
        )
        monitor._last_stats_time = float("inf")

        # Need 4GB but only have 2GB - 2.4GB buffer = negative
        result = await monitor.can_start_task(estimated_memory_mb=4000)
        assert result is False


class TestConvenienceFunctions:
    """Tests for module-level convenience functions"""

    @pytest.mark.asyncio
    async def test_get_gpu_optimal_concurrency(self):
        """Test get_gpu_optimal_concurrency function"""
        with patch.object(GPUMonitor, 'get_optimal_concurrency', new_callable=AsyncMock) as mock:
            mock.return_value = 5
            result = await get_gpu_optimal_concurrency()
            assert result == 5

    @pytest.mark.asyncio
    async def test_get_gpu_optimal_batch_size(self):
        """Test get_gpu_optimal_batch_size function"""
        with patch.object(GPUMonitor, 'get_optimal_batch_size', new_callable=AsyncMock) as mock:
            mock.return_value = 15
            result = await get_gpu_optimal_batch_size()
            assert result == 15

    @pytest.mark.asyncio
    async def test_should_throttle_gpu_tasks(self):
        """Test should_throttle_gpu_tasks function"""
        with patch.object(GPUMonitor, 'should_throttle', new_callable=AsyncMock) as mock:
            mock.return_value = False
            result = await should_throttle_gpu_tasks()
            assert result is False
