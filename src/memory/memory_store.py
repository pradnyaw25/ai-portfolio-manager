from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from src.config import QDRANT_API_KEY, QDRANT_URL
from src.memory.schemas import MemoryRecord

COLLECTION_NAME = "fund_memory"


class FundMemoryStore:
    def __init__(self, collection_name: str = COLLECTION_NAME):
        embeddings = OpenAIEmbeddings()
        qdrant_options = {"url": QDRANT_URL}
        if QDRANT_API_KEY:
            qdrant_options["api_key"] = QDRANT_API_KEY

        self.store = QdrantVectorStore.from_existing_collection(
            embedding=embeddings,
            collection_name=collection_name,
            **qdrant_options,
        )

    def upsert_records(self, records: list[MemoryRecord]) -> int:
        if not records:
            return 0

        documents = [
            Document(
                page_content=record.content,
                metadata=record.to_document_metadata(),
            )
            for record in records
        ]
        self.store.add_documents(
            documents=documents,
            ids=[record.id for record in records],
        )
        return len(records)
