from src.memory.extractors import (
    extract_decision_memories,
    extract_report_memories,
    extract_trade_memory,
)
from src.memory.ingestion_service import MemoryIngestionService
from src.memory import memory_store
from src.memory.schemas import MemoryIngestionResult, MemoryRecord
from src.models.run_state import PortfolioRunState
from src.workflows import daily_graph


class FakeDecisionStore:
    def __init__(self, rows):
        self.rows = rows

    def load_all(self):
        return self.rows


class FakeTradeStore:
    def __init__(self, rows):
        self.rows = rows

    def load_all(self):
        return self.rows


class FakeMemoryStore:
    def __init__(self):
        self.records = []

    def upsert_records(self, records):
        self.records.extend(records)
        return len(records)


def test_memory_record_metadata_excludes_content_and_keeps_type_alias():
    record = MemoryRecord(
        id="thesis:run_1",
        memory_type="thesis",
        content="Hold more cash until volatility settles.",
        date="2026-06-28",
        run_id="run_1",
    )

    metadata = record.to_document_metadata()

    assert "content" not in metadata
    assert metadata["id"] == "thesis:run_1"
    assert metadata["memory_type"] == "thesis"
    assert metadata["type"] == "thesis"


def test_fund_memory_store_uses_uuid_point_ids_and_keeps_semantic_metadata():
    class FakeVectorStore:
        def __init__(self):
            self.documents = []
            self.ids = []

        def add_documents(self, *, documents, ids):
            self.documents = documents
            self.ids = ids

    fake_store = FakeVectorStore()
    store = memory_store.FundMemoryStore.__new__(memory_store.FundMemoryStore)
    store.store = fake_store
    record = MemoryRecord(
        id="10k:AAPL:000032019325000079:item_1a",
        memory_type="risk_lesson",
        content="Risk factors mention supply concentration.",
        date="2026-06-30",
        symbols=["AAPL"],
    )

    created = store.upsert_records([record])

    assert created == 1
    assert fake_store.ids == [memory_store.memory_point_id(record.id)]
    assert fake_store.ids[0] != record.id
    assert fake_store.documents[0].metadata["id"] == record.id


def test_extract_report_memories_creates_typed_report_thesis_and_risk_records():
    report = """# Portfolio Report

## Summary
- Total Value: $1

## Analysis
AI infrastructure remains the strongest thesis.

## Risk Assessment
Semiconductor concentration is elevated.
"""

    records = extract_report_memories(
        report_markdown=report,
        run_id="run_1",
        report_date="2026-06-28",
    )

    assert [record.memory_type for record in records] == [
        "report_summary",
        "thesis",
        "risk_lesson",
    ]
    assert records[1].id == "thesis:run_1:report_analysis"
    assert records[2].content == "Semiconductor concentration is elevated."


def test_extract_decision_memories_captures_summary_cash_and_rejections():
    records = extract_decision_memories(
        {
            "run_id": "run_1",
            "date": "2026-06-28",
            "raw_decision": {"summary": "Stay selective.", "outlook": "neutral"},
            "cash_thesis": "Keep cash high.",
            "rejected_trades": [
                {
                    "symbol": "NVDA",
                    "action": "BUY",
                    "reason": "sector exposure too high",
                }
            ],
        }
    )

    assert [record.memory_type for record in records] == [
        "thesis",
        "risk_lesson",
        "risk_lesson",
    ]
    assert records[2].symbols == ["NVDA"]
    assert "sector exposure too high" in records[2].content


def test_extract_trade_memory_creates_symbol_trade_record():
    record = extract_trade_memory(
        {
            "run_id": "run_1",
            "date": "2026-06-28",
            "symbol": "msft",
            "action": "buy",
            "shares": "3",
            "price": "400.00",
            "total": "1200.00",
            "reasoning": "Cloud momentum.",
        }
    )

    assert record is not None
    assert record.id == "trade:run_1:MSFT:BUY"
    assert record.symbols == ["MSFT"]
    assert record.metadata["action"] == "BUY"


def test_memory_ingestion_service_collects_dedupes_and_upserts_records():
    fake_store = FakeMemoryStore()
    service = MemoryIngestionService(
        store_factory=lambda: fake_store,
        decision_store=FakeDecisionStore(
            [
                {
                    "run_id": "run_1",
                    "date": "2026-06-28",
                    "raw_decision": {"summary": "Stay selective."},
                    "rejected_trades": [],
                }
            ]
        ),
        trade_store=FakeTradeStore(
            [
                {
                    "run_id": "run_1",
                    "date": "2026-06-28",
                    "symbol": "AAPL",
                    "action": "BUY",
                }
            ]
        ),
    )

    result = service.ingest_run(
        run_id="run_1",
        report_markdown="## Analysis\nStay selective.",
        report_date="2026-06-28",
    )

    assert result.status == "ok"
    assert result.created == len(fake_store.records)
    assert len({record.id for record in fake_store.records}) == len(fake_store.records)


def test_memory_ingestion_service_returns_unavailable_when_store_fails():
    def failing_store():
        raise RuntimeError("qdrant offline")

    service = MemoryIngestionService(
        store_factory=failing_store,
        decision_store=FakeDecisionStore([]),
        trade_store=FakeTradeStore([]),
    )

    result = service.ingest_run(
        run_id="run_1",
        report_markdown="## Analysis\nStay selective.",
    )

    assert result.status == "unavailable"
    assert result.errors == ["qdrant offline"]


def test_graph_ingest_node_updates_run_status_and_exports(monkeypatch):
    exported = []

    run = PortfolioRunState(run_id="run_1", started_at="2026-06-28T12:00:00Z")
    run.report_markdown = "## Analysis\nStay selective."
    run.run_status = {"warnings": [], "memory_ingestion": None}

    monkeypatch.setattr(
        daily_graph.steps,
        "ingest_run_memory",
        lambda run_id, report_markdown: MemoryIngestionResult(status="ok", created=2),
    )
    monkeypatch.setattr(
        daily_graph.steps,
        "export_run_status",
        lambda status: exported.append(status),
    )

    result = daily_graph.ingest_run_memory_node({"run": run})

    assert result["run"].run_status["memory_ingestion"]["status"] == "ok"
    assert result["run"].run_status["memory_ingestion"]["created"] == 2
    assert exported == [result["run"].run_status]
