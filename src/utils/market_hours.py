"""Regular US market-hours check, shared by the CI guard and the run's
execution gate so trades never fill outside 9:30–16:00 America/New_York."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def is_regular_market_hours(now: datetime | None = None) -> bool:
    """True on a weekday between 9:30 and 16:00 America/New_York.

    Does not account for market holidays — a conservative approximation that is
    fine for a paper-trading fund (a holiday just means a no-op run).
    """
    current = (now or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ)
    if current.weekday() >= 5:
        return False
    return MARKET_OPEN <= current.time() < MARKET_CLOSE
