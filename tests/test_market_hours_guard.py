from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.market_hours_guard import is_regular_market_hours


NY = ZoneInfo("America/New_York")


def test_market_hours_guard_allows_weekday_market_hours():
    now = datetime(2026, 6, 15, 10, 0, tzinfo=NY)

    assert is_regular_market_hours(now)


def test_market_hours_guard_rejects_before_open():
    now = datetime(2026, 6, 15, 9, 0, tzinfo=NY)

    assert not is_regular_market_hours(now)


def test_market_hours_guard_rejects_after_close():
    now = datetime(2026, 6, 15, 16, 0, tzinfo=NY)

    assert not is_regular_market_hours(now)


def test_market_hours_guard_rejects_weekends():
    now = datetime(2026, 6, 13, 12, 0, tzinfo=NY)

    assert not is_regular_market_hours(now)
