"""Multi-model live calibration: the PM's exact prompt, answered by comparison
models on the same day, recorded as shadow predictions that never trade.

The sequential comparison (gpt-4.1-mini in July vs gpt-5.6-terra in Aug–Sep 2026)
was confounded by regime: 59% of names lagged SPY in one window, 52% beat it in the
other. These tests pin what makes the live comparison clean — identical prompt,
pinned route with no fallback, separate per-model files, no leakage into anything
the fund publishes or trades on — and what keeps it harmless: disabled by default,
one provider's failure never costs another or the run.
"""

import json
from types import SimpleNamespace

import pytest

from src import config
from src import main as steps
from src.agents.portfolio_manager import PortfolioManagerAgent
from src.llm import gateway as gateway_module
from src.llm.gateway import LLMGateway
from src.llm.providers import ProviderError, ProviderResponse, build_default_providers
from src.llm.routing import Route, parse_route, shadow_routes
from src.llm.schemas import RebalanceResponse
from src.models.run_state import PortfolioRunState
from src.scoring.prediction_scorer import PredictionScorer
from src.storage import prediction_store
from src.storage.prediction_store import PredictionStore, shadow_store_path, shadow_stores
from src.workflows import daily_graph


# -- routes and providers ------------------------------------------------------


def test_parse_route_splits_provider_and_model_and_lowercases_provider():
    assert parse_route("Groq:llama-3.3-70b-versatile") == Route("groq", "llama-3.3-70b-versatile")


@pytest.mark.parametrize("spec", ["llama", ":llama", "groq:"])
def test_parse_route_rejects_malformed_specs(spec):
    with pytest.raises(ValueError):
        parse_route(spec)


def test_shadow_routes_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_SHADOW_ROUTES", [("groq", "llama"), ("openai", "gpt-5.6-luna")])

    assert shadow_routes() == [Route("groq", "llama"), Route("openai", "gpt-5.6-luna")]


def test_shadow_routes_are_empty_by_default():
    """Nothing runs and nothing costs until a route is configured."""
    assert config.CALIBRATION_SHADOW_ROUTES == []


def test_compat_provider_is_registered_only_when_its_key_is_present(monkeypatch):
    # Fake the provider class: the real one builds an OpenAI SDK client, which refuses
    # to construct without OPENAI_API_KEY — and CI has none. The registry logic is
    # what is under test, not the SDK.
    class _FakeProvider:
        def __init__(self, client=None, *, name="openai", base_url=None, api_key=None):
            self.name, self.base_url, self.api_key = name, base_url, api_key

    monkeypatch.setattr("src.llm.providers.openai_provider.OpenAIProvider", _FakeProvider)
    compat = {"groq": "https://api.groq.com/openai/v1"}

    without = build_default_providers(compat=compat, environ={})
    with_key = build_default_providers(compat=compat, environ={"GROQ_API_KEY": "k"})

    assert set(without) == {"openai"}
    assert set(with_key) == {"openai", "groq"}
    assert with_key["groq"].name == "groq"
    assert with_key["groq"].base_url == "https://api.groq.com/openai/v1"
    assert with_key["groq"].api_key == "k"


def test_config_rejects_a_shadow_route_on_an_unknown_provider(monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_SHADOW_ROUTES", [("together", "llama")])
    with pytest.raises(config.ConfigError, match="not supported"):
        config.validate_config()


def test_config_rejects_shadowing_the_strong_tier_itself(monkeypatch):
    monkeypatch.setattr(
        config, "CALIBRATION_SHADOW_ROUTES", [(config.LLM_STRONG_PROVIDER, config.LLM_STRONG_MODEL)]
    )
    with pytest.raises(config.ConfigError, match="strong tier itself"):
        config.validate_config()


# -- a pinned route never falls back -------------------------------------------


class _Provider:
    def __init__(self, name, content=None, fail=False):
        self.name = name
        self.content = content
        self.fail = fail
        self.calls = []

    def chat(self, *, model, messages, temperature, response_format=None, tools=None, max_tokens=None):
        self.calls.append(model)
        if self.fail:
            raise ProviderError(f"{self.name} is down")
        return ProviderResponse(content=self.content, prompt_tokens=1, completion_tokens=1)


@pytest.fixture(autouse=True)
def _log_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway_module, "LLM_CALL_LOG", tmp_path / "llm_calls.jsonl")


def test_an_explicit_route_bypasses_the_tier():
    groq = _Provider("groq", content=json.dumps({"action": "hold_cash"}))
    openai = _Provider("openai", content=json.dumps({"action": "deploy"}))
    gw = LLMGateway(providers={"groq": groq, "openai": openai}, fallback_route=None, sleep=lambda _: None)

    out = gw.complete_structured([{"role": "user", "content": "?"}], RebalanceResponse, tier="strong",
                                 route=Route("groq", "llama"))

    assert out.action == "hold_cash"
    assert groq.calls == ["llama"] and openai.calls == []


