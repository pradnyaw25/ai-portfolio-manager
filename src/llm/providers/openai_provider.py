"""OpenAI provider — wraps chat.completions and normalizes the response."""

from typing import Any

import openai
from openai import OpenAI

from src.config import LLM_REQUEST_TIMEOUT
from src.llm.providers import LLMProvider, ProviderError, ProviderResponse, ToolCall


class OpenAIProvider(LLMProvider):
    name = "openai"

    # Models that reject any temperature other than the default. The gpt-5.6 family
    # returns 400 "does not support 0 with this model" — which matters here because
    # every eval in this repo pins temperature=0 for determinism, so a new model
    # would fail outright rather than degrade. Learned at runtime rather than
    # hardcoded: a fixed list goes stale the moment the next model ships.
    _NO_TEMPERATURE: set[str] = set()

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
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if model not in self._NO_TEMPERATURE:
            kwargs["temperature"] = temperature
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.APIError as exc:
            # A model that only accepts its default temperature: drop the parameter,
            # remember that for the rest of the process, and retry once. Anything else
            # normalizes to a provider-agnostic error the gateway can retry/fall back on.
            if "temperature" in str(exc) and "does not support" in str(exc):
                self._NO_TEMPERATURE.add(model)
                kwargs.pop("temperature", None)
                try:
                    response = self._client.chat.completions.create(**kwargs)
                except openai.APIError as retry_exc:
                    raise ProviderError(str(retry_exc)) from retry_exc
            else:
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
