"""The slot claim: pushed to origin before the cycle so a backup fire can never
re-run a slot whose run_history row failed to push after trades and tweet were out."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.claim_slot import KEEP_DAYS, claim_row, main, prune, write_claim
from scripts.slot_already_served import claim_path, claimed_by

UTC = ZoneInfo("UTC")

ENV = {
    "RUN_SLOT": "morning",
    "RUN_SLOT_TIME": "14:40",
    "RUN_SLOT_AT": "2026-11-20T14:40:00Z",
    "GITHUB_RUN_ID": "9001",
    "GITHUB_RUN_ATTEMPT": "1",
}


def test_the_claim_names_the_slots_market_date_run_and_time():
    row = claim_row(datetime(2026, 11, 20, 14, 40, 30, tzinfo=UTC), ENV)

    assert row == {
        "date": "2026-11-20",
        "slot": "morning",
        "slot_time": "14:40",
        "slot_at": "2026-11-20T14:40:00Z",
        "claimed_at": "2026-11-20T14:40:30Z",
        "github_run_id": "9001",
        "github_run_attempt": "1",
    }


def test_a_manual_dispatch_claims_nothing():
    assert claim_row(datetime(2026, 11, 20, 19, 0, tzinfo=UTC), {}) is None
    assert claim_row(datetime(2026, 11, 20, 19, 0, tzinfo=UTC), {"RUN_SLOT": "manual"}) is None


def test_the_claim_is_what_the_served_check_reads(tmp_path):
    """Writer and reader must agree on the path, or the claim protects nothing."""
    root = tmp_path / "claims"
    row = claim_row(datetime(2026, 11, 20, 14, 40, 30, tzinfo=UTC), ENV)

    path = write_claim(row, root)

    assert path == claim_path("morning", datetime(2026, 11, 20).date(), root)
    assert claimed_by("morning", datetime(2026, 11, 20).date(), root)["github_run_id"] == "9001"
    assert json.loads(path.read_text())["slot"] == "morning"


def test_old_claims_are_pruned_so_the_directory_stays_small(tmp_path):
    root = tmp_path / "claims"
    root.mkdir()
    old = root / f"2026-09-01-morning.json"
    recent = root / "2026-11-19-afternoon.json"
    stray = root / "README.json"
    for f in (old, recent, stray):
        f.write_text("{}")

    removed = prune(root, datetime(2026, 11, 20).date(), keep_days=KEEP_DAYS)

    assert removed == [old]
    assert recent.exists() and stray.exists()


def test_main_writes_the_claim_and_reports_it(tmp_path, capsys):
    root = tmp_path / "claims"

    rc = main(now=datetime(2026, 11, 20, 14, 40, 30, tzinfo=UTC), env=ENV, claims_dir=root)

    assert rc == 0
    assert claimed_by("morning", datetime(2026, 11, 20).date(), root) is not None
    assert "Claimed the morning slot for 2026-11-20 (workflow run 9001)" in capsys.readouterr().out


def test_main_refuses_to_claim_a_slot_already_claimed(tmp_path, capsys):
    """slot_already_served.py should have ended the job first; if a claim is somehow
    already there, failing is the safe side - never run the cycle twice."""
    root = tmp_path / "claims"
    main(now=datetime(2026, 11, 20, 14, 40, 30, tzinfo=UTC), env=ENV, claims_dir=root)

    rc = main(now=datetime(2026, 11, 20, 16, 40, 0, tzinfo=UTC), env=ENV | {"GITHUB_RUN_ID": "9002"}, claims_dir=root)

    assert rc == 1
    assert "already claimed by workflow run 9001" in capsys.readouterr().err
    assert claimed_by("morning", datetime(2026, 11, 20).date(), root)["github_run_id"] == "9001"


def test_main_on_manual_dispatch_writes_nothing(tmp_path, capsys):
    root = tmp_path / "claims"

    rc = main(now=datetime(2026, 11, 20, 19, 0, tzinfo=UTC), env={"RUN_SLOT": "manual"}, claims_dir=root)

    assert rc == 0
    assert not root.exists()
    assert "nothing to claim" in capsys.readouterr().out


def test_an_unknown_slot_is_a_configuration_error(tmp_path):
    rc = main(now=datetime(2026, 11, 20, 19, 0, tzinfo=UTC), env={"RUN_SLOT": "evening"}, claims_dir=tmp_path)
    assert rc == 1
