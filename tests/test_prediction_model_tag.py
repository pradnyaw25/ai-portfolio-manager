"""Predictions must record which model made them.

Without the tag, a model migration silently merges two populations into one
calibration curve and the before/after comparison is unrecoverable. Predictions
accrue forward only — there is no way to re-derive the tag later for calls that
were never labelled, so it has to be written at creation time.
"""

import json

import pytest

from scripts.backfill_prediction_models import backfill, served_models
from src.storage.prediction_store import PredictionStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "predictions.jsonl"
    monkeypatch.setattr("src.storage.prediction_store.PREDICTIONS_FILE", path)
    return PredictionStore(), path


def _call(store, **over):
    kwargs = dict(
        run_id="run_1", symbol="AAPL", direction="OUTPERFORM", confidence=0.7,
        thesis="momentum", start_price=100.0, spy_price=500.0, horizon=5,
    )
    kwargs.update(over)
    return store.create_call(**kwargs)


def test_a_new_prediction_records_the_model(store):
    s, _ = store
    created = _call(s, model="gpt-5.6-terra")
    assert created["model"] == "gpt-5.6-terra"


def test_the_model_survives_the_round_trip_to_disk(store):
    s, path = store
    _call(s, model="gpt-5.6-terra")
    row = json.loads(path.read_text().splitlines()[0])
    assert row["model"] == "gpt-5.6-terra"


def test_an_untagged_prediction_is_null_not_missing(store):
    """Explicit null so a reader can tell "unknown model" from "field not supported
    yet" — they mean different things when comparing curves across a migration."""
    s, _ = store
    created = _call(s)
    assert created["model"] is None


# --- backfill ---------------------------------------------------------------


def test_backfill_uses_the_model_that_actually_served_the_run(tmp_path):
    """Recovered from the call log, not inferred from a config date range: the log
    records the served model, so it survives fallbacks and mid-period changes."""
    log = tmp_path / "llm_calls.jsonl"
    log.write_text(
        json.dumps({"run_id": "r1", "model": "gpt-4.1-mini", "prompt_version": "portfolio_manager/v1"}) + "\n"
        + json.dumps({"run_id": "r2", "model": "gpt-4o-mini", "prompt_version": "portfolio_manager/v1"}) + "\n"
        # a cheap-tier call for the same run must not be mistaken for the decision
        + json.dumps({"run_id": "r1", "model": "gpt-4o-mini", "prompt_version": "bull_analyst/v2"}) + "\n"
    )
    rows, stats = backfill(
        [{"run_id": "r1"}, {"run_id": "r2"}], served_models(log)
    )

    assert rows[0]["model"] == "gpt-4.1-mini"   # not the analyst's model
    assert rows[1]["model"] == "gpt-4o-mini"


def test_backfill_leaves_unresolvable_rows_null_rather_than_guessing(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    log.write_text(json.dumps({"run_id": "r1", "model": "gpt-4.1-mini", "prompt_version": "portfolio_manager/v1"}) + "\n")

    rows, stats = backfill([{"run_id": "unknown"}], served_models(log))

    assert rows[0]["model"] is None
    assert stats["left null (no logged call)"] == 1


def test_backfill_is_idempotent(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    log.write_text(json.dumps({"run_id": "r1", "model": "gpt-4.1-mini", "prompt_version": "portfolio_manager/v1"}) + "\n")
    served = served_models(log)

    rows, _ = backfill([{"run_id": "r1"}], served)
    rows, stats = backfill(rows, served)

    assert rows[0]["model"] == "gpt-4.1-mini"
    assert stats["already tagged"] == 1


def test_backfill_never_overwrites_an_existing_tag(tmp_path):
    """A re-run after a migration must not relabel older rows."""
    log = tmp_path / "llm_calls.jsonl"
    log.write_text(json.dumps({"run_id": "r1", "model": "gpt-5.6-terra", "prompt_version": "portfolio_manager/v1"}) + "\n")

    rows, _ = backfill([{"run_id": "r1", "model": "gpt-4.1-mini"}], served_models(log))

    assert rows[0]["model"] == "gpt-4.1-mini"
