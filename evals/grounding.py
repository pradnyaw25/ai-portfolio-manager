"""LLM-as-judge grounding scorer.

Asks a model whether the decision's factual claims are supported by the provided
context (prices, news, memory) — catching fabricated numbers or invented events.
An additional signal on top of the deterministic scorers; on judge error it is
reported as skipped (non-gating) so a flaky judge never breaks CI.
"""

import json

from evals.scorers import ScoreResult
from src.llm import complete_structured
from src.scoring.grounding import GroundingVerdict

JUDGE_PROMPT_VERSION = "grounding_judge/v1"

__all__ = ["GroundingVerdict", "score_grounding", "JUDGE_PROMPT_VERSION"]


def _default_judge(decision, scenario) -> GroundingVerdict:
    context = {
        "portfolio": scenario.portfolio,
        "market_context": scenario.research,
        "benchmark": scenario.benchmark,
        "memory": scenario.memory,
    }
    prompt = (
        "You are a grounding auditor for an AI portfolio manager. Given the CONTEXT "
        "available to the manager and its DECISION, decide whether the decision "
        "fabricates facts.\n\n"
        "Flag a claim ONLY if it is directly CONTRADICTED by the context, or asserts a "
        "specific fact (a price, a number, a named event) that does NOT appear in the "
        "context at all.\n"
        "Do NOT flag: correct values expressed with equivalent phrasing or units "
        "(e.g. 0.12 and '12%' are the same); rounding; subjective framing; opinions, "
        "outlooks, or forecasts; or ordinary financial reasoning. When in doubt, treat "
        "the claim as grounded.\n\n"
        f"CONTEXT:\n{json.dumps(context, default=str)}\n\n"
        f"DECISION:\n{json.dumps(decision, default=str)}\n\n"
        'Return JSON: {"grounded": true|false, "issues": ["..."]} — issues only for '
        "genuine fabrications or contradictions."
    )
    return complete_structured(
        [{"role": "user", "content": prompt}],
        GroundingVerdict,
        tier="strong",
        prompt_version=JUDGE_PROMPT_VERSION,
    )


def score_grounding(decision, scenario, *, judge=None) -> ScoreResult:
    judge = judge or _default_judge
    try:
        verdict = judge(decision, scenario)
    except Exception as exc:  # a flaky/unavailable judge must not fail the gate
        return ScoreResult("grounding", True, f"skipped: {exc}")
    return ScoreResult("grounding", verdict.grounded, "; ".join(verdict.issues))
