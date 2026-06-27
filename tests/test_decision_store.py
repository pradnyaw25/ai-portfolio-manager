import json
from datetime import date

from src.models.portfolio import PortfolioSnapshot
from src.storage import decision_store
from src.storage.decision_store import DecisionStore


def test_decision_store_records_memory_status_and_error(tmp_path, monkeypatch):
    decisions_file = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(decision_store, "DECISIONS_FILE", decisions_file)

    DecisionStore().save(
        portfolio=PortfolioSnapshot(date=date.today(), cash=100000, positions=[]),
        raw_decision={"summary": "hold"},
        approved=[],
        rejected=[],
        executed=[],
        memory_used=[],
        memory_status="unavailable",
        memory_error="qdrant offline",
    )

    row = json.loads(decisions_file.read_text().strip())

    assert row["memory_status"] == "unavailable"
    assert row["memory_error"] == "qdrant offline"
    assert row["memory_used"] == []
