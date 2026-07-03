import math

from src.memory.embeddings import HashingEmbeddings


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_deterministic():
    emb = HashingEmbeddings()
    assert emb.embed_query("supply chain risk") == emb.embed_query("supply chain risk")


def test_query_and_document_paths_agree():
    emb = HashingEmbeddings()
    assert emb.embed_documents(["abc def ghi"])[0] == emb.embed_query("abc def ghi")


def test_vectors_are_l2_normalized():
    emb = HashingEmbeddings()
    v = emb.embed_query("foreign currency exchange rate risk")
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-9


def test_empty_text_is_zero_vector():
    emb = HashingEmbeddings()
    assert emb.embed_query("   ") == [0.0] * emb.dim


def test_focused_passage_beats_diluted_passage():
    """The core property that makes chunking measurable."""
    emb = HashingEmbeddings()
    query = emb.embed_query("foreign currency exchange rate risk")
    focused = emb.embed_documents(["foreign currency exchange rate risk"])[0]
    diluted = emb.embed_documents(
        ["foreign currency exchange rate risk " + "the board reviews governance annually. " * 50]
    )[0]
    assert _cosine(query, focused) > _cosine(query, diluted)
