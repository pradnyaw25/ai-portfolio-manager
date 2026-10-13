"""The daily-run schedule is correctness-critical config, so test it.

The market-hours guard aborts the WHOLE run (tweet, journal, site update) outside
9:30am-4:00pm America/New_York, and GitHub's scheduler fires this repo's crons late:
59-101 minutes through July 2026, then a median of ~105 min and a p90 of ~220 min
from late August (max 476). The first design budgeted ~2h of delay into the cron
times and lost four whole trading days plus 21 of 23 afternoon slots when the delay
outgrew the budget.

The current design fires each cron hours EARLY and sleeps until its slot
(scripts/wait_for_slot.py). These tests pin that invariant end to end: every cron
maps to a slot, the headroom fits the wait cap and the 6-hour job limit, the slot
lands inside market hours on the correct side of the receipts/spotlight boundary in
both DST seasons for any delay up to the headroom, and the workflow refreshes its
checkout after sleeping before it reads any data.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from scripts.wait_for_slot import (
    DEFAULT_MAX_WAIT_MINUTES,
    parse_slot_targets,
    seconds_to_wait,
)
from src.config import RECEIPTS_MORNING_CUTOFF_HOUR_UTC
from src.utils.market_hours import is_regular_market_hours

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "daily-run.yml"

# A summer (EDT) and a winter (EST) weekday.
SEASON_DAYS = ((2026, 7, 6), (2026, 1, 5))
# Delays the wait absorbs completely: on time, the old 59-101 norm, the new median
# and p90, and the full headroom.
ABSORBED_DELAYS_MIN = (0, 59, 101, 105, 220, 270)
# Delays past the headroom: the run starts the moment it fires. Still in-hours up to
# here; beyond it the slot is lost and the watchdog pages.
LATE_DELAYS_MIN = (300, 390)

# Hosted runners kill a job at 6 hours. The sleep plus install, cycle and deploy must
# stay inside that with margin.
JOB_LIMIT_MIN = 360
CYCLE_BUDGET_MIN = 30


def _spec() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _crons(spec: dict) -> list[str]:
    # PyYAML parses the bare key `on:` as the boolean True.
    triggers = spec.get(True) if True in spec else spec["on"]
    return [" ".join(entry["cron"].split()) for entry in triggers["schedule"]]


def _hhmm(cron: str) -> tuple[int, int]:
    minute, hour = cron.split()[:2]
    return int(hour), int(minute)


def _slots() -> list[tuple[str, str]]:
    """(cron, target HH:MM) for every scheduled run, from the workflow itself."""
    spec = _spec()
    targets = parse_slot_targets(spec["env"]["SLOT_TARGETS"])
    return [(cron, targets[cron]) for cron in _crons(spec)]


def _start_time(day, cron: str, target: str, delay_min: int) -> datetime:
    """When the cycle actually starts: fire time plus whatever the wait step adds."""
    fired = datetime(*day, *_hhmm(cron), tzinfo=UTC) + timedelta(minutes=delay_min)
    wait = seconds_to_wait(fired, target, timedelta(minutes=DEFAULT_MAX_WAIT_MINUTES))
    return fired + timedelta(seconds=wait)


def test_workflow_declares_two_weekday_runs():
    assert len(_crons(_spec())) == 2


def test_every_cron_maps_to_a_slot_and_nothing_else_does():
    """An unmapped cron would fail the wait step on every fire; a stale mapping would
    hide a cron that no longer exists."""
    spec = _spec()
    assert set(parse_slot_targets(spec["env"]["SLOT_TARGETS"])) == set(_crons(spec))


def test_headroom_fits_the_wait_cap_and_the_job_limit():
    for cron, target in _slots():
        fire = datetime(2026, 7, 6, *_hhmm(cron), tzinfo=UTC)
        slot = fire.replace(hour=int(target[:2]), minute=int(target[3:]))
        headroom = (slot - fire).total_seconds() / 60
        assert 0 < headroom <= DEFAULT_MAX_WAIT_MINUTES, (
            f"cron {cron} -> {target}: headroom {headroom:.0f} min exceeds the wait cap"
        )
        assert headroom + CYCLE_BUDGET_MIN < JOB_LIMIT_MIN, (
            f"cron {cron} -> {target}: a sleep of {headroom:.0f} min plus the cycle "
            "would hit the 6-hour job limit"
        )


@pytest.mark.parametrize("day", SEASON_DAYS)
@pytest.mark.parametrize("delay", ABSORBED_DELAYS_MIN)
def test_the_slot_lands_inside_market_hours_whatever_the_delay(day, delay):
    """The whole point: a delay inside the headroom must not move the start time."""
    for cron, target in _slots():
        start = _start_time(day, cron, target, delay)
        assert f"{start:%H:%M}" == target, (
            f"cron {cron} +{delay}min started at {start:%H:%M}Z, not the {target}Z slot"
        )
        assert is_regular_market_hours(start)


@pytest.mark.parametrize("day", SEASON_DAYS)
@pytest.mark.parametrize("delay", LATE_DELAYS_MIN)
def test_a_delay_past_the_headroom_still_lands_in_hours(day, delay):
    """Beyond the headroom the run starts immediately. The slots sit early enough in
    the session that even a 6.5h delay stays in-hours - the old design's whole
    tolerance was ~2h on the afternoon slot."""
    for cron, target in _slots():
        start = _start_time(day, cron, target, delay)
        assert is_regular_market_hours(start), (
            f"cron {cron} +{delay}min -> {start:%H:%M}Z falls outside market hours"
        )


@pytest.mark.parametrize("delay", ABSORBED_DELAYS_MIN + LATE_DELAYS_MIN)
def test_runs_stay_on_their_side_of_the_morning_afternoon_boundary(delay):
    """Receipts post on the morning run and the spotlight on the afternoon one, keyed
    off RECEIPTS_MORNING_CUTOFF_HOUR_UTC. Neither the wait nor a late fire may flip a
    run's side. September 2026 had zero morning runs: no receipts for a month."""
    (am_cron, am_target), (pm_cron, pm_target) = _slots()

    start_am = _start_time((2026, 7, 6), am_cron, am_target, delay)
    assert start_am.hour < RECEIPTS_MORNING_CUTOFF_HOUR_UTC, (
        f"morning run +{delay}min starts at {start_am:%H:%M}Z, past the cutoff - "
        "receipts would be skipped and the spotlight would fire instead"
    )

    start_pm = _start_time((2026, 7, 6), pm_cron, pm_target, delay)
    assert start_pm.hour >= RECEIPTS_MORNING_CUTOFF_HOUR_UTC, (
        f"afternoon run +{delay}min starts at {start_pm:%H:%M}Z, before the cutoff - "
        "it would be treated as the morning run"
    )


def test_the_job_waits_then_refreshes_its_checkout_before_reading_anything():
    """The checkout is hours old once the wait ends, and the other slot has usually
    pushed in between. Running on stale data would re-decide the morning's trades on
    yesterday's state. The refresh must sit between the wait and the first step that
    reads the repo, and must be fast-forward only."""
    steps = _spec()["jobs"]["run"]["steps"]
    names = [step.get("name", step.get("uses", "")) for step in steps]

    wait = names.index("Wait for the slot")
    refresh = names.index("Refresh checkout")
    guard = names.index("Check market hours")
    cycle = names.index("Run portfolio manager")
    assert wait < refresh < guard < cycle

    assert "--ff-only" in steps[refresh]["run"]
    assert "GITHUB_EVENT_SCHEDULE" in steps[wait]["env"]
