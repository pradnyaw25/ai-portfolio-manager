"""The daily-run cron times are correctness-critical config, so test them.

The market-hours guard aborts the WHOLE run (tweet, journal, site update) outside
9:30am-4:00pm America/New_York, and GitHub has started this repo's scheduled runs
59-101 minutes late on every observed run. A cron time without room for that delay
silently kills the run — which is exactly what happened when the afternoon run was
moved to 19:47 UTC (3:47pm ET, 13 minutes of margin) and then landed past the close
every day, taking the spotlight tweet with it.

These tests pin the invariant: whether a run fires on time or ~2h late, in either DST
season, it must land inside market hours AND on the correct side of the
receipts/spotlight morning-vs-afternoon boundary.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from src.config import RECEIPTS_MORNING_CUTOFF_HOUR_UTC
from src.utils.market_hours import is_regular_market_hours

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "daily-run.yml"

# Observed GitHub scheduler delays are 59-101 min; test the full plausible spread
# including an on-time run and a worse-than-observed one.
DELAYS_MIN = (0, 30, 59, 101, 120)
# A summer (EDT) and a winter (EST) weekday.
SEASON_DAYS = ((2026, 7, 6), (2026, 1, 5))


def _cron_times() -> list[tuple[int, int]]:
    """(hour, minute) for every scheduled cron in the daily-run workflow."""
    spec = yaml.safe_load(WORKFLOW.read_text())
    # PyYAML parses the bare key `on:` as the boolean True.
    triggers = spec.get(True) if True in spec else spec["on"]
    times = []
    for entry in triggers["schedule"]:
        minute, hour = entry["cron"].split()[:2]
        for h in str(hour).split(","):
            times.append((int(h), int(minute)))
    return sorted(times)


def test_workflow_declares_two_weekday_runs():
    assert len(_cron_times()) == 2


@pytest.mark.parametrize("day", SEASON_DAYS)
@pytest.mark.parametrize("delay", DELAYS_MIN)
def test_every_scheduled_run_lands_inside_market_hours(day, delay):
    """A run must survive the scheduler delay in both DST seasons — otherwise the
    market-hours guard skips the entire cycle and nothing publishes."""
    for hour, minute in _cron_times():
        fired = datetime(*day, hour, minute, tzinfo=UTC) + timedelta(minutes=delay)
        assert is_regular_market_hours(fired), (
            f"cron {hour:02d}:{minute:02d}Z +{delay}min -> {fired:%H:%M}Z falls outside "
            "market hours; the whole run (tweets included) would be skipped"
        )


@pytest.mark.parametrize("delay", DELAYS_MIN)
def test_runs_stay_on_their_side_of_the_morning_afternoon_boundary(delay):
    """Receipts post on the morning run and the spotlight on the afternoon one, keyed
    off RECEIPTS_MORNING_CUTOFF_HOUR_UTC. The delay must not flip a run's side."""
    morning, afternoon = _cron_times()

    fired_am = datetime(2026, 7, 6, *morning, tzinfo=UTC) + timedelta(minutes=delay)
    assert fired_am.hour < RECEIPTS_MORNING_CUTOFF_HOUR_UTC, (
        f"morning run +{delay}min lands at {fired_am:%H:%M}Z, past the cutoff — "
        "receipts would be skipped and the spotlight would fire instead"
    )

    fired_pm = datetime(2026, 7, 6, *afternoon, tzinfo=UTC) + timedelta(minutes=delay)
    assert fired_pm.hour >= RECEIPTS_MORNING_CUTOFF_HOUR_UTC, (
        f"afternoon run +{delay}min lands at {fired_pm:%H:%M}Z, before the cutoff — "
        "it would be treated as the morning run"
    )
