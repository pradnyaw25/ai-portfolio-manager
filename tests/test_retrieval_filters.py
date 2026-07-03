"""Server-side Qdrant metadata filtering (run against a real in-memory Qdrant)."""

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from src.memory.embeddings import HashingEmbeddings
from src.memory.memory_store import memory_point_id
from src.memory.retriever import build_qdrant_filter
from src.memory.schemas import MemoryRecord


def _record(mem_id, memory_type, content, *, symbols, sector, item):
    return MemoryRecord(
        id=mem_id,
        memory_type=memory_type,
        content=content,
        date="2026-01-01",
        symbols=symbols,
        sectors=[sector],
        source_type="sec_10k",
        metadata={"item": item, "sector": sector},
    )


def _store(records):
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
    return store


_CORPUS = [
    _record("a", "thesis", "apple designs consumer hardware and services",
            symbols=["AAPL"], sector="Information Technology", item="item_1"),
    _record("b", "thesis", "exxon explores and produces oil and gas",
            symbols=["XOM"], sector="Energy", item="item_1"),
    _record("c", "risk_lesson", "exxon faces commodity price and drilling risk",
            symbols=["XOM"], sector="Energy", item="item_1a"),
]


def test_empty_filter_is_none():
    assert build_qdrant_filter() is None


def test_filter_uses_langchain_nested_metadata_keys():
    flt = build_qdrant_filter(
        symbols=["aapl"], memory_types={"thesis"}, sectors=["Energy"], items=["item_1a"]
    )
    assert {c.key for c in flt.must} == {
        "metadata.symbols",
        "metadata.memory_type",
        "metadata.sectors",
        "metadata.metadata.item",
    }


def test_symbol_filter_returns_only_matching_symbol():
    store = _store(_CORPUS)
    results = store.similarity_search("business", k=5, filter=build_qdrant_filter(symbols=["XOM"]))
    assert {d.metadata["id"] for d in results} == {"b", "c"}


def test_sector_filter_returns_only_matching_sector():
    store = _store(_CORPUS)
    results = store.similarity_search(
        "business", k=5, filter=build_qdrant_filter(sectors=["Information Technology"])
    )
    assert {d.metadata["id"] for d in results} == {"a"}


def test_type_filter_returns_only_matching_type():
    store = _store(_CORPUS)
    results = store.similarity_search(
        "risk", k=5, filter=build_qdrant_filter(memory_types={"risk_lesson"})
    )
    assert {d.metadata["id"] for d in results} == {"c"}
