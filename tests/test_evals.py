"""Decision eval harness tests — fully offline via injected fake decide/judge."""

import json

from evals import runner
from evals.runner import run_evals
from evals.grounding import GroundingVerdict, score_grounding
from evals.scenarios import SCENARIOS, HIGH_CASH, MISSING_DATA, STALE_MEMORY, Scenario
from evals.scorers import (
    score_citation_validity,
    score_risk_compliance,
    score_schema_validity,
)


def _good_decision():
    return {
        "outlook": "BULLISH",
        "summary": "Holding quality names.",
        "cash_thesis": "",
        "trades": [{"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.72}],
    }


# -- scenarios ---------------------------------------------------------------


def test_at_least_six_golden_scenarios():
    assert len(SCENARIOS) >= 6
    names = {s.name for s in SCENARIOS}
    assert {"bull_market", "market_crash", "high_cash", "overconcentration",
            "missing_data", "stale_memory"} <= names


# -- schema validity ---------------------------------------------------------


def test_schema_validity_passes_well_formed_decision():
    assert score_schema_validity(_good_decision(), SCENARIOS[0]).passed


def test_schema_validity_flags_missing_keys():
    result = score_schema_validity({"trades": []}, SCENARIOS[0])
    assert not result.passed
    assert "outlook" in result.detail


def test_schema_validity_flags_malformed_trade():
    decision = {"outlook": "NEUTRAL", "summary": "x", "trades": [{"symbol": "AAPL"}]}
    result = score_schema_validity(decision, SCENARIOS[0])
    assert not result.passed
    assert "action" in result.detail


# -- risk compliance ---------------------------------------------------------


def test_risk_compliance_flags_off_universe_trade():
    decision = {"trades": [{"symbol": "DOGE", "action": "BUY", "confidence": 0.7}]}
    result = score_risk_compliance(decision, SCENARIOS[0])
    assert not result.passed
    assert "not in tradable universe" in result.detail


def test_risk_compliance_flags_out_of_range_confidence():
    decision = {"trades": [{"symbol": "AAPL", "action": "BUY", "confidence": 1.7}]}
    assert not score_risk_compliance(decision, SCENARIOS[0]).passed


def test_missing_data_scenario_rejects_priceless_symbol():
    # MSFT has no price in the missing_data scenario → not tradable.
    decision = {"trades": [{"symbol": "MSFT", "action": "BUY", "confidence": 0.8}]}
    assert not score_risk_compliance(decision, MISSING_DATA).passed


def test_high_cash_requires_deployment_or_thesis():
    idle = {"trades": [{"symbol": "AAPL", "action": "HOLD", "confidence": 0.7}], "cash_thesis": ""}
    assert not score_risk_compliance(idle, HIGH_CASH).passed

    justified = {"trades": [], "cash_thesis": "Holding cash ahead of an expected drawdown."}
    assert score_risk_compliance(justified, HIGH_CASH).passed

    deployed = {"trades": [{"symbol": "AAPL", "action": "BUY", "confidence": 0.7}], "cash_thesis": ""}
    assert score_risk_compliance(deployed, HIGH_CASH).passed


# -- citation validity -------------------------------------------------------


def test_citation_validity_flags_unknown_memory_id():
    decision = {"trades": [{"symbol": "AAPL", "action": "BUY", "confidence": 0.7,
                            "sources_used": ["thesis:ghost-id"]}]}
    assert not score_citation_validity(decision, STALE_MEMORY).passed


def test_citation_validity_accepts_known_memory_id():
    decision = {"trades": [{"symbol": "AAPL", "action": "SELL", "confidence": 0.7,
                            "sources_used": ["thesis:aapl-2026-01-15"]}]}
    assert score_citation_validity(decision, STALE_MEMORY).passed


# -- grounding ---------------------------------------------------------------


def test_grounding_uses_injected_judge():
    verdict = GroundingVerdict(grounded=False, issues=["fabricated price for TSLA"])
    result = score_grounding(_good_decision(), SCENARIOS[0], judge=lambda d, s: verdict)
    assert not result.passed
    assert "fabricated" in result.detail


def test_grounding_skips_non_gating_on_judge_error():
    def boom(decision, scenario):
        raise RuntimeError("judge unavailable")

    result = score_grounding(_good_decision(), SCENARIOS[0], judge=boom)
    assert result.passed  # skipped, not failed
    assert "skipped" in result.detail


# -- runner (the CI gate) ----------------------------------------------------


def test_runner_passes_when_all_decisions_are_compliant():
    def decide(scenario):
        decision = _good_decision()
        if scenario.expects_cash_thesis:
            decision["cash_thesis"] = "Deliberately holding cash."
        # Trade a symbol that is actually tradable in each scenario.
        tradable = scenario.tradable_symbols()
        decision["trades"] = [{"symbol": tradable[0], "action": "BUY", "confidence": 0.7}] if tradable else []
        return decision

    summary = run_evals(
        decide_fn=decide,
        judge_fn=lambda d, s: GroundingVerdict(grounded=True),
        timestamp="2026-01-01T00:00:00Z",
    )
    assert summary["passed"] == summary["total"] == len(SCENARIOS)
    assert summary["prompt_version"] == "portfolio_manager/v1"


def test_grounding_is_advisory_and_does_not_gate():
    # A fully compliant decision must PASS even when the grounding judge objects —
    # grounding is a reported signal, not a gate.
    def decide(scenario):
        tradable = scenario.tradable_symbols()
        decision = {"outlook": "NEUTRAL", "summary": "ok",
                    "trades": [{"symbol": tradable[0], "action": "BUY", "confidence": 0.7}] if tradable else []}
        if scenario.expects_cash_thesis:
            decision["cash_thesis"] = "Holding cash on purpose."
        return decision

    summary = run_evals(
        decide_fn=decide,
        judge_fn=lambda d, s: GroundingVerdict(grounded=False, issues=["nitpick"]),
        timestamp="2026-01-01T00:00:00Z",
    )
    assert summary["passed"] == summary["total"] == len(SCENARIOS)
    # ...but the advisory grounding failure is still reported per scenario.
    grounding_scores = [s for r in summary["results"] for s in r["scores"] if s["name"] == "grounding"]
    assert grounding_scores and all(not s["passed"] for s in grounding_scores)


def test_runner_fails_on_broken_decision():
    # Simulates a broken prompt: trades an off-universe symbol everywhere.
    def broken_decide(scenario):
        return {"outlook": "BULLISH", "summary": "x",
                "trades": [{"symbol": "DOGE", "action": "BUY", "confidence": 0.7}]}

    summary = run_evals(decide_fn=broken_decide, use_grounding=False)
    assert summary["passed"] == 0
    assert summary["total"] == len(SCENARIOS)


def test_runner_marks_scenario_failed_when_decide_raises():
    def raising_decide(scenario):
        raise ValueError("LLM returned invalid JSON")

    summary = run_evals(decide_fn=raising_decide, use_grounding=False)
    assert summary["passed"] == 0
    assert summary["results"][0]["scores"][0]["name"] == "decide"


def test_persist_writes_record_with_model_and_prompt_version(tmp_path):
    summary = {"timestamp": "t", "model": "gpt-4o-mini", "prompt_version": "portfolio_manager/v1",
               "total": 1, "passed": 1, "results": []}
    path = tmp_path / "eval_results.jsonl"
    runner.persist(summary, path=path)

    record = json.loads(path.read_text().strip())
    assert record["model"] == "gpt-4o-mini"
    assert record["prompt_version"] == "portfolio_manager/v1"
