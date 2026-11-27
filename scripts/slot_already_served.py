#!/usr/bin/env python3
"""Has this run's slot already been served - or claimed - today? Then stop, green.

The daily workflow fires each slot's cron every two hours from ~10 hours before the
slot (see daily-run.yml) so that GitHub's scheduler - a median of ~8.5 hours late in
November 2026 - cannot push the whole day past the close. Every fire sleeps to the
slot; the first to reach it runs the cycle. This check is how the rest know to stand
down: after the wait and the checkout refresh, either of these on origin means the
decision for this slot has been made, and this job ends with no cycle, no commit, no
tweet:

* a row in ``data/run_history.jsonl`` for the slot's market date and this slot, or
* a claim file ``data/slot_claims/<date>-<slot>.json``, which the serving run pushes
  BEFORE its cycle starts (``scripts/claim_slot.py``). The run_history row is pushed
  last; if that push fails the trades are done and the tweet is out but origin has no
  row, and without the claim the next fire would run the whole cycle again.

Any run_history row counts, failed ones included. A run that failed may have executed
trades before it died; re-deciding the same slot on the moved portfolio could
double-trade. The recovery path for a failed slot is the day's OTHER slot, exactly as
before, and the run-health watchdog pages on a failed final run.

The slot's market date comes from the slot instant (``RUN_SLOT_AT``), not from the fire
time: the 04:40 UTC fire is 23:40 New York the evening before, and judged by its own
clock it would read yesterday's rows and stand down for a slot nobody has served.

Stdlib only - runs before ``pip install``. Reuses the row readers from
``scripts/check_run_health.py`` so both tools agree on which slot a row served.

Environment:
  RUN_SLOT       ``morning`` or ``afternoon`` (from the wait step). ``manual`` or
                 empty on a workflow_dispatch, which always proceeds and never
                 counts as a scheduled slot.
  RUN_SLOT_AT    ISO instant of the slot this fire serves (from the wait step).
  GITHUB_OUTPUT  when set, ``already_served=true|false`` is written as a step output;
                 the market-hours guard step is gated on it.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_run_health import (  # noqa: E402
    DATA_DIR,
    EXPECTED_SLOTS,
    MARKET_TZ,
    _slot,
    _started_on,
    load_runs,
)

MANUAL_SLOT = "manual"
SLOT_CLAIMS_DIR = DATA_DIR / "slot_claims"


def market_date(now: datetime, slot_at: str | None = None) -> date:
    """The trading day (America/New_York) of the slot this fire serves.

    ``slot_at`` is the slot's own instant; without it (old callers, tests) fall back to
    the fire time, which is right whenever the fire is inside the New York day.
    """
    if slot_at:
        stamp = datetime.fromisoformat(slot_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return stamp.astimezone(MARKET_TZ).date()
    return now.astimezone(MARKET_TZ).date()


def served_by(runs: list[dict], slot: str, day: date) -> dict | None:
    """The earliest row that already served ``slot`` on ``day``, or None."""
    matches = [r for r in runs if _started_on(r) == day and _slot(r) == slot]
    if not matches:
        return None
    return min(matches, key=lambda r: str(r.get("started_at") or ""))


def claim_path(slot: str, day: date, root: Path | None = None) -> Path:
    """One file per (date, slot), so two slots' claims can never textually conflict
    when their pushes race and rebase onto each other."""
    return (root or SLOT_CLAIMS_DIR) / f"{day.isoformat()}-{slot}.json"


def claimed_by(slot: str, day: date, root: Path | None = None) -> dict | None:
    """The claim a run pushed for ``slot`` on ``day`` before starting its cycle."""
    path = claim_path(slot, day, root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"path": str(path), "corrupt": True}  # a claim file exists: honour it


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
    claims_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> int:
    env = os.environ if env is None else env
    slot = env.get("RUN_SLOT", "").strip().lower()
    if not slot or slot == MANUAL_SLOT:
        print("No scheduled slot (manual dispatch) - not checking run history; proceeding.")
        _write_output(False, env)
        return 0
    if slot not in EXPECTED_SLOTS:
        print(f"::error::RUN_SLOT={slot!r} is not one of {EXPECTED_SLOTS}", file=sys.stderr)
        return 1

    current = now or datetime.now(MARKET_TZ)
    day = market_date(current, env.get("RUN_SLOT_AT", "").strip() or None)

    earlier = served_by(load_runs() if runs is None else runs, slot, day)
    if earlier is not None:
        print(
            f"::notice::The {slot} slot on {day} was already served by "
            f"{earlier.get('run_id')} (started {earlier.get('started_at')}, "
            f"status={earlier.get('status')}) - this is a backup fire; ending with no cycle."
        )
        _write_output(True, env)
        return 0

    claim = claimed_by(slot, day, claims_dir)
    if claim is not None:
        print(
            f"::notice::The {slot} slot on {day} was claimed by workflow run "
            f"{claim.get('github_run_id')} at {claim.get('claimed_at')} but has no "
            f"run_history row on origin: that run's cycle ran and its final push did not "
            f"land (or it is still pushing). Not re-running the cycle; check that run's log."
        )
        _write_output(True, env)
        return 0

    print(f"The {slot} slot has not run on {day} - proceeding to the market-hours guard.")
    _write_output(False, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
