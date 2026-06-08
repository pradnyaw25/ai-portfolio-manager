#!/usr/bin/env python3
"""Backfill portfolio history with historical data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, timedelta
from src.utils.logger import get_logger

logger = get_logger(__name__)


def backfill(start_date: str, end_date: str | None = None):
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else date.today()

    logger.info("Backfilling from %s to %s", start, end)

    current = start
    while current <= end:
        if current.weekday() < 5:
            logger.info("Processing %s", current)
            # TODO: implement historical simulation
        current += timedelta(days=1)

    logger.info("Backfill complete")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backfill.py START_DATE [END_DATE]")
        print("  e.g. python backfill.py 2024-01-01 2024-12-31")
        sys.exit(1)

    backfill(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
