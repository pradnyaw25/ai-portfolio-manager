#!/usr/bin/env python3
"""Hold a scheduled run until its slot time.

GitHub's scheduler does not fire cron jobs on time. On this repo it started runs
59-101 minutes late through July, then drifted to a median of ~105 minutes and a p90
of ~220 minutes from late August 2026 (max observed: 476 minutes). The daily cycle is
gated to regular market hours, so a cron time that "budgets for the delay" fails as
soon as the delay grows past the budget - which it did: four whole trading days were
lost in five weeks and, from 2026-09-01, the afternoon slot landed after the close on
21 of 23 trading days.

The fix is to stop budgeting and start absorbing. Each cron fires HOURS before the
slot it serves, and this script sleeps until the slot time. Fire on time: wait the
full headroom. Fire late: wait less. Fire after the slot has passed: don't wait at
all and let the market-hours guard decide. Hosted-runner minutes are free on a public
repo, so a sleeping job costs nothing.

Stdlib only - this runs before ``pip install`` on a bare checkout, and it must not be
able to fail for reasons of its own.

Environment:
  GITHUB_EVENT_SCHEDULE  the cron expression that fired (``github.event.schedule``).
                         Empty on ``workflow_dispatch``, which never waits.
  SLOT_TARGETS           ``"<cron>=HH:MM,<cron>=HH:MM"`` mapping each cron to the UTC
                         slot it serves. An unmapped cron is a configuration error and
                         fails loudly rather than guessing.
  MAX_WAIT_MINUTES       safety cap on the sleep (default 300), well inside the 6-hour
                         job limit. A target further away than this means the cron
                         fired on the wrong side of midnight; don't wait, let the
                         guard skip.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime, timedelta

DEFAULT_MAX_WAIT_MINUTES = 300
_SLEEP_CHUNK_SECONDS = 600


def parse_slot_targets(spec: str) -> dict[str, str]:
    """``"10 10 * * 1-5=14:40,20 13 * * 1-5=17:50"`` -> ``{cron: "HH:MM"}``."""
    targets: dict[str, str] = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        cron, sep, hhmm = item.rpartition("=")
        if not sep or not cron.strip() or not hhmm.strip():
            raise ValueError(f"bad slot target {item!r}; expected '<cron>=HH:MM'")
        _parse_hhmm(hhmm.strip())  # validate early, at config-read time
        targets[" ".join(cron.split())] = hhmm.strip()
    return targets


def resolve_target(schedule: str, targets: dict[str, str]) -> str | None:
    """The ``HH:MM`` slot this cron serves, or None for a manual dispatch."""
    if not schedule.strip():
        return None
    key = " ".join(schedule.split())
    if key not in targets:
        raise KeyError(
            f"cron {schedule!r} has no entry in SLOT_TARGETS {sorted(targets)}; "
            "add it next to the cron line in daily-run.yml"
        )
    return targets[key]


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    hour_s, _, minute_s = hhmm.partition(":")
    hour, minute = int(hour_s), int(minute_s)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"slot time out of range: {hhmm!r}")
    return hour, minute


def seconds_to_wait(now: datetime, target_hhmm: str, max_wait: timedelta) -> float:
    """How long to sleep so the run starts at ``target_hhmm`` UTC today.

    Zero when the slot has already passed (the scheduler was later than the headroom:
    run immediately, the market-hours guard decides) and zero when the slot is further
    away than ``max_wait`` (the cron fired on the wrong side of midnight: waiting would
    burn the cap and still land outside hours).
    """
    hour, minute = _parse_hhmm(target_hhmm)
    current = now.astimezone(UTC)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    remaining = (target - current).total_seconds()
    if remaining <= 0 or remaining > max_wait.total_seconds():
        return 0.0
    return remaining


def main(
    *,
    now: datetime | None = None,
    sleep=time.sleep,
    env: dict[str, str] | None = None,
) -> int:
    env = os.environ if env is None else env
    targets = parse_slot_targets(env.get("SLOT_TARGETS", ""))
    target = resolve_target(env.get("GITHUB_EVENT_SCHEDULE", ""), targets)
    if target is None:
        print("No cron slot (manual dispatch) - not waiting.")
        return 0

    max_wait = timedelta(minutes=int(env.get("MAX_WAIT_MINUTES", DEFAULT_MAX_WAIT_MINUTES)))
    current = now or datetime.now(UTC)
    wait = seconds_to_wait(current, target, max_wait)
    if wait <= 0:
        print(
            f"Slot {target}Z has passed or is out of reach (now {current:%H:%M}Z) - "
            "starting immediately; the market-hours guard decides."
        )
        return 0

    print(f"Fired at {current:%H:%M}Z; holding {wait / 60:.0f} min for the {target}Z slot.")
    while wait > 0:
        chunk = min(wait, _SLEEP_CHUNK_SECONDS)
        sleep(chunk)
        wait -= chunk
    print(f"Slot {target}Z reached; releasing the run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
