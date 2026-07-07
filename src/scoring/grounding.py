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
from typing import Literal

from pydantic import BaseModel, Field

from src.llm import complete_structured
from src.utils.logger import get_logger

logger = get_logger(__name__)

GROUNDING_PROMPT_VERSION = "grounding_check/v2"

Severity = Literal["none", "minor", "material"]


class GroundingVerdict(BaseModel):
    grounded: bool = True
    # "material" is the ONLY blocking level. Rounding/approximation/phrasing are
    # "minor" — recorded for transparency but never block publication.
    severity: Severity = "none"
    issues: list[str] = Field(default_factory=list)


@dataclass
class GroundingResult:
    status: str  # "ok" | "flagged" | "unavailable"
    grounded: bool
    severity: str = "none"
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "grounded": self.grounded,
            "severity": self.severity,
            "issues": self.issues,
        }


GROUNDING_INSTRUCTIONS = (
    "You are a grounding auditor for an AI portfolio manager. Given the CONTEXT the "
    "manager had and its DECISION, classify any factual problems by severity.\n\n"
    "severity = \"material\" ONLY for a genuine fabrication: a made-up price or event, a "
    "number with NO basis in the context, or a number that is MATERIALLY wrong (wrong "
    "sign/direction, or off by a large margin).\n"
    "severity = \"minor\" for harmless imprecision that does not mislead: rounding or "
    "approximation (e.g. the context says AAPL rose 4.84% and the decision says "
    "\"about 5%\" or \"roughly 5%\" — this is MINOR, not material), equivalent phrasing "
    "or units (0.12 vs \"12%\"), a rounded percentage (26.7% called \"26%\"), or "
    "subjective framing (\"relatively high\").\n"
    "severity = \"none\" when there are no problems. Opinions, outlooks, forecasts, and "
    "ordinary financial reasoning are never problems.\n\n"
    "Set grounded=false ONLY when severity is \"material\". Reasonable rounding must NEVER "
    "be material. When in doubt, choose the lower severity.\n"
    "List every noted problem (minor or material) in issues for transparency.\n\n"
)


def _default_judge(decision: dict, context: dict) -> GroundingVerdict:
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
        prompt_version=GROUNDING_PROMPT_VERSION,
    )


def check_grounding(decision, *, research, memory, portfolio, judge=None) -> GroundingResult:
    """Judge whether ``decision``'s claims are grounded. Only a *material* problem
    blocks publication; minor imprecisions (rounding, phrasing) are recorded but
    never block."""
    judge = judge or _default_judge
    context = {"portfolio": portfolio, "market_context": research, "memory": memory}
    try:
        verdict = judge(decision, context)
    except Exception as exc:  # never fail a run on a grounding-infra hiccup
        logger.warning("Grounding check unavailable — continuing: %s", exc)
        return GroundingResult(status="unavailable", grounded=True, issues=[])

    issues = list(verdict.issues)
    if verdict.severity == "material":
        logger.warning("Decision grounding flagged MATERIAL issue(s): %s", issues)
        return GroundingResult(status="flagged", grounded=False, severity="material", issues=issues)

    if issues:
        logger.info("Decision grounding noted minor issue(s) (non-blocking): %s", issues)
    return GroundingResult(status="ok", grounded=True, severity=verdict.severity, issues=issues)
