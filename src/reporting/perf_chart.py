"""Render a Glasshouse-vs-benchmarks performance chart to a PNG (for tweets).

Server-side rendering with matplotlib (the dashboard's Chart.js is client-only).
Plots cumulative return since inception for the fund vs SPY and QQQ, normalized to
0% at the first shared date so the lines are comparable.
"""

import csv
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — no display, safe in CI
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from src.config import DATA_DIR  # noqa: E402

PORTFOLIO_HISTORY = DATA_DIR / "portfolio_history.csv"
BENCHMARK_HISTORY = DATA_DIR / "benchmark_history.csv"

# Distinct, high-contrast, colorblind-aware hues: the fund is a bold brand green (the
# hero line); benchmarks are a clearly different blue and amber so all three separate.
_FUND_COLOR = "#2e7d32"  # green — Glasshouse (emphasized)
_SPY_COLOR = "#1f6feb"  # blue — SPY
_QQQ_COLOR = "#d97706"  # amber — QQQ
_TEXT = "#12140d"
_AXIS = "#3f4834"
_GRID = "#dfe1d6"
_ZERO = "#9aa08d"


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _cumulative_series(dates: list[str], values: list[float]) -> list[float]:
    """Return each value as % change from the first, e.g. 1.023 -> +2.3."""
    if not values or values[0] in (0, None):
        return [0.0 for _ in values]
    base = values[0]
    return [(v / base - 1.0) * 100 for v in values]


def render_performance_chart(portfolio_rows: list[dict], benchmark_rows: list[dict]) -> bytes | None:
    """Render the chart to PNG bytes. Returns None if there isn't enough data."""
    from datetime import date as _date

    pf = sorted(portfolio_rows, key=lambda r: str(r.get("date", "")))
    pf = [r for r in pf if r.get("date") and r.get("total_value") not in (None, "")]
    if len(pf) < 2:
        return None

    pf_dates = [str(r["date"]) for r in pf]
    pf_vals = [float(r["total_value"]) for r in pf]

    def bench_series(symbol: str) -> tuple[list[str], list[float]]:
        rows = sorted(
            (r for r in benchmark_rows if r.get("symbol") == symbol and r.get("price") not in (None, "")),
            key=lambda r: str(r.get("date", "")),
        )
        return [str(r["date"]) for r in rows], [float(r["price"]) for r in rows]

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=200)

    def to_dates(ds):
        return [_date.fromisoformat(d) for d in ds]

    ax.plot(to_dates(pf_dates), _cumulative_series(pf_dates, pf_vals),
            color=_FUND_COLOR, linewidth=3.0, label="Glasshouse", zorder=4)
    for symbol, color in (("SPY", _SPY_COLOR), ("QQQ", _QQQ_COLOR)):
        ds, vs = bench_series(symbol)
        if len(vs) >= 2:
            ax.plot(to_dates(ds), _cumulative_series(ds, vs), color=color,
                    linewidth=1.8, linestyle="--", label=symbol, zorder=3)

    ax.axhline(0, color=_ZERO, linewidth=1, zorder=1)
    ax.set_title("Glasshouse vs benchmarks — cumulative return", fontsize=13, fontweight="bold", color=_TEXT)
    ax.set_ylabel("Return since inception (%)", fontsize=10, color=_AXIS)
    ax.tick_params(colors=_AXIS, labelsize=9)
    ax.legend(loc="upper left", frameon=False, fontsize=11, labelcolor=_TEXT)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.grid(True, color=_GRID, linewidth=0.8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(_AXIS)
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def render_performance_chart_from_files() -> bytes | None:
    return render_performance_chart(_read_csv(PORTFOLIO_HISTORY), _read_csv(BENCHMARK_HISTORY))
