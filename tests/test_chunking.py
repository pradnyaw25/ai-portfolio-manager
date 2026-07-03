from src.memory.chunking import CHUNK_SIZE, Chunk, chunk_text


def test_short_text_is_single_chunk():
    chunks = chunk_text("A brief risk disclosure.")
    assert chunks == [Chunk(index=0, total=1, text="A brief risk disclosure.")]


def test_empty_text_yields_no_chunks():
    assert chunk_text("   \n  ") == []


def test_long_text_splits_into_ordered_chunks():
    text = "Sentence about market risk. " * 200  # well above CHUNK_SIZE
    chunks = chunk_text(text)

    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.total == len(chunks) for c in chunks)
    assert all(len(c.text) <= CHUNK_SIZE * 1.5 for c in chunks)  # splitter honors size


def test_is_deterministic():
    text = "Repeatable content for hashing. " * 100
    assert chunk_text(text) == chunk_text(text)


def test_max_chunks_cap_is_enforced():
    text = "word " * 5000  # would produce many chunks
    chunks = chunk_text(text, max_chunks=5)
    assert len(chunks) == 5
    assert all(c.total == 5 for c in chunks)
