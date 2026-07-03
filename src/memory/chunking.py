"""Recursive text chunking for long documents (SEC filing sections).

Previously each 10-K section was stored as a single ~12k-char vector, which
dilutes semantic similarity: a query about one risk factor has to match against
a wall of unrelated text. Splitting a section into focused, overlapping chunks
lets retrieval surface the specific passage that answers a query.

Sizes are chars (not tokens) — deterministic and dependency-light. A hard cap on
chunks per section bounds embedding cost/latency; truncation is logged, never
silent.
"""

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.utils.logger import get_logger

logger = get_logger(__name__)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MAX_CHUNKS_PER_SECTION = 30

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
    keep_separator=True,
)


@dataclass(frozen=True)
class Chunk:
    index: int
    total: int
    text: str


def chunk_text(
    text: str,
    *,
    max_chunks: int = MAX_CHUNKS_PER_SECTION,
    label: str = "",
) -> list[Chunk]:
    """Split ``text`` into overlapping chunks.

    Returns at least one chunk for any non-empty input (short text yields a
    single chunk). Chunks beyond ``max_chunks`` are dropped with a warning so
    embedding cost stays bounded; ``label`` identifies the source in that log.
    """
    stripped = text.strip()
    if not stripped:
        return []

    pieces = [piece.strip() for piece in _SPLITTER.split_text(stripped) if piece.strip()]
    if not pieces:
        pieces = [stripped]

    if len(pieces) > max_chunks:
        logger.warning(
            "Section %s produced %d chunks; truncating to %d",
            label or "(unlabeled)",
            len(pieces),
            max_chunks,
        )
        pieces = pieces[:max_chunks]

    total = len(pieces)
    return [Chunk(index=index, total=total, text=piece) for index, piece in enumerate(pieces)]
