"""The daily run fires early and waits for its slot, instead of budgeting for GitHub's
scheduler delay. From late August 2026 that delay grew from ~1h to a median of ~105
minutes (p90 ~220, max 476), and the budget-based cron times silently lost four whole
trading days and the afternoon slot on 21 of 23 days. These tests pin the wait."""

from datetime import UTC, datetime, timedelta

import pytest

from scripts.wait_for_slot import (
    DEFAULT_MAX_WAIT_MINUTES,
    main,
    parse_slot_targets,
    resolve_target,
    seconds_to_wait,
)

TARGETS = "10 10 * * 1-5=14:40,20 13 * * 1-5=17:50"
MAX_WAIT = timedelta(minutes=DEFAULT_MAX_WAIT_MINUTES)


def _utc(h, m):
    return datetime(2026, 9, 15, h, m, tzinfo=UTC)


# --- how long to hold ------------------------------------------------------


def test_an_on_time_fire_waits_the_full_headroom():
    assert seconds_to_wait(_utc(10, 10), "14:40", MAX_WAIT) == 270 * 60


def test_a_late_fire_waits_less():
    """Fired 100 minutes late: the slot is 170 minutes away, not 270."""
    assert seconds_to_wait(_utc(11, 50), "14:40", MAX_WAIT) == 170 * 60


def test_a_fire_past_the_slot_does_not_wait():
    """The scheduler was later than the headroom. Run now; the guard decides."""
    assert seconds_to_wait(_utc(14, 41), "14:40", MAX_WAIT) == 0
    assert seconds_to_wait(_utc(19, 0), "14:40", MAX_WAIT) == 0


def test_a_fire_on_the_wrong_side_of_midnight_does_not_wait():
    """Fired at 00:30Z (a 14-hour delay): the next 14:40 is 14 hours away, far past
    the cap. Waiting would burn five runner-hours and still land outside hours."""
    assert seconds_to_wait(_utc(0, 30), "14:40", MAX_WAIT) == 0


def test_the_wait_is_computed_in_utc_whatever_the_input_zone():
    from zoneinfo import ZoneInfo

    fired = datetime(2026, 9, 15, 6, 10, tzinfo=ZoneInfo("America/New_York"))  # 10:10Z
    assert seconds_to_wait(fired, "14:40", MAX_WAIT) == 270 * 60


# --- mapping crons to slots -------------------------------------------------


def test_slot_targets_parse_and_normalise_whitespace():
    targets = parse_slot_targets(" 10 10 * * 1-5 = 14:40 ,20  13 * * 1-5=17:50,")
    assert targets == {"10 10 * * 1-5": "14:40", "20 13 * * 1-5": "17:50"}


@pytest.mark.parametrize("spec", ["10 10 * * 1-5", "=14:40", "10 10 * * 1-5=25:00"])
def test_malformed_slot_targets_fail_loudly(spec):
    with pytest.raises(ValueError):
        parse_slot_targets(spec)


def test_an_unmapped_cron_is_a_configuration_error():
    """Adding a cron without a slot must not silently run with no wait."""
    with pytest.raises(KeyError, match="no entry in SLOT_TARGETS"):
        resolve_target("0 12 * * 1-5", parse_slot_targets(TARGETS))


def test_manual_dispatch_has_no_slot():
    assert resolve_target("", parse_slot_targets(TARGETS)) is None


# --- the script end to end --------------------------------------------------


def test_main_sleeps_until_the_slot_in_chunks():
    slept = []
    env = {"SLOT_TARGETS": TARGETS, "GITHUB_EVENT_SCHEDULE": "20 13 * * 1-5"}

    rc = main(now=_utc(17, 25), sleep=slept.append, env=env)

    assert rc == 0
    assert sum(slept) == 25 * 60
    assert max(slept) <= 600


def test_main_does_not_sleep_on_manual_dispatch():
    slept = []

    rc = main(now=_utc(10, 10), sleep=slept.append, env={"SLOT_TARGETS": TARGETS})

    assert rc == 0
    assert slept == []


def test_main_releases_immediately_when_the_slot_has_passed(capsys):
    slept = []
    env = {"SLOT_TARGETS": TARGETS, "GITHUB_EVENT_SCHEDULE": "10 10 * * 1-5"}

    rc = main(now=_utc(16, 0), sleep=slept.append, env=env)

    assert rc == 0
    assert slept == []
    assert "guard decides" in capsys.readouterr().out
