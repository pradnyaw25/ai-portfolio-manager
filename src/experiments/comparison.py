"""Assemble the fund-vs-baselines comparison payload (roadmap V1-1).

Reads the fund's recorded value history + benchmark prices, fetches watchlist
prices for the same window, and scores the fund against buy-and-hold SPY/QQQ and a
random-from-watchlist baseline. Used by both ``scripts/compare_baselines.py`` and
the daily export (so the dashboard panel stays fresh).
"""

import csv
from datetime import date
from pathlib import Path

from src.config import DATA_DIR, INITIAL_CAPITAL, WATCHLIST
from src.experiments.baselines import (
    buy_and_hold,
    fund_variant,
    random_from_watchlist,
    with_alpha,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

COMPARISON_FILENAME = "baseline_comparison.json"
_BENCHMARKS = ("SPY", "QQQ")


def _fund_window(data_dir: Path) -> tuple[str, str, float, float]:
    """(start_date, end_date, start_value, end_value) from the fund value history."""
    path = data_dir / "portfolio_history.csv"
    if not path.exists():
        raise ValueError("no portfolio history yet")
    rows = [r for r in csv.DictReader(path.open()) if r.get("total_value")]
    if len(rows) < 2:
        raise ValueError("not enough portfolio history to compare (need >= 2 days)")
    return rows[0]["date"], rows[-1]["date"], float(rows[0]["total_value"]), float(rows[-1]["total_value"])


def _benchmark_prices(data_dir: Path, start_date: str, end_date: str) -> dict[str, tuple[float, float]]:
    path = data_dir / "benchmark_history.csv"
    if not path.exists():
        return {}
    rows = list(csv.DictReader(path.open()))
    out = {}
    for sym in _BENCHMARKS:
        window = sorted(
            (r for r in rows if r["symbol"] == sym and r.get("price") and start_date <= r["date"] <= end_date),
            key=lambda r: r["date"],
        )
        if window:
            out[sym] = (float(window[0]["price"]), float(window[-1]["price"]))
    return out


def _watchlist_prices(market_data, start_date: str, end_date: str) -> dict[str, tuple[float, float]]:
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


def build_comparison(market_data, *, picks: int = 5, trials: int = 500, data_dir: Path = DATA_DIR) -> dict:
    """Build the fund-vs-baselines payload. Raises ValueError if there isn't yet
    enough fund history to compare."""
    start_date, end_date, start_value, end_value = _fund_window(data_dir)
    capital = start_value or INITIAL_CAPITAL
    bench = _benchmark_prices(data_dir, start_date, end_date)
    watchlist = _watchlist_prices(market_data, start_date, end_date)

    variants = [fund_variant(start_value, end_value)]
    for sym in _BENCHMARKS:
        if sym in bench:
            variants.append(buy_and_hold(sym, bench[sym][0], bench[sym][1], capital))
    # Only include the random baseline when we actually fetched enough prices — a
    # transient price-fetch failure must not render as a misleading 0.00% return.
    usable = [s for s, (a, b) in watchlist.items() if a and b and a > 0]
    if len(usable) >= 2:
        variants.append(random_from_watchlist(watchlist, capital, picks=picks, trials=trials))

    spy_return = (bench["SPY"][1] / bench["SPY"][0] - 1) if "SPY" in bench else 0.0
    with_alpha(variants, spy_return)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "start_capital": round(capital, 2),
        "variants": [v.to_dict() for v in variants],
    }
