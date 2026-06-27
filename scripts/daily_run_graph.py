#!/usr/bin/env python3
"""Run the daily portfolio management cycle through LangGraph."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.workflows.daily_graph import run_daily_cycle_graph


if __name__ == "__main__":
    run_daily_cycle_graph()
