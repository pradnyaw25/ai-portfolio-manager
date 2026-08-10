"""LLM provider abstraction.

The gateway talks to providers through :class:`LLMProvider` instead of the OpenAI
SDK directly, so routing and fallback can span providers. Only OpenAI ships today;
Anthropic/Ollama slot in by adding a module here and registering it.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """A provider failure the gateway may retry and/or fall back on.

    ``retryable`` distinguishes "the network wobbled, try again" from "this request
    is malformed for this model, and will be malformed every time". Retrying the
    latter buys nothing but delay: on 2026-08-10 two runs died on unsupported
    parameters, and each burned two pointless retries plus 3s of backoff before the
    error surfaced. Providers set it; the gateway honors it. Defaults to True so an
    unclassified failure keeps the old, safer behavior.
    """

    def __init__(self, *args: Any, retryable: bool = True):
        super().__init__(*args)
        self.retryable = retryable


@dataclass
class ToolCall:
    """A normalized tool/function call requested by the model."""

    id: str
    name: str
    arguments: str  # raw JSON string as returned by the model


@dataclass
class ProviderResponse:
    content: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None


class LLMProvider(Protocol):
    name: str

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        response_format: dict | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse: ...


def build_default_providers() -> dict[str, LLMProvider]:
    """The provider registry used by the gateway (name → instance)."""
    from src.llm.providers.openai_provider import OpenAIProvider

    return {"openai": OpenAIProvider()}
