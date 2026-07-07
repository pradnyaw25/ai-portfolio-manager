"""Rubric-based decision-quality scoring for the model-comparison harness.

The deterministic eval scorers gate on *structural* correctness (schema, risk
compliance, citations) — which even a cheap model already passes, so they can't
separate models on the *substance* of a decision. This module adds an
LLM-as-judge that grades a decision on a small rubric (reasoning, specificity,
risk-awareness).

In the comparison harness (`scripts/compare_strong_model.py`) the judge model is
held **constant** while the decision-maker's model varies, so the score isolates
the decision-maker rather than the grader. The judge is injectable so tests run
offline.
"""

import json

from pydantic import BaseModel, Field

from src.llm import complete_structured

QUALITY_PROMPT_VERSION = "decision_quality/v1"


class DecisionQuality(BaseModel):
    """A 1–5 rubric score for a portfolio decision's reasoning (not its outcome)."""

    reasoning: int = Field(ge=1, le=5)  # is the rationale sound and evidence-based?
    specificity: int = Field(ge=1, le=5)  # concrete + grounded in THIS context, not boilerplate?
    risk_awareness: int = Field(ge=1, le=5)  # weighs downside / concentration / guardrails?
    notes: str = ""

    @property
    def overall(self) -> float:
        return round((self.reasoning + self.specificity + self.risk_awareness) / 3, 3)


QUALITY_INSTRUCTIONS = (
    "You are grading the QUALITY of an AI portfolio manager's decision against the "
    "CONTEXT it was given. Grade the reasoning, NOT the outcome — you are not judging "
    "whether the trades will be profitable. Score three dimensions from 1 (poor) to 5 "
    "(excellent):\n"
    "- reasoning: is the rationale logically sound and tied to the evidence in context?\n"
    "- specificity: is it concrete and grounded in THIS context's numbers/news/memory, "
    "or generic boilerplate that could apply to any day?\n"
    "- risk_awareness: does it weigh downside, concentration, the cash target, and the "
    "stated risks rather than ignoring them?\n"
    "Be discerning: reserve 5 for genuinely strong work and give 1–2 for vague or "
    "unsupported reasoning. Put a brief justification in notes.\n\n"
)


def _default_judge(decision: dict, context: dict) -> DecisionQuality:
    prompt = (
        f"{QUALITY_INSTRUCTIONS}"
        f"CONTEXT:\n{json.dumps(context, default=str)}\n\n"
        f"DECISION:\n{json.dumps(decision, default=str)}\n\n"
        'Return JSON: {"reasoning": 1-5, "specificity": 1-5, "risk_awareness": 1-5, '
        '"notes": "..."}.'
    )
    return complete_structured(
        [{"role": "user", "content": prompt}],
        DecisionQuality,
        tier="strong",
        prompt_version=QUALITY_PROMPT_VERSION,
    )


def score_decision_quality(decision: dict, context: dict, *, judge=None) -> DecisionQuality:
    """Grade ``decision`` against ``context`` on the quality rubric.

    ``judge`` is injectable (defaults to an LLM judge on the ``strong`` tier). The
    caller pins the judge model by setting the strong-tier config before calling, so
    a comparison can hold the grader constant while varying the decision-maker.
    """
    judge = judge or _default_judge
    return judge(decision, context)
