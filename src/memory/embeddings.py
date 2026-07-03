"""A deterministic, offline text embedder for retrieval evals and tests.

Not a production embedder — it exists so the retrieval eval harness and tests can
run in CI with no API key and no network, yet still exercise *real* vector search
(an in-memory Qdrant) rather than a mock. It uses signed feature hashing over a
bag of tokens (term frequency), L2-normalized, so cosine similarity rewards
*concentration* of query terms. That is exactly the property that makes chunking
measurable: a focused chunk whose terms are mostly the query scores higher than
the same passage diluted inside a large multi-topic section.
"""

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _hash(token: str, salt: str) -> int:
    digest = hashlib.blake2b(f"{salt}:{token}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


class HashingEmbeddings(Embeddings):
    """Signed feature-hashing term-frequency embedder (deterministic)."""

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokens(text):
            bucket = _hash(token, "bucket") % self.dim
            sign = 1.0 if _hash(token, "sign") & 1 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vec))
        if norm == 0.0:
            return vec
        return [value / norm for value in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
