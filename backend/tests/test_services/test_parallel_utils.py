"""
Tests for Parallel Processing Utilities
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from services.parallel_utils import (
    ParallelResult,
    parallel_gather,
    parallel_map,
    parallel_batch,
    ParallelAnalyzer,
)


class TestParallelResult:
    """Tests for ParallelResult dataclass"""

    def test_empty_result(self):
        result = ParallelResult()
        assert result.results == []
        assert result.errors == []
        assert result.success_count == 0
        assert result.error_count == 0
        assert result.duration_ms == 0.0

    def test_result_with_data(self):
        result = ParallelResult(
            results=[1, 2, 3],
            errors=[Exception("test")],
            duration_ms=100.5,
            success_count=3,
            error_count=1,
        )
        assert len(result.results) == 3
        assert len(result.errors) == 1
        assert result.success_count == 3


class TestParallelGather:
    """Tests for parallel_gather function"""

    @pytest.mark.asyncio
    async def test_gather_all_success(self):
        """Test gathering tasks that all succeed"""
        async def success_task(value: int):
            await asyncio.sleep(0.01)
            return value * 2

        tasks = [success_task(i) for i in range(5)]
        result = await parallel_gather(tasks)

        assert result.success_count == 5
        assert result.error_count == 0
        assert sorted(result.results) == [0, 2, 4, 6, 8]
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_gather_with_errors(self):
        """Test gathering tasks with some errors"""
        async def maybe_fail(value: int):
            if value % 2 == 0:
                raise ValueError(f"Even number: {value}")
            return value

        tasks = [maybe_fail(i) for i in range(5)]
        result = await parallel_gather(tasks, return_exceptions=True)

        assert result.success_count == 2  # 1, 3
        assert result.error_count == 3  # 0, 2, 4
        assert sorted(result.results) == [1, 3]

    @pytest.mark.asyncio
    async def test_gather_with_concurrency_limit(self):
        """Test concurrency limiting"""
        active = 0
        max_active = 0

        async def track_concurrency(value: int):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1
            return value

        tasks = [track_concurrency(i) for i in range(10)]
        result = await parallel_gather(tasks, max_concurrency=3)

        assert result.success_count == 10
        assert max_active <= 3  # Should never exceed concurrency limit

    @pytest.mark.asyncio
    async def test_gather_unlimited_concurrency(self):
        """Test without concurrency limit"""
        tasks = [asyncio.sleep(0.01) for _ in range(5)]
        result = await parallel_gather(tasks, max_concurrency=None)

        assert result.success_count == 5


class TestParallelMap:
    """Tests for parallel_map function"""

    @pytest.mark.asyncio
    async def test_map_success(self):
        """Test mapping function over items"""
        async def double(x: int) -> int:
            await asyncio.sleep(0.01)
            return x * 2

        items = [1, 2, 3, 4, 5]
        result = await parallel_map(items, double, max_concurrency=3)

        assert result.success_count == 5
        assert result.error_count == 0
        assert sorted(result.results) == [2, 4, 6, 8, 10]

    @pytest.mark.asyncio
    async def test_map_with_errors(self):
        """Test map with function that raises errors"""
        async def maybe_fail(x: int) -> int:
            if x > 3:
                raise ValueError(f"Too big: {x}")
            return x

        items = [1, 2, 3, 4, 5]
        result = await parallel_map(items, maybe_fail)

        assert result.success_count == 3
        assert result.error_count == 2

    @pytest.mark.asyncio
    async def test_map_with_progress_callback(self):
        """Test progress callback is called"""
        progress_calls = []

        def on_progress(completed: int, total: int):
            progress_calls.append((completed, total))

        async def identity(x: int) -> int:
            return x

        items = [1, 2, 3]
        result = await parallel_map(
            items, identity, max_concurrency=1, on_progress=on_progress
        )

        assert len(progress_calls) == 3
        # Should have progress updates for each item
        assert (3, 3) in progress_calls  # Final call


class TestParallelBatch:
    """Tests for parallel_batch function"""

    @pytest.mark.asyncio
    async def test_batch_processing(self):
        """Test batch processing"""
        async def process_batch(batch: list) -> list:
            await asyncio.sleep(0.01)
            return [x * 2 for x in batch]

        items = list(range(25))
        result = await parallel_batch(
            items,
            process_batch,
            batch_size=10,
            max_parallel_batches=2,
        )

        assert result.success_count == 25
        assert sorted(result.results) == [x * 2 for x in range(25)]

    @pytest.mark.asyncio
    async def test_batch_with_error(self):
        """Test batch processing with failing batch"""
        call_count = 0

        async def maybe_fail_batch(batch: list) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Batch failed")
            return batch

        items = list(range(30))
        result = await parallel_batch(
            items,
            maybe_fail_batch,
            batch_size=10,
            max_parallel_batches=3,
        )

        # 2 batches should succeed, 1 should fail
        assert result.success_count == 20
        assert result.error_count == 1


class TestParallelAnalyzer:
    """Tests for ParallelAnalyzer class"""

    @pytest.mark.asyncio
    async def test_run_empty(self):
        """Test running with no tasks"""
        analyzer = ParallelAnalyzer()
        results = await analyzer.run()
        assert results == {}

    @pytest.mark.asyncio
    async def test_run_multiple_tasks(self):
        """Test running multiple named tasks"""
        async def task_a():
            await asyncio.sleep(0.01)
            return {"signal": "buy"}

        async def task_b():
            await asyncio.sleep(0.01)
            return {"score": 0.8}

        analyzer = ParallelAnalyzer()
        analyzer.add_task("analysis_a", task_a())
        analyzer.add_task("analysis_b", task_b())

        results = await analyzer.run()

        assert "analysis_a" in results
        assert "analysis_b" in results
        assert results["analysis_a"]["signal"] == "buy"
        assert results["analysis_b"]["score"] == 0.8

    @pytest.mark.asyncio
    async def test_run_with_failing_task(self):
        """Test running with one failing task"""
        async def success_task():
            return "ok"

        async def fail_task():
            raise ValueError("Task failed")

        analyzer = ParallelAnalyzer()
        analyzer.add_task("success", success_task())
        analyzer.add_task("failure", fail_task())

        results = await analyzer.run()

        assert results["success"] == "ok"
        assert results["failure"] is None  # Failed task returns None

    @pytest.mark.asyncio
    async def test_run_with_timeout(self):
        """Test timeout handling"""
        async def slow_task():
            await asyncio.sleep(10)  # Very slow
            return "done"

        analyzer = ParallelAnalyzer(timeout=0.1)  # Short timeout
        analyzer.add_task("slow", slow_task())

        results = await analyzer.run()

        # Should return empty dict on timeout
        assert results == {}

    @pytest.mark.asyncio
    async def test_chained_add_task(self):
        """Test chained add_task calls"""
        async def task():
            return 1

        analyzer = ParallelAnalyzer()
        result = analyzer.add_task("a", task()).add_task("b", task())

        assert result is analyzer
        assert len(analyzer._tasks) == 2

    @pytest.mark.asyncio
    async def test_clear_tasks(self):
        """Test clearing tasks"""
        async def task():
            return 1

        analyzer = ParallelAnalyzer()
        analyzer.add_task("test", task())
        assert len(analyzer._tasks) == 1

        analyzer.clear()
        assert len(analyzer._tasks) == 0

    @pytest.mark.asyncio
    async def test_parallel_execution_performance(self):
        """Test that tasks run in parallel (not sequentially)"""
        import time

        async def slow_task():
            await asyncio.sleep(0.1)
            return "done"

        analyzer = ParallelAnalyzer()
        # Add 5 tasks that each take 100ms
        for i in range(5):
            analyzer.add_task(f"task_{i}", slow_task())

        start = time.perf_counter()
        results = await analyzer.run()
        elapsed = time.perf_counter() - start

        # If parallel, should take ~100ms, not 500ms
        assert elapsed < 0.3  # Allow some overhead
        assert len(results) == 5
