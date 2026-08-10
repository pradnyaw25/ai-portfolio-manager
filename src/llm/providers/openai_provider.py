"""OpenAI provider — wraps chat.completions and normalizes the response."""

from typing import Any

import openai
from openai import OpenAI

from src.config import LLM_REQUEST_TIMEOUT
from src.llm.providers import LLMProvider, ProviderError, ProviderResponse, ToolCall

# Number of per-model API quirks `OpenAIProvider._adapt` knows how to work around.
# Bounds the retry loop: one extra attempt per quirk, and no more.
_KNOWN_QUIRKS = 2


class OpenAIProvider(LLMProvider):
    name = "openai"

    # Per-model API quirks, learned at runtime rather than hardcoded: a fixed list
    # goes stale the moment the next model ships, and the quirks are not guessable
    # from the model name.
    #
    # Models that reject any temperature other than the default. The gpt-5.6 family
    # returns 400 "does not support 0 with this model" — which matters here because
    # every eval in this repo pins temperature=0 for determinism, so a new model
    # would fail outright rather than degrade.
    _NO_TEMPERATURE: set[str] = set()

    # Models whose *default* reasoning effort is incompatible with function tools on
    # chat.completions: "Function tools with reasoning_effort are not supported for
    # <model> in /v1/chat/completions ... or set reasoning_effort to 'none'". We never
    # send reasoning_effort ourselves — the server-side default is what collides — so
    # the fix is to send it explicitly as "none" for those models. Both gpt-5.6-luna
    # and gpt-5.6-terra need this; sending it to a model that predates the parameter
    # (gpt-4.1-mini) is itself a 400, hence per-model rather than unconditional.
    _TOOLS_NEED_EFFORT_NONE: set[str] = set()

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
            if model in self._TOOLS_NEED_EFFORT_NONE:
                kwargs["reasoning_effort"] = "none"
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        # Each known quirk can be worked around at most once, so the loop terminates
        # even if a model trips several of them. Anything unrecognized normalizes to a
        # provider-agnostic error the gateway can retry or fall back on.
        for _ in range(_KNOWN_QUIRKS + 1):
            try:
                response = self._client.chat.completions.create(**kwargs)
            except openai.APIError as exc:
                if not self._adapt(model, kwargs, exc):
                    raise ProviderError(str(exc)) from exc
                continue
            return self._normalize(response)

        raise ProviderError(f"exhausted API-quirk workarounds for model {model}")

    def _adapt(self, model: str, kwargs: dict[str, Any], exc: Exception) -> bool:
        """Rewrite ``kwargs`` in place to work around a known per-model 400, recording
        the quirk so the rest of the process skips the failed attempt. Returns whether
        a workaround was applied — False means the error is real and should surface."""
        message = str(exc)

        # Only accepts its default temperature: drop the parameter.
        if "temperature" in message and "does not support" in message and "temperature" in kwargs:
            self._NO_TEMPERATURE.add(model)
            kwargs.pop("temperature", None)
            return True

        # Default reasoning effort collides with function tools: pin it off.
        if (
            "reasoning_effort" in message
            and kwargs.get("tools")
            and "reasoning_effort" not in kwargs
        ):
            self._TOOLS_NEED_EFFORT_NONE.add(model)
            kwargs["reasoning_effort"] = "none"
            return True

        return False

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
