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

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from src.config import (
    LLM_CALL_LOG,
    LLM_CHEAP_MODEL,
    LLM_MAX_RETRIES,
    LLM_STRONG_MODEL,
    LLM_TEMPERATURE,
)
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


class LLMGateway:
    """Wraps an OpenAI client with validation, retries, and cost logging.

    The client and sleep function are injectable so tests run offline and without
    real backoff delays.
    """

    def __init__(
        self,
        client: OpenAI | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = LLM_MAX_RETRIES,
    ) -> None:
        self._client = client or OpenAI()
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
        model = self._model_for_tier(tier)
        convo: list[Message] = list(messages)

        last_error: Exception | None = None
        for attempt in range(2):  # initial attempt + one repair
            content = self._call(
                convo,
                model=model,
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
        model = self._model_for_tier(tier)
        content = self._call(
            list(messages),
            model=model,
            temperature=temperature,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
        )
        return content.strip()

    # -- internals ------------------------------------------------------------

    def _model_for_tier(self, tier: str) -> str:
        if tier == "cheap":
            return LLM_CHEAP_MODEL
        return LLM_STRONG_MODEL

    def _call(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float | None,
        prompt_version: str,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """One model call with exponential backoff on transient API errors."""
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": LLM_TEMPERATURE if temperature is None else temperature,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        started = time.monotonic()
        response = self._request_with_backoff(kwargs)
        latency_ms = (time.monotonic() - started) * 1000

        self._log_call(response, model=model, prompt_version=prompt_version, latency_ms=latency_ms)

        content = response.choices[0].message.content
        if content is None:
            raise LLMError(f"Model {model} returned empty content")
        return content

    def _request_with_backoff(self, kwargs: dict[str, Any]) -> Any:
        attempt = 0
        while True:
            try:
                return self._client.chat.completions.create(**kwargs)
            except openai.APIError as exc:
                if attempt >= self._max_retries:
                    logger.error(
                        "LLM call failed after %d retries: %s", self._max_retries, exc
                    )
                    raise LLMError(str(exc)) from exc
                delay = 2.0**attempt
                logger.warning(
                    "LLM call error (attempt %d/%d), backing off %.1fs: %s",
                    attempt + 1,
                    self._max_retries,
                    delay,
                    str(exc)[:200],
                )
                self._sleep(delay)
                attempt += 1

    def _log_call(
        self, response: Any, *, model: str, prompt_version: str, latency_ms: float
    ) -> None:
        """Record token usage, latency, and estimated cost. Never raises."""
        try:
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            cost = _estimate_cost(model, prompt_tokens, completion_tokens)
            record = {
                "model": model,
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
