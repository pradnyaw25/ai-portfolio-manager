"""Chunked-vs-unchunked retrieval eval over an in-memory vector store.

Proves the P4-1 hypothesis deterministically and offline: splitting a long
multi-topic section into focused chunks improves retrieval of the passage that
answers a query, versus storing the whole section as one vector.

Construction (honest by design): each scenario's answer paragraph is buried after
a paragraph break in a block of shared 10-K boilerplate (``FILLER``) — the way a
real risk factor sits inside a section. A focused *distractor* passage sharing
some query terms competes for the top rank. Unchunked, the host section's vector
is dominated by boilerplate and loses to the distractor; chunked, the answer
paragraph is its own vector and wins. Uses :class:`HashingEmbeddings` so it runs
in CI with no API key.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from src.memory.chunking import chunk_text
from src.memory.embeddings import HashingEmbeddings
from src.memory.memory_store import memory_point_id

# Generic 10-K boilerplate that shares no vocabulary with the scenario queries, so
# it dilutes an unchunked section's vector without itself being retrievable.
FILLER = (
    "The company files annual and quarterly reports with the Commission and "
    "furnishes current reports as required by applicable rules. This document "
    "contains forward looking statements that involve substantial risks and "
    "uncertainties. Actual outcomes may differ materially from those expressed. "
    "The board of directors has adopted governance guidelines and committee "
    "charters that are reviewed periodically. "
) * 15


@dataclass
class RetrievalMetrics:
    strategy: str
    hit_at_1: float
    mrr: float
    recall_at_k: float
    k: int
    num_scenarios: int

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "hit_at_1": round(self.hit_at_1, 4),
            "mrr": round(self.mrr, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "k": self.k,
            "num_scenarios": self.num_scenarios,
        }


@dataclass
class ChunkingEvalResult:
    k: int
    chunked: RetrievalMetrics
    unchunked: RetrievalMetrics

    @property
    def improvement(self) -> dict:
        return {
            "hit_at_1": round(self.chunked.hit_at_1 - self.unchunked.hit_at_1, 4),
            "mrr": round(self.chunked.mrr - self.unchunked.mrr, 4),
            "recall_at_k": round(self.chunked.recall_at_k - self.unchunked.recall_at_k, 4),
        }

    def to_dict(self) -> dict:
        return {
            "k": self.k,
            "num_scenarios": self.chunked.num_scenarios,
            "chunked": self.chunked.to_dict(),
            "unchunked": self.unchunked.to_dict(),
            "improvement": self.improvement,
        }


def load_chunking_scenarios(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())


def run_chunking_eval(
    scenarios: list[dict],
    *,
    k: int = 5,
    embeddings: HashingEmbeddings | None = None,
) -> ChunkingEvalResult:
    embeddings = embeddings or HashingEmbeddings()
    chunked_store = _build_store(scenarios, embeddings, chunked=True)
    unchunked_store = _build_store(scenarios, embeddings, chunked=False)
    return ChunkingEvalResult(
        k=k,
        chunked=_score(chunked_store, scenarios, k=k, strategy="chunked"),
        unchunked=_score(unchunked_store, scenarios, k=k, strategy="unchunked"),
    )


def _build_store(
    scenarios: list[dict],
    embeddings: HashingEmbeddings,
    *,
    chunked: bool,
) -> QdrantVectorStore:
    client = QdrantClient(location=":memory:")
    collection = "chunked" if chunked else "unchunked"
    client.create_collection(
        collection,
        vectors_config=models.VectorParams(size=embeddings.dim, distance=models.Distance.COSINE),
    )
    store = QdrantVectorStore(client=client, collection_name=collection, embedding=embeddings)

    documents: list[Document] = []
    ids: list[str] = []
    for scenario in scenarios:
        host_id = f"host:{scenario['id']}"
        host_text = f"{scenario['answer']}\n\n{FILLER}"
        if chunked:
            for chunk in chunk_text(host_text, label=host_id):
                documents.append(Document(page_content=chunk.text, metadata={"section_id": host_id}))
                ids.append(memory_point_id(f"{host_id}:{chunk.index}"))
        else:
            documents.append(Document(page_content=host_text, metadata={"section_id": host_id}))
            ids.append(memory_point_id(host_id))

        distractor_id = f"dist:{scenario['id']}"
        documents.append(
            Document(page_content=scenario["distractor"], metadata={"section_id": distractor_id})
        )
        ids.append(memory_point_id(distractor_id))

    store.add_documents(documents=documents, ids=ids)
    return store


def _score(
    store: QdrantVectorStore,
    scenarios: list[dict],
    *,
    k: int,
    strategy: str,
) -> RetrievalMetrics:
    hits = 0
    reciprocal_rank = 0.0
    recall = 0
    for scenario in scenarios:
        want = f"host:{scenario['id']}"
        results = store.similarity_search(scenario["query"], k=k)
        section_ids = [doc.metadata["section_id"] for doc in results]
        if section_ids and section_ids[0] == want:
            hits += 1
        if want in section_ids:
            recall += 1
            reciprocal_rank += 1.0 / (section_ids.index(want) + 1)

    n = len(scenarios) or 1
    return RetrievalMetrics(
        strategy=strategy,
        hit_at_1=hits / n,
        mrr=reciprocal_rank / n,
        recall_at_k=recall / n,
        k=k,
        num_scenarios=len(scenarios),
    )
