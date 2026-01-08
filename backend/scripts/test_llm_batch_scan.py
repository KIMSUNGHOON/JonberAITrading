"""
LLM Batch Analysis Test Script

Tests the GPU-based LLM batch analysis feature with a small set of stocks.
"""

import asyncio
import sys
import io
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime


async def test_llm_batch_scan():
    """Test LLM batch analysis with 10 stocks."""
    print("=" * 60)
    print("LLM Batch Analysis Test")
    print("=" * 60)

    # Test stocks (10 major KOSPI/KOSDAQ stocks)
    test_stocks = [
        ("005930", "삼성전자", "코스피"),
        ("000660", "SK하이닉스", "코스피"),
        ("035420", "NAVER", "코스피"),
        ("005380", "현대차", "코스피"),
        ("051910", "LG화학", "코스피"),
        ("006400", "삼성SDI", "코스피"),
        ("035720", "카카오", "코스피"),
        ("068270", "셀트리온", "코스피"),
        ("247540", "에코프로비엠", "코스닥"),
        ("086520", "에코프로", "코스닥"),
    ]

    print(f"\nTest stocks: {len(test_stocks)} stocks")
    for code, name, market in test_stocks:
        print(f"  - [{market}] {code} {name}")

    # Check GPU availability first
    print("\n" + "-" * 60)
    print("Step 1: Checking GPU availability...")
    print("-" * 60)

    from services.gpu_monitor import get_gpu_monitor

    gpu_monitor = get_gpu_monitor()
    gpu_available = await gpu_monitor.is_available()

    if gpu_available:
        stats = await gpu_monitor.get_stats()
        print(f"  GPU: {stats.name}")
        print(f"  Memory: {stats.memory_used_mb}MB / {stats.memory_total_mb}MB ({stats.memory_usage_pct:.1f}%)")
        print(f"  Utilization: {stats.utilization_pct}%")
        print(f"  Temperature: {stats.temperature_c}°C")

        optimal_concurrency = await gpu_monitor.get_optimal_concurrency()
        print(f"  Recommended concurrency: {optimal_concurrency}")
    else:
        print("  GPU not available - will use default concurrency")

    # Initialize scanner
    print("\n" + "-" * 60)
    print("Step 2: Starting LLM batch scan...")
    print("-" * 60)

    from services.background_scanner import get_background_scanner

    scanner = await get_background_scanner()

    # Start scan with LLM mode
    start_time = datetime.now()
    print(f"  Start time: {start_time.strftime('%H:%M:%S')}")
    print(f"  Mode: LLM Batch Analysis")
    print(f"  Auto GPU Scaling: Enabled")

    await scanner.start_scan(
        stock_list=test_stocks,
        notify_progress=False,  # Disable Telegram for testing
        use_llm=True,
        auto_gpu_scaling=True,
    )

    # Monitor progress
    print("\n" + "-" * 60)
    print("Step 3: Monitoring progress...")
    print("-" * 60)

    from services.background_scanner import ScanStatus

    last_completed = 0
    while True:
        progress = scanner.get_progress()

        if progress.completed != last_completed:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"  [{elapsed:.1f}s] Completed: {progress.completed}/{progress.total_stocks} "
                  f"({progress.progress_pct:.1f}%) - In progress: {progress.in_progress}")
            last_completed = progress.completed

        if progress.status in (ScanStatus.COMPLETED, ScanStatus.FAILED, ScanStatus.IDLE):
            break

        await asyncio.sleep(0.5)

    # Show results
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print("\n" + "-" * 60)
    print("Step 4: Results")
    print("-" * 60)

    progress = scanner.get_progress()
    print(f"  Status: {progress.status.value}")
    print(f"  Duration: {duration:.1f} seconds")
    print(f"  Completed: {progress.completed}/{progress.total_stocks}")
    print(f"  Failed: {progress.failed}")

    print(f"\n  Action Distribution:")
    print(f"    BUY:   {progress.buy_count}")
    print(f"    SELL:  {progress.sell_count}")
    print(f"    HOLD:  {progress.hold_count}")
    print(f"    WATCH: {progress.watch_count}")
    print(f"    AVOID: {progress.avoid_count}")

    # Show individual results
    print("\n" + "-" * 60)
    print("Step 5: Individual Stock Results")
    print("-" * 60)

    results = scanner.get_results()
    for result in results:
        confidence_bar = "#" * int(result.confidence * 10) + "-" * (10 - int(result.confidence * 10))
        print(f"\n  [{result.market_type}] {result.stk_cd} {result.stk_nm}")
        print(f"    Action: {result.action} ({result.confidence:.0%}) [{confidence_bar}]")
        print(f"    Price: {result.current_price:,}")
        summary_display = result.summary[:60] + "..." if len(result.summary) > 60 else result.summary
        print(f"    Summary: {summary_display}")
        if result.key_factors:
            print(f"    Key Factors: {', '.join(result.key_factors[:3])}")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)

    return results


async def test_quick_scan_comparison():
    """Run quick scan for comparison."""
    print("\n" + "=" * 60)
    print("Quick Analysis Comparison Test")
    print("=" * 60)

    test_stocks = [
        ("005930", "삼성전자", "코스피"),
        ("000660", "SK하이닉스", "코스피"),
        ("035420", "NAVER", "코스피"),
    ]

    print(f"\nTest stocks: {len(test_stocks)} stocks (subset for comparison)")

    from services.background_scanner import get_background_scanner, ScanStatus

    # Need to create new scanner instance for fresh test
    from services.background_scanner import scanner as scanner_module
    scanner_module._scanner_instance = None

    scanner = await get_background_scanner()

    start_time = datetime.now()

    await scanner.start_scan(
        stock_list=test_stocks,
        notify_progress=False,
        use_llm=False,  # Quick mode
        auto_gpu_scaling=False,
    )

    # Wait for completion
    while True:
        progress = scanner.get_progress()
        if progress.status in (ScanStatus.COMPLETED, ScanStatus.FAILED, ScanStatus.IDLE):
            break
        await asyncio.sleep(0.5)

    duration = (datetime.now() - start_time).total_seconds()

    print(f"\n  Quick Analysis completed in {duration:.1f} seconds")
    print(f"  Results:")

    results = scanner.get_results()
    for result in results:
        print(f"    {result.stk_cd} {result.stk_nm}: {result.action} ({result.confidence:.0%})")

    return results


if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("# GPU-based LLM Batch Analysis Test")
    print("#" * 60)

    asyncio.run(test_llm_batch_scan())
