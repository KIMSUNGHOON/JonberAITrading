"""
GPU Monitor Service

Monitors GPU memory usage and provides dynamic concurrency recommendations.
Supports NVIDIA GPUs via nvidia-smi or pynvml.

Optimized for:
- RTX 3090 (24GB VRAM) - Primary target
- Lower VRAM cards with automatic scaling
"""

import asyncio
import subprocess
import time
from typing import Optional, Tuple
from dataclasses import dataclass, field
from collections import deque

import structlog

logger = structlog.get_logger()


@dataclass
class GPUStats:
    """GPU statistics"""
    gpu_id: int = 0
    name: str = "Unknown"
    memory_used_mb: int = 0
    memory_total_mb: int = 0
    memory_free_mb: int = 0
    utilization_pct: float = 0.0
    temperature_c: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def memory_usage_pct(self) -> float:
        if self.memory_total_mb == 0:
            return 0.0
        return (self.memory_used_mb / self.memory_total_mb) * 100

    @property
    def is_high_memory_pressure(self) -> bool:
        """Check if GPU is under high memory pressure (>85%)."""
        return self.memory_usage_pct > 85.0

    @property
    def is_critical_memory(self) -> bool:
        """Check if GPU is in critical memory state (>95%)."""
        return self.memory_usage_pct > 95.0

    @property
    def is_overheating(self) -> bool:
        """Check if GPU temperature is too high (>85°C)."""
        return self.temperature_c > 85


