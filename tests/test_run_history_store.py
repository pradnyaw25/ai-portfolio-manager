import json

from src.reporting import public_exporter
from src.storage import run_history_store
from src.storage.run_history_store import RunHistoryStore


def _store(tmp_path):
    return RunHistoryStore(path=tmp_path / "run_history.jsonl")


def test_records_and_loads_multiple_runs(tmp_path):
    store = _store(tmp_path)
    store.record({"run_id": "run_1", "status": "success"})
    store.record({"run_id": "run_2", "status": "failed"})

    rows = store.load()
    assert [r["run_id"] for r in rows] == ["run_1", "run_2"]


def test_record_upserts_by_run_id(tmp_path):
    store = _store(tmp_path)
    store.record({"run_id": "run_1", "status": "success", "trades_executed": 1})
    store.record({"run_id": "run_1", "status": "success", "trades_executed": 5})

    rows = store.load()
    assert len(rows) == 1
    assert rows[0]["trades_executed"] == 5


def test_empty_status_is_ignored(tmp_path):
    store = _store(tmp_path)
    store.record({})
    assert store.load() == []


def test_load_missing_file_returns_empty(tmp_path):
    assert _store(tmp_path).load() == []


def test_survives_across_store_instances(tmp_path):
    path = tmp_path / "run_history.jsonl"
    RunHistoryStore(path=path).record({"run_id": "run_1", "status": "success"})
    # A fresh instance (like a later process) still sees prior runs.
    assert [r["run_id"] for r in RunHistoryStore(path=path).load()] == ["run_1"]


def test_exporter_writes_public_run_history(tmp_path, monkeypatch):
    monkeypatch.setattr(run_history_store, "RUN_HISTORY_LOG", tmp_path / "run_history.jsonl")
    monkeypatch.setattr(public_exporter, "PUBLIC_DIR", tmp_path / "public")

    RunHistoryStore().record(
        {"run_id": "run_1", "status": "success", "trades_executed": 2,
         "warnings": ["w"], "portfolio_value": 1000000,
         "llm": {"cost_usd": 0.0021, "calls": 4, "latency_ms": 5310.0}}
    )
    public_exporter.PublicExporter().write_run_history()

    payload = json.loads((tmp_path / "public" / "run_history.json").read_text())
    assert payload["count"] == 1
    run = payload["runs"][0]
    assert run["run_id"] == "run_1"
    assert run["llm_cost_usd"] == 0.0021
    assert run["llm_calls"] == 4
    assert run["warnings"] == 1  # count, not the list
