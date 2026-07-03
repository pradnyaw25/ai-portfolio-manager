"""P3-2: tool registry validation, the gateway tool loop, and the research agent."""

import json
from types import SimpleNamespace

import pandas as pd
from pydantic import BaseModel

from src.agents.research_agent import ResearchAnalyst, build_research_registry
from src.llm.gateway import LLMGateway
from src.llm.providers import ProviderResponse, ToolCall
from src.llm.tools import Tool, ToolRegistry


class _AddInput(BaseModel):
    a: int
    b: int


def _registry():
    return ToolRegistry([Tool("add", "add two ints", _AddInput, lambda args: args.a + args.b)])


# -- registry ----------------------------------------------------------------


def test_registry_renders_openai_tools():
    schema = _registry().openai_tools()[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "add"
    assert "properties" in schema["function"]["parameters"]


def test_dispatch_runs_valid_call():
    outcome = _registry().dispatch("add", json.dumps({"a": 2, "b": 3}))
    assert outcome == {"ok": True, "result": 5}


def test_dispatch_rejects_invalid_arguments():
    outcome = _registry().dispatch("add", json.dumps({"a": "not-an-int"}))
    assert outcome["ok"] is False
    assert "invalid arguments" in outcome["error"]


def test_dispatch_rejects_bad_json_and_unknown_tool():
    assert _registry().dispatch("add", "{not json").get("ok") is False
    assert _registry().dispatch("nope", "{}")["error"].startswith("unknown tool")


def test_dispatch_wraps_handler_error():
    def boom(_args):
        raise RuntimeError("data source down")

    reg = ToolRegistry([Tool("x", "d", _AddInput, boom)])
    outcome = reg.dispatch("x", json.dumps({"a": 1, "b": 2}))
    assert outcome["ok"] is False and "data source down" in outcome["error"]


# -- gateway tool loop -------------------------------------------------------


class _ScriptedProvider:
    """Returns queued ProviderResponses (tool calls, then a final answer)."""

    def __init__(self, script):
        self._script = list(script)

    def chat(self, *, model, messages, temperature, response_format=None, tools=None, max_tokens=None):
        return self._script.pop(0)


def _gateway(script, tmp_path, monkeypatch):
    from src.llm import gateway as gateway_module
    from src import config

    monkeypatch.setattr(gateway_module, "LLM_CALL_LOG", tmp_path / "calls.jsonl")
    monkeypatch.setattr(config, "LLM_CHEAP_PROVIDER", "scripted")
    monkeypatch.setattr(config, "LLM_CHEAP_MODEL", "m")
    return LLMGateway(providers={"scripted": _ScriptedProvider(script)}, fallback_route=None)


def test_tool_loop_executes_then_returns_final(tmp_path, monkeypatch):
    script = [
        ProviderResponse(content=None, tool_calls=[ToolCall(id="c1", name="add", arguments='{"a": 4, "b": 5}')]),
        ProviderResponse(content="The sum is 9."),
    ]
    gw = _gateway(script, tmp_path, monkeypatch)

    result = gw.complete_with_tools([{"role": "user", "content": "add 4 and 5"}], _registry())

    assert result.content == "The sum is 9."
    assert result.truncated is False
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "add"
    assert result.tool_calls[0]["outcome"] == {"ok": True, "result": 9}


def test_tool_loop_enforces_max_rounds(tmp_path, monkeypatch):
    # Provider always asks for another tool call → loop must stop at max_rounds.
    always_tool = ProviderResponse(
        content=None, tool_calls=[ToolCall(id="c", name="add", arguments='{"a": 1, "b": 1}')]
    )
    gw = _gateway([always_tool] * 10, tmp_path, monkeypatch)

    result = gw.complete_with_tools([{"role": "user", "content": "go"}], _registry(), max_rounds=3)

    assert result.truncated is True
    assert len(result.tool_calls) == 3  # one per round, capped


# -- research agent ----------------------------------------------------------


def test_build_research_registry_tools_wrap_clients():
    market = SimpleNamespace(
        get_price=lambda s: 201.5,
        get_history=lambda s, days=30: pd.DataFrame({"Close": [100.0, 110.0]}),
    )
    news = SimpleNamespace(get_stock_news=lambda q, limit=5: [{"title": "t", "source": "s", "published": "p"}])
    snap = SimpleNamespace(total_value=1_000_000, cash=100_000, cash_pct=0.1, positions=[])
    reg = build_research_registry(market, news, snap)

    assert set(reg.names()) == {"get_price", "get_history", "search_news", "retrieve_memory", "get_portfolio"}
    assert reg.dispatch("get_price", '{"symbol": "aapl"}')["result"] == {"symbol": "AAPL", "price": 201.5}
    assert reg.dispatch("get_history", '{"symbol": "AAPL", "days": 5}')["result"]["return_pct"] == 10.0
    assert reg.dispatch("get_portfolio", "{}")["result"]["total_value"] == 1_000_000


def test_research_analyst_returns_brief_and_tool_trace():
    from src.llm import ToolCallingResult

    captured = {}

    def fake_complete(messages, registry, *, tier, prompt_version):
        captured["tier"] = tier
        return ToolCallingResult(content="Concise brief.", tool_calls=[{"name": "get_price", "outcome": {"ok": True}}])

    brief = ResearchAnalyst().investigate({"symbols": []}, _registry(), complete_fn=fake_complete)

    assert brief["brief"] == "Concise brief."
    assert brief["tool_calls"][0]["name"] == "get_price"
    assert captured["tier"] == "cheap"  # research runs on the cheap tier
