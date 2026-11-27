#!/usr/bin/env python3
"""Hold a scheduled run until its slot time, and say which slot it serves.

GitHub's scheduler does not fire cron jobs on time. On this repo it started runs
59-101 minutes late through July 2026, drifted to a median of ~105 minutes (max 476)
from late August, and in November 2026 ran a median of ~8.5 HOURS late (AM p90 627
min, max 710; PM p90 579, max 694). The daily cycle is gated to regular market hours,
so a cron time that "budgets for the delay" fails as soon as the delay grows past the
budget - which it did twice: four whole trading days were lost in September and the
afternoon slot landed after the close on 21 of 23 days; then in November a single early
cron with 4.5h of headroom was outrun again, the morning run was mistaken for the
afternoon one for a month (no receipts tweet) and 2026-11-23 was lost outright.

The fix is to stop budgeting and start absorbing. Each slot's cron fires EVERY TWO
HOURS from ~10 hours before the slot, and this script sleeps until the slot time. A
fire more than MAX_WAIT_MINUTES early starts at once, lands before the open and is
skipped by the market-hours guard. A fire inside the window waits the remaining time.
A fire after the slot starts at once and runs if the slot is still unserved
(scripts/slot_already_served.py) and the market is open. Fires two hours apart with a
five-hour window mean any delay from 0 to 10 hours puts at least two fires inside the
window; the first to wake runs the cycle, the rest find the slot served. Hosted-runner
minutes are free on a public repo, so sleeping and no-op jobs cost nothing.

Stdlib only - this runs before ``pip install`` on a bare checkout, and it must not be
able to fail for reasons of its own.

Environment:
  GITHUB_EVENT_SCHEDULE  the cron expression that fired (``github.event.schedule``).
                         Empty on ``workflow_dispatch``, which never waits.
  SLOT_TARGETS           ``"<cron>=HH:MM;<cron>=HH:MM"`` mapping each cron expression
                         to the UTC slot it serves (';'-separated: the expressions
                         carry commas in their hour field). An unmapped cron is a
                         configuration error and fails loudly rather than guessing.
  MAX_WAIT_MINUTES       safety cap on the sleep (default 300), well inside the 6-hour
                         job limit. A target further away than this means the fire is
                         an early backup; don't wait, let the guard skip.
  RECEIPTS_MORNING_CUTOFF_HOUR_UTC
                         slot times before this UTC hour are the "morning" slot, the
                         rest "afternoon" (default 17, mirroring src.config).
  GITHUB_OUTPUT          when set, the resolved slot (``slot``, ``slot_time``, the
                         slot instant ``slot_at``, ``cron``), the fire time
                         (``fired_at``), the scheduler delay in minutes (``delay_min``)
                         and whether this was the cron's last tick of the day
                         (``last_fire``) are written as step outputs for the later
                         steps and the run_history row. A manual dispatch writes
                         ``slot=manual`` only, so a manual run is recorded as such and
                         never counts as (or consumes) a scheduled slot.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime, timedelta

DEFAULT_MAX_WAIT_MINUTES = 300
DEFAULT_MORNING_CUTOFF_HOUR_UTC = 17
SLOT_NAMES = ("morning", "afternoon")
MANUAL_SLOT = "manual"
_SLEEP_CHUNK_SECONDS = 600


def parse_slot_targets(spec: str) -> dict[str, str]:
    """``"40 4,6 * * 1-5=14:40;50 7,9 * * 1-5=17:50"`` -> ``{cron: "HH:MM"}``."""
    targets: dict[str, str] = {}
    for item in spec.split(";"):
        item = item.strip()
        if not item:
            continue
        cron, sep, hhmm = item.rpartition("=")
        if not sep or not cron.strip() or not hhmm.strip():
            raise ValueError(f"bad slot target {item!r}; expected '<cron>=HH:MM'")
        if len(cron.split()) != 5 or "=" in cron:
            # Catches the old ','-separated format too, which would otherwise swallow
            # two entries into one mis-keyed mapping.
            raise ValueError(f"bad cron expression in slot target {item!r}; expected 5 fields")
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


def slot_name(target_hhmm: str, cutoff_hour: int = DEFAULT_MORNING_CUTOFF_HOUR_UTC) -> str:
    """``"14:40"`` -> ``"morning"``, ``"17:50"`` -> ``"afternoon"``.

    Judged on the SLOT time, which never moves, not on when the run starts - that
    was the November 2026 bug: a morning run that landed after the cutoff posted the
    spotlight instead of the receipts.
    """
    hour, _ = _parse_hhmm(target_hhmm)
    return SLOT_NAMES[0] if hour < cutoff_hour else SLOT_NAMES[1]


def _expand_field(field: str, lo: int, hi: int) -> list[int]:
    """A cron minute/hour field (``"*"``, ``"4,6,8"``, ``"4-8"``, ``"*/2"``) -> values."""
    values: set[int] = set()
    for part in field.split(","):
        part, _, step_s = part.partition("/")
        step = int(step_s) if step_s else 1
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            start_s, _, end_s = part.partition("-")
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(part)
        values.update(range(start, end + 1, step))
    return sorted(v for v in values if lo <= v <= hi)


def cron_ticks(cron: str) -> list[tuple[int, int]]:
    """The (hour, minute) pairs a cron expression fires at within a day, sorted."""
    minute_field, hour_field = cron.split()[:2]
    return sorted(
        (hour, minute)
        for hour in _expand_field(hour_field, 0, 23)
        for minute in _expand_field(minute_field, 0, 59)
    )


def _cron_weekdays(cron: str) -> set[int]:
    """The Python ``weekday()`` values (Mon=0) a cron's day-of-week field allows."""
    fields = cron.split()
    dow_field = fields[4] if len(fields) >= 5 else "*"
    # cron: 0 or 7 = Sunday, 1 = Monday ... 6 = Saturday; Python: Monday = 0.
    return {(d - 1) % 7 for d in _expand_field(dow_field, 0, 7)}