class GPUMonitor:
    """
    GPU monitoring service for dynamic concurrency control.

    Features:
    - Real-time GPU memory monitoring
    - Dynamic concurrency recommendations based on memory usage
    - Adaptive batch size calculation based on available memory
    - Temperature-based throttling
    - Memory pressure detection with graceful degradation
    - Support for NVIDIA GPUs via nvidia-smi

    Optimized for RTX 3090 (24GB):
    - LLM inference typically uses 8-16GB depending on model
    - Batch processing can use additional memory
    - Leave headroom for system stability
    """

    # Concurrency thresholds based on GPU memory usage (more granular for large VRAM)
    # Optimized for RTX 3090 24GB running DeepSeek-R1
    THRESHOLDS = {
        0.95: 1,   # 95%+ usage -> 1 concurrent (critical)
        0.90: 1,   # 90-95% usage -> 1 concurrent
        0.85: 2,   # 85-90% usage -> 2 concurrent
        0.80: 3,   # 80-85% usage -> 3 concurrent
        0.70: 4,   # 70-80% usage -> 4 concurrent
        0.60: 5,   # 60-70% usage -> 5 concurrent
        0.50: 6,   # 50-60% usage -> 6 concurrent
        0.40: 7,   # 40-50% usage -> 7 concurrent
        0.0: 8,    # <40% usage -> 8 concurrent (max throughput)
    }

    # Batch size recommendations based on free memory (MB)
    # For LLM batch processing with context
    BATCH_SIZE_THRESHOLDS = {
        16000: 20,  # 16GB+ free -> batch of 20
        12000: 15,  # 12-16GB free -> batch of 15
        8000: 10,   # 8-12GB free -> batch of 10
        4000: 5,    # 4-8GB free -> batch of 5
        2000: 3,    # 2-4GB free -> batch of 3
        0: 1,       # <2GB free -> batch of 1
    }

    MIN_CONCURRENT = 1
    MAX_CONCURRENT = 8
    DEFAULT_CONCURRENT = 3

    # Cache settings
    STATS_CACHE_TTL_MS = 500  # Cache stats for 500ms to reduce nvidia-smi calls

    def __init__(self):
        self._available = None
        self._last_stats: Optional[GPUStats] = None
        self._last_stats_time: float = 0
        self._pynvml_initialized = False
        # Track memory usage history for trend analysis
        self._memory_history: deque = deque(maxlen=10)
        # Track concurrency adjustments to prevent oscillation
        self._last_concurrency: int = self.DEFAULT_CONCURRENT
        self._concurrency_stable_count: int = 0

    async def is_available(self) -> bool:
        """Check if GPU monitoring is available."""
        if self._available is not None:
            return self._available

        try:
            # Try nvidia-smi first
            result = await asyncio.to_thread(
                subprocess.run,
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self._available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._available = False
        except Exception as e:
            logger.warning(f"GPU availability check failed: {e}")
            self._available = False

        logger.info(f"GPU monitoring available: {self._available}")
        return self._available

    async def get_stats(self, force_refresh: bool = False) -> Optional[GPUStats]:
        """
        Get current GPU statistics with caching.

        Args:
            force_refresh: If True, bypass cache and fetch fresh stats

        Returns:
            GPUStats or None if unavailable
        """
        if not await self.is_available():
            return None

        # Check cache validity (all in seconds)
        current_time = time.time()
        cache_age_ms = (current_time - self._last_stats_time) * 1000

        if not force_refresh and self._last_stats and cache_age_ms < self.STATS_CACHE_TTL_MS:
            return self._last_stats

        try:
            # Query GPU stats via nvidia-smi
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.used,memory.total,memory.free,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits"
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return self._last_stats

            # Parse output (use first GPU if multiple)
            line = result.stdout.strip().split('\n')[0]
            parts = [p.strip() for p in line.split(',')]

            if len(parts) >= 7:
                stats = GPUStats(
                    gpu_id=int(parts[0]),
                    name=parts[1],
                    memory_used_mb=int(parts[2]),
                    memory_total_mb=int(parts[3]),
                    memory_free_mb=int(parts[4]),
                    utilization_pct=float(parts[5]),
                    temperature_c=int(parts[6]),
                    timestamp=time.time(),
                )
                self._last_stats = stats
                self._last_stats_time = time.time()

                # Track memory history for trend analysis
                self._memory_history.append(stats.memory_usage_pct)

                return stats

        except Exception as e:
            logger.warning("gpu_stats_fetch_failed", error=str(e))

        return self._last_stats

    async def get_optimal_concurrency(self) -> int:
        """
        Get optimal concurrency based on current GPU memory usage.

        Features:
        - Temperature-based throttling
        - Oscillation prevention (gradual changes)
        - Memory trend analysis

        Returns:
            Recommended number of concurrent tasks
        """
        stats = await self.get_stats()

        if stats is None:
            logger.debug("no_gpu_stats_available", using="default_concurrency")
            return self.DEFAULT_CONCURRENT

        # Temperature throttling - reduce concurrency if overheating
        if stats.is_overheating:
            logger.warning(
                "gpu_overheating_throttle",
                temperature=stats.temperature_c,
                concurrency=1,
            )
            self._last_concurrency = 1
            return 1

        # Critical memory - immediate reduction to minimum
        if stats.is_critical_memory:
            logger.warning(
                "gpu_critical_memory",
                usage_pct=stats.memory_usage_pct,
                concurrency=1,
            )
            self._last_concurrency = 1
            return 1

        usage_ratio = stats.memory_usage_pct / 100.0

        # Find appropriate concurrency based on thresholds
        target_concurrency = self.MAX_CONCURRENT
        for threshold, concurrency in sorted(self.THRESHOLDS.items(), reverse=True):
            if usage_ratio >= threshold:
                target_concurrency = concurrency
                break

        # Oscillation prevention: only change by 1 at a time unless critical
        if target_concurrency < self._last_concurrency:
            # Memory pressure increasing - reduce faster (by up to 2)
            new_concurrency = max(
                target_concurrency,
                self._last_concurrency - 2,
            )
        elif target_concurrency > self._last_concurrency:
            # Memory freed up - increase slowly (by 1)
            new_concurrency = min(
                target_concurrency,
                self._last_concurrency + 1,
            )
        else:
            new_concurrency = target_concurrency

        # Track stability
        if new_concurrency == self._last_concurrency:
            self._concurrency_stable_count += 1
        else:
            self._concurrency_stable_count = 0
            logger.info(
                "gpu_concurrency_adjusted",
                old=self._last_concurrency,
                new=new_concurrency,
                memory_usage_pct=round(stats.memory_usage_pct, 1),
            )

        self._last_concurrency = new_concurrency
        return new_concurrency

    async def get_optimal_batch_size(self, default: int = 10) -> int:
        """
        Get optimal batch size based on available GPU memory.

        This is useful for LLM batch processing where larger batches
        are more efficient but require more memory.

        Args:
            default: Default batch size if GPU not available

        Returns:
            Recommended batch size
        """
        stats = await self.get_stats()

        if stats is None:
            return default

        # Use free memory to determine batch size
        free_mb = stats.memory_free_mb

        for threshold_mb, batch_size in sorted(
            self.BATCH_SIZE_THRESHOLDS.items(), reverse=True
        ):
            if free_mb >= threshold_mb:
                logger.debug(
                    "gpu_batch_size_calculated",
                    free_mb=free_mb,
                    batch_size=batch_size,
                )
                return batch_size

        return 1  # Minimum batch size

    def get_memory_trend(self) -> str:
        """
        Analyze memory usage trend.

        Returns:
            "increasing", "decreasing", or "stable"
        """
        if len(self._memory_history) < 3:
            return "stable"

        recent = list(self._memory_history)[-3:]
        if recent[-1] > recent[0] + 5:
            return "increasing"
        elif recent[-1] < recent[0] - 5:
            return "decreasing"
        return "stable"

    async def should_throttle(self) -> bool:
        """
        Check if we should throttle new tasks.

        Returns:
            True if system should wait before starting new tasks
        """
        stats = await self.get_stats()

        if stats is None:
            return False

        # Throttle if critical memory or overheating
        if stats.is_critical_memory or stats.is_overheating:
            return True

        # Throttle if memory usage is high AND increasing
        if stats.is_high_memory_pressure and self.get_memory_trend() == "increasing":
            return True

        return False

    async def get_memory_info(self) -> Tuple[int, int, float]:
        """
        Get GPU memory information.

        Returns:
            Tuple of (used_mb, total_mb, usage_percentage)
        """
        stats = await self.get_stats()

        if stats is None:
            return (0, 0, 0.0)

        return (
            stats.memory_used_mb,
            stats.memory_total_mb,
            stats.memory_usage_pct,
        )

    async def can_start_task(self, estimated_memory_mb: int = 2000) -> bool:
        """
        Check if there's enough GPU memory to start a new task.

        Args:
            estimated_memory_mb: Estimated memory required for the task (default: 2GB for LLM)

        Returns:
            True if there's enough memory, False otherwise
        """
        stats = await self.get_stats()

        if stats is None:
            return True  # Assume OK if can't check

        # Reserve at least 10% of total memory as buffer
        buffer_mb = stats.memory_total_mb * 0.1
        available = stats.memory_free_mb - buffer_mb

        can_start = available >= estimated_memory_mb

        if not can_start:
            logger.warning(
                f"Insufficient GPU memory: {stats.memory_free_mb}MB free, "
                f"need {estimated_memory_mb}MB + {buffer_mb:.0f}MB buffer"
            )

        return can_start


# Singleton instance with thread-safe initialization
import threading

_gpu_monitor: Optional[GPUMonitor] = None
_gpu_monitor_lock = threading.Lock()


def get_gpu_monitor() -> GPUMonitor:
    """Get or create the GPU monitor singleton (thread-safe)."""
    global _gpu_monitor

    if _gpu_monitor is None:
        with _gpu_monitor_lock:
            # Double-check locking pattern
            if _gpu_monitor is None:
                _gpu_monitor = GPUMonitor()

    return _gpu_monitor


async def get_gpu_optimal_concurrency() -> int:
    """Convenience function to get optimal concurrency."""
    monitor = get_gpu_monitor()
    return await monitor.get_optimal_concurrency()


async def get_gpu_optimal_batch_size(default: int = 10) -> int:
    """Convenience function to get optimal batch size."""
    monitor = get_gpu_monitor()
    return await monitor.get_optimal_batch_size(default)


async def should_throttle_gpu_tasks() -> bool:
    """Convenience function to check if GPU tasks should be throttled."""
    monitor = get_gpu_monitor()
    return await monitor.should_throttle()
