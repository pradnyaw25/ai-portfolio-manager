"""The daily run fires early - many times - and waits for its slot, instead of
budgeting for GitHub's scheduler delay. From late August 2026 that delay grew from ~1h
to a median of ~105 minutes (max 476) and the budget-based cron times silently lost
four whole trading days and the afternoon slot on 21 of 23 days; in November 2026 it
reached a median of ~8.5h (max 710 min) and outran a single early cron with 4.5h of
headroom. These tests pin the wait, the slot naming and the step outputs."""

from datetime import UTC, datetime, timedelta

import pytest

from scripts.wait_for_slot import (
    DEFAULT_MAX_WAIT_MINUTES,
    cron_ticks,
    last_tick_before,
    main,
    parse_slot_targets,
    resolve_target,
    seconds_to_wait,
    slot_name,
)

AM = "40 4,6,8,10,12 * * 1-5"
PM = "50 7,9,11,13,15 * * 1-5"
TARGETS = f"{AM}=14:40;{PM}=17:50"
MAX_WAIT = timedelta(minutes=DEFAULT_MAX_WAIT_MINUTES)


def _utc(h, m):
    return datetime(2026, 9, 15, h, m, tzinfo=UTC)


# --- how long to hold ------------------------------------------------------


def test_an_on_time_fire_inside_the_window_waits_the_full_headroom():
    assert seconds_to_wait(_utc(10, 40), "14:40", MAX_WAIT) == 240 * 60


def test_a_late_fire_waits_less():
    """Fired 100 minutes late: the slot is 140 minutes away, not 240."""
    assert seconds_to_wait(_utc(12, 20), "14:40", MAX_WAIT) == 140 * 60


def test_an_early_backup_fire_does_not_wait():
    """The 04:40 fire on time is 10 hours from its slot: start now, land pre-open,
    let the guard skip it. The wait cap is what keeps the job inside the 6h limit."""
    assert seconds_to_wait(_utc(4, 40), "14:40", MAX_WAIT) == 0
    assert seconds_to_wait(_utc(9, 39), "14:40", MAX_WAIT) == 0
    assert seconds_to_wait(_utc(9, 40), "14:40", MAX_WAIT) == 300 * 60


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

    fired = datetime(2026, 9, 15, 6, 40, tzinfo=ZoneInfo("America/New_York"))  # 10:40Z
    assert seconds_to_wait(fired, "14:40", MAX_WAIT) == 240 * 60


# --- mapping crons to slots -------------------------------------------------


def test_slot_targets_parse_and_normalise_whitespace():
    targets = parse_slot_targets(f" {AM} = 14:40 ;50 7,9,11,13,15  * * 1-5=17:50;")
    assert targets == {AM: "14:40", PM: "17:50"}


@pytest.mark.parametrize(
    "spec",
    [
        AM,
        "=14:40",
        f"{AM}=25:00",
        # The pre-November ','-separated format: the hour field now carries commas, so
        # this must fail rather than silently mis-key two entries into one.
        "10 10 * * 1-5=14:40,20 13 * * 1-5=17:50",
    ],
)
def test_malformed_slot_targets_fail_loudly(spec):
    with pytest.raises(ValueError):
        parse_slot_targets(spec)


# --- naming the slot and measuring the delay --------------------------------


def test_slot_name_is_a_function_of_the_slot_time_not_the_clock():
    assert slot_name("14:40") == "morning"
    assert slot_name("17:50") == "afternoon"
    assert slot_name("16:59", cutoff_hour=17) == "morning"
    assert slot_name("17:00", cutoff_hour=17) == "afternoon"


def test_cron_ticks_expand_hour_lists_ranges_and_steps():
    assert cron_ticks(AM) == [(4, 40), (6, 40), (8, 40), (10, 40), (12, 40)]
    assert cron_ticks("0 9-11 * * 1-5") == [(9, 0), (10, 0), (11, 0)]
    assert cron_ticks("30 */12 * * *") == [(0, 30), (12, 30)]


def test_the_delay_is_measured_from_the_most_recent_tick():
    # 12:40 tick fired at 14:10 -> 90 min late (not measured from 04:40).
    assert last_tick_before(_utc(14, 10), AM) == _utc(12, 40)
    # Fired at 04:39, a minute before today's first tick: that is yesterday's 12:40.
    assert last_tick_before(_utc(4, 39), AM) == _utc(12, 40) - timedelta(days=1)


def test_an_unmapped_cron_is_a_configuration_error():
    """Adding a cron without a slot must not silently run with no wait."""
    with pytest.raises(KeyError, match="no entry in SLOT_TARGETS"):
        resolve_target("0 12 * * 1-5", parse_slot_targets(TARGETS))


def test_manual_dispatch_has_no_slot():
    assert resolve_target("", parse_slot_targets(TARGETS)) is None


# --- the script end to end --------------------------------------------------


def test_main_sleeps_until_the_slot_in_chunks():
    slept = []
    env = {"SLOT_TARGETS": TARGETS, "GITHUB_EVENT_SCHEDULE": PM}

    rc = main(now=_utc(17, 25), sleep=slept.append, env=env)

    assert rc == 0
    assert sum(slept) == 25 * 60
    assert max(slept) <= 600


def test_main_does_not_sleep_on_manual_dispatch(tmp_path):
    slept = []
    out = tmp_path / "out"
    env = {"SLOT_TARGETS": TARGETS, "GITHUB_OUTPUT": str(out)}

    rc = main(now=_utc(10, 10), sleep=slept.append, env=env)

    assert rc == 0
    assert slept == []
    assert not out.exists()  # no slot outputs: downstream steps see an empty slot


def test_main_releases_immediately_when_the_slot_has_passed(capsys):
    slept = []
    env = {"SLOT_TARGETS": TARGETS, "GITHUB_EVENT_SCHEDULE": AM}

    rc = main(now=_utc(16, 0), sleep=slept.append, env=env)

    assert rc == 0
    assert slept == []
    assert "guard decide" in capsys.readouterr().out


def test_main_writes_the_slot_fire_time_and_delay_as_step_outputs(tmp_path):
    """Everything downstream keys off these: the already-served check, the guard's
    skip warning, and the run_history row's `slot`."""
    out = tmp_path / "out"
    env = {"SLOT_TARGETS": TARGETS, "GITHUB_EVENT_SCHEDULE": AM, "GITHUB_OUTPUT": str(out)}

    main(now=_utc(14, 10), sleep=lambda s: None, env=env)

    lines = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert lines == {
        "slot": "morning",
        "slot_time": "14:40",
        "cron": AM,
        "fired_at": "2026-09-15T14:10:00Z",
        "delay_min": "90",
    }


def test_a_late_morning_fire_is_still_the_morning_slot(tmp_path):
    """The November 2026 bug: the 14:40 slot landing at 19:00Z was treated as the
    afternoon run because only the clock was consulted."""
    out = tmp_path / "out"
    env = {"SLOT_TARGETS": TARGETS, "GITHUB_EVENT_SCHEDULE": AM, "GITHUB_OUTPUT": str(out)}

    main(now=_utc(19, 0), sleep=lambda s: None, env=env)

    assert "slot=morning\n" in out.read_text()
