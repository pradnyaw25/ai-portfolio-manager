"""The watchdog for the daily cycle.

#92 made a failed run visible (non-zero exit, red job). It did not make it *noticed* —
both August 2026 incidents were found days later by hand. This check is the observer,
and it must satisfy two competing constraints:

1. Catch a day the fund silently skipped. A run cancelled before its first step writes
   no run_history row at all, so only an independent check can see the hole.
2. Never cry wolf. An alert that fires on weekends, market holidays, or a failure the
   second cron slot already recovered is an alert people learn to ignore, which is
   worse than no alert.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.check_run_health import (
    MARKET_HOLIDAYS,
    check,
    is_trading_day,
    target_day,
)

ET = ZoneInfo("America/New_York")


def _run(started_at, status="success", run_id="r1", errors=None):
    return {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": started_at,
        "status": status,
        "errors": errors or [],
    }


def _date(s):
    return datetime.fromisoformat(f"{s}T12:00:00+00:00").date()


# --- what counts as a day the fund owes us a run ---------------------------


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2026-08-07", True),  # Friday
        ("2026-08-08", False),  # Saturday
        ("2026-08-09", False),  # Sunday
        ("2026-07-03", False),  # Independence Day (observed)
        ("2026-11-26", False),  # Thanksgiving
    ],
)
def test_trading_day_recognises_weekends_and_holidays(day, expected):
    assert is_trading_day(_date(day)) is expected


def test_every_listed_holiday_is_a_weekday():
    """A weekend date in the list is dead weight and hints the list is wrong."""
    for iso in MARKET_HOLIDAYS:
        assert _date(iso).weekday() < 5, f"{iso} is not a weekday"


# --- the two real incidents ------------------------------------------------


def test_a_day_with_no_run_at_all_alerts():
    """The 2026-08-06 failure: the fund lost a whole trading day and nothing noticed.

    A cancelled run leaves no run_history row, so absence is the only signal.
    """
    runs = [_run("2026-08-05T16:18:00Z"), _run("2026-08-07T15:30:00Z")]

    healthy, message = check(runs, _date("2026-08-06"))

    assert healthy is False
    assert "NO RUN RECORDED" in message
    assert "2026-08-06" in message


def test_a_failed_run_alerts_with_its_error():
    """The 2026-08-05 failure mode, when nothing recovers it."""
    runs = [
        _run(
            "2026-08-05T16:18:00Z",
            status="failed",
            run_id="r_bad",
            errors=["decide_trades: Request timed out."],
        )
    ]

    healthy, message = check(runs, _date("2026-08-05"))

    assert healthy is False
    assert "RUN FAILED" in message
    assert "decide_trades: Request timed out." in message
    assert "r_bad" in message


# --- not crying wolf -------------------------------------------------------


def test_a_recovered_failure_does_not_alert_but_is_reported():
    """What actually happened on 2026-08-05: the morning run failed, the afternoon
    run succeeded, and the fund did trade. Paging on that is noise."""
    runs = [
        _run("2026-08-05T16:18:00Z", status="failed", run_id="r_am"),
        _run("2026-08-05T19:06:00Z", status="success", run_id="r_pm"),
    ]

    healthy, message = check(runs, _date("2026-08-05"))

    assert healthy is True
    assert "1 earlier run(s) failed" in message  # surfaced, not hidden


def test_weekends_and_holidays_never_alert():
    for day in ("2026-08-08", "2026-07-03"):
        healthy, message = check([], _date(day))
        assert healthy is True
        assert "not a trading day" in message


def test_a_late_evening_run_still_counts_for_that_day():
    """Runs are stamped UTC; 2026-08-07T23:30Z is still Aug 7 in market time."""
    runs = [_run("2026-08-07T23:30:00Z")]

    healthy, _ = check(runs, _date("2026-08-07"))

    assert healthy is True


# --- the watchdog's own lateness -------------------------------------------


@pytest.mark.parametrize(
    "fired,expected",
    [
        (datetime(2026, 8, 7, 18, 15, tzinfo=ET), "2026-08-07"),  # on time
        (datetime(2026, 8, 7, 22, 15, tzinfo=ET), "2026-08-07"),  # hours late
        (datetime(2026, 8, 8, 0, 30, tzinfo=ET), "2026-08-07"),  # past midnight
        (datetime(2026, 8, 10, 2, 0, tzinfo=ET), "2026-08-07"),  # Mon, back to Fri
        (datetime(2026, 7, 6, 0, 30, tzinfo=ET), "2026-07-02"),  # skips Jul 3 holiday
    ],
)
def test_target_day_survives_the_scheduler_being_late(fired, expected):
    """This repo's scheduler has fired up to ~4h45m late. If a 22:15 UTC check rolls
    past midnight in market time, judging "today" would test a day the fund hasn't run
    yet and alarm every single time — the watchdog itself becoming the false alarm."""
    assert target_day(fired).isoformat() == expected


# --- robustness ------------------------------------------------------------


def test_unparseable_timestamps_do_not_mask_a_real_alert():
    runs = [_run(None), _run("garbage"), _run("")]

    healthy, message = check(runs, _date("2026-08-06"))

    assert healthy is False
    assert "NO RUN RECORDED" in message


def test_an_unknown_status_is_treated_as_a_failure():
    """Fail closed: a status we don't recognise is not evidence of success."""
    runs = [_run("2026-08-07T15:30:00Z", status="cancelled")]

    healthy, message = check(runs, _date("2026-08-07"))

    assert healthy is False
    assert "RUN FAILED" in message
