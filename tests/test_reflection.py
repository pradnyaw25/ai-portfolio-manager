"""P4-3: weekly reflection agent — gather, synthesize, ingest, retrieve."""

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from src.agents.reflection import build_lesson_records, gather_week
from src.llm.schemas import ReflectionLesson, ReflectionResponse
from src.memory.embeddings import HashingEmbeddings
from src.memory.memory_store import memory_point_id
from src.memory.retriever import FundMemoryRetriever
from src.workflows.weekly_reflection_graph import run_weekly_reflection_graph

WEEK_END = "2026-06-28"  # window: 2026-06-22 .. 2026-06-28


class FakePredictionStore:
    def __init__(self, rows):
        self._rows = rows

    def load_all(self):
        return self._rows


class FakeTradeStore:
    def __init__(self, rows):
        self._rows = rows

    def load_all(self):
        return self._rows


class FakeAgent:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def reflect(self, predictions, trades):
        self.calls += 1
        return self.response


class RecordingStore:
    """In-memory upsert store capturing point ids (mimics FundMemoryStore)."""

    instances = []

    def __init__(self):
        self.records = []
        self.ids = []
        RecordingStore.instances.append(self)

    def upsert_records(self, records):
        self.records = list(records)
        self.ids = [memory_point_id(r.id) for r in records]
        return len(records)


def _scored(pred_id, symbol, scored_date, outperformed):
    return {
        "id": pred_id,
        "symbol": symbol,
        "status": "scored",
        "thesis": f"{symbol} thesis",
        "confidence": 0.7,
        "result": {"scored_date": scored_date, "outperformed": outperformed, "alpha": 0.05},
    }


def test_gather_week_filters_to_window_and_scored():
    predictions = [
        _scored("in1", "AAPL", "2026-06-24", True),
        _scored("out_old", "MSFT", "2026-06-01", False),   # before window
        {"id": "open1", "symbol": "NVDA", "status": "open"},  # not resolved
    ]
    trades = [
        {"run_id": "r1", "symbol": "AAPL", "action": "BUY", "shares": 10, "date": "2026-06-23"},
        {"run_id": "r0", "symbol": "TSLA", "action": "SELL", "shares": 5, "date": "2026-06-10"},
    ]
    week_start, preds, trs = gather_week(
        WEEK_END,
        prediction_store=FakePredictionStore(predictions),
        trade_store=FakeTradeStore(trades),
    )
    assert week_start == "2026-06-22"
    assert [p["id"] for p in preds] == ["prediction:in1"]
    assert preds[0]["outcome"] == "WIN"
    assert [t["id"] for t in trs] == ["trade:r1:AAPL:BUY"]


def test_build_lesson_records_are_deterministic_and_citable():
    response = ReflectionResponse(lessons=[
        ReflectionLesson(lesson_type="mistake", content="Oversized a losing NVDA bet.",
                         symbols=["nvda"], cited_ids=["prediction:in1"]),
        ReflectionLesson(lesson_type="risk_lesson", content="Cap single-name exposure.",
                         symbols=["NVDA"]),
        ReflectionLesson(lesson_type="risk_lesson", content="   ", symbols=[]),  # empty dropped
    ])
    records = build_lesson_records(response, week_start="2026-06-22", week_end=WEEK_END)

    assert [r.id for r in records] == [
        f"mistake:reflection:{WEEK_END}:0",
        f"risk_lesson:reflection:{WEEK_END}:1",
    ]
    assert records[0].symbols == ["NVDA"]
    assert records[0].sectors == ["Information Technology"]
    assert records[0].metadata["cited_ids"] == ["prediction:in1"]
    assert records[0].source_type == "reflection"


def _run(**kwargs):
    RecordingStore.instances.clear()
    response = ReflectionResponse(lessons=[
        ReflectionLesson(lesson_type="risk_lesson", content="Keep sector tilt in check.",
                         symbols=["AAPL"], cited_ids=["prediction:in1"]),
    ])
    return run_weekly_reflection_graph(
        week_end=WEEK_END,
        agent=FakeAgent(response),
        prediction_store=FakePredictionStore([_scored("in1", "AAPL", "2026-06-24", False)]),
        trade_store=FakeTradeStore([]),
        store_factory=RecordingStore,
        **kwargs,
    )


def test_graph_ingests_lessons():
    result = _run()
    assert result.status == "ok"
    assert result.created == 1
    assert RecordingStore.instances[-1].records[0].memory_type == "risk_lesson"


def test_graph_is_idempotent_across_runs():
    _run()
    first_ids = list(RecordingStore.instances[-1].ids)
    _run()
    second_ids = list(RecordingStore.instances[-1].ids)
    assert first_ids == second_ids  # same deterministic point ids → upsert, no dupes


def test_graph_skips_when_no_data():
    RecordingStore.instances.clear()
    agent = FakeAgent(ReflectionResponse(lessons=[]))
    result = run_weekly_reflection_graph(
        week_end=WEEK_END,
        agent=agent,
        prediction_store=FakePredictionStore([]),
        trade_store=FakeTradeStore([]),
        store_factory=RecordingStore,
    )
    assert result.status == "skipped"
    assert agent.calls == 0  # reflect node skipped entirely


def test_ingested_lessons_surface_in_risk_lessons_retrieval():
    """End-to-end: a reflection lesson is retrieved in the daily risk_lessons group."""
    records = build_lesson_records(
        ReflectionResponse(lessons=[
            ReflectionLesson(lesson_type="risk_lesson",
                             content="Avoid concentration; trim NVDA on strength.",
                             symbols=["NVDA"], cited_ids=["prediction:in1"]),
        ]),
        week_start="2026-06-22", week_end=WEEK_END,
    )
    emb = HashingEmbeddings()
    client = QdrantClient(location=":memory:")
    client.create_collection(
        "m", vectors_config=models.VectorParams(size=emb.dim, distance=models.Distance.COSINE)
    )
    store = QdrantVectorStore(client=client, collection_name="m", embedding=emb)
    store.add_documents(
        [Document(page_content=r.content, metadata=r.to_document_metadata()) for r in records],
        ids=[memory_point_id(r.id) for r in records],
    )

    grouped = FundMemoryRetriever(store=store).retrieve_grouped(query="risk", symbols=["NVDA"])
    assert records[0].id in [m["id"] for m in grouped["risk_lessons"]]
