"""The daily-run schedule is correctness-critical config, so test it.

The market-hours guard aborts the WHOLE run (tweet, journal, site update) outside
9:30am-4:00pm America/New_York, and GitHub's scheduler fires this repo's crons late:
59-101 minutes through July 2026, a median of ~105 min from late August (max 476), and
a median of ~8.5 HOURS in November 2026 (max 710 min). Two designs have already been
outrun by that drift: cron times that budgeted ~2h of delay, then one early cron per
slot with 4.5h of headroom.

The current design fires each slot's cron EVERY TWO HOURS from ~10h before the slot
(one multi-hour expression per slot, so all fires share a concurrency group and are
serialized), sleeps each fire to the slot (scripts/wait_for_slot.py), lets the first
fire to reach the slot run the cycle and the rest find it served
(scripts/slot_already_served.py). These tests pin that end to end: every expression
maps to a slot; a delay anywhere from 0 to 10 hours still produces a fire that waits
and lands exactly on the slot, in-hours, in both DST seasons; an early fire lands
before the open so the guard skips it instead of serving the slot early; each run is
told which slot it serves so the receipts/spotlight choice no longer depends on the
clock; and the workflow refreshes its checkout and checks for an earlier run before
reading anything.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from scripts.wait_for_slot import (
    DEFAULT_MAX_WAIT_MINUTES,
    cron_ticks,
    parse_slot_targets,
    seconds_to_wait,
    slot_name,
)
from src.config import RECEIPTS_MORNING_CUTOFF_HOUR_UTC
from src.utils.market_hours import is_regular_market_hours

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "daily-run.yml"

# A summer (EDT) and a winter (EST) weekday.
SEASON_DAYS = ((2026, 7, 6), (2026, 1, 5))
# The scheduler delay the schedule must absorb completely, i.e. the slot is still
# served at its slot time. November 2026 maxed at 710 min; 10h is the design target.
ABSORBED_DELAY_MAX_MIN = 600
# Past that the first fire to land in-hours runs late, which the guard allows up to
# the close. Fires land every 2h, so a 12h delay is a run within ~2h of the slot.
LATE_DELAYS_MIN = (610, 660, 720)
# Hosted runners kill a job at 6 hours. The sleep plus install, cycle and deploy must
# stay inside that with margin.
JOB_LIMIT_MIN = 360
CYCLE_BUDGET_MIN = 30
MAX_WAIT = timedelta(minutes=DEFAULT_MAX_WAIT_MINUTES)


def _spec() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _crons(spec: dict) -> list[str]:
    # PyYAML parses the bare key `on:` as the boolean True.
    triggers = spec.get(True) if True in spec else spec["on"]
    return [" ".join(entry["cron"].split()) for entry in triggers["schedule"]]


def _slots() -> list[tuple[str, str]]:
    """(cron expression, target HH:MM) for every scheduled slot, from the workflow."""
    spec = _spec()
    targets = parse_slot_targets(spec["env"]["SLOT_TARGETS"])
    return [(cron, targets[cron]) for cron in _crons(spec)]


def _slot_dt(day, target: str) -> datetime:
    return datetime(*day, int(target[:2]), int(target[3:]), tzinfo=UTC)


def _fires(day, cron: str, delay_min: int) -> list[datetime]:
    """When each tick of ``cron`` actually fires on ``day``, ``delay_min`` late."""
    return [
        datetime(*day, hour, minute, tzinfo=UTC) + timedelta(minutes=delay_min)
        for hour, minute in cron_ticks(cron)
    ]


def _start(fired: datetime, target: str) -> datetime:
    """When a fire's cycle would start: fire time plus whatever the wait step adds."""
    return fired + timedelta(seconds=seconds_to_wait(fired, target, MAX_WAIT))


