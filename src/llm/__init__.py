"""LLM gateway: the single choke point for all model calls.

Every LLM call in the system flows through :mod:`src.llm.gateway`, which owns
structured-output validation, repair retries, transient-error backoff, model
routing by tier, and per-call cost/latency logging. Agents never import an
OpenAI client directly.
"""

from src.llm.gateway import (
    LLMGateway,
    LLMError,
    LLMValidationError,
    complete_structured,
    complete_text,
)

__all__ = [
    "LLMGateway",
    "LLMError",
    "LLMValidationError",
    "complete_structured",
    "complete_text",
]
