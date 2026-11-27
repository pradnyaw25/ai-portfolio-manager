#!/usr/bin/env python3
"""Gate scheduled portfolio runs to regular US market hours.

When it skips a scheduled run it prints a ``::warning::`` naming the slot, when the
cron fired and how late the scheduler was. Every skipped run is green - the job exits
0 - and in September and again in November 2026 that is how weeks of lost slots hid in
plain sight in the Actions list. The warning is what makes a skipped run look
different from a run.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.market_hours import MARKET_TZ, is_regular_market_hours


def _write_github_output(should_run: bool, reason: str, env: dict[str, str]) -> None:
    output_path = env.get("GITHUB_OUTPUT")
    if not output_path:
        return

    with open(output_path, "a") as f:
        f.write(f"should_run={str(should_run).lower()}\n")
        f.write(f"reason={reason}\n")


def _fmt(raw: str) -> str:
    """ISO timestamp -> ``HH:MMZ``; anything else passes through."""
    try:
        return f"{datetime.fromisoformat(raw.replace('Z', '+00:00')).astimezone(UTC):%H:%M}Z"
    except ValueError:
        return raw


def skip_warning(now: datetime, env: dict[str, str]) -> str:
    """The ``::warning::`` line for a scheduled run skipped outside market hours."""
    slot = env.get("RUN_SLOT", "").strip() or "unknown"
    slot_time = env.get("RUN_SLOT_TIME", "").strip()
    fired_at = env.get("RUN_FIRED_AT", "").strip()
    delay = env.get("RUN_SCHEDULER_DELAY_MIN", "").strip()
    cron = env.get("RUN_CRON", "").strip()

    slot_desc = f"{slot} slot" + (f" ({slot_time}Z)" if slot_time else "")
    fire_desc = f"fired at {_fmt(fired_at)}" if fired_at else "fire time unknown"
    if delay:
        try:
            minutes = int(delay)
            fire_desc += f", {minutes // 60}h{minutes % 60:02d}m after cron {cron!r}"
        except ValueError:
            fire_desc += f", delay {delay!r}"
    local = now.astimezone(MARKET_TZ)
    return (
        f"::warning::Skipped the {slot_desc}: {fire_desc}; reached the guard at "
        f"{now.astimezone(UTC):%H:%M}Z ({local:%H:%M} {local:%Z}), outside regular market "
        f"hours. No cycle, no decision, no tweet for this slot unless a later fire "
        f"lands in-hours."
    )


def main(*, now: datetime | None = None, env: dict[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    current = now or datetime.now(UTC)
    event_name = env.get("GITHUB_EVENT_NAME", "")
    manual_run = event_name == "workflow_dispatch"
    should_run = manual_run or is_regular_market_hours(current)
    reason = "manual dispatch" if manual_run else "regular market hours"

    if not should_run:
        reason = "outside regular market hours"
        print(skip_warning(current, env))

    _write_github_output(should_run, reason, env)
    print(f"should_run={str(should_run).lower()} ({reason})")


if __name__ == "__main__":
    main()
