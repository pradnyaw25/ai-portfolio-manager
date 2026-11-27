from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from scripts.market_hours_guard import is_regular_market_hours, main
from src.utils import market_hours


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


# --- the guard says why it skipped (the calendar itself is tested in test_market_hours.py)


def _freeze(monkeypatch, now: datetime) -> None:
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(market_hours, "datetime", _Clock)


def test_guard_names_the_holiday_it_skipped(monkeypatch, tmp_path, capsys):
    """The Thanksgiving 2026 run: 19:34 UTC passed the old guard and traded."""
    _freeze(monkeypatch, datetime(2026, 11, 26, 19, 34, tzinfo=UTC))
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    main()

    assert "should_run=false (market closed: market holiday (2026-11-26))" in capsys.readouterr().out
    assert out.read_text() == "should_run=false\nreason=market closed: market holiday (2026-11-26)\n"


def test_guard_names_the_early_close_it_skipped(monkeypatch, capsys):
    """18:30 UTC on 2026-11-27 is 13:30 ET, past the 13:00 early bell."""
    _freeze(monkeypatch, datetime(2026, 11, 27, 18, 30, tzinfo=UTC))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    main()

    assert "should_run=false (market closed: after the 13:00 early close (2026-11-27))" in capsys.readouterr().out
