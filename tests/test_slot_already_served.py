"""Backup fires stand down once a slot has run.

Each slot's cron fires every two hours from ~10h before the slot, so several fires a
day reach the slot. The first runs the cycle; this check is how the rest learn that
and exit green with no cycle, instead of making a second decision for the same slot.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.slot_already_served import claim_path, claimed_by, main, market_date, served_by

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


def test_the_market_date_comes_from_the_slot_not_the_fire(tmp_path):
    """The 04:40Z fire on 11-20 is 23:40 EST on 11-19. Judged by its own clock it
    would read 11-19's rows, find the morning slot served, and stand down for a slot
    nobody has served today. The slot instant (14:40Z on 11-20) is the right day."""
    fire = _at(4, 40)
    assert market_date(fire).isoformat() == "2026-11-19"  # the trap
    assert market_date(fire, "2026-11-20T14:40:00Z").isoformat() == "2026-11-20"

    out = tmp_path / "out"
    env = {"RUN_SLOT": "morning", "RUN_SLOT_AT": "2026-11-20T14:40:00Z", "GITHUB_OUTPUT": str(out)}
    runs = [_run("2026-11-19T14:41:00Z", slot="morning")]  # yesterday's morning run

    rc = main(now=fire, runs=runs, claims_dir=tmp_path / "claims", env=env)

    assert rc == 0
    assert out.read_text() == "already_served=false\n"


def test_a_fire_delayed_past_midnight_still_names_yesterdays_slot():
    # The 15:50Z Friday tick fired at 03:50Z Saturday: slot_at is Friday 17:50Z.
    assert market_date(
        datetime(2026, 11, 21, 3, 50, tzinfo=UTC), "2026-11-20T17:50:00Z"
    ).isoformat() == "2026-11-20"


def test_a_failed_row_still_counts_as_served():
    """A failed run may have executed trades before dying; re-deciding the same slot
    could double-trade. The other slot is the recovery path, as before."""
    runs = [_run("2026-11-20T14:41:00Z", slot="morning", status="failed")]
    assert served_by(runs, "morning", market_date(_at(15, 0))) is not None


# --- a claim stands in for a row whose push never landed -----------------------


def _claim(tmp_path, slot, day="2026-11-20", run_id="9001"):
    import json

    root = tmp_path / "claims"
    root.mkdir(exist_ok=True)
    path = claim_path(slot, datetime.fromisoformat(day).date(), root)
    path.write_text(json.dumps({"date": day, "slot": slot, "github_run_id": run_id,
                                "claimed_at": f"{day}T14:40:30Z"}))
    return root


def test_a_claimed_slot_with_no_row_is_still_served(tmp_path, capsys):
    """THE failed-push scenario: the serving run claimed the slot, ran the cycle,
    traded and tweeted, and then could not push its run_history row. The next fire
    must not run the cycle again."""
    root = _claim(tmp_path, "morning")
    out = tmp_path / "out"
    env = {"RUN_SLOT": "morning", "RUN_SLOT_AT": "2026-11-20T14:40:00Z", "GITHUB_OUTPUT": str(out)}

    rc = main(now=_at(16, 40), runs=[], claims_dir=root, env=env)

    assert rc == 0
    assert out.read_text() == "already_served=true\n"
    printed = capsys.readouterr().out
    assert "::notice::" in printed and "claimed by workflow run 9001" in printed
    assert "final push did not land" in printed


def test_a_claim_for_the_other_slot_or_another_day_does_not_count(tmp_path):
    root = _claim(tmp_path, "morning")
    _claim(tmp_path, "afternoon", day="2026-11-19")

    assert claimed_by("afternoon", datetime(2026, 11, 20).date(), root) is None
    assert claimed_by("morning", datetime(2026, 11, 21).date(), root) is None
    assert claimed_by("morning", datetime(2026, 11, 20).date(), root)["github_run_id"] == "9001"


def test_a_corrupt_claim_file_still_counts(tmp_path):
    """Half a claim is still a claim: the run that wrote it got as far as the cycle."""
    root = tmp_path / "claims"
    root.mkdir()
    claim_path("morning", datetime(2026, 11, 20).date(), root).write_text("{not json")

    assert claimed_by("morning", datetime(2026, 11, 20).date(), root) is not None


# --- the script end to end --------------------------------------------------


def test_main_writes_already_served_true_and_a_notice(tmp_path, capsys):
    out = tmp_path / "out"
    runs = [_run("2026-11-20T14:41:00Z", slot="morning")]
    env = {"RUN_SLOT": "morning", "GITHUB_OUTPUT": str(out)}

    rc = main(now=_at(16, 40), runs=runs, claims_dir=tmp_path / "claims", env=env)

    assert rc == 0
    assert out.read_text() == "already_served=true\n"
    assert "::notice::" in capsys.readouterr().out


def test_main_writes_false_when_the_slot_is_open(tmp_path):
    out = tmp_path / "out"
    env = {"RUN_SLOT": "afternoon", "GITHUB_OUTPUT": str(out)}

    rc = main(now=_at(17, 50), runs=[_run("2026-11-20T14:41:00Z", slot="morning")],
              claims_dir=tmp_path / "claims", env=env)

    assert rc == 0
    assert out.read_text() == "already_served=false\n"


def test_manual_dispatch_has_no_slot_and_always_proceeds(tmp_path):
    out = tmp_path / "out"
    runs = [_run("2026-11-20T14:41:00Z", slot="morning")]

    for env in ({"GITHUB_OUTPUT": str(out)}, {"RUN_SLOT": "manual", "GITHUB_OUTPUT": str(out)}):
        out.write_text("")
        rc = main(now=_at(16, 0), runs=runs, claims_dir=tmp_path / "claims", env=env)
        assert rc == 0
        assert out.read_text() == "already_served=false\n"


def test_a_manual_run_never_consumes_a_scheduled_slot(tmp_path):
    """A workflow_dispatch at 19:00Z used to look like the afternoon run by its start
    hour, so the real 17:50 fire would have stood down. Its row says "manual" now."""
    out = tmp_path / "out"
    runs = [_run("2026-11-20T19:00:00Z", slot="manual")]
    env = {"RUN_SLOT": "afternoon", "RUN_SLOT_AT": "2026-11-20T17:50:00Z", "GITHUB_OUTPUT": str(out)}

    rc = main(now=_at(19, 30), runs=runs, claims_dir=tmp_path / "claims", env=env)

    assert rc == 0
    assert out.read_text() == "already_served=false\n"


def test_an_unknown_slot_is_a_configuration_error(tmp_path):
    rc = main(now=_at(16, 0), runs=[], env={"RUN_SLOT": "evening"})
    assert rc == 1
