#!/usr/bin/env python3
"""Has this run's slot already been served today? Then stop here, green.

The daily workflow fires each slot's cron every two hours from ~10 hours before the
slot (see daily-run.yml) so that GitHub's scheduler - a median of ~8.5 hours late in
November 2026 - cannot push the whole day past the close. Every fire sleeps to the
slot; the first to reach it runs the cycle. This check is how the rest know to stand
down: after the wait and the checkout refresh, a row in ``data/run_history.jsonl`` for
today's market date and this slot means the decision has been made, and this job
ends with no cycle, no commit, no tweet.

Any row counts, failed ones included. A run that failed may have executed trades
before it died; re-deciding the same slot on the moved portfolio could double-trade.
The recovery path for a failed slot is the day's OTHER slot, exactly as before, and
the run-health watchdog pages on a failed final run.

Stdlib only - runs before ``pip install``. Reuses the row readers from
``scripts/check_run_health.py`` so both tools agree on which slot a row served.

Environment:
  RUN_SLOT       ``morning`` or ``afternoon`` (from the wait step). Empty on manual
                 dispatch, which always proceeds.
  GITHUB_OUTPUT  when set, ``already_served=true|false`` is written as a step output;
                 the market-hours guard step is gated on it.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_run_health import (  # noqa: E402
    EXPECTED_SLOTS,
    MARKET_TZ,
    _slot,
    _started_on,
    load_runs,
)


def market_date(now: datetime) -> date:
    """The trading day a run starting at ``now`` belongs to (America/New_York)."""
    return now.astimezone(MARKET_TZ).date()


def served_by(runs: list[dict], slot: str, day: date) -> dict | None:
    """The earliest row that already served ``slot`` on ``day``, or None."""
    matches = [r for r in runs if _started_on(r) == day and _slot(r) == slot]
    if not matches:
        return None
    return min(matches, key=lambda r: str(r.get("started_at") or ""))


def _write_output(already_served: bool, env: dict[str, str]) -> None:
    path = env.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a") as fh:
        fh.write(f"already_served={str(already_served).lower()}\n")


def main(
    *,
    now: datetime | None = None,
    runs: list[dict] | None = None,
    env: dict[str, str] | None = None,
) -> int:
    env = os.environ if env is None else env
    slot = env.get("RUN_SLOT", "").strip().lower()
    if not slot:
        print("No slot (manual dispatch) - not checking run history; proceeding.")
        _write_output(False, env)
        return 0
    if slot not in EXPECTED_SLOTS:
        print(f"::error::RUN_SLOT={slot!r} is not one of {EXPECTED_SLOTS}", file=sys.stderr)
        return 1

    current = now or datetime.now(MARKET_TZ)
    day = market_date(current)
    earlier = served_by(load_runs() if runs is None else runs, slot, day)
    if earlier is None:
        print(f"The {slot} slot has not run on {day} - proceeding to the market-hours guard.")
        _write_output(False, env)
        return 0

    print(
        f"::notice::The {slot} slot on {day} was already served by "
        f"{earlier.get('run_id')} (started {earlier.get('started_at')}, "
        f"status={earlier.get('status')}) - this is a backup fire; ending with no cycle."
    )
    _write_output(True, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