def test_an_explicit_route_does_not_fall_back_to_another_model():
    """Silently answering from the fallback model would corrupt the comparison."""
    groq = _Provider("groq", fail=True)
    openai = _Provider("openai", content=json.dumps({"action": "deploy"}))
    gw = LLMGateway(
        providers={"groq": groq, "openai": openai},
        fallback_route=Route("openai", "gpt-5.6-luna"),
        sleep=lambda _: None,
        max_retries=0,
    )

    with pytest.raises(gateway_module.LLMError):
        gw.complete_structured([{"role": "user", "content": "?"}], RebalanceResponse, route=Route("groq", "llama"))
    assert openai.calls == []


# -- identical prompt ------------------------------------------------------------


def test_shadow_and_fund_see_the_identical_prompt(monkeypatch):
    captured = []

    def fake(messages, schema, *, tier, prompt_version, route=None):
        captured.append((messages[0]["content"], route))
        return SimpleNamespace(model_dump=lambda: {"market_calls": []})

    monkeypatch.setattr("src.agents.portfolio_manager.complete_structured", fake)
    pm = PortfolioManagerAgent()
    args = ({"cash": 1}, {"symbols": []}, {"spy": 0.01})
    kwargs = {"memory": {"theses": []}, "analysts": {"bull": {"thesis": "up"}}}

    pm.decide(*args, **kwargs)
    pm.decide(*args, **kwargs, route=Route("groq", "llama"))

    (fund_prompt, fund_route), (shadow_prompt, shadow_route) = captured
    assert fund_prompt == shadow_prompt
    assert fund_route is None and shadow_route == Route("groq", "llama")


# -- separate files, independent windows ----------------------------------------


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    monkeypatch.setattr(prediction_store, "SHADOW_DIR", tmp_path / "predictions_shadow")
    return tmp_path


def _call(store, **over):
    kwargs = dict(run_id="run_1", symbol="AAPL", direction="OUTPERFORM", confidence=0.7,
                  thesis="", start_price=100.0, spy_price=500.0, horizon=5)
    kwargs.update(over)
    return store.create_call(**kwargs)


def test_shadow_rows_live_in_their_own_file_and_say_so(stores):
    fund = PredictionStore()
    shadow = PredictionStore(shadow_store_path("groq", "llama-3.3-70b-versatile"))

    _call(fund, model="gpt-5.6-terra")
    row = _call(shadow, model="llama-3.3-70b-versatile", provider="groq", role="shadow")

    assert fund.path == stores / "predictions.jsonl"
    assert shadow.path == stores / "predictions_shadow" / "groq__llama-3.3-70b-versatile.jsonl"
    assert row["role"] == "shadow" and row["provider"] == "groq"
    assert "role" not in fund.load_all()[0]  # the fund's own rows are unchanged
    assert len(fund.load_all()) == 1 and len(shadow.load_all()) == 1


def test_each_model_gets_its_own_independence_guard(stores):
    """The fund's open AAPL/5d window must not block a shadow model's, and vice versa
    — but a model must still not stack two open windows on the same name."""
    fund = PredictionStore()
    shadow = PredictionStore(shadow_store_path("groq", "llama"))

    assert _call(fund) is not None
    assert _call(shadow, run_id="run_1") is not None
    assert _call(shadow, run_id="run_2") is None


def test_shadow_store_path_sanitises_model_names(stores):
    assert shadow_store_path("openai", "gpt-5.6/luna:beta").name == "openai__gpt-5.6_luna_beta.jsonl"


def test_shadow_stores_lists_every_file_in_stable_order(stores):
    assert shadow_stores() == []
    _call(PredictionStore(shadow_store_path("openai", "luna")))
    _call(PredictionStore(shadow_store_path("groq", "llama")))

    assert [s.path.name for s in shadow_stores()] == ["groq__llama.jsonl", "openai__luna.jsonl"]


# -- scoring --------------------------------------------------------------------


class _Market:
    def __init__(self, prices):
        self.prices = prices

    def get_price(self, symbol):
        return self.prices[symbol]


def test_scorer_scores_shadow_files_but_returns_only_the_funds_rows(stores):
    fund = PredictionStore()
    shadow = PredictionStore(shadow_store_path("groq", "llama"))
    past = "2020-01-01"
    for store in (fund, shadow):
        _call(store)
        rows = store.load_all()
        rows[0]["due_date"] = past
        store.save_all(rows)

    scored = PredictionScorer().score_due_predictions(_Market({"SPY": 550.0, "AAPL": 120.0}))

    assert [r["symbol"] for r in scored] == ["AAPL"] and len(scored) == 1
    assert fund.load_all()[0]["status"] == "scored"
    assert shadow.load_all()[0]["status"] == "scored"
    assert shadow.load_all()[0]["result"]["correct"] is True  # +20% vs SPY +10%


# -- the step and the node ---------------------------------------------------------


class _Manager:
    """Stands in for PortfolioManagerAgent: answers per route, or fails for one."""

    def __init__(self, answers, failing=()):
        self.answers = answers
        self.failing = set(failing)
        self.seen = []

    def decide(self, portfolio, research, benchmark, memory=None, analysts=None, *, route=None):
        self.seen.append((route, analysts, portfolio))
        if route.provider in self.failing:
            raise RuntimeError(f"{route.provider} 503")
        return {"market_calls": self.answers[route.provider]}


