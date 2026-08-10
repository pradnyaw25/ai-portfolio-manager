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


# -- per-model API quirks ----------------------------------------------------
#
# Regression cover for 2026-08-10: the gpt-5.6 family applies a default
# reasoning_effort that chat.completions rejects alongside function tools, which
# killed the daily run's research-followup node. The workarounds are learned from
# the 400 and cached on the class, so each test starts from a clean slate.


@pytest.fixture(autouse=True)
def _clear_learned_quirks():
    OpenAIProvider._NO_TEMPERATURE.clear()
    OpenAIProvider._TOOLS_NEED_EFFORT_NONE.clear()
    yield
    OpenAIProvider._NO_TEMPERATURE.clear()
    OpenAIProvider._TOOLS_NEED_EFFORT_NONE.clear()


def _bad_request(message):
    import httpx
    import openai

    request = httpx.Request("POST", "http://t")
    return openai.BadRequestError(
        message, response=httpx.Response(400, request=request), body=None
    )


class _RecordingClient:
    """Fails the first ``fail_times`` calls with ``error``, recording every kwargs."""

    def __init__(self, error, fail_times=1):
        self.calls = []
        self._error = error
        self._fail_times = fail_times
        outer = self

        class completions:
            @staticmethod
            def create(**kwargs):
                outer.calls.append(kwargs)
                if len(outer.calls) <= outer._fail_times:
                    raise outer._error
                return _fake_sdk_response("done")

        class chat:
            pass

        chat.completions = completions
        self.chat = chat


TOOLS = [{"type": "function", "function": {"name": "get_price"}}]
_EFFORT_ERROR = (
    "Function tools with reasoning_effort are not supported for gpt-5.6-luna in "
    "/v1/chat/completions. To use function tools, use /v1/responses or set "
    "reasoning_effort to 'none'."
)


def test_tool_call_retries_with_reasoning_effort_none():
    client = _RecordingClient(_bad_request(_EFFORT_ERROR))
    provider = OpenAIProvider(client)

    resp = provider.chat(model="gpt-5.6-luna", messages=[], temperature=0, tools=TOOLS)

    assert resp.content == "done"
    assert len(client.calls) == 2
    assert "reasoning_effort" not in client.calls[0]
    assert client.calls[1]["reasoning_effort"] == "none"
    assert client.calls[1]["tools"] == TOOLS


def test_reasoning_effort_quirk_is_remembered_for_later_calls():
    client = _RecordingClient(_bad_request(_EFFORT_ERROR))
    provider = OpenAIProvider(client)
    provider.chat(model="gpt-5.6-luna", messages=[], temperature=0, tools=TOOLS)

    second = _RecordingClient(_bad_request(_EFFORT_ERROR), fail_times=0)
    OpenAIProvider(second).chat(
        model="gpt-5.6-luna", messages=[], temperature=0, tools=TOOLS
    )

    # Learned on the class, so the second provider pays no failed attempt.
    assert len(second.calls) == 1
    assert second.calls[0]["reasoning_effort"] == "none"


def test_reasoning_effort_workaround_is_not_applied_without_tools():
    # A model that predates the parameter 400s on receiving it at all, so it must
    # never be sent speculatively — only in response to the tools-specific error.
    client = _RecordingClient(_bad_request("Unrecognized request argument supplied: reasoning_effort"))
    with pytest.raises(ProviderError):
        OpenAIProvider(client).chat(model="gpt-4.1-mini", messages=[], temperature=0)

    assert len(client.calls) == 1
    assert "reasoning_effort" not in client.calls[0]


def test_default_only_temperature_is_dropped_and_remembered():
    client = _RecordingClient(_bad_request("temperature does not support 0 with this model"))
    provider = OpenAIProvider(client)

    provider.chat(model="gpt-5.6-terra", messages=[], temperature=0)

    assert len(client.calls) == 2
    assert client.calls[0]["temperature"] == 0
    assert "temperature" not in client.calls[1]
    assert "gpt-5.6-terra" in OpenAIProvider._NO_TEMPERATURE


def test_unrecognized_bad_request_surfaces_without_retrying():
    client = _RecordingClient(_bad_request("context_length_exceeded"))
    with pytest.raises(ProviderError):
        OpenAIProvider(client).chat(model="m", messages=[], temperature=0, tools=TOOLS)

    assert len(client.calls) == 1


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
