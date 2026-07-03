#!/usr/bin/env python3
"""Run the daily portfolio management cycle through LangGraph.

``--resume`` re-enters the most recent run a prior process left unfinished
(reusing its run_id); idempotent stores dedupe any re-executed writes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.workflows.daily_graph import run_daily_cycle_graph

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the most recent unfinished run instead of starting a new one.",
    )
    args = parser.parse_args()
    run_daily_cycle_graph(resume=args.resume)
