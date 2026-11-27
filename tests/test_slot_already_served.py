"""Backup fires stand down once a slot has run.

Each slot's cron fires every two hours from ~10h before the slot, so several fires a
day reach the slot. The first runs the cycle; this check is how the rest learn that
and exit green with no cycle, instead of making a second decision for the same slot.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.slot_already_served import main, market_date, served_by

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _run(started_at, slot=None, status="success", run_id="r1"):
    row = {"run_id": run_id, "started_at": started_at, "completed_at": started_at,
           "status": status, "errors": []}
    if slot:
        row["slot"] = slot
    return row


def _at(h, m):
    return datetime(2026, 11, 20, h, m, tzinfo=UTC)


def test_an_explicit_slot_row_for_today_means_served():
    runs = [_run("2026-11-20T19:02:00Z", slot="morning")]  # a late morning run
    served = served_by(runs, "morning", market_date(_at(19, 30)))
    assert served is not None and served["run_id"] == "r1"


def test_the_other_slot_is_not_served_by_it():
    runs = [_run("2026-11-20T19:02:00Z", slot="morning")]
    assert served_by(runs, "afternoon", market_date(_at(19, 30))) is None


def test_old_rows_without_a_slot_field_fall_back_to_the_start_hour():
    runs = [_run("2026-11-20T15:02:00Z")]  # pre-field row, before the 17Z cutoff
    assert served_by(runs, "morning", market_date(_at(16, 0))) is not None
    assert served_by(runs, "afternoon", market_date(_at(16, 0))) is None


def test_yesterdays_run_does_not_serve_today():
    runs = [_run("2026-11-19T14:41:00Z", slot="morning")]
    assert served_by(runs, "morning", market_date(_at(14, 40))) is None


def test_the_market_date_is_judged_in_new_york():
    # 23:30Z on 11-20 is still 11-20 in New York (18:30 EST).
    assert market_date(datetime(2026, 11, 20, 23, 30, tzinfo=UTC)).isoformat() == "2026-11-20"
    # 03:00Z on 11-21 is 22:00 EST on 11-20: the same trading day as the row above.
    assert market_date(datetime(2026, 11, 21, 3, 0, tzinfo=UTC)).isoformat() == "2026-11-20"


def test_a_failed_row_still_counts_as_served():
    """A failed run may have executed trades before dying; re-deciding the same slot
    could double-trade. The other slot is the recovery path, as before."""
    runs = [_run("2026-11-20T14:41:00Z", slot="morning", status="failed")]
    assert served_by(runs, "morning", market_date(_at(15, 0))) is not None


# --- the script end to end --------------------------------------------------


def test_main_writes_already_served_true_and_a_notice(tmp_path, capsys):
    out = tmp_path / "out"
    runs = [_run("2026-11-20T14:41:00Z", slot="morning")]
    env = {"RUN_SLOT": "morning", "GITHUB_OUTPUT": str(out)}

    rc = main(now=_at(16, 40), runs=runs, env=env)

    assert rc == 0
    assert out.read_text() == "already_served=true\n"
    assert "::notice::" in capsys.readouterr().out


def test_main_writes_false_when_the_slot_is_open(tmp_path):
    out = tmp_path / "out"
    env = {"RUN_SLOT": "afternoon", "GITHUB_OUTPUT": str(out)}

    rc = main(now=_at(17, 50), runs=[_run("2026-11-20T14:41:00Z", slot="morning")], env=env)

    assert rc == 0
    assert out.read_text() == "already_served=false\n"


def test_manual_dispatch_has_no_slot_and_always_proceeds(tmp_path):
    out = tmp_path / "out"
    env = {"GITHUB_OUTPUT": str(out)}

    rc = main(now=_at(16, 0), runs=[_run("2026-11-20T14:41:00Z", slot="morning")], env=env)

    assert rc == 0
    assert out.read_text() == "already_served=false\n"


def test_an_unknown_slot_is_a_configuration_error(tmp_path):
    rc = main(now=_at(16, 0), runs=[], env={"RUN_SLOT": "evening"})
    assert rc == 1
