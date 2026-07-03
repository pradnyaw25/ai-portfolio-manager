"""The LLM gateway — every model call in the system flows through here.

Responsibilities:

* **Structured outputs** — validate JSON responses against a Pydantic schema and
  perform one *repair retry* (re-prompt with the validation error) before giving
  up. No caller ever runs a raw ``json.loads`` on model output.
* **Transient-error backoff** — retry API errors (rate limits, connection drops)
  with exponential backoff, up to ``LLM_MAX_RETRIES``.
* **Model routing by tier** — ``strong`` for final decisions, ``cheap`` for
  summaries and tweets. Both tiers currently resolve to the same model; real
  routing is a later roadmap item.
* **Cost/latency logging** — every call records model, prompt version, token
  counts, latency, and estimated cost to ``data/llm_calls.jsonl``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

from src.config import LLM_CALL_LOG, LLM_MAX_RETRIES, LLM_TEMPERATURE
from src.llm.context import get_run_id
from src.llm.providers import ProviderError, ProviderResponse, build_default_providers
from src.llm.providers.openai_provider import OpenAIProvider
from src.llm.routing import Route, resolve_fallback, resolve_route
from src.observability import tracing
from src.utils.logger import get_logger

logger = get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

Message = dict[str, str]

# USD per 1K tokens (input, output). Missing models fall back to zero cost so a
# new model never crashes a run over cost estimation.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.00015, 0.00060),
    "gpt-4o": (0.00250, 0.01000),
    "gpt-4.1-mini": (0.00040, 0.00160),
    "gpt-4.1": (0.00200, 0.00800),
}


class LLMError(Exception):
    """Base class for gateway failures."""


class LLMValidationError(LLMError):
    """Raised when a response cannot be parsed/validated even after a repair retry."""


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_rate, out_rate = _MODEL_PRICING.get(model, (0.0, 0.0))
    return (prompt_tokens / 1000) * in_rate + (completion_tokens / 1000) * out_rate


_DEFAULT_FALLBACK = object()  # sentinel: resolve fallback route from config


class LLMGateway:
    """Routes calls to LLM providers by tier, with validation, retries, backoff,
    an optional cross-provider fallback, and cost logging.

    Providers/client, fallback route, and sleep are injectable so tests run offline.
    Passing ``client=`` wraps it as the OpenAI provider (back-compat).
    """

    def __init__(
        self,
        client=None,
        *,
        providers: dict | None = None,
        fallback_route=_DEFAULT_FALLBACK,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = LLM_MAX_RETRIES,
    ) -> None:
        if providers is not None:
            self._providers = providers
        elif client is not None:
            self._providers = {"openai": OpenAIProvider(client)}
        else:
            self._providers = build_default_providers()
        self._fallback_route = (
            resolve_fallback() if fallback_route is _DEFAULT_FALLBACK else fallback_route
        )
        self._sleep = sleep
        self._max_retries = max_retries

    # -- public API -----------------------------------------------------------

    def complete_structured(
        self,
        messages: Sequence[Message],
        schema: type[TModel],
        *,
        tier: str = "strong",
        temperature: float | None = None,
        prompt_version: str = "unversioned",
    ) -> TModel:
        """Call the model in JSON mode and validate against ``schema``.

        Performs one repair retry: if the response is not valid JSON or fails
        schema validation, the model is re-prompted with the error and asked to
        fix it. Raises :class:`LLMValidationError` if that also fails.
        """
        convo: list[Message] = list(messages)

        last_error: Exception | None = None
        for attempt in range(2):  # initial attempt + one repair
            content = self._call(
                convo,
                tier=tier,
                temperature=temperature,
                prompt_version=prompt_version,
                response_format={"type": "json_object"},
            )
            try:
                return schema.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    logger.warning(
                        "LLM response failed validation for %s (repairing): %s",
                        schema.__name__,
                        str(exc)[:200],
                    )
                    convo = convo + [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was not valid. Fix it and "
                                "return ONLY valid JSON matching the requested schema. "
                                f"Validation error:\n{exc}"
                            ),
                        },
                    ]

        raise LLMValidationError(
            f"{schema.__name__} validation failed after repair retry: {last_error}"
        )

    def complete_text(
        self,
        messages: Sequence[Message],
        *,
        tier: str = "cheap",
        max_tokens: int | None = None,
        temperature: float | None = None,
        prompt_version: str = "unversioned",
    ) -> str:
        """Call the model for free-form text (no schema). Returns stripped content."""
        content = self._call(
            list(messages),
            tier=tier,
            temperature=temperature,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
        )
        return content.strip()

    # -- internals ------------------------------------------------------------

    def _call(
        self,
        messages: list[Message],
        *,
        tier: str,
        temperature: float | None,
        prompt_version: str,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Resolve the tier's route and call it, falling back if the primary fails."""
        route = resolve_route(tier)
        chat_kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": LLM_TEMPERATURE if temperature is None else temperature,
            "response_format": response_format,
            "max_tokens": max_tokens,
        }

        started = time.monotonic()
        response, served, fell_back = self._request_with_fallback(route, chat_kwargs)
        latency_ms = (time.monotonic() - started) * 1000

        self._log_call(
            response,
            model=served.model,
            provider=served.provider,
            fell_back=fell_back,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
            input_messages=messages,
            output_content=response.content,
        )

        if response.content is None:
            raise LLMError(f"Model {served.model} returned empty content")
        return response.content

    def _request_with_fallback(
        self, primary: Route, chat_kwargs: dict[str, Any]
    ) -> tuple[ProviderResponse, Route, bool]:
        try:
            return self._request_with_backoff(primary, chat_kwargs), primary, False
        except LLMError as exc:
            if self._fallback_route is None:
                raise
            logger.warning(
                "Primary route %s/%s failed; falling back to %s/%s: %s",
                primary.provider,
                primary.model,
                self._fallback_route.provider,
                self._fallback_route.model,
                str(exc)[:150],
            )
            return self._request_with_backoff(self._fallback_route, chat_kwargs), self._fallback_route, True

    def _request_with_backoff(self, route: Route, chat_kwargs: dict[str, Any]) -> ProviderResponse:
        provider = self._providers.get(route.provider)
        if provider is None:
            raise LLMError(f"No provider registered for '{route.provider}'")

        attempt = 0
        while True:
            try:
                return provider.chat(model=route.model, **chat_kwargs)
            except ProviderError as exc:
                if attempt >= self._max_retries:
                    logger.error(
                        "LLM call failed after %d retries (%s/%s): %s",
                        self._max_retries,
                        route.provider,
                        route.model,
                        exc,
                    )
                    raise LLMError(str(exc)) from exc
                delay = 2.0**attempt
                logger.warning(
                    "LLM call error (attempt %d/%d) %s/%s, backing off %.1fs: %s",
                    attempt + 1,
                    self._max_retries,
                    route.provider,
                    route.model,
                    delay,
                    str(exc)[:200],
                )
                self._sleep(delay)
                attempt += 1

    def _log_call(
        self,
        response: ProviderResponse,
        *,
        model: str,
        provider: str,
        fell_back: bool,
        prompt_version: str,
        latency_ms: float,
        input_messages: Any = None,
        output_content: Any = None,
    ) -> None:
        """Record token usage, latency, and estimated cost. Never raises."""
        try:
            prompt_tokens = response.prompt_tokens or 0
            completion_tokens = response.completion_tokens or 0
            cost = _estimate_cost(model, prompt_tokens, completion_tokens)
            record = {
                "run_id": get_run_id(),
                "provider": provider,
                "model": model,
                "fell_back": fell_back,
                "prompt_version": prompt_version,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": round(latency_ms, 1),
                "est_cost_usd": round(cost, 6),
            }
            logger.info(
                "LLM %s v=%s tokens=%d/%d latency=%.0fms cost=$%.6f",
                model,
                prompt_version,
                prompt_tokens,
                completion_tokens,
                latency_ms,
                cost,
            )
            LLM_CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LLM_CALL_LOG, "a") as fh:
                fh.write(json.dumps(record) + "\n")

            tracing.record_generation(
                name=prompt_version,
                model=model,
                input=input_messages,
                output=output_content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=round(latency_ms, 1),
            )
        except Exception as exc:  # logging must never break a run
            logger.warning("Failed to log LLM call: %s", exc)


# Module-level default gateway plus thin convenience functions, so agents can
# call the gateway without each constructing their own client.
_default_gateway: LLMGateway | None = None


def _gateway() -> LLMGateway:
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = LLMGateway()
    return _default_gateway


def complete_structured(
    messages: Sequence[Message],
    schema: type[TModel],
    *,
    tier: str = "strong",
    temperature: float | None = None,
    prompt_version: str = "unversioned",
) -> TModel:
    return _gateway().complete_structured(
        messages,
        schema,
        tier=tier,
        temperature=temperature,
        prompt_version=prompt_version,
    )


def complete_text(
    messages: Sequence[Message],
    *,
    tier: str = "cheap",
    max_tokens: int | None = None,
    temperature: float | None = None,
    prompt_version: str = "unversioned",
) -> str:
    return _gateway().complete_text(
        messages,
        tier=tier,
        max_tokens=max_tokens,
        temperature=temperature,
        prompt_version=prompt_version,
    )
