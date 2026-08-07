"""A failed cycle must be visible from outside the process.

On 2026-08-05 the morning run died with ``decide_trades: Request timed out.`` — no
trades were considered at all — and GitHub Actions reported the job green, because
``daily_run.py`` discarded the run object and exited 0. The failure was only
discoverable by reading ``data/run_history.jsonl`` by hand. Nothing alerted, and the
site published a normal-looking day on top of it.

These tests pin the two halves of the fix: the script signals failure via its exit
code, and the workflow both preserves the audit trail and goes red when it does.
"""

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "daily-run.yml"


def load_daily_run():
    """Import scripts/daily_run.py, which isn't an importable package module."""
    spec = importlib.util.spec_from_file_location(
        "daily_run_script", REPO / "scripts" / "daily_run.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["daily_run_script"] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeRun:
    errors: list[str] = field(default_factory=list)
    failed_step: str | None = None


@pytest.fixture
def daily_run():
    return load_daily_run()


def test_clean_run_exits_zero(daily_run, monkeypatch):
    monkeypatch.setattr(
        daily_run, "run_daily_cycle_graph", lambda resume=False: FakeRun()
    )
    assert daily_run.main([]) == 0


def test_failed_run_exits_nonzero(daily_run, monkeypatch, capsys):
    """The exact 2026-08-05 failure must now exit non-zero."""
    monkeypatch.setattr(
        daily_run,
        "run_daily_cycle_graph",
        lambda resume=False: FakeRun(
            errors=["decide_trades: Request timed out."], failed_step="decide_trades"
        ),
    )

    assert daily_run.main([]) == 1

    stderr = capsys.readouterr().err
    assert "decide_trades" in stderr
    assert "Request timed out." in stderr


def test_resume_flag_is_forwarded(daily_run, monkeypatch):
    seen = {}

    def fake(resume=False):
        seen["resume"] = resume
        return FakeRun()

    monkeypatch.setattr(daily_run, "run_daily_cycle_graph", fake)

    daily_run.main(["--resume"])
    assert seen["resume"] is True

    daily_run.main([])
    assert seen["resume"] is False


# --- workflow wiring -------------------------------------------------------


@pytest.fixture
def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def step_by_id(workflow, step_id):
    for step in workflow["jobs"]["run"]["steps"]:
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"no step with id={step_id!r}")


def test_run_step_does_not_abort_the_audit_trail(workflow):
    """A failed cycle must still journal and publish, or we lose the evidence."""
    assert step_by_id(workflow, "portfolio-run")["continue-on-error"] is True


def test_a_failed_cycle_turns_the_job_red(workflow):
    """continue-on-error alone would keep the silent-success bug; this is the gate."""
    steps = workflow["jobs"]["run"]["steps"]
    gates = [
        s for s in steps if "steps.portfolio-run.outcome" in str(s.get("if", ""))
    ]
    assert gates, "no step fails the job when the portfolio run fails"

    gate = gates[0]
    assert "failure" in gate["if"]
    assert "exit 1" in gate["run"]

    # The gate must come after the publish steps, otherwise it short-circuits them
    # and we trade a silent failure for a lost audit trail.
    assert steps.index(gate) > steps.index(step_by_id(workflow, "deployment"))


def test_daily_run_does_not_share_a_concurrency_group_with_pages(workflow):
    """The 2026-08-06 total-loss day: a shared group cancelled the queued morning run.

    A group holds one in-progress plus one pending run; a third arrival evicts the
    pending one. Both cron slots sat in the shared ``pages`` group, so a late morning
    run was cancelled by the afternoon one and the whole trading day was lost.
    """
    group = workflow["concurrency"]["group"]

    assert group != "pages"
    # Keyed per cron slot, so the two daily runs can never evict each other.
    assert "github.event.schedule" in group
    # Still serialized against a second run of the SAME slot.
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_push_tolerates_a_concurrent_run(workflow):
    """Independent groups let the slots overlap, so the push must handle a race."""
    push = next(
        s
        for s in workflow["jobs"]["run"]["steps"]
        if s.get("name") == "Push changes"
    )
    assert "--rebase" in push["run"]