def _serving_fire(day, cron: str, target: str, delay_min: int) -> datetime | None:
    """The first fire that lands in-hours, i.e. the one that serves the slot (the
    workflow serializes a slot's fires, and the later ones find the slot served)."""
    for fired in _fires(day, cron, delay_min):
        start = _start(fired, target)
        if is_regular_market_hours(start):
            return start
    return None


# --- the mapping itself -------------------------------------------------------


def test_workflow_declares_one_expression_per_slot_on_weekdays():
    crons = _crons(_spec())
    assert len(crons) == 2
    assert all(cron.split()[4] == "1-5" for cron in crons)


def test_every_cron_maps_to_a_slot_and_nothing_else_does():
    """An unmapped cron would fail the wait step on every fire; a stale mapping would
    hide a cron that no longer exists."""
    spec = _spec()
    assert set(parse_slot_targets(spec["env"]["SLOT_TARGETS"])) == set(_crons(spec))


def test_each_slot_is_one_expression_so_its_fires_share_a_concurrency_group():
    """Two fires sleeping to the same slot in DIFFERENT groups would both wake at the
    slot and both run the cycle. The group is keyed on github.event.schedule, so the
    fires of a slot must come from ONE expression with several hours."""
    group = _spec()["concurrency"]["group"]
    assert "github.event.schedule" in group
    for cron, _ in _slots():
        assert len(cron_ticks(cron)) >= 2, f"{cron!r} fires once: no backups"
    targets = [target for _, target in _slots()]
    assert len(set(targets)) == len(targets), "two expressions serve the same slot"


def test_the_two_slots_are_one_morning_and_one_afternoon():
    assert sorted(slot_name(target) for _, target in _slots()) == ["afternoon", "morning"]
    for _, target in _slots():
        assert slot_name(target, RECEIPTS_MORNING_CUTOFF_HOUR_UTC) == slot_name(target)


# --- fires, headroom and the job limit ----------------------------------------


def test_fires_are_close_enough_together_that_the_wait_window_never_has_a_gap():
    """With fires at most MAX_WAIT apart, every delay puts at least one fire inside
    the [slot - MAX_WAIT, slot] window, so the slot is served ON TIME for any delay
    up to the earliest fire's distance from the slot."""
    for cron, target in _slots():
        ticks = cron_ticks(cron)
        slot = _slot_dt((2026, 7, 6), target)
        times = [datetime(2026, 7, 6, h, m, tzinfo=UTC) for h, m in ticks]
        gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
        assert all(gap <= DEFAULT_MAX_WAIT_MINUTES for gap in gaps), (cron, gaps)
        headroom_last = (slot - times[-1]).total_seconds() / 60
        assert 0 < headroom_last <= DEFAULT_MAX_WAIT_MINUTES, (cron, headroom_last)
        headroom_first = (slot - times[0]).total_seconds() / 60
        assert headroom_first >= ABSORBED_DELAY_MAX_MIN, (
            f"{cron!r}: earliest fire is only {headroom_first:.0f} min before the "
            f"{target}Z slot; the design target is {ABSORBED_DELAY_MAX_MIN}"
        )
        assert all(t.date() == slot.date() for t in times), "a fire crosses midnight"


def test_the_longest_sleep_fits_the_job_limit():
    assert DEFAULT_MAX_WAIT_MINUTES + CYCLE_BUDGET_MIN < JOB_LIMIT_MIN


# --- the whole point: any delay up to 10h still lands on the slot ---------------


@pytest.mark.parametrize("day", SEASON_DAYS)
@pytest.mark.parametrize("delay", range(0, ABSORBED_DELAY_MAX_MIN + 1, 15))
def test_a_delay_up_to_ten_hours_still_serves_the_slot_at_its_slot_time(day, delay):
    for cron, target in _slots():
        start = _serving_fire(day, cron, target, delay)
        assert start is not None, f"{cron!r} +{delay}min: no fire lands in-hours"
        assert f"{start:%H:%M}" == target, (
            f"{cron!r} +{delay}min: served at {start:%H:%M}Z, not the {target}Z slot"
        )


