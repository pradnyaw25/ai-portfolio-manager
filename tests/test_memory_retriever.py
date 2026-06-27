from src.memory import retriever


def test_retrieve_fund_memory_returns_unavailable_when_setup_fails(monkeypatch):
    class BrokenRetriever:
        def __init__(self):
            raise RuntimeError("qdrant offline")

    monkeypatch.setattr(retriever, "FundMemoryRetriever", BrokenRetriever)

    result = retriever.retrieve_fund_memory("prior lessons", k=2)

    assert result.status == "unavailable"
    assert result.chunks == []
    assert result.error == "qdrant offline"
