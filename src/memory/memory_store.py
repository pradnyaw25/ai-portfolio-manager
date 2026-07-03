import uuid

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from src.config import QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_URL
from src.memory.schemas import MemoryRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLLECTION_NAME = QDRANT_COLLECTION
POINT_ID_NAMESPACE = uuid.UUID("9c2ef9d1-4b7d-4b7c-a344-ecf6ab01c7df")

# Payload keys that grouped retrieval filters on. Qdrant requires a keyword index
# on a field before it can be used in a filter, so ingestion creates these.
INDEXED_PAYLOAD_FIELDS = (
    "metadata.memory_type",
    "metadata.symbols",
    "metadata.sectors",
    "metadata.metadata.item",
)


class FundMemoryStore:
    def __init__(self, collection_name: str = COLLECTION_NAME):
        embeddings = OpenAIEmbeddings()
        qdrant_options = {"url": QDRANT_URL}
        if QDRANT_API_KEY:
            qdrant_options["api_key"] = QDRANT_API_KEY

        self.collection_name = collection_name
        self.store = QdrantVectorStore.from_existing_collection(
            embedding=embeddings,
            collection_name=collection_name,
            **qdrant_options,
        )

    def ensure_payload_indexes(self) -> None:
        """Create keyword indexes for the fields grouped retrieval filters on.

        Best-effort and idempotent: creating an existing index is a no-op/error we
        swallow. Without these, a filtered query returns HTTP 400 in Qdrant Cloud.
        """
        client = getattr(self.store, "client", None)
        if client is None:
            return
        for field in INDEXED_PAYLOAD_FIELDS:
            try:
                client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema="keyword",
                )
            except Exception as exc:  # already indexed, or transient
                logger.debug("payload index for %s not created: %s", field, exc)

    def upsert_records(self, records: list[MemoryRecord]) -> int:
        if not records:
            return 0

        self.ensure_payload_indexes()
        documents = [
            Document(
                page_content=record.content,
                metadata=record.to_document_metadata(),
            )
            for record in records
        ]
        self.store.add_documents(
            documents=documents,
            ids=[memory_point_id(record.id) for record in records],
        )
        return len(records)


def memory_point_id(memory_id: str) -> str:
    return str(uuid.uuid5(POINT_ID_NAMESPACE, memory_id))
