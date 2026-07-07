"""Weekly "state of the fund" tweet — identity + honest performance vs benchmarks.

Distinct from the daily trade recap: an occasional, context-setting post that says
what Glasshouse is and how it's doing vs SPY/QQQ, framed honestly (small sample) so
it reinforces the transparency brand rather than bragging about returns.
"""

import csv
import json
from datetime import date
from pathlib import Path

from src.config import DATA_DIR, PROMPTS_DIR
from src.llm import complete_text
from src.storage.portfolio_store import PortfolioStore
from src.storage.prediction_store import PredictionStore
from src.utils.logger import get_logger

logger = get_logger(__name__)

STATE_TWEET_PROMPT_VERSION = "state_tweet/v1"
PERFORMANCE_FILE = DATA_DIR / "portfolio_history.csv"
BENCHMARK_FILE = DATA_DIR / "benchmark_history.csv"

# Below this many tracked days, the copy must carry a "small sample" caveat.
SHORT_TRACK_DAYS = 90


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _pct_change(rows: list[dict], field: str) -> float | None:
    vals = [float(r[field]) for r in rows if r.get(field) not in (None, "")]
    if len(vals) < 2 or vals[0] == 0:
        return None
    return round((vals[-1] / vals[0] - 1.0) * 100, 2)


def gather_state_facts(
    *,
    performance_rows: list[dict] | None = None,
    benchmark_rows: list[dict] | None = None,
    portfolio_store=None,
    prediction_store=None,
) -> dict:
    """Deterministic, inception-to-date facts the tweet must be grounded in."""
    perf = sorted(
        performance_rows if performance_rows is not None else _read_csv(PERFORMANCE_FILE),
        key=lambda r: str(r.get("date", "")),
    )
    perf = [r for r in perf if r.get("total_value") not in (None, "")]
    if len(perf) < 2:
        return {"enough_data": False, "days": len(perf)}

    fund_return = _pct_change(perf, "total_value")
    start_day, end_day = str(perf[0]["date"]), str(perf[-1]["date"])
    days = (date.fromisoformat(end_day) - date.fromisoformat(start_day)).days

    bench = benchmark_rows if benchmark_rows is not None else _read_csv(BENCHMARK_FILE)

    def bench_return(symbol: str) -> float | None:
        rows = sorted(
            (r for r in bench if r.get("symbol") == symbol),
            key=lambda r: str(r.get("date", "")),
        )
        return _pct_change(rows, "price")

    spy = bench_return("SPY")
    qqq = bench_return("QQQ")

    snapshot = (portfolio_store or PortfolioStore()).load()
    cash_pct = round(snapshot.cash_pct * 100, 1) if snapshot is not None else None
    num_positions = len(snapshot.positions) if snapshot is not None else 0
    top_holdings = []
    if snapshot is not None:
        top_holdings = [
            p.symbol
            for p in sorted(snapshot.positions, key=lambda p: p.market_value, reverse=True)[:3]
        ]

    predictions = (prediction_store or PredictionStore()).load_all()
    resolved = sum(1 for p in predictions if p.get("status") == "scored")

    return {
        "enough_data": True,
        "days": days,
        "portfolio_value": round(float(perf[-1]["total_value"]), 0),
        "fund_return_pct": fund_return,
        "spy_return_pct": spy,
        "qqq_return_pct": qqq,
        "alpha_vs_spy_pct": round(fund_return - spy, 2) if (fund_return is not None and spy is not None) else None,
        "ahead_of_spy": (fund_return is not None and spy is not None and fund_return > spy),
        "ahead_of_qqq": (fund_return is not None and qqq is not None and fund_return > qqq),
        "cash_pct": cash_pct,
        "num_positions": num_positions,
        "top_holdings": top_holdings,
        "resolved_predictions": resolved,
        "small_sample": days < SHORT_TRACK_DAYS or resolved == 0,
    }


def generate_state_tweet(facts: dict, *, complete_fn=None) -> str:
    """Generate the tweet text from the fact base (cheap tier)."""
    complete_fn = complete_fn or complete_text
    system_prompt = (PROMPTS_DIR / "state_tweet.txt").read_text()
    user = "Facts (use only these numbers):\n" + json.dumps(facts, indent=2)
    text = complete_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ],
        tier="cheap",
        prompt_version=STATE_TWEET_PROMPT_VERSION,
    )
    return text.strip()[:280]