@pytest.mark.parametrize("day", SEASON_DAYS)
@pytest.mark.parametrize("delay", LATE_DELAYS_MIN)
def test_a_delay_past_ten_hours_still_lands_in_hours(day, delay):
    """Beyond the absorbed range the slot is served late, but still inside the
    session - the November 2026 max of 710 min would have been a late run, not a
    lost one."""
    for cron, target in _slots():
        start = _serving_fire(day, cron, target, delay)
        assert start is not None, f"{cron!r} +{delay}min: the day is lost"
        assert start - _slot_dt(day, target) <= timedelta(hours=2, minutes=30)


@pytest.mark.parametrize("day", SEASON_DAYS)
@pytest.mark.parametrize("delay", range(0, ABSORBED_DELAY_MAX_MIN + 1, 15))
def test_an_early_fire_never_serves_the_slot_early(day, delay):
    """A fire more than MAX_WAIT before its slot starts at once. It must land before
    the open, so the guard skips it, rather than inside hours, where it would make
    the day's decision hours early."""
    for cron, target in _slots():
        slot = _slot_dt(day, target)
        for fired in _fires(day, cron, delay):
            if fired < slot and seconds_to_wait(fired, target, MAX_WAIT) == 0:
                assert not is_regular_market_hours(fired), (
                    f"{cron!r} +{delay}min: fire at {fired:%H:%M}Z would run early"
                )


def test_the_slot_decides_morning_vs_afternoon_not_the_clock():
    """A morning fire that lands at 19:00Z is still the morning run. The slot name is
    a function of the slot TIME alone and both slots sit on their side of the cutoff,
    so no delay can flip receipts and spotlight again (November 2026: zero receipts)."""
    for _, target in _slots():
        hour = int(target[:2])
        expected = "morning" if hour < RECEIPTS_MORNING_CUTOFF_HOUR_UTC else "afternoon"
        assert slot_name(target) == expected


# --- the workflow's shape ------------------------------------------------------


def _steps():
    return _spec()["jobs"]["run"]["steps"]


def _names(steps):
    return [step.get("name", step.get("uses", "")) for step in steps]


def test_the_job_waits_refreshes_then_checks_the_slot_before_the_guard_and_the_cycle():
    """The checkout is hours old once the wait ends, and the other slot - or an
    earlier fire of this one - has usually pushed in between. The refresh must sit
    between the wait and the first step that reads the repo, and the already-served
    check must read the REFRESHED run_history, before the guard and the cycle."""
    steps = _steps()
    names = _names(steps)

    wait = names.index("Wait for the slot")
    refresh = names.index("Refresh checkout")
    served = names.index("Check slot already served")
    guard = names.index("Check market hours")
    cycle = names.index("Run portfolio manager")
    assert wait < refresh < served < guard < cycle

    assert "--ff-only" in steps[refresh]["run"]
    assert "GITHUB_EVENT_SCHEDULE" in steps[wait]["env"]
    assert steps[wait]["id"] == "wait"
    assert steps[served]["env"]["RUN_SLOT"] == "${{ steps.wait.outputs.slot }}"
    assert "steps.slot-check.outputs.already_served != 'true'" in steps[guard]["if"]


def test_the_cycle_is_told_which_slot_it_serves():
    """RUN_SLOT reaches the cycle so the run_history row and the receipts/spotlight
    choice carry the slot the cron fired for, not a guess from the start hour."""
    steps = _steps()
    cycle = steps[_names(steps).index("Run portfolio manager")]
    guard = steps[_names(steps).index("Check market hours")]
    for env in (cycle["env"], guard["env"]):
        assert env["RUN_SLOT"] == "${{ steps.wait.outputs.slot }}"
        assert env["RUN_FIRED_AT"] == "${{ steps.wait.outputs.fired_at }}"
        assert env["RUN_SCHEDULER_DELAY_MIN"] == "${{ steps.wait.outputs.delay_min }}"
