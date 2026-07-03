#!/usr/bin/env python3
"""Gate scheduled portfolio runs to regular US market hours."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.market_hours import is_regular_market_hours


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
