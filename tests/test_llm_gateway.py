import json

import httpx
import openai
import pytest

from src.llm import gateway as gateway_module
from src.llm.gateway import LLMError, LLMGateway, LLMValidationError
from src.llm.schemas import DecisionResponse, RebalanceResponse


# -- fake OpenAI client ------------------------------------------------------


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, content, prompt_tokens=10, completion_tokens=20):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


class _FakeCompletions:
    def __init__(self, script):
        # script: list of str (content to return) or Exception (to raise)
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


class _FakeClient:
    def __init__(self, script):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(script)})()


def _gateway(script, **kwargs):
    client = _FakeClient(script)
    gw = LLMGateway(client=client, sleep=lambda _s: None, **kwargs)
    return gw, client.chat.completions


def _api_error():
    return openai.APIConnectionError(request=httpx.Request("POST", "http://test"))


@pytest.fixture(autouse=True)
def _log_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway_module, "LLM_CALL_LOG", tmp_path / "llm_calls.jsonl")


# -- structured output -------------------------------------------------------


def test_valid_structured_response_parses():
    payload = json.dumps({"action": "hold_cash", "cash_thesis": "waiting"})
    gw, completions = _gateway([payload])

    result = gw.complete_structured([{"role": "user", "content": "x"}], RebalanceResponse)

    assert isinstance(result, RebalanceResponse)
    assert result.action == "hold_cash"
    assert result.cash_thesis == "waiting"
    assert len(completions.calls) == 1


def test_malformed_json_triggers_repair_retry_then_succeeds():
    good = json.dumps({"outlook": "BULLISH", "summary": "ok"})
    gw, completions = _gateway(["this is not json{{{", good])

    result = gw.complete_structured([{"role": "user", "content": "x"}], DecisionResponse)

    assert result.outlook == "BULLISH"
    # Two calls: the initial malformed one and the repair.
    assert len(completions.calls) == 2
    # The repair call includes the assistant's bad output plus a fix instruction.
    repair_messages = completions.calls[1]["messages"]
    assert any("valid JSON" in m["content"] for m in repair_messages if m["role"] == "user")


def test_schema_invalid_then_valid_on_retry():
    # action must be "deploy" or "hold_cash"; "banana" fails Literal validation.
    bad = json.dumps({"action": "banana"})
    good = json.dumps({"action": "deploy", "trades": []})
    gw, completions = _gateway([bad, good])

    result = gw.complete_structured([{"role": "user", "content": "x"}], RebalanceResponse)

    assert result.action == "deploy"
    assert len(completions.calls) == 2


def test_persistent_invalid_raises_validation_error():
    bad = json.dumps({"action": "banana"})
    gw, completions = _gateway([bad, bad])

    with pytest.raises(LLMValidationError):
        gw.complete_structured([{"role": "user", "content": "x"}], RebalanceResponse)

    # Initial attempt + one repair, then give up.
    assert len(completions.calls) == 2


# -- transient error backoff -------------------------------------------------


def test_transient_error_retries_then_succeeds():
    good = json.dumps({"action": "hold_cash"})
    sleeps = []
    client = _FakeClient([_api_error(), good])
    gw = LLMGateway(client=client, sleep=lambda s: sleeps.append(s), max_retries=2)

    result = gw.complete_structured([{"role": "user", "content": "x"}], RebalanceResponse)

    assert result.action == "hold_cash"
    assert sleeps == [1.0]  # one backoff before the successful retry


def test_persistent_api_error_raises_after_max_retries():
    sleeps = []
    client = _FakeClient([_api_error(), _api_error(), _api_error()])
    gw = LLMGateway(client=client, sleep=lambda s: sleeps.append(s), max_retries=2)

    with pytest.raises(LLMError):
        gw.complete_structured([{"role": "user", "content": "x"}], RebalanceResponse)

    assert sleeps == [1.0, 2.0]  # exponential backoff, max_retries times


# -- text completion ---------------------------------------------------------


def test_complete_text_returns_stripped_string():
    gw, _ = _gateway(["  a tweet body  \n"])

    result = gw.complete_text([{"role": "user", "content": "x"}])

    assert result == "a tweet body"


# -- cost logging ------------------------------------------------------------


def test_call_is_logged_to_jsonl(tmp_path, monkeypatch):
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setattr(gateway_module, "LLM_CALL_LOG", log_path)
    gw, _ = _gateway([json.dumps({"action": "deploy"})])

    gw.complete_structured(
        [{"role": "user", "content": "x"}], RebalanceResponse, prompt_version="test/v1"
    )

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["prompt_version"] == "test/v1"
    assert record["prompt_tokens"] == 10
    assert record["completion_tokens"] == 20
    assert record["est_cost_usd"] > 0
