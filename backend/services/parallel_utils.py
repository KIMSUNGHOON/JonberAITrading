"""
Parallel Processing Utilities

Provides utilities for parallel execution of async tasks with:
- Configurable concurrency limits
- Progress tracking
- Error handling and resilience
- Batch processing support
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class ParallelResult:
    """Result of a parallel execution."""
    results: List[Any] = field(default_factory=list)
    errors: List[Exception] = field(default_factory=list)
    duration_ms: float = 0.0
    success_count: int = 0
    error_count: int = 0


async def parallel_gather(
    tasks: List[Awaitable[T]],
    max_concurrency: Optional[int] = None,
    return_exceptions: bool = True,
) -> ParallelResult:
    """
    Execute multiple async tasks in parallel with optional concurrency limit.

    Args:
        tasks: List of awaitable tasks to execute
        max_concurrency: Maximum concurrent tasks (None = unlimited)
        return_exceptions: If True, exceptions are returned in results

    Returns:
        ParallelResult with results and execution statistics
    """
    start_time = time.perf_counter()

    if max_concurrency is not None and max_concurrency > 0:
        # Use semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrency)

        async def wrapped_task(task: Awaitable[T]) -> T:
            async with semaphore:
                return await task

        wrapped = [wrapped_task(t) for t in tasks]
        raw_results = await asyncio.gather(*wrapped, return_exceptions=return_exceptions)
    else:
        # No concurrency limit
        raw_results = await asyncio.gather(*tasks, return_exceptions=return_exceptions)

    duration_ms = (time.perf_counter() - start_time) * 1000

    # Separate results and errors
    results = []
    errors = []
    for r in raw_results:
        if isinstance(r, Exception):
            errors.append(r)
        else:
            results.append(r)

    return ParallelResult(
        results=results,
        errors=errors,
        duration_ms=duration_ms,
        success_count=len(results),
        error_count=len(errors),
    )


async def parallel_map(
    items: List[T],
    func: Callable[[T], Awaitable[R]],
    max_concurrency: int = 5,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> ParallelResult:
    """
    Apply an async function to items in parallel with concurrency control.

    Args:
        items: List of items to process
        func: Async function to apply to each item
        max_concurrency: Maximum concurrent operations
        on_progress: Optional callback (completed, total)

    Returns:
        ParallelResult with processed results
    """
    start_time = time.perf_counter()
    semaphore = asyncio.Semaphore(max_concurrency)
    completed = 0
    results = []
    errors = []

    async def process_item(item: T) -> Optional[R]:
        nonlocal completed
        async with semaphore:
            try:
                result = await func(item)
                completed += 1
                if on_progress:
                    on_progress(completed, len(items))
                return result
            except Exception as e:
                completed += 1
                if on_progress:
                    on_progress(completed, len(items))
                raise

    tasks = [process_item(item) for item in items]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in raw_results:
        if isinstance(r, Exception):
            errors.append(r)
        else:
            results.append(r)

    duration_ms = (time.perf_counter() - start_time) * 1000

    return ParallelResult(
        results=results,
        errors=errors,
        duration_ms=duration_ms,
        success_count=len(results),
        error_count=len(errors),
    )


async def parallel_batch(
    items: List[T],
    batch_func: Callable[[List[T]], Awaitable[List[R]]],
    batch_size: int = 10,
    max_parallel_batches: int = 3,
) -> ParallelResult:
    """
    Process items in batches with parallel batch execution.

    Args:
        items: List of items to process
        batch_func: Async function that processes a batch
        batch_size: Size of each batch
        max_parallel_batches: Maximum parallel batch executions

    Returns:
        ParallelResult with all batch results
    """
    start_time = time.perf_counter()

    # Create batches
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

    # Process batches in parallel
    semaphore = asyncio.Semaphore(max_parallel_batches)
    all_results = []
    errors = []

    async def process_batch(batch: List[T]) -> List[R]:
        async with semaphore:
            return await batch_func(batch)

    batch_results = await asyncio.gather(
        *[process_batch(b) for b in batches],
        return_exceptions=True
    )

    for r in batch_results:
        if isinstance(r, Exception):
            errors.append(r)
        elif isinstance(r, list):
            all_results.extend(r)
        else:
            all_results.append(r)

    duration_ms = (time.perf_counter() - start_time) * 1000

    return ParallelResult(
        results=all_results,
        errors=errors,
        duration_ms=duration_ms,
        success_count=len(all_results),
        error_count=len(errors),
    )


class ParallelAnalyzer:
    """
    Parallel analyzer for running multiple analysis functions concurrently.

    Usage:
        analyzer = ParallelAnalyzer()
        analyzer.add_task("technical", technical_analysis_func(state))
        analyzer.add_task("fundamental", fundamental_analysis_func(state))
        analyzer.add_task("sentiment", sentiment_analysis_func(state))

        results = await analyzer.run()
        # results = {"technical": {...}, "fundamental": {...}, "sentiment": {...}}
    """

    def __init__(self, timeout: float = 60.0):
        self._tasks: dict[str, Awaitable] = {}
        self._timeout = timeout

    def add_task(self, name: str, task: Awaitable) -> "ParallelAnalyzer":
        """Add a named task to execute."""
        self._tasks[name] = task
        return self

    async def run(self) -> dict[str, Any]:
        """
        Execute all tasks in parallel and return results.

        Returns:
            Dictionary mapping task names to their results
        """
        if not self._tasks:
            return {}

        start_time = time.perf_counter()
        names = list(self._tasks.keys())
        tasks = list(self._tasks.values())

        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._timeout
            )
        except asyncio.TimeoutError:
            logger.error("parallel_analyzer_timeout", timeout=self._timeout)
            return {}

        results = {}
        for name, result in zip(names, raw_results):
            if isinstance(result, Exception):
                logger.error(
                    "parallel_task_failed",
                    task=name,
                    error=str(result),
                )
                results[name] = None
            else:
                results[name] = result

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "parallel_analysis_completed",
            task_count=len(self._tasks),
            success_count=sum(1 for v in results.values() if v is not None),
            duration_ms=round(duration_ms, 2),
        )

        return results

    def clear(self) -> None:
        """Clear all tasks."""
        self._tasks.clear()
