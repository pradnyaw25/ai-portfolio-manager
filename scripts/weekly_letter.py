#!/usr/bin/env python3
"""Generate the weekly investor letter (grounded, idempotent per week)."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.investor_letter import generate_weekly_letter
from src.config import validate_config


def main() -> int:
    args = parse_args()
    validate_config()
    result = generate_weekly_letter(week_end=args.week_end)
    print(json.dumps(result, indent=2, default=str))
    # skipped/published are fine; a grounding block is a soft (non-zero) signal.
    return 0 if result["status"] in {"published", "skipped"} else 1


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
