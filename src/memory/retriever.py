from dataclasses import dataclass

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from src.config import QDRANT_API_KEY, QDRANT_URL
from src.utils.logger import get_logger

COLLECTION_NAME = "fund_memory"

logger = get_logger(__name__)


@dataclass
class MemoryRetrievalResult:
    chunks: list[dict]
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
        docs = self.store.similarity_search(query, k=k)

        return [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
            }
            for doc in docs
        ]


def retrieve_fund_memory(query: str, k: int = 5) -> MemoryRetrievalResult:
    try:
        chunks = FundMemoryRetriever().retrieve(query=query, k=k)
    except Exception as exc:
        logger.warning("Memory retrieval unavailable; continuing without memory: %s", exc)
        return MemoryRetrievalResult(chunks=[], status="unavailable", error=str(exc))

    return MemoryRetrievalResult(chunks=chunks, status="ok")
