from src.memory.citations import review_memory_citations


def memory(memory_id, memory_type="thesis", symbols=None):
    return {
        "id": memory_id,
        "type": memory_type,
        "date": "2026-06-28",
        "source_type": "decision",
        "source_id": "decision:run_1",
        "symbols": symbols or [],
        "metadata": {
            "id": memory_id,
            "memory_type": memory_type,
            "date": "2026-06-28",
        },
    }


def test_review_memory_citations_accepts_known_trade_citation():
    review = review_memory_citations(
        raw_decision={
            "trades": [
                {
                    "symbol": "NVDA",
                    "action": "BUY",
                    "sources_used": ["thesis:run_1:decision_summary", "30d return"],
                }
            ]
        },
        memory_used=[memory("thesis:run_1:decision_summary", symbols=["NVDA"])],
    )

    assert review.warnings == []
    assert len(review.citations) == 1
    citation = review.citations[0]
    assert citation.memory_id == "thesis:run_1:decision_summary"
    assert citation.trade_symbol == "NVDA"
    assert citation.trade_action == "BUY"
    assert citation.memory_type == "thesis"
    assert citation.symbols == ["NVDA"]


def test_review_memory_citations_warns_on_unknown_memory_id():
    review = review_memory_citations(
        raw_decision={
            "trades": [
                {
                    "symbol": "NVDA",
                    "action": "BUY",
                    "sources_used": ["risk_lesson:missing"],
                }
            ]
        },
        memory_used=[],
    )

    assert review.citations == []
    assert review.warnings == ["Trade NVDA cited unknown memory id: risk_lesson:missing"]


def test_review_memory_citations_dedupes_repeated_trade_citations():
    review = review_memory_citations(
        raw_decision={
            "trades": [
                {
                    "symbol": "NVDA",
                    "action": "BUY",
                    "sources_used": [
                        "trade:run_1:NVDA:BUY",
                        "trade:run_1:NVDA:BUY",
                    ],
                }
            ]
        },
        memory_used=[memory("trade:run_1:NVDA:BUY", memory_type="trade", symbols=["NVDA"])],
    )

    assert len(review.citations) == 1
    assert review.to_dict()["citations"][0]["memory_id"] == "trade:run_1:NVDA:BUY"
