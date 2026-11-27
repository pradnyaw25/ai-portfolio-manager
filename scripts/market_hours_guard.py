#!/usr/bin/env python3
"""Gate scheduled portfolio runs to NYSE trading sessions.

Runs before ``pip install`` on a bare checkout, so it may only import the stdlib and
``src.utils.market_hours`` (itself stdlib-only). Skips on weekends, full-day
closures and after an early close, and says which — a skipped run's log should tell
you whether the scheduler was late or the market was shut.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.market_hours import is_regular_market_hours, market_status  # noqa: E402,F401


def _write_github_output(should_run: bool, reason: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    with open(output_path, "a") as f:
        f.write(f"should_run={str(should_run).lower()}\n")
        f.write(f"reason={reason}\n")


def decide(event_name: str) -> tuple[bool, str]:
    """``(should_run, reason)`` for a run fired by ``event_name``."""
    if event_name == "workflow_dispatch":
        return True, "manual dispatch"
    is_open, why = market_status()
    if is_open:
        return True, why
    return False, f"market closed: {why}"


def main() -> None:
    should_run, reason = decide(os.getenv("GITHUB_EVENT_NAME", ""))
    _write_github_output(should_run, reason)
    print(f"should_run={str(should_run).lower()} ({reason})")


if __name__ == "__main__":
    main()
