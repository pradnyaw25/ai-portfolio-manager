"""Ablation wiring: make_decide toggles + build_ablation_payload aggregation.

The LLM run loop lives in scripts/compare_ablations.py; here we test the pure
pieces with injected fakes, no API key required.
"""

from evals.scenarios import Scenario
from src.experiments import ablations
from src.experiments.ablations import build_ablation_payload, make_decide


def _scenario(memory=None, expects_debate=False):
    return Scenario(
        name="t",
        description="",
        portfolio={"total_value": 1},
        research={"symbols": []},
        benchmark={"return_pct": 0.0},
        memory=memory or [],
        expects_debate=expects_debate,
    )


def test_make_decide_strips_memory_when_disabled(monkeypatch):
    captured = {}

    class FakePM:
        def decide(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

    monkeypatch.setattr(ablations, "PortfolioManagerAgent", FakePM)
    make_decide(use_memory=False, use_debate=True)(_scenario(memory=[{"id": "m"}]))
    assert captured["memory"] == []


def test_make_decide_passes_memory_when_enabled(monkeypatch):
    captured = {}

    class FakePM:
        def decide(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

    monkeypatch.setattr(ablations, "PortfolioManagerAgent", FakePM)
    make_decide(use_memory=True, use_debate=True)(_scenario(memory=[{"id": "m"}]))
    assert captured["memory"] == [{"id": "m"}]


def test_debate_runs_only_when_enabled_and_expected(monkeypatch):
    calls = {"debate": 0, "pm": 0}

    def fake_debate(*args, **kwargs):
        calls["debate"] += 1
        return {"debate": True}

    class FakePM:
        def decide(self, **kwargs):
            calls["pm"] += 1
            return {"pm": True}

    monkeypatch.setattr(ablations, "run_debate", fake_debate)
    monkeypatch.setattr(ablations, "PortfolioManagerAgent", FakePM)

    # debate scenario + debate enabled -> debate path
    make_decide(use_memory=True, use_debate=True)(_scenario(expects_debate=True))
    # debate scenario + debate disabled -> single-shot PM
    make_decide(use_memory=True, use_debate=False)(_scenario(expects_debate=True))
    # non-debate scenario + debate enabled -> still PM (nothing to debate)
    make_decide(use_memory=True, use_debate=True)(_scenario(expects_debate=False))

    assert calls == {"debate": 1, "pm": 2}


def test_no_memory_variant_strips_memory_even_in_debate(monkeypatch):
    captured = {}

    def fake_debate(portfolio, research, benchmark, memory):
        captured["memory"] = memory
        return {"debate": True}

    monkeypatch.setattr(ablations, "run_debate", fake_debate)
    make_decide(use_memory=False, use_debate=True)(_scenario(memory=[{"id": "m"}], expects_debate=True))
    assert captured["memory"] == []


def test_build_payload_computes_delta_vs_full():
    results = [
        {"key": "full", "name": "Full", "detail": "", "pass_rate": 1.0, "quality_mean": 4.0},
        {"key": "no_memory", "name": "No memory", "detail": "", "pass_rate": 1.0, "quality_mean": 3.4},
        {"key": "no_debate", "name": "No debate", "detail": "", "pass_rate": 1.0, "quality_mean": 4.1},
    ]
    payload = build_ablation_payload(
        results, generated_at="2026-07-08T00:00:00Z", judge_model="gpt-4o", scenarios=8
    )
    by_key = {v["key"]: v for v in payload["variants"]}
    assert by_key["full"]["quality_delta"] is None
    assert by_key["no_memory"]["quality_delta"] == -0.6
    assert by_key["no_debate"]["quality_delta"] == 0.1
    assert payload["judge_model"] == "gpt-4o"
    assert payload["scenarios"] == 8


def test_build_payload_handles_missing_full():
    results = [{"key": "no_memory", "name": "x", "detail": "", "pass_rate": 1.0, "quality_mean": 3.0}]
    payload = build_ablation_payload(results, generated_at="t", judge_model="j", scenarios=1)
    assert payload["variants"][0]["quality_delta"] is None
