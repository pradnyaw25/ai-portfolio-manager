"""LLM-as-judge grounding scorer.

Asks a model whether the decision's factual claims are supported by the provided
context (prices, news, memory) — catching fabricated numbers or invented events.
An additional signal on top of the deterministic scorers; on judge error it is
reported as skipped (non-gating) so a flaky judge never breaks CI.
"""

import json

from pydantic import BaseModel, Field

from evals.scorers import ScoreResult
from src.llm import complete_structured

JUDGE_PROMPT_VERSION = "grounding_judge/v1"


class GroundingVerdict(BaseModel):
    grounded: bool = True
    issues: list[str] = Field(default_factory=list)


def _default_judge(decision, scenario) -> GroundingVerdict:
    context = {
        "portfolio": scenario.portfolio,
        "market_context": scenario.research,
        "benchmark": scenario.benchmark,
        "memory": scenario.memory,
    }
    prompt = (
        "You are a grounding auditor for an AI portfolio manager. Given the CONTEXT "
        "available to the manager and its DECISION, determine whether every factual "
        "claim in the decision (prices, returns, news, memory references) is supported "
        "by the context. Flag any fabricated prices, invented events, or claims with no "
        "basis in the context. Opinions and forecasts are fine; unsupported facts are not.\n\n"
        f"CONTEXT:\n{json.dumps(context, default=str)}\n\n"
        f"DECISION:\n{json.dumps(decision, default=str)}\n\n"
        'Return JSON: {"grounded": true|false, "issues": ["..."]}'
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
