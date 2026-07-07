"""LLM-as-judge grounding scorer.

Asks a model whether the decision's factual claims are supported by the provided
context (prices, news, memory) — catching fabricated numbers or invented events.
An additional signal on top of the deterministic scorers; on judge error it is
reported as skipped (non-gating) so a flaky judge never breaks CI.
"""

import json

from evals.scorers import ScoreResult
from src.llm import complete_structured
from src.scoring.grounding import GROUNDING_INSTRUCTIONS, GroundingVerdict

JUDGE_PROMPT_VERSION = "grounding_judge/v2"

__all__ = ["GroundingVerdict", "score_grounding", "JUDGE_PROMPT_VERSION"]


def _default_judge(decision, scenario) -> GroundingVerdict:
    context = {
        "portfolio": scenario.portfolio,
        "market_context": scenario.research,
        "benchmark": scenario.benchmark,
        "memory": scenario.memory,
    }
    prompt = (
        f"{GROUNDING_INSTRUCTIONS}"
        f"CONTEXT:\n{json.dumps(context, default=str)}\n\n"
        f"DECISION:\n{json.dumps(decision, default=str)}\n\n"
        'Return JSON: {"grounded": true|false, "severity": "none"|"minor"|"material", '
        '"issues": ["..."]}.'
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