def _fakes():
    engine = SimpleNamespace(get_snapshot=lambda: {"cash": 1.0})
    benchmark = SimpleNamespace(get_sp500_performance=lambda: {"spy": 0.01})
    market = _Market({"SPY": 500.0, "AAPL": 100.0, "NVDA": 200.0})
    decisions = {"market_calls": [{"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.6}],
                 "debate": {"bull": {"thesis": "up"}}}
    return engine, benchmark, market, decisions


def test_shadow_step_records_each_route_into_its_own_file(stores, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_SHADOW_ROUTES", [("groq", "llama"), ("openai", "luna")])
    manager = _Manager({
        "groq": [{"symbol": "AAPL", "direction": "UNDERPERFORM", "confidence": 0.55, "thesis": "x"}],
        "openai": [{"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.7},
                   {"symbol": "NVDA", "direction": "OUTPERFORM", "confidence": 0.8}],
    })
    monkeypatch.setattr(steps, "PortfolioManagerAgent", lambda: manager)
    engine, benchmark, market, decisions = _fakes()

    summary = steps.shadow_market_calls(decisions, {}, engine, benchmark, {"theses": []}, market, "run_1")

    assert summary == {
        "groq:llama": {"calls": 1, "recorded": 2},   # 5d + 30d
        "openai:luna": {"calls": 2, "recorded": 4},
    }
    groq_rows = PredictionStore(shadow_store_path("groq", "llama")).load_all()
    assert {r["model"] for r in groq_rows} == {"llama"}
    assert all(r["role"] == "shadow" and r["provider"] == "groq" for r in groq_rows)
    assert groq_rows[0]["direction"] == "UNDERPERFORM" and groq_rows[0]["start_price"] == 100.0
    assert PredictionStore().load_all() == []  # the fund's own file is untouched
    # Every shadow saw the debate transcript and the same (pre-trade) snapshot.
    assert all(analysts == decisions["debate"] and snap == {"cash": 1.0} for _, analysts, snap in manager.seen)


def test_one_failing_route_does_not_cost_the_others(stores, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_SHADOW_ROUTES", [("groq", "llama"), ("openai", "luna")])
    manager = _Manager({"openai": [{"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.7}]},
                       failing={"groq"})
    monkeypatch.setattr(steps, "PortfolioManagerAgent", lambda: manager)
    engine, benchmark, market, decisions = _fakes()

    summary = steps.shadow_market_calls(decisions, {}, engine, benchmark, {}, market, "run_1")

    assert summary["groq:llama"] == {"error": "RuntimeError: groq 503"}
    assert summary["openai:luna"] == {"calls": 1, "recorded": 2}


def test_shadow_step_is_a_noop_without_routes(stores, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_SHADOW_ROUTES", [])
    monkeypatch.setattr(steps, "PortfolioManagerAgent", lambda: pytest.fail("must not build a PM"))

    assert steps.shadow_market_calls({"market_calls": [1]}, {}, None, None, {}, None, "r") == {}


def test_shadow_step_skips_when_the_fund_made_no_calls(stores, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_SHADOW_ROUTES", [("groq", "llama")])
    monkeypatch.setattr(steps, "PortfolioManagerAgent", lambda: pytest.fail("must not call a model"))

    out = steps.shadow_market_calls({"market_calls": []}, {}, None, None, {}, None, "r")

    assert out["status"].startswith("skipped")


def test_node_is_optional_and_sits_between_decide_and_grounding():
    assert "shadow_market_calls" in daily_graph.OPTIONAL_NODES
    src = daily_graph.build_daily_cycle_graph  # the node list is inside; pin via the compiled graph
    nodes = list(src().get_graph().nodes)
    assert nodes.index("decide_trades") < nodes.index("shadow_market_calls") < nodes.index("check_grounding")


def test_node_records_disabled_diagnostic_without_touching_steps(monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_SHADOW_ROUTES", [])
    monkeypatch.setattr(daily_graph.steps, "shadow_market_calls", lambda *a: pytest.fail("called"))
    run = PortfolioRunState(run_id="r", started_at="2026-10-02T14:40:00Z")

    daily_graph.shadow_market_calls_node({"run": run})

    assert run.diagnostics["shadow_market_calls"].startswith("disabled")


def test_node_surfaces_a_failed_route_as_a_warning_not_an_error(monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_SHADOW_ROUTES", [("groq", "llama")])
    monkeypatch.setattr(
        daily_graph.steps, "shadow_market_calls",
        lambda *a: {"groq:llama": {"error": "ProviderError: down"}, "openai:luna": {"calls": 3, "recorded": 6}},
    )
    run = PortfolioRunState(run_id="r", started_at="2026-10-02T14:40:00Z")

    daily_graph.shadow_market_calls_node({"run": run})

    assert run.warnings == ["shadow_market_calls: groq:llama failed: ProviderError: down"]
    assert run.errors == []
    assert run.diagnostics["shadow_market_calls"]["openai:luna"]["recorded"] == 6
