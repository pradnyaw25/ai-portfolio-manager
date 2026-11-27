#!/usr/bin/env python3
"""Claim this run's slot on origin BEFORE the cycle runs.

The daily run writes its ``run_history`` row last and pushes it last. If that push
fails after its rebase retries, the trades are executed and the tweet is out, but
origin has no row for the slot - and the next backup fire, two hours later, would
find the slot unserved and run the whole cycle again: a second decision on the same
day and a duplicate tweet. Before the backup fires existed a failed push cost only a
commit; now it must not cost a double run.

So the serving run first writes ``data/slot_claims/<market-date>-<slot>.json`` and the
workflow commits and pushes that file before ``pip install``. ``slot_already_served.py``
honours the claim like a run_history row. If the claim itself cannot be pushed, the job
fails right there - nothing irreversible has happened yet, and the next fire tries
again. One file per (date, slot): the two slots' claims can race each other's pushes,
and separate files rebase cleanly where two appends to one JSONL would conflict.

Claims older than ``KEEP_DAYS`` are deleted on the way through, so the directory stays
a few dozen files; the run's own commit step picks up the deletions.

Stdlib only - runs before ``pip install``.

Environment (all from the wait step):
  RUN_SLOT, RUN_SLOT_TIME, RUN_SLOT_AT   the slot being claimed; ``manual``/empty
                                         claims nothing (a manual dispatch is not a
                                         scheduled slot).
  GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT      recorded so the claim points at its run.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_run_health import EXPECTED_SLOTS  # noqa: E402
from scripts.slot_already_served import (  # noqa: E402
    MANUAL_SLOT,
    SLOT_CLAIMS_DIR,
    claim_path,
    claimed_by,
    market_date,
)

KEEP_DAYS = 30


def claim_row(now: datetime, env: dict[str, str]) -> dict | None:
    """The claim to write, or None when this run has no scheduled slot."""
    slot = env.get("RUN_SLOT", "").strip().lower()
    if not slot or slot == MANUAL_SLOT:
        return None
    if slot not in EXPECTED_SLOTS:
        raise ValueError(f"RUN_SLOT={slot!r} is not one of {EXPECTED_SLOTS}")
    day = market_date(now, env.get("RUN_SLOT_AT", "").strip() or None)
    return {
        "date": day.isoformat(),
        "slot": slot,
        "slot_time": env.get("RUN_SLOT_TIME", "").strip() or None,
        "slot_at": env.get("RUN_SLOT_AT", "").strip() or None,
        "claimed_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "github_run_id": env.get("GITHUB_RUN_ID", "").strip() or None,
        "github_run_attempt": env.get("GITHUB_RUN_ATTEMPT", "").strip() or None,
    }


def prune(root: Path, today: date, keep_days: int = KEEP_DAYS) -> list[Path]:
    """Delete claim files older than ``keep_days``; return what was removed."""
    cutoff = today - timedelta(days=keep_days)
    removed = []
    for path in sorted(root.glob("*.json")):
        try:
            day = date.fromisoformat(path.name[:10])
        except ValueError:
            continue
        if day < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def write_claim(row: dict, root: Path | None = None) -> Path:
    root = root or SLOT_CLAIMS_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = claim_path(row["slot"], date.fromisoformat(row["date"]), root)
    path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    prune(root, date.fromisoformat(row["date"]))
    return path


def main(
    *,
    now: datetime | None = None,
    env: dict[str, str] | None = None,
    claims_dir: Path | None = None,
) -> int:
    env = os.environ if env is None else env
    current = now or datetime.now(UTC)
    try:
        row = claim_row(current, env)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if row is None:
        print("No scheduled slot (manual dispatch) - nothing to claim.")
        return 0

    day = date.fromisoformat(row["date"])
    existing = claimed_by(row["slot"], day, claims_dir)
    if existing is not None:
        # slot_already_served.py should have ended the job before this step. If we are
        # here anyway, something upstream is wrong - refuse rather than double-run.
        print(
            f"::error::The {row['slot']} slot on {day} is already claimed by workflow run "
            f"{existing.get('github_run_id')} ({existing.get('claimed_at')}); refusing to "
            f"run the cycle twice.",
            file=sys.stderr,
        )
        return 1

    path = write_claim(row, claims_dir)
    print(
        f"Claimed the {row['slot']} slot for {day} (workflow run {row['github_run_id']}) "
        f"in {path}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
