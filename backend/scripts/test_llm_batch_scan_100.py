"""
LLM Batch Analysis Performance Test - 100 Stocks

Tests the GPU-based LLM batch analysis with 100 stocks to measure performance.
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


# 100 major KOSPI/KOSDAQ stocks for testing
TEST_STOCKS_100 = [
    # KOSPI Top 50
    ("005930", "삼성전자", "코스피"),
    ("000660", "SK하이닉스", "코스피"),
    ("035420", "NAVER", "코스피"),
    ("005380", "현대차", "코스피"),
    ("051910", "LG화학", "코스피"),
    ("006400", "삼성SDI", "코스피"),
    ("207940", "삼성바이오로직스", "코스피"),
    ("005490", "POSCO홀딩스", "코스피"),
    ("035720", "카카오", "코스피"),
    ("068270", "셀트리온", "코스피"),
    ("000270", "기아", "코스피"),
    ("028260", "삼성물산", "코스피"),
    ("012330", "현대모비스", "코스피"),
    ("055550", "신한지주", "코스피"),
    ("066570", "LG전자", "코스피"),
    ("003670", "포스코퓨처엠", "코스피"),
    ("105560", "KB금융", "코스피"),
    ("096770", "SK이노베이션", "코스피"),
    ("034730", "SK", "코스피"),
    ("373220", "LG에너지솔루션", "코스피"),
    ("003550", "LG", "코스피"),
    ("032830", "삼성생명", "코스피"),
    ("086790", "하나금융지주", "코스피"),
    ("015760", "한국전력", "코스피"),
    ("017670", "SK텔레콤", "코스피"),
    ("030200", "KT", "코스피"),
    ("033780", "KT&G", "코스피"),
    ("018260", "삼성에스디에스", "코스피"),
    ("009150", "삼성전기", "코스피"),
    ("316140", "우리금융지주", "코스피"),
    ("010130", "고려아연", "코스피"),
    ("024110", "기업은행", "코스피"),
    ("259960", "크래프톤", "코스피"),
    ("011200", "HMM", "코스피"),
    ("009540", "한국조선해양", "코스피"),
    ("034020", "두산에너빌리티", "코스피"),
    ("090430", "아모레퍼시픽", "코스피"),
    ("000810", "삼성화재", "코스피"),
    ("010950", "S-Oil", "코스피"),
    ("021240", "코웨이", "코스피"),
    ("011170", "롯데케미칼", "코스피"),
    ("036570", "엔씨소프트", "코스피"),
    ("251270", "넷마블", "코스피"),
    ("004020", "현대제철", "코스피"),
    ("088980", "맥쿼리인프라", "코스피"),
    ("047050", "포스코인터내셔널", "코스피"),
    ("138040", "메리츠금융지주", "코스피"),
    ("032640", "LG유플러스", "코스피"),
    ("011780", "금호석유", "코스피"),
    ("001570", "금양", "코스피"),
    # KOSDAQ Top 50
    ("247540", "에코프로비엠", "코스닥"),
    ("086520", "에코프로", "코스닥"),
    ("041510", "에스엠", "코스닥"),
    ("035900", "JYP Ent.", "코스닥"),
    ("352820", "하이브", "코스닥"),
    ("293490", "카카오게임즈", "코스닥"),
    ("263750", "펄어비스", "코스닥"),
    ("112040", "위메이드", "코스닥"),
    ("095340", "ISC", "코스닥"),
    ("039030", "이오테크닉스", "코스닥"),
    ("257720", "실리콘투", "코스닥"),
    ("058470", "리노공업", "코스닥"),
    ("090460", "비에이치", "코스닥"),
    ("067310", "하나마이크론", "코스닥"),
    ("145020", "휴젤", "코스닥"),
    ("214150", "클래시스", "코스닥"),
    ("028300", "에이치엘비", "코스닥"),
    ("196170", "알테오젠", "코스닥"),
    ("048410", "현대바이오", "코스닥"),
    ("140410", "메지온", "코스닥"),
    ("314930", "바이오다인", "코스닥"),
    ("000250", "삼천당제약", "코스닥"),
    ("226330", "신테카바이오", "코스닥"),
    ("137310", "에스디바이오센서", "코스닥"),
    ("009520", "포스코엠텍", "코스닥"),
    ("117730", "티로보틱스", "코스닥"),
    ("377300", "카카오페이", "코스닥"),
    ("323410", "카카오뱅크", "코스닥"),
    ("357780", "솔브레인", "코스닥"),
    ("005290", "동진쎄미켐", "코스닥"),
    ("131970", "테스나", "코스닥"),
    ("033640", "네패스", "코스닥"),
    ("036930", "주성엔지니어링", "코스닥"),
    ("222800", "심텍", "코스닥"),
    ("240810", "원익IPS", "코스닥"),
    ("083310", "엘오티베큠", "코스닥"),
    ("078600", "대주전자재료", "코스닥"),
    ("053610", "프로텍", "코스닥"),
    ("950130", "엑세스바이오", "코스닥"),
    ("060280", "큐렉소", "코스닥"),
    ("241560", "두산퓨얼셀", "코스닥"),
    ("336260", "두산로보틱스", "코스닥"),
    ("064350", "현대로템", "코스닥"),
    ("042700", "한미반도체", "코스닥"),
    ("403870", "HPSP", "코스닥"),
    ("348210", "넥스틴", "코스닥"),
    ("035760", "CJ ENM", "코스닥"),
    ("069960", "현대백화점", "코스닥"),
    ("004170", "신세계", "코스닥"),
    ("097950", "CJ제일제당", "코스닥"),
]


async def test_llm_batch_scan_100():
    """Performance test with 100 stocks."""
    print("=" * 70)
    print("LLM Batch Analysis Performance Test - 100 Stocks")
    print("=" * 70)

    print(f"\nTest stocks: {len(TEST_STOCKS_100)} stocks")
    print(f"  KOSPI: {len([s for s in TEST_STOCKS_100 if s[2] == '코스피'])} stocks")
    print(f"  KOSDAQ: {len([s for s in TEST_STOCKS_100 if s[2] == '코스닥'])} stocks")

    # Check GPU availability
    print("\n" + "-" * 70)
    print("Step 1: GPU Status")
    print("-" * 70)

    from services.gpu_monitor import get_gpu_monitor

    gpu_monitor = get_gpu_monitor()
    gpu_available = await gpu_monitor.is_available()

    if gpu_available:
        stats = await gpu_monitor.get_stats()
        print(f"  GPU: {stats.name}")
        print(f"  Memory: {stats.memory_used_mb}MB / {stats.memory_total_mb}MB ({stats.memory_usage_pct:.1f}%)")
        print(f"  Free Memory: {stats.memory_free_mb}MB")
        print(f"  Utilization: {stats.utilization_pct}%")
        print(f"  Temperature: {stats.temperature_c}C")

        optimal_concurrency = await gpu_monitor.get_optimal_concurrency()
        print(f"  Recommended concurrency: {optimal_concurrency}")
    else:
        print("  GPU not available")

    # Initialize scanner
    print("\n" + "-" * 70)
    print("Step 2: Starting LLM Batch Scan (100 stocks)")
    print("-" * 70)

    # Reset scanner instance for fresh test
    from services.background_scanner import scanner as scanner_module
    scanner_module._scanner_instance = None

    from services.background_scanner import get_background_scanner, ScanStatus

    scanner = await get_background_scanner()

    start_time = datetime.now()
    print(f"  Start time: {start_time.strftime('%H:%M:%S')}")
    print(f"  Mode: LLM Batch Analysis")
    print(f"  Batch size: 10 stocks per LLM call")

    await scanner.start_scan(
        stock_list=TEST_STOCKS_100,
        notify_progress=False,
        use_llm=True,
        auto_gpu_scaling=True,
    )

    # Monitor progress
    print("\n" + "-" * 70)
    print("Step 3: Progress")
    print("-" * 70)

    last_completed = 0
    last_print_time = datetime.now()

    while True:
        progress = scanner.get_progress()

        # Print progress every 10 stocks or every 10 seconds
        now = datetime.now()
        if progress.completed != last_completed or (now - last_print_time).seconds >= 10:
            elapsed = (now - start_time).total_seconds()
            rate = progress.completed / elapsed if elapsed > 0 else 0
            eta = (progress.total_stocks - progress.completed) / rate if rate > 0 else 0

            print(f"  [{elapsed:.0f}s] {progress.completed}/{progress.total_stocks} "
                  f"({progress.progress_pct:.1f}%) | Rate: {rate:.1f}/s | ETA: {eta:.0f}s")

            last_completed = progress.completed
            last_print_time = now

        if progress.status in (ScanStatus.COMPLETED, ScanStatus.FAILED, ScanStatus.IDLE):
            break

        await asyncio.sleep(1)

    # Results
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print("\n" + "-" * 70)
    print("Step 4: Performance Results")
    print("-" * 70)

    progress = scanner.get_progress()

    print(f"\n  === Performance Metrics ===")
    print(f"  Total Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
    print(f"  Stocks Analyzed: {progress.completed}/{progress.total_stocks}")
    print(f"  Failed: {progress.failed}")
    print(f"  Average Time per Stock: {duration/progress.completed:.2f} seconds" if progress.completed > 0 else "")
    print(f"  Throughput: {progress.completed/duration*60:.1f} stocks/minute" if duration > 0 else "")

    # Data fetch vs LLM time estimation
    data_fetch_time = progress.completed * 1.5  # ~1.5s per stock for API calls
    llm_time = duration - data_fetch_time
    print(f"\n  === Time Breakdown (estimated) ===")
    print(f"  Data Fetching: ~{data_fetch_time:.0f}s ({data_fetch_time/duration*100:.0f}%)")
    print(f"  LLM Analysis: ~{llm_time:.0f}s ({llm_time/duration*100:.0f}%)")
    print(f"  LLM Batches: {(progress.completed + 9) // 10} batches of 10 stocks")

    print(f"\n  === Action Distribution ===")
    print(f"  BUY:   {progress.buy_count} ({progress.buy_count/progress.completed*100:.1f}%)" if progress.completed > 0 else "")
    print(f"  SELL:  {progress.sell_count} ({progress.sell_count/progress.completed*100:.1f}%)" if progress.completed > 0 else "")
    print(f"  HOLD:  {progress.hold_count} ({progress.hold_count/progress.completed*100:.1f}%)" if progress.completed > 0 else "")
    print(f"  WATCH: {progress.watch_count} ({progress.watch_count/progress.completed*100:.1f}%)" if progress.completed > 0 else "")
    print(f"  AVOID: {progress.avoid_count} ({progress.avoid_count/progress.completed*100:.1f}%)" if progress.completed > 0 else "")

    # Show BUY recommendations
    print("\n" + "-" * 70)
    print("Step 5: BUY Recommendations")
    print("-" * 70)

    results = scanner.get_results(action_filter="BUY")
    if results:
        for result in sorted(results, key=lambda x: x.confidence, reverse=True)[:10]:
            print(f"\n  [{result.market_type}] {result.stk_cd} {result.stk_nm}")
            print(f"    Confidence: {result.confidence:.0%}")
            print(f"    Price: {result.current_price:,}")
            summary = result.summary[:70] + "..." if len(result.summary) > 70 else result.summary
            print(f"    Summary: {summary}")
    else:
        print("  No BUY recommendations")

    # Show WATCH recommendations (top 10)
    print("\n" + "-" * 70)
    print("Step 6: Top WATCH Recommendations")
    print("-" * 70)

    results = scanner.get_results(action_filter="WATCH")
    if results:
        for result in sorted(results, key=lambda x: x.confidence, reverse=True)[:10]:
            print(f"  [{result.confidence:.0%}] {result.stk_cd} {result.stk_nm} - {result.current_price:,}")
    else:
        print("  No WATCH recommendations")

    print("\n" + "=" * 70)
    print("Performance Test Completed!")
    print("=" * 70)

    return progress


if __name__ == "__main__":
    print("\n" + "#" * 70)
    print("# GPU-based LLM Batch Analysis - 100 Stock Performance Test")
    print("#" * 70)

    asyncio.run(test_llm_batch_scan_100())
