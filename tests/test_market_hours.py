"""The NYSE calendar behind the CI guard and the execution gate.

``is_regular_market_hours()`` used to know only the weekday session. On Thanksgiving
2026 (NYSE closed) a late scheduled run passed it at 19:34 UTC and sold ORCL on the
prior day's close; the next day was a 13:00 early close it did not know about either.
These tests pin the calendar: the two times that got through, the early-close morning
that must still run, both DST boundaries, the early-close rule, and the agreement
between this module's holiday list and the copy the dependency-free watchdog carries.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import scripts.check_run_health as watchdog
from src.utils import market_hours
from src.utils.market_hours import (
    EARLY_CLOSES,
    MARKET_HOLIDAYS,
    is_regular_market_hours,
    is_trading_day,
    market_close,
    market_status,
)

NY = ZoneInfo("America/New_York")


# --- a normal day --------------------------------------------------------------------


def test_a_normal_day_is_open_from_the_bell_to_four():
    assert market_status(datetime(2026, 6, 15, 9, 29, tzinfo=NY)) == (False, "before the open")
    assert market_status(datetime(2026, 6, 15, 9, 30, tzinfo=NY)) == (True, "regular market hours")
    assert market_status(datetime(2026, 6, 15, 15, 59, tzinfo=NY)) == (True, "regular market hours")
    assert market_status(datetime(2026, 6, 15, 16, 0, tzinfo=NY)) == (False, "after the close")
    assert market_close(date(2026, 6, 15)) == market_hours.MARKET_CLOSE
    assert is_trading_day(date(2026, 6, 15))


def test_a_weekend_is_closed():
    assert market_status(datetime(2026, 6, 13, 12, 0, tzinfo=NY)) == (False, "weekend")


def test_an_aware_utc_input_is_read_in_new_york_time():
    now = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)  # 06:00 ET, pre-open
    assert not is_regular_market_hours(now)


# --- the two times that got through ---------------------------------------------------


def test_thanksgiving_2026_is_closed_all_day():
    """The 2026-11-26 run started 19:35 UTC (14:34 ET) — inside the weekday session,
    on a day the exchange never opened. It sold ORCL on Wednesday's close."""
    now = datetime(2026, 11, 26, 19, 34, tzinfo=UTC)

    assert not is_regular_market_hours(now)
    assert market_status(now) == (False, "market holiday (2026-11-26)")
    assert not is_trading_day(date(2026, 11, 26))


def test_day_after_thanksgiving_2026_closes_at_one():
    """18:30 UTC on 2026-11-27 is 13:30 ET: half an hour after the early bell."""
    now = datetime(2026, 11, 27, 18, 30, tzinfo=UTC)

    assert not is_regular_market_hours(now)
    assert market_status(now) == (False, "after the 13:00 early close (2026-11-27)")
    assert market_close(date(2026, 11, 27)) == market_hours.EARLY_CLOSE


def test_the_early_close_morning_still_trades():
    """An early close is a short session, not a closure. The 14:40 UTC morning slot
    (09:40 ET) and the 17:50 UTC afternoon slot (12:50 ET) both land inside it in
    winter — the guard must let them through."""
    for utc_hour, utc_minute in ((14, 40), (17, 50)):
        now = datetime(2026, 11, 27, utc_hour, utc_minute, tzinfo=UTC)
        assert is_regular_market_hours(now), f"{now:%H:%M}Z should be in session"
        assert market_status(now) == (True, "early-close session (closes 13:00)")
    assert is_trading_day(date(2026, 11, 27))


def test_the_early_bell_is_exclusive():
    assert is_regular_market_hours(datetime(2026, 12, 24, 12, 59, tzinfo=NY))
    assert not is_regular_market_hours(datetime(2026, 12, 24, 13, 0, tzinfo=NY))


# --- DST boundaries -----------------------------------------------------------------
#
# The crons are in UTC; the session is in New York time. The same UTC instant moves
# an hour relative to the bell when the clocks change, so pin a UTC time on either
# side of both 2026 transitions (spring forward 2026-03-08, fall back 2026-11-01).


def test_spring_forward_moves_the_open_an_hour_earlier_in_utc():
    before = datetime(2026, 3, 6, 13, 30, tzinfo=UTC)  # Fri, EST: 08:30 ET — pre-open
    after = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)  # Mon, EDT: 09:30 ET — the open

    assert market_status(before) == (False, "before the open")
    assert is_regular_market_hours(after)


def test_fall_back_moves_the_close_an_hour_later_in_utc():
    before = datetime(2026, 10, 30, 20, 30, tzinfo=UTC)  # Fri, EDT: 16:30 ET — closed
    after = datetime(2026, 11, 2, 20, 30, tzinfo=UTC)  # Mon, EST: 15:30 ET — open
    bell = datetime(2026, 11, 2, 21, 0, tzinfo=UTC)  # Mon, EST: 16:00 ET — closed

    assert not is_regular_market_hours(before)
    assert is_regular_market_hours(after)
    assert not is_regular_market_hours(bell)


# --- the calendar itself -------------------------------------------------------------


def test_every_listed_closure_is_a_weekday():
    for iso in MARKET_HOLIDAYS | EARLY_CLOSES:
        assert date.fromisoformat(iso).weekday() < 5, f"{iso} is a weekend"


def test_no_day_is_both_a_holiday_and_an_early_close():
    assert not MARKET_HOLIDAYS & EARLY_CLOSES


def test_ten_full_day_closures_per_year():
    for year in (2026, 2027):
        count = sum(1 for iso in MARKET_HOLIDAYS if iso.startswith(f"{year}-"))
        assert count == 10, f"NYSE closes ten weekdays a year, {year} lists {count}"


def _fourth_thursday_of_november(year: int) -> date:
    first = date(year, 11, 1)
    offset = (3 - first.weekday()) % 7  # Thursday is weekday 3
    return first + timedelta(days=offset + 21)


def test_early_closes_follow_the_rule():
    """13:00 ET on the day after Thanksgiving, Christmas Eve and July 3 whenever
    those are trading days. Derive the set from the rule and compare to the literal,
    so a typo or a forgotten year fails here rather than in production."""
    expected = set()
    for year in (2026, 2027):
        candidates = (
            _fourth_thursday_of_november(year) + timedelta(days=1),
            date(year, 12, 24),
            date(year, 7, 3),
        )
        expected.update(d.isoformat() for d in candidates if is_trading_day(d))
    assert set(EARLY_CLOSES) == expected


def test_watchdog_holiday_copy_agrees_with_the_source_of_truth():
    """scripts/check_run_health.py inlines MARKET_HOLIDAYS so it runs on a bare
    checkout without importing src. The two lists must never drift."""
    assert set(watchdog.MARKET_HOLIDAYS) == set(MARKET_HOLIDAYS)
    for iso in MARKET_HOLIDAYS:
        assert watchdog.is_trading_day(date.fromisoformat(iso)) is False


def test_market_hours_module_is_stdlib_only():
    """The guard imports it before ``pip install`` on the runner."""
    import ast
    import sys
    from pathlib import Path

    source = Path(market_hours.__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
