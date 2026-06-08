#!/usr/bin/env python3
"""Compare portfolio performance against benchmarks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_sources.benchmarks import BenchmarkClient
from src.simulator.performance import PerformanceTracker
from src.utils.dates import format_pct
from src.utils.logger import get_logger

logger = get_logger(__name__)


def run_benchmark(days: int = 30):
    tracker = PerformanceTracker()
    stats = tracker.get_stats()

    if not stats:
        print("No portfolio history found. Run daily_run.py first.")
        return

    bench_client = BenchmarkClient()
    benchmarks = bench_client.get_all_benchmarks(days=days)

    print(f"\n{'='*50}")
    print(f"Portfolio Performance ({days} days)")
    print(f"{'='*50}")
    print(f"  Total Return:    {format_pct(stats['total_return'])}")
    print(f"  Avg Daily Return:{format_pct(stats['avg_daily_return'])}")
    print(f"  Volatility:      {format_pct(stats['volatility'])}")
    print(f"  Sharpe Ratio:    {stats['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown:    {format_pct(stats['max_drawdown'])}")
    print(f"  Days Tracked:    {stats['days_tracked']}")

    print(f"\n{'='*50}")
    print("Benchmarks")
    print(f"{'='*50}")
    for b in benchmarks:
        print(f"  {b['name'].upper():8s} Return: {format_pct(b['return_pct'])}")

    alpha = stats["total_return"] - benchmarks[0]["return_pct"] if benchmarks else 0
    print(f"\n  Alpha vs S&P 500: {format_pct(alpha)}")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_benchmark(days)
