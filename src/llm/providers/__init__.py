"""LLM provider abstraction.

The gateway talks to providers through :class:`LLMProvider` instead of the OpenAI
SDK directly, so routing and fallback can span providers. Only OpenAI ships today;
Anthropic/Ollama slot in by adding a module here and registering it.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """A transient or terminal provider failure the gateway may retry/fall back on."""


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
