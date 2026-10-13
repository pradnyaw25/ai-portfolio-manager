#!/usr/bin/env python3
"""Probe every call shape the pipeline uses against the configured models.

Three production incidents in 72 hours came from the same place: a model swap
(#112 moved both tiers to gpt-5.6) that CI could not see, because no test
exercises a live provider. The gpt-5.6 family rejects `temperature=0`, rejects
`max_tokens` in favour of `max_completion_tokens`, and rejects function tools
unless `reasoning_effort` is pinned to "none" — none of which appear anywhere in
a diff that only changes model strings. Each one was found by a failed daily run.

This script finds them all at once, before production does. It issues one small
raw request per (model, call shape), deliberately bypassing `OpenAIProvider` —
the point is to discover what the *API* accepts, not to test our workarounds.
`OpenAIProvider._adapt` is where the discovered quirks get handled.

Run it before switching models, and treat any FAIL as work to do:

    make probe-models
    python scripts/probe_model_compat.py --models gpt-5.6-terra,gpt-4.1-mini

Costs a fraction of a cent. Needs OPENAI_API_KEY. Exits non-zero if any shape
fails for a reason the provider does not already work around.
"""

import argparse
import os
import sys

from openai import OpenAI

from src import config
from src.config import LLM_REQUEST_TIMEOUT
from src.llm.providers.openai_provider import OpenAIProvider

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "Get the latest price for a ticker",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    }
]
_ASK = [{"role": "user", "content": 'Reply with the JSON object {"ok": true}.'}]
_TOOL_ASK = [{"role": "user", "content": "What is AAPL trading at? Use the tool."}]

# Each shape mirrors a way the gateway actually calls chat.completions:
# `complete_structured` (JSON mode), `complete_text` (max_tokens), and
# `complete_with_tools`. `handled_by` names the provider workaround that covers a
# failure, or None if a failure here is a genuine gap.
SHAPES = [
    ("plain", {"messages": _ASK}, None),
    ("temperature=0", {"messages": _ASK, "temperature": 0}, "_NO_TEMPERATURE"),
    ("json response_format", {"messages": _ASK, "response_format": {"type": "json_object"}}, None),
    ("max_tokens", {"messages": _ASK, "max_tokens": 64}, "_RENAMED_MAX_TOKENS"),
    ("tools", {"messages": _TOOL_ASK, "tools": _TOOLS}, "_TOOLS_NEED_EFFORT_NONE"),
    (
        "json + temperature=0 + max_tokens",
        {
            "messages": _ASK,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "max_tokens": 64,
        },
        "_NO_TEMPERATURE/_RENAMED_MAX_TOKENS",
    ),
]


def probe(client: OpenAI, model: str) -> list[tuple[str, str | None, str | None]]:
    """Return (shape, handled_by, error) per call shape; error is None on success."""
    results = []
    for label, kwargs, handled_by in SHAPES:
        try:
            client.chat.completions.create(model=model, **kwargs)
            results.append((label, handled_by, None))
        except Exception as exc:  # noqa: BLE001 — any failure is a finding
            results.append((label, handled_by, str(exc)))
    return results


def client_for(provider_name: str) -> OpenAI:
    """An SDK client for 'openai' or any name in config.LLM_COMPAT_PROVIDERS."""
    if provider_name == "openai":
        return OpenAI(timeout=LLM_REQUEST_TIMEOUT)
    from src.llm.providers import compat_api_key_env

    base_url = config.LLM_COMPAT_PROVIDERS.get(provider_name)
    if base_url is None:
        raise SystemExit(
            f"unknown provider '{provider_name}' (known: openai, {', '.join(config.LLM_COMPAT_PROVIDERS) or 'none'})"
        )
    api_key = os.environ.get(compat_api_key_env(provider_name))
    if not api_key:
        raise SystemExit(f"{compat_api_key_env(provider_name)} is not set")
    return OpenAI(timeout=LLM_REQUEST_TIMEOUT, base_url=base_url, api_key=api_key)


def verify_provider(model: str, provider_name: str = "openai") -> str | None:
    """Run the same shapes through OpenAIProvider, which should absorb every known
    quirk. Returns an error string if it cannot."""
    provider = OpenAIProvider(client_for(provider_name), name=provider_name)
    try:
        provider.chat(model=model, messages=_ASK, temperature=0, max_tokens=64)
        provider.chat(model=model, messages=_TOOL_ASK, temperature=0, tools=_TOOLS)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        default=",".join(
            dict.fromkeys(
                [config.LLM_STRONG_MODEL, config.LLM_CHEAP_MODEL]
                + [f"{p}:{m}" for p, m in config.CALIBRATION_SHADOW_ROUTES]
            )
        ),
        help=(
            "comma-separated models, optionally provider-prefixed as provider:model "
            "(default: the configured strong and cheap tiers, plus any shadow routes)"
        ),
    )
    args = parser.parse_args()

    unhandled = 0

    for spec in [m.strip() for m in args.models.split(",") if m.strip()]:
        provider_name, sep, model = spec.rpartition(":")
        provider_name = provider_name if sep else "openai"
        client = client_for(provider_name)
        print(f"\n=== {provider_name}:{model} ===")
        for label, handled_by, error in probe(client, model):
            if error is None:
                print(f"  ok      {label}")
            elif handled_by:
                print(f"  quirk   {label} — worked around by {handled_by}")
            else:
                unhandled += 1
                print(f"  FAIL    {label}: {error[:160]}")

        provider_error = verify_provider(model, provider_name)
        if provider_error:
            unhandled += 1
            print(f"  FAIL    via OpenAIProvider: {provider_error[:160]}")
        else:
            print("  ok      via OpenAIProvider (every quirk absorbed)")

    if unhandled:
        print(f"\n{unhandled} unhandled failure(s) — add a workaround in OpenAIProvider._adapt")
        return 1
    print("\nAll call shapes usable on every model probed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
