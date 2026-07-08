#!/usr/bin/env python3
"""Compare the live fund against non-AI baselines over its own trading window.

Scores the fund's recorded performance against buy-and-hold SPY/QQQ and a
random-from-watchlist Monte-Carlo baseline over the SAME dates, prints a
comparison table, and writes the payload to data/ and public/ (for the dashboard
panel). First slice of roadmap V1-1 — "does the AI beat the index, or a monkey?"
(the AI ablations — no-debate / no-memory / no-tools — come in a follow-up).

    make baselines
    python scripts/compare_baselines.py
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DATA_DIR
from src.experiments.comparison import COMPARISON_FILENAME, build_comparison


def _print_table(payload: dict) -> None:
    variants = payload["variants"]
    print(f"\nBaseline comparison — {payload['start_date']} to {payload['end_date']}  (equal start capital)\n")
    headers = ["variant", "return", "alpha vs SPY", "end value"]
    rows = [
        [
            v["name"],
            f"{v['return_pct'] * 100:+.2f}%",
            "—" if v["alpha_vs_spy"] is None else f"{v['alpha_vs_spy'] * 100:+.2f}%",
            f"${v['end_value']:,.0f}",
        ]
        for v in variants
    ]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def line(cells):
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))

    print(line(headers))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line(r))
    for v in variants:
        if v.get("detail"):
            print(f"  · {v['name']}: {v['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picks", type=int, default=5, help="names per random portfolio")
    parser.add_argument("--trials", type=int, default=500, help="random portfolios to average")
    args = parser.parse_args()

    from src.data_sources.market_data import MarketDataClient

    try:
        payload = build_comparison(MarketDataClient(), picks=args.picks, trials=args.trials)
    except ValueError as exc:
        raise SystemExit(f"Cannot compare yet: {exc}")

    blob = json.dumps(payload, indent=2)
    (DATA_DIR / COMPARISON_FILENAME).write_text(blob)
    public = Path("public")
    if public.exists():
        (public / COMPARISON_FILENAME).write_text(blob)

    _print_table(payload)
    print(f"\nSaved {DATA_DIR / COMPARISON_FILENAME} and public/{COMPARISON_FILENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
