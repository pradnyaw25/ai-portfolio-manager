"""OpenAI provider — wraps chat.completions and normalizes the response."""

from typing import Any

import openai
from openai import OpenAI

from src.config import LLM_REQUEST_TIMEOUT
from src.llm.providers import LLMProvider, ProviderError, ProviderResponse, ToolCall


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, client: OpenAI | None = None):
        # Cap the per-request timeout so a stalled connection fails fast and lets the
        # gateway's retry/backoff recover, instead of hanging on the SDK's 600s default.
        self._client = client or OpenAI(timeout=LLM_REQUEST_TIMEOUT)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        response_format: dict | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.APIError as exc:
            # Normalize to a provider-agnostic error the gateway can retry/fall back on.
            raise ProviderError(str(exc)) from exc

        return self._normalize(response)

    def _normalize(self, response: Any) -> ProviderResponse:
        message = response.choices[0].message
        usage = getattr(response, "usage", None)
        tool_calls = []
        for call in getattr(message, "tool_calls", None) or []:
            tool_calls.append(
                ToolCall(
                    id=getattr(call, "id", ""),
                    name=call.function.name,
                    arguments=call.function.arguments or "{}",
                )
            )
        return ProviderResponse(
            content=message.content,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            tool_calls=tool_calls,
            raw=response,
        )