def last_tick_before(now: datetime, cron: str) -> datetime:
    """The most recent moment ``cron`` was due at or before ``now`` (UTC).

    Honours the day-of-week field: a weekday fire delayed past midnight into
    Saturday is measured against Friday's last tick, never against a Saturday tick
    the ``1-5`` field would not have produced, and Monday's first fire is never
    measured against a phantom Sunday tick.
    """
    current = now.astimezone(UTC)
    ticks = cron_ticks(cron)
    weekdays = _cron_weekdays(cron)
    for day_offset in range(0, 8):
        day = (current - timedelta(days=day_offset)).replace(second=0, microsecond=0)
        if day.weekday() not in weekdays:
            continue
        for hour, minute in reversed(ticks):
            candidate = day.replace(hour=hour, minute=minute)
            if candidate <= current:
                return candidate
    raise ValueError(f"cron {cron!r} has no ticks in the last week")


def is_last_tick(due: datetime, cron: str) -> bool:
    """Whether ``due`` is the cron's final tick of its day - the slot's last chance.

    The market-hours guard warns about a lost slot only on this fire: an earlier
    fire that lands out of hours still has later fires behind it.
    """
    return (due.hour, due.minute) == cron_ticks(cron)[-1]


def slot_instant(due: datetime, target_hhmm: str) -> datetime:
    """The UTC instant of the slot a fire due at ``due`` serves: the slot time on the
    tick's own date, so a fire delayed past midnight still names yesterday's slot."""
    hour, minute = _parse_hhmm(target_hhmm)
    return due.astimezone(UTC).replace(hour=hour, minute=minute, second=0, microsecond=0)


def seconds_to_wait(now: datetime, target_hhmm: str, max_wait: timedelta) -> float:
    """How long to sleep so the run starts at ``target_hhmm`` UTC today.

    Zero when the slot has already passed (the scheduler was later than the headroom:
    run immediately if the slot is still unserved; the guard decides) and zero when
    the slot is further away than ``max_wait`` (an early backup fire: waiting would
    burn the cap, and the guard skips a pre-open run anyway).
    """
    hour, minute = _parse_hhmm(target_hhmm)
    current = now.astimezone(UTC)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    remaining = (target - current).total_seconds()
    if remaining <= 0 or remaining > max_wait.total_seconds():
        return 0.0
    return remaining


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_outputs(outputs: dict[str, str], env: dict[str, str]) -> None:
    path = env.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a") as fh:
        for key, value in outputs.items():
            fh.write(f"{key}={value}\n")


def main(
    *,
    now: datetime | None = None,
    sleep=time.sleep,
    env: dict[str, str] | None = None,
) -> int:
    env = os.environ if env is None else env
    targets = parse_slot_targets(env.get("SLOT_TARGETS", ""))
    schedule = env.get("GITHUB_EVENT_SCHEDULE", "")
    target = resolve_target(schedule, targets)
    if target is None:
        print("No cron slot (manual dispatch) - not waiting.")
        _write_outputs({"slot": MANUAL_SLOT}, env)
        return 0

    cron = " ".join(schedule.split())
    cutoff = int(env.get("RECEIPTS_MORNING_CUTOFF_HOUR_UTC", DEFAULT_MORNING_CUTOFF_HOUR_UTC))
    slot = slot_name(target, cutoff)
    max_wait = timedelta(minutes=int(env.get("MAX_WAIT_MINUTES", DEFAULT_MAX_WAIT_MINUTES)))
    current = (now or datetime.now(UTC)).astimezone(UTC)
    due = last_tick_before(current, cron)
    delay_min = int((current - due).total_seconds() // 60)
    print(
        f"Cron {cron!r} due {due:%H:%M}Z fired at {current:%H:%M}Z ({delay_min} min late); "
        f"serves the {slot} slot at {target}Z."
    )
    _write_outputs(
        {
            "slot": slot,
            "slot_time": target,
            "slot_at": _iso(slot_instant(due, target)),
            "cron": cron,
            "fired_at": _iso(current),
            "delay_min": str(delay_min),
            "last_fire": str(is_last_tick(due, cron)).lower(),
        },
        env,
    )

    wait = seconds_to_wait(current, target, max_wait)
    if wait <= 0:
        print(
            f"Slot {target}Z has passed or is out of reach (now {current:%H:%M}Z) - "
            "starting immediately; the slot check and the market-hours guard decide."
        )
        return 0

    print(f"Holding {wait / 60:.0f} min for the {target}Z slot.")
    while wait > 0:
        chunk = min(wait, _SLEEP_CHUNK_SECONDS)
        sleep(chunk)
        wait -= chunk
    print(f"Slot {target}Z reached; releasing the run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
