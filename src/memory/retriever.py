# src/memory/retriever.py

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from src.config import QDRANT_API_KEY, QDRANT_URL

COLLECTION_NAME = "fund_memory"


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
