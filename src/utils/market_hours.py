"""Is the NYSE open right now? Shared by the CI guard and the run's execution gate
so trades never fill on a closed market or outside the session.

The check knows three things: the regular session (weekdays 9:30–16:00
America/New_York), the exchange's full-day closures, and its 13:00 early closes.
It did not always. Until 2026-11-27 it only knew the weekday session, on the theory
that "a holiday just means a no-op run" — and on Thanksgiving 2026 a late-firing
scheduled run passed the guard at 14:34 ET and sold ORCL on the previous day's
close, because yfinance happily serves the last print on a day with no prints.
``docs/incidents.md`` has the entry.

Stdlib only, on purpose: the CI guard imports this module *before* ``pip install``
runs, on a bare checkout. ``scripts/check_run_health.py`` carries its own copy of
``MARKET_HOLIDAYS`` for the same reason and a test asserts the two agree
(``tests/test_market_hours_guard.py``). Extend both before each January.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

# NYSE full-day closures. Weekends are handled separately, so only weekdays appear.
# Source of truth for the repo; scripts/check_run_health.py mirrors it.
MARKET_HOLIDAYS: frozenset[str] = frozenset({
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King Jr. Day
    "2026-02-16",  # Washington's Birthday
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed; July 4 is a Saturday)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving Day
    "2026-12-25",  # Christmas Day
    # 2027
    "2027-01-01",  # New Year's Day
    "2027-01-18",  # Martin Luther King Jr. Day
    "2027-02-15",  # Washington's Birthday
    "2027-03-26",  # Good Friday
    "2027-05-31",  # Memorial Day
    "2027-06-18",  # Juneteenth (observed; June 19 is a Saturday)
    "2027-07-05",  # Independence Day (observed; July 4 is a Sunday)
    "2027-09-06",  # Labor Day
    "2027-11-25",  # Thanksgiving Day
    "2027-12-24",  # Christmas Day (observed; December 25 is a Saturday)
})

# NYSE 13:00 ET early closes: the day after Thanksgiving, Christmas Eve and July 3,
# on the years when those fall on a trading day. In 2026 July 3 is itself a holiday;
# in 2027 July 3 is a Saturday and December 24 is the observed Christmas holiday, so
# neither year has more than the ones listed. A test derives this set from the rule.
EARLY_CLOSES: frozenset[str] = frozenset({
    "2026-11-27",  # day after Thanksgiving
    "2026-12-24",  # Christmas Eve
    "2027-11-26",  # day after Thanksgiving
})


def is_market_holiday(day: date) -> bool:
    return day.isoformat() in MARKET_HOLIDAYS


def is_early_close(day: date) -> bool:
    return day.isoformat() in EARLY_CLOSES


def is_trading_day(day: date) -> bool:
    """A weekday that is not a full-day closure (early-close days count)."""
    return day.weekday() < 5 and not is_market_holiday(day)


def market_close(day: date) -> time:
    """The session's closing bell on ``day`` — 13:00 on an early close, else 16:00."""
    return EARLY_CLOSE if is_early_close(day) else MARKET_CLOSE


def market_status(now: datetime | None = None) -> tuple[bool, str]:
    """``(is_open, reason)`` for ``now`` (default: the current time).

    ``reason`` names what decided it, so the guard and the gate can print *why* a run
    was skipped rather than a bare "outside market hours": ``weekend``,
    ``market holiday (2026-11-26)``, ``before the open``, ``after the 13:00 early
    close (2026-11-27)``, ``after the close``, ``regular market hours`` or
    ``early-close session (closes 13:00)``.
    """
    current = (now or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ)
    day = current.date()
    if current.weekday() >= 5:
        return False, "weekend"
    if is_market_holiday(day):
        return False, f"market holiday ({day.isoformat()})"
    if current.time() < MARKET_OPEN:
        return False, "before the open"
    close = market_close(day)
    if current.time() >= close:
        if is_early_close(day):
            return False, f"after the {close:%H:%M} early close ({day.isoformat()})"
        return False, "after the close"
    if is_early_close(day):
        return True, f"early-close session (closes {close:%H:%M})"
    return True, "regular market hours"


def is_regular_market_hours(now: datetime | None = None) -> bool:
    """True when the NYSE is in session at ``now``: a trading day (weekday, not a
    full-day closure) between 9:30 and that day's close, 13:00 on an early-close
    day and 16:00 otherwise. ``market_status()`` says why when it is False.
    """
    return market_status(now)[0]
