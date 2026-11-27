from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.market_hours_guard import is_regular_market_hours, main, skip_warning


NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

SCHEDULED = {
    "GITHUB_EVENT_NAME": "schedule",
    "RUN_SLOT": "afternoon",
    "RUN_SLOT_TIME": "17:50",
    "RUN_CRON": "50 7,9,11,13,15 * * 1-5",
    "RUN_FIRED_AT": "2026-11-23T21:29:00Z",
    "RUN_SCHEDULER_DELAY_MIN": "339",
    "RUN_LAST_FIRE": "true",
}


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


# --- a skipped scheduled run must not look like a run --------------------------


def test_a_skipped_scheduled_run_prints_a_warning_with_slot_fire_time_and_delay(tmp_path, capsys):
    """Every skipped run exits 0. In September and November 2026 that is how weeks of
    lost slots hid in a green Actions list. The ::warning:: is the tell."""
    out = tmp_path / "out"

    main(now=datetime(2026, 11, 23, 21, 30, tzinfo=UTC), env=SCHEDULED | {"GITHUB_OUTPUT": str(out)})

    printed = capsys.readouterr().out
    assert "::warning::Skipped the afternoon slot (17:50Z)" in printed
    assert "fired at 21:29Z, 5h39m after cron '50 7,9,11,13,15 * * 1-5'" in printed
    assert "21:30Z (16:30 EST)" in printed
    assert "last fire of the day: the slot is lost" in printed
    assert "should_run=false\n" in out.read_text()


def test_an_early_backup_fire_skipped_before_the_open_is_a_notice_not_a_warning(tmp_path, capsys):
    """Each slot's cron fires five times a day and the early fires land pre-open by
    design. A ::warning:: on each would be six a day and mean nothing; they get a
    ::notice::, and the warning is kept for the fire that was the slot's last chance."""
    out = tmp_path / "out"
    backup = SCHEDULED | {
        "RUN_SLOT": "morning", "RUN_SLOT_TIME": "14:40", "RUN_CRON": "40 4,6,8,10,12 * * 1-5",
        "RUN_FIRED_AT": "2026-11-23T04:41:00Z", "RUN_SCHEDULER_DELAY_MIN": "1",
        "RUN_LAST_FIRE": "false", "GITHUB_OUTPUT": str(out),
    }

    main(now=datetime(2026, 11, 23, 4, 41, tzinfo=UTC), env=backup)

    printed = capsys.readouterr().out
    assert "::warning::" not in printed
    assert "::notice::Skipped the morning slot (14:40Z): fired at 04:41Z" in printed
    assert "a later fire of this cron still serves the slot" in printed
    assert "should_run=false\n" in out.read_text()


def test_an_in_hours_scheduled_run_prints_no_warning(tmp_path, capsys):
    out = tmp_path / "out"

    main(now=datetime(2026, 11, 23, 17, 50, tzinfo=UTC), env=SCHEDULED | {"GITHUB_OUTPUT": str(out)})

    assert "::warning::" not in capsys.readouterr().out
    assert "should_run=true\n" in out.read_text()


def test_a_manual_dispatch_outside_hours_runs_without_a_warning(capsys):
    main(now=datetime(2026, 11, 23, 23, 0, tzinfo=UTC), env={"GITHUB_EVENT_NAME": "workflow_dispatch"})

    printed = capsys.readouterr().out
    assert "::warning::" not in printed
    assert "should_run=true (manual dispatch)" in printed


def test_the_warning_degrades_gracefully_without_scheduling_context():
    """A run whose wait step produced no outputs still gets a usable line."""
    line = skip_warning(datetime(2026, 11, 23, 21, 30, tzinfo=UTC), {})

    assert line.startswith("::warning::Skipped the unknown slot: fire time unknown;")
