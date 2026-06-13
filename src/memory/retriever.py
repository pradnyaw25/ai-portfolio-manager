# src/memory/retriever.py

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

COLLECTION_NAME = "fund_memory"


class FundMemoryRetriever:
    def __init__(self):
        embeddings = OpenAIEmbeddings()

        self.store = QdrantVectorStore.from_existing_collection(
            embedding=embeddings,
            url="http://localhost:6333",
            collection_name=COLLECTION_NAME,
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
