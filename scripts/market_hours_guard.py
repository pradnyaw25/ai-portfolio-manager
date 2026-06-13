#!/usr/bin/env python3
"""Gate scheduled portfolio runs to regular US market hours."""

from __future__ import annotations

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo


MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def is_regular_market_hours(now: datetime | None = None) -> bool:
    current = now or datetime.now(MARKET_TZ)
    current = current.astimezone(MARKET_TZ)

    if current.weekday() >= 5:
        return False

    current_time = current.time()
    return MARKET_OPEN <= current_time < MARKET_CLOSE


def _write_github_output(should_run: bool, reason: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    with open(output_path, "a") as f:
        f.write(f"should_run={str(should_run).lower()}\n")
        f.write(f"reason={reason}\n")


def main() -> None:
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    manual_run = event_name == "workflow_dispatch"
    should_run = manual_run or is_regular_market_hours()
    reason = "manual dispatch" if manual_run else "regular market hours"

    if not should_run:
        reason = "outside regular market hours"

    _write_github_output(should_run, reason)
    print(f"should_run={str(should_run).lower()} ({reason})")


if __name__ == "__main__":
    main()
