#!/usr/bin/env python3
"""Run the legacy sequential daily portfolio management cycle."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.main import run_daily_cycle


if __name__ == "__main__":
    run_daily_cycle()
