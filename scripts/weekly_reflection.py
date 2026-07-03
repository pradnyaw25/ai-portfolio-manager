#!/usr/bin/env python3
"""Run the weekly lessons-learned reflection through the reflection graph.

Reads the past week's resolved predictions and trades, synthesizes risk_lesson /
mistake memories, and ingests them (idempotent per week).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.workflows.weekly_reflection_graph import run_weekly_reflection_graph


def main() -> int:
    args = parse_args()
    result = run_weekly_reflection_graph(week_end=args.week_end)
    print(json.dumps(result.to_dict(), indent=2))
    # A down Qdrant is a soft failure (nothing to gate); skipped/ok are fine.
    return 0 if result.status in {"ok", "skipped"} else 1


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--week-end",
        default=None,
        help="ISO date ending the 7-day window (default: today).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
