from dataclasses import dataclass
from typing import Any

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from src.config import QDRANT_API_KEY, QDRANT_URL
from src.utils.logger import get_logger

COLLECTION_NAME = "fund_memory"

logger = get_logger(__name__)

EMPTY_GROUPED_MEMORY = {
    "symbol_theses": [],
    "risk_lessons": [],
    "recent_trades": [],
    "macro_context": [],
}


@dataclass
class MemoryRetrievalResult:
    chunks: list[dict]
    grouped: dict[str, list[dict]]
    status: str
    error: str | None = None


class FundMemoryRetriever:
    def __init__(self):
        embeddings = OpenAIEmbeddings()
        qdrant_options = {"url": QDRANT_URL}
        if QDRANT_API_KEY:
            qdrant_options["api_key"] = QDRANT_API_KEY

        self.store = QdrantVectorStore.from_existing_collection(
            embedding=embeddings,
            collection_name=COLLECTION_NAME,
            **qdrant_options,
        )

    def retrieve(self, query: str, k: int = 5) -> list[dict]:
        return self._search(query, k=k)

    def retrieve_grouped(
        self,
        *,
        query: str,
        symbols: list[str] | None = None,
        k_per_group: int = 4,
    ) -> dict[str, list[dict]]:
        symbols = [symbol.upper() for symbol in symbols or []]
        symbol_query = query
        if symbols:
            symbol_query = f"{query} Relevant symbols: {', '.join(symbols)}."

        symbol_candidates = self._search(symbol_query, k=k_per_group * 2)
        return {
            "symbol_theses": _filter_memories(
                symbol_candidates,
                memory_types={"thesis", "report_summary"},
                symbols=symbols,
                limit=k_per_group,
            ),
            "risk_lessons": _filter_memories(
                self._search(
                    "Prior risk lessons, rejected trades, cash discipline, mistakes, and warnings.",
                    k=k_per_group,
                ),
                memory_types={"risk_lesson", "mistake"},
                limit=k_per_group,
            ),
            "recent_trades": _filter_memories(
                self._search(
                    "Recent executed trades, trade rationales, and portfolio action history.",
                    k=k_per_group,
                ),
                memory_types={"trade"},
                symbols=symbols,
                limit=k_per_group,
            ),
            "macro_context": _filter_memories(
                self._search(
                    "Macro regime, market outlook, benchmark context, and portfolio report summaries.",
                    k=k_per_group,
                ),
                memory_types={"macro_regime", "report_summary"},
                limit=k_per_group,
            ),
        }

    def _search(self, query: str, k: int) -> list[dict]:
        docs = self.store.similarity_search(query, k=k)
        return [serialize_memory_doc(doc) for doc in docs]


def retrieve_fund_memory(query: str, k: int = 5) -> MemoryRetrievalResult:
    try:
        chunks = FundMemoryRetriever().retrieve(query=query, k=k)
    except Exception as exc:
        logger.warning("Memory retrieval unavailable; continuing without memory: %s", exc)
        return MemoryRetrievalResult(
            chunks=[],
            grouped=empty_grouped_memory(),
            status="unavailable",
            error=str(exc),
        )

    return MemoryRetrievalResult(
        chunks=chunks,
        grouped={
            "symbol_theses": chunks,
            "risk_lessons": [],
            "recent_trades": [],
            "macro_context": [],
        },
        status="ok",
    )


def retrieve_grouped_fund_memory(
    *,
    query: str,
    symbols: list[str] | None = None,
    k_per_group: int = 4,
) -> MemoryRetrievalResult:
    try:
        grouped = FundMemoryRetriever().retrieve_grouped(
            query=query,
            symbols=symbols,
            k_per_group=k_per_group,
        )
    except Exception as exc:
        logger.warning("Grouped memory retrieval unavailable; continuing without memory: %s", exc)
        return MemoryRetrievalResult(
            chunks=[],
            grouped=empty_grouped_memory(),
            status="unavailable",
            error=str(exc),
        )

    return MemoryRetrievalResult(
        chunks=flatten_grouped_memory(grouped),
        grouped=grouped,
        status="ok",
    )


def serialize_memory_doc(doc: Any) -> dict:
    metadata = dict(doc.metadata)
    memory_type = metadata.get("memory_type") or metadata.get("type")
    symbols = metadata.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [symbols]

    return {
        "id": metadata.get("id"),
        "type": memory_type,
        "content": doc.page_content,
        "metadata": metadata,
        "symbols": [str(symbol).upper() for symbol in symbols],
        "date": metadata.get("date"),
        "source_type": metadata.get("source_type"),
        "source_id": metadata.get("source_id"),
    }


def empty_grouped_memory() -> dict[str, list[dict]]:
    return {key: [] for key in EMPTY_GROUPED_MEMORY}


def flatten_grouped_memory(grouped: dict[str, list[dict]]) -> list[dict]:
    flattened = []
    seen = set()
    for memories in grouped.values():
        for memory in memories:
            memory_key = memory.get("id") or (memory.get("type"), memory.get("content"))
            if memory_key in seen:
                continue
            seen.add(memory_key)
            flattened.append(memory)
    return flattened


def format_grouped_memory_for_prompt(grouped: dict[str, list[dict]]) -> dict[str, list[dict]]:
    formatted = {}
    for group, memories in grouped.items():
        formatted[group] = [
            {
                "id": memory.get("id"),
                "type": memory.get("type"),
                "date": memory.get("date"),
                "symbols": memory.get("symbols", []),
                "source": memory.get("source_id") or memory.get("source_type"),
                "content": memory.get("content"),
            }
            for memory in memories
        ]
    return formatted


def _filter_memories(
    memories: list[dict],
    *,
    memory_types: set[str],
    symbols: list[str] | None = None,
    limit: int,
) -> list[dict]:
    symbols = [symbol.upper() for symbol in symbols or []]
    filtered = []
    seen = set()
    for memory in memories:
        memory_type = memory.get("type")
        memory_symbols = memory.get("symbols") or []
        if memory_type not in memory_types:
            continue
        if symbols and memory_symbols and not set(memory_symbols).intersection(symbols):
            continue
        memory_key = memory.get("id") or (memory_type, memory.get("content"))
        if memory_key in seen:
            continue
        seen.add(memory_key)
        filtered.append(memory)
        if len(filtered) >= limit:
            break
    return filtered
