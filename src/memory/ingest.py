# src/memory/ingest.py

from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from src.config import QDRANT_API_KEY, QDRANT_URL

REPORTS_DIR = Path("reports")
COLLECTION_NAME = "fund_memory"


def load_documents():
    docs = []

    for path in REPORTS_DIR.glob("*.md"):
        docs.append(
            Document(
                page_content=path.read_text(),
                metadata={
                    "source": str(path),
                    "type": "daily_report",
                    "date": path.stem.replace("report_", ""),
                },
            )
        )

    return docs


def main():
    docs = load_documents()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
    )

    chunks = splitter.split_documents(docs)

    embeddings = OpenAIEmbeddings()
    qdrant_options = {"url": QDRANT_URL}
    if QDRANT_API_KEY:
        qdrant_options["api_key"] = QDRANT_API_KEY

    QdrantVectorStore.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        **qdrant_options,
    )

    print(f"Ingested {len(chunks)} chunks into {COLLECTION_NAME}")


if __name__ == "__main__":
    main()
