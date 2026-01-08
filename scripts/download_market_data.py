#!/usr/bin/env python3
"""
Market Data Download Script

Downloads historical stock data for offline development and testing.
Data is stored in a local SQLite database for fast access.

Usage:
    python scripts/download_market_data.py [OPTIONS]

Examples:
    # Download popular tickers (default)
    python scripts/download_market_data.py

    # Download specific tickers
    python scripts/download_market_data.py --tickers AAPL MSFT GOOGL

    # Download with longer history
    python scripts/download_market_data.py --period 5y

    # Show cache statistics
    python scripts/download_market_data.py --stats

    # Export to CSV files
    python scripts/download_market_data.py --export
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from agents.tools.market_data import (
    POPULAR_TICKERS,
    download_historical_data,
    export_cache_to_csv,
    get_cache_stats,
    get_cached_tickers,
)


async def main():
    parser = argparse.ArgumentParser(
        description="Download market data for offline development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                          # Download popular tickers (2 years)
    %(prog)s --tickers AAPL MSFT     # Download specific tickers
    %(prog)s --period 5y              # Download 5 years of history
    %(prog)s --stats                  # Show cache statistics
    %(prog)s --export                 # Export cached data to CSV
        """,
    )

    parser.add_argument(
        "--tickers",
        nargs="+",
        help="Specific tickers to download (default: popular tickers)",
    )
    parser.add_argument(
        "--period",
        default="2y",
        choices=["1y", "2y", "5y", "max"],
        help="Time period to download (default: 2y)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show cache statistics and exit",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export cached data to CSV files",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List cached tickers and exit",
    )

    args = parser.parse_args()

    # Show cache statistics
    if args.stats:
        stats = get_cache_stats()
        print("\n📊 Cache Statistics")
        print("=" * 50)

        if stats["status"] == "no_cache":
            print("No cache found. Run without --stats to download data.")
            return

        print(f"Total tickers: {stats['total_tickers']}")
        print("\nTicker Details:")
        print("-" * 50)

        for ticker, info in sorted(stats["tickers"].items()):
            print(f"  {ticker:6s}: {info['days']:4d} days ({info['start']} to {info['end']})")

        return

    # List cached tickers
    if args.list:
        tickers = get_cached_tickers()
        print("\n📋 Cached Tickers")
        print("=" * 50)

        if not tickers:
            print("No tickers in cache. Run without --list to download data.")
            return

        print(f"Total: {len(tickers)}")
        for i, ticker in enumerate(sorted(tickers)):
            print(f"  {ticker}", end="")
            if (i + 1) % 8 == 0:
                print()
        print()
        return

    # Export to CSV
    if args.export:
        print("\n📁 Exporting cached data to CSV...")
        export_cache_to_csv()
        print("Done! Files saved to data/exports/")
        return

    # Download data
    tickers = args.tickers or POPULAR_TICKERS

    print("\n📥 Market Data Downloader")
    print("=" * 50)
    print(f"Tickers: {len(tickers)}")
    print(f"Period: {args.period}")
    print("-" * 50)

    results = await download_historical_data(tickers, period=args.period)

    print("\n✅ Download Complete!")
    print(f"Successfully downloaded: {len(results)} tickers")

    # Show summary
    if results:
        print("\nSummary:")
        print("-" * 50)
        for ticker, df in sorted(results.items()):
            print(f"  {ticker:6s}: {len(df):4d} days ({df.index.min().strftime('%Y-%m-%d')} to {df.index.max().strftime('%Y-%m-%d')})")


if __name__ == "__main__":
    asyncio.run(main())
