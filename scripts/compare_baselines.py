#!/usr/bin/env python3
"""Compare the live fund against non-AI baselines over its own trading window.

Scores the fund's recorded performance against buy-and-hold SPY/QQQ and a
random-from-watchlist Monte-Carlo baseline over the SAME dates, and prints a
comparison table. This is the first slice of roadmap V1-1 — it answers "does the
AI machinery beat buying the index, or a monkey?" (the AI ablations —
no-debate / no-memory / no-tools — come in a follow-up).

    make baselines
    python scripts/compare_baselines.py
"""

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DATA_DIR, INITIAL_CAPITAL, WATCHLIST
from src.experiments.baselines import (
    buy_and_hold,
    fund_variant,
    random_from_watchlist,
    with_alpha,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

COMPARISON_OUTPUT = DATA_DIR / "baseline_comparison.json"
_BENCHMARKS = ("SPY", "QQQ")


def _fund_window() -> tuple[str, str, float, float]:
    """(start_date, end_date, start_value, end_value) from the fund's value history."""
    rows = [r for r in csv.DictReader((DATA_DIR / "portfolio_history.csv").open()) if r.get("total_value")]
    if len(rows) < 2:
        raise SystemExit("Not enough portfolio history yet to compare (need >= 2 days).")
    return rows[0]["date"], rows[-1]["date"], float(rows[0]["total_value"]), float(rows[-1]["total_value"])


def _benchmark_prices(start_date: str, end_date: str) -> dict[str, tuple[float, float]]:
    rows = list(csv.DictReader((DATA_DIR / "benchmark_history.csv").open()))
    out = {}
    for sym in _BENCHMARKS:
        window = sorted(
            (r for r in rows if r["symbol"] == sym and r.get("price") and start_date <= r["date"] <= end_date),
            key=lambda r: r["date"],
        )
        if window:
            out[sym] = (float(window[0]["price"]), float(window[-1]["price"]))
    return out


def _watchlist_prices(start_date: str, end_date: str, market_data) -> dict[str, tuple[float, float]]:
    """Start/end close for each tradable watchlist name over the window (live fetch)."""
    days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 5
    out = {}
    for sym in WATCHLIST:
        if sym in {"SPY", "QQQ", "^VIX"}:
            continue
        try:
            hist = market_data.get_history(sym, days=days)
            if hist is None or hist.empty or len(hist) < 2:
                continue
            out[sym] = (float(hist["Close"].iloc[0]), float(hist["Close"].iloc[-1]))
        except Exception as exc:  # a single missing name shouldn't sink the baseline
            logger.warning("No history for %s: %s", sym, exc)
    return out


def _print_table(variants, start_date, end_date) -> None:
    print(f"\nBaseline comparison — {start_date} to {end_date}  (all start at the same capital)\n")
    headers = ["variant", "return", "alpha vs SPY", "end value"]
    rows = [
        [
            v.name,
            f"{v.return_pct * 100:+.2f}%",
            "—" if v.alpha_vs_spy is None else f"{v.alpha_vs_spy * 100:+.2f}%",
            f"${v.end_value:,.0f}",
        ]
        for v in variants
    ]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))
    print(line(headers))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line(r))
    for v in variants:
        if v.detail:
            print(f"  · {v.name}: {v.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picks", type=int, default=5, help="names per random portfolio")
    parser.add_argument("--trials", type=int, default=500, help="random portfolios to average")
    args = parser.parse_args()

    start_date, end_date, start_value, end_value = _fund_window()
    capital = start_value or INITIAL_CAPITAL
    bench = _benchmark_prices(start_date, end_date)

    from src.data_sources.market_data import MarketDataClient

    watchlist = _watchlist_prices(start_date, end_date, MarketDataClient())

    variants = [fund_variant(start_value, end_value)]
    for sym in _BENCHMARKS:
        if sym in bench:
            variants.append(buy_and_hold(sym, bench[sym][0], bench[sym][1], capital))
    variants.append(random_from_watchlist(watchlist, capital, picks=args.picks, trials=args.trials))

    spy_return = (bench["SPY"][1] / bench["SPY"][0] - 1) if "SPY" in bench else 0.0
    with_alpha(variants, spy_return)

    payload = {
        "start_date": start_date,
        "end_date": end_date,
        "start_capital": round(capital, 2),
        "variants": [v.to_dict() for v in variants],
    }
    COMPARISON_OUTPUT.write_text(json.dumps(payload, indent=2))

    _print_table(variants, start_date, end_date)
    print(f"\nSaved {COMPARISON_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
