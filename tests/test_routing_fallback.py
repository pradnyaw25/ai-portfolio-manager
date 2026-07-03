"""P3-3: provider normalization, tier routing, and cross-route fallback."""

import json
from types import SimpleNamespace

import pytest

from src import config
from src.llm import gateway as gateway_module
from src.llm.gateway import LLMError, LLMGateway
from src.llm.providers import ProviderError, ProviderResponse
from src.llm.providers.openai_provider import OpenAIProvider
from src.llm.routing import Route, resolve_fallback, resolve_route
from src.llm.schemas import RebalanceResponse


# -- OpenAIProvider normalization --------------------------------------------


def _fake_sdk_response(content, prompt=10, completion=20):
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


def test_openai_provider_normalizes_response():
    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _fake_sdk_response("hello")

    resp = OpenAIProvider(_Client()).chat(model="m", messages=[], temperature=0)
    assert isinstance(resp, ProviderResponse)
    assert resp.content == "hello"
    assert resp.prompt_tokens == 10 and resp.completion_tokens == 20


def test_openai_provider_wraps_api_error_as_provider_error():
    import httpx
    import openai

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise openai.APIConnectionError(request=httpx.Request("POST", "http://t"))

    with pytest.raises(ProviderError):
        OpenAIProvider(_Client()).chat(model="m", messages=[], temperature=0)


# -- routing -----------------------------------------------------------------


def test_resolve_route_by_tier(monkeypatch):
    monkeypatch.setattr(config, "LLM_STRONG_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_STRONG_MODEL", "gpt-strong")
    monkeypatch.setattr(config, "LLM_CHEAP_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_CHEAP_MODEL", "gpt-cheap")

    assert resolve_route("strong") == Route("openai", "gpt-strong")
    assert resolve_route("cheap") == Route("openai", "gpt-cheap")


def test_resolve_fallback_none_by_default(monkeypatch):
    monkeypatch.setattr(config, "LLM_FALLBACK_PROVIDER", "")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "")
    assert resolve_fallback() is None


def test_resolve_fallback_when_configured(monkeypatch):
    monkeypatch.setattr(config, "LLM_FALLBACK_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "gpt-backup")
    assert resolve_fallback() == Route("openai", "gpt-backup")


# -- fallback behavior in the gateway ----------------------------------------


class _FakeProvider:
    """Records the models it was asked to serve; can be scripted to fail."""

    def __init__(self, name, *, fail=False, content="{}"):
        self.name = name
        self.fail = fail
        self.content = content
        self.calls = []

    def chat(self, *, model, messages, temperature, response_format=None, tools=None, max_tokens=None):
        self.calls.append(model)
        if self.fail:
            raise ProviderError(f"{self.name} down")
        return ProviderResponse(content=self.content, prompt_tokens=5, completion_tokens=5)


@pytest.fixture(autouse=True)
def _log_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway_module, "LLM_CALL_LOG", tmp_path / "llm_calls.jsonl")
    monkeypatch.setattr(config, "LLM_STRONG_PROVIDER", "primary")
    monkeypatch.setattr(config, "LLM_STRONG_MODEL", "primary-model")


def test_falls_back_to_secondary_when_primary_fails(tmp_path, monkeypatch):
    primary = _FakeProvider("primary", fail=True)
    backup = _FakeProvider("backup", content=json.dumps({"action": "hold_cash"}))
    log = tmp_path / "calls.jsonl"
    monkeypatch.setattr(gateway_module, "LLM_CALL_LOG", log)

    gw = LLMGateway(
        providers={"primary": primary, "backup": backup},
        fallback_route=Route("backup", "backup-model"),
        sleep=lambda _s: None,
        max_retries=1,
    )
    result = gw.complete_structured([{"role": "user", "content": "x"}], RebalanceResponse)

    assert result.action == "hold_cash"
    assert primary.calls == ["primary-model", "primary-model"]  # tried + retried
    assert backup.calls == ["backup-model"]  # then fell back
    record = json.loads(log.read_text().strip().splitlines()[-1])
    assert record["provider"] == "backup" and record["fell_back"] is True


def test_no_fallback_raises_after_retries():
    primary = _FakeProvider("primary", fail=True)
    gw = LLMGateway(
        providers={"primary": primary},
        fallback_route=None,
        sleep=lambda _s: None,
        max_retries=1,
    )
    with pytest.raises(LLMError):
        gw.complete_structured([{"role": "user", "content": "x"}], RebalanceResponse)
    assert primary.calls == ["primary-model", "primary-model"]  # no fallback attempted


def test_fallback_also_failing_raises():
    primary = _FakeProvider("primary", fail=True)
    backup = _FakeProvider("backup", fail=True)
    gw = LLMGateway(
        providers={"primary": primary, "backup": backup},
        fallback_route=Route("backup", "backup-model"),
        sleep=lambda _s: None,
        max_retries=0,
    )
    with pytest.raises(LLMError):
        gw.complete_structured([{"role": "user", "content": "x"}], RebalanceResponse)
    assert primary.calls == ["primary-model"] and backup.calls == ["backup-model"]
