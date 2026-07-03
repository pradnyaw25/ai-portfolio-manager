from dataclasses import dataclass

from src.memory import retriever


@dataclass
class FakeDocument:
    page_content: str
    metadata: dict


class FakeStore:
    def __init__(self, docs_by_query):
        self.docs_by_query = docs_by_query

    def similarity_search(self, query, k, filter=None):
        for query_part, docs in self.docs_by_query.items():
            if query_part in query:
                return docs[:k]
        return []


def memory_doc(memory_id, memory_type, content, symbols=None):
    return FakeDocument(
        page_content=content,
        metadata={
            "id": memory_id,
            "memory_type": memory_type,
            "symbols": symbols or [],
            "date": "2026-06-28",
            "source_id": f"source:{memory_id}",
        },
    )


def test_retrieve_fund_memory_returns_unavailable_when_setup_fails(monkeypatch):
    class BrokenRetriever:
        def __init__(self):
            raise RuntimeError("qdrant offline")

    monkeypatch.setattr(retriever, "FundMemoryRetriever", BrokenRetriever)

    result = retriever.retrieve_fund_memory("prior lessons", k=2)

    assert result.status == "unavailable"
    assert result.chunks == []
    assert result.grouped == retriever.empty_grouped_memory()
    assert result.error == "qdrant offline"


def test_retrieve_grouped_fund_memory_groups_typed_results(monkeypatch):
    class FakeRetriever:
        def __init__(self):
            self.store = FakeStore(
                {
                    "Relevant symbols": [
                        memory_doc("thesis:1", "thesis", "NVDA thesis", ["NVDA"]),
                        memory_doc("risk:ignored", "risk_lesson", "Ignored risk", ["NVDA"]),
                    ],
                    "Prior risk lessons": [
                        memory_doc("risk:1", "risk_lesson", "Avoid concentration"),
                    ],
                    "Recent executed trades": [
                        memory_doc("trade:1", "trade", "Bought NVDA", ["NVDA"]),
                    ],
                    "Macro regime": [
                        memory_doc("macro:1", "macro_regime", "Risk-on tape"),
                    ],
                }
            )

        retrieve_grouped = retriever.FundMemoryRetriever.retrieve_grouped
        _search = retriever.FundMemoryRetriever._search

    monkeypatch.setattr(retriever, "FundMemoryRetriever", FakeRetriever)

    result = retriever.retrieve_grouped_fund_memory(
        query="prior lessons",
        symbols=["NVDA"],
        k_per_group=2,
    )

    assert result.status == "ok"
    assert [m["id"] for m in result.grouped["symbol_theses"]] == ["thesis:1"]
    assert [m["id"] for m in result.grouped["risk_lessons"]] == ["risk:1"]
    assert [m["id"] for m in result.grouped["recent_trades"]] == ["trade:1"]
    assert [m["id"] for m in result.grouped["macro_context"]] == ["macro:1"]
    assert [m["id"] for m in result.chunks] == ["thesis:1", "risk:1", "trade:1", "macro:1"]


def test_search_falls_back_to_unfiltered_when_server_filter_fails():
    """A missing Qdrant payload index makes a filtered query 400 — retrieval must
    still work by retrying unfiltered (then Python-side _filter_memories narrows)."""
    calls = []

    class UnindexedStore:
        def similarity_search(self, query, k, filter=None):
            calls.append(filter is not None)
            if filter is not None:
                raise RuntimeError('Index required but not found for "metadata.symbols"')
            return [memory_doc("thesis:1", "thesis", "NVDA thesis", ["NVDA"])][:k]

    result = retriever.FundMemoryRetriever(store=UnindexedStore())._search(
        "q", k=3, flt=retriever.build_qdrant_filter(symbols=["NVDA"])
    )

    assert [m["id"] for m in result] == ["thesis:1"]
    assert calls == [True, False]  # tried filtered, then fell back to unfiltered


def test_format_grouped_memory_for_prompt_keeps_citation_fields():
    grouped = {
        "symbol_theses": [
            {
                "id": "thesis:1",
                "type": "thesis",
                "date": "2026-06-28",
                "symbols": ["NVDA"],
                "source_id": "decision:run_1",
                "content": "AI infrastructure thesis.",
                "metadata": {"extra": "not included"},
            }
        ],
        "risk_lessons": [],
        "recent_trades": [],
        "macro_context": [],
    }

    formatted = retriever.format_grouped_memory_for_prompt(grouped)

    assert formatted["symbol_theses"] == [
        {
            "id": "thesis:1",
            "type": "thesis",
            "date": "2026-06-28",
            "symbols": ["NVDA"],
            "source": "decision:run_1",
            "content": "AI infrastructure thesis.",
        }
    ]
