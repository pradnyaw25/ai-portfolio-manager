"""Runtime grounding check for AI decisions.

Before a decision is journaled and tweeted, an LLM-as-judge verifies that its
factual claims (prices, returns, news, memory references) are supported by the
context the manager actually had. Unsupported claims are flagged, stored with the
decision, and block tweeting.

Degrades gracefully: if the judge is unavailable, the result is ``unavailable``
(non-blocking) rather than failing the run. The ``GroundingVerdict`` schema is
shared with the offline eval harness (`evals/grounding.py`).
"""

import json
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from src.llm import complete_structured
from src.utils.logger import get_logger

logger = get_logger(__name__)

GROUNDING_PROMPT_VERSION = "grounding_check/v1"


class GroundingVerdict(BaseModel):
    grounded: bool = True
    issues: list[str] = Field(default_factory=list)


@dataclass
class GroundingResult:
    status: str  # "ok" | "flagged" | "unavailable"
    grounded: bool
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"status": self.status, "grounded": self.grounded, "issues": self.issues}


def _default_judge(decision: dict, context: dict) -> GroundingVerdict:
    prompt = (
        "You are a grounding auditor for an AI portfolio manager. Given the CONTEXT "
        "the manager had and its DECISION, decide whether the decision fabricates "
        "facts.\n\n"
        "Flag a claim ONLY if it is directly CONTRADICTED by the context, or asserts a "
        "specific fact (a price, a number, a named event) that does NOT appear in the "
        "context at all.\n"
        "Do NOT flag: correct values expressed with equivalent phrasing or units "
        "(e.g. 0.12 and '12%' are the same); rounding; subjective framing ('relatively "
        "high'); opinions, outlooks, or forecasts; or ordinary financial reasoning. "
        "When in doubt, treat the claim as grounded.\n\n"
        f"CONTEXT:\n{json.dumps(context, default=str)}\n\n"
        f"DECISION:\n{json.dumps(decision, default=str)}\n\n"
        'Return JSON: {"grounded": true|false, "issues": ["..."]} — issues only for '
        "genuine fabrications or contradictions."
    )
    return complete_structured(
        [{"role": "user", "content": prompt}],
        GroundingVerdict,
        tier="strong",
        prompt_version=GROUNDING_PROMPT_VERSION,
    )


def check_grounding(decision, *, research, memory, portfolio, judge=None) -> GroundingResult:
    """Judge whether ``decision``'s claims are grounded in the provided context."""
    judge = judge or _default_judge
    context = {"portfolio": portfolio, "market_context": research, "memory": memory}
    try:
        verdict = judge(decision, context)
    except Exception as exc:  # never fail a run on a grounding-infra hiccup
        logger.warning("Grounding check unavailable — continuing: %s", exc)
        return GroundingResult(status="unavailable", grounded=True, issues=[])

    if verdict.grounded:
        return GroundingResult(status="ok", grounded=True, issues=list(verdict.issues))
    logger.warning("Decision grounding flagged issues: %s", verdict.issues)
    return GroundingResult(status="flagged", grounded=False, issues=list(verdict.issues))
