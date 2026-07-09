"""Ablation variants for the machinery-value harness (roadmap V1-1).

The baselines (``baselines.py``) answer "does the fund beat the market / a
monkey?". Ablations answer the deeper question: does the *machinery* — retrieved
memory and the bull/bear/risk debate — actually improve the decision, or is it
theater? Each variant runs the SAME golden scenarios through the SAME decision
code with one component switched off; a fixed judge then grades every resulting
decision, so the score reflects the ablated component, not the grader.

This module is pure wiring + aggregation (no I/O, no file writes) so it stays
unit-testable; the scenario run loop, LLM cost accounting, and file output live in
``scripts/compare_ablations.py``.

Scope note (kept honest on the dashboard/writeup): the *tools* ablation ("no
tool-calling research") is NOT measurable here — the eval scenarios carry
pre-baked research as a fixed input, so there are no tools to remove. Measuring it
needs the live pipeline / a replay harness (roadmap V1-6). Only memory and debate
are ablatable on the eval path.
"""

from src.agents.debate import run_debate
from src.agents.portfolio_manager import PortfolioManagerAgent


# Each variant toggles memory and/or the debate. ``full`` is the live fund config;
# every other variant removes exactly one component so the delta is attributable.
ABLATION_VARIANTS = [
    {
        "key": "full",
        "name": "Full system",
        "use_memory": True,
        "use_debate": True,
        "detail": "retrieved memory + bull/bear/risk debate — the live fund",
    },
    {
        "key": "no_memory",
        "name": "No memory",
        "use_memory": False,
        "use_debate": True,
        "detail": "retrieval disabled — the PM cannot cite prior theses or filings",
    },
    {
        "key": "no_debate",
        "name": "No debate",
        "use_memory": True,
        "use_debate": False,
        "detail": "single-shot PM — no bull/bear/risk argument before the call",
    },
]


def make_decide(*, use_memory: bool, use_debate: bool):
    """Return a ``decide(scenario)`` matching ``evals.runner.default_decide`` but
    with memory and/or the debate switched off.

    - ``use_memory=False`` strips the scenario's memory so the PM decides blind to
      retrieval (it can no longer ground a view in a prior thesis or filing).
    - ``use_debate=False`` forces the single-shot PM path even for scenarios that
      would otherwise run the full debate.
    """

    def decide(scenario):
        memory = scenario.memory if use_memory else []
        if use_debate and getattr(scenario, "expects_debate", False):
            return run_debate(
                scenario.portfolio,
                scenario.research,
                scenario.benchmark,
                memory,
            )
        return PortfolioManagerAgent().decide(
            portfolio=scenario.portfolio,
            research=scenario.research,
            benchmark=scenario.benchmark,
            memory=memory,
        )

    return decide


def build_ablation_payload(results: list[dict], *, generated_at: str, judge_model: str, scenarios: int) -> dict:
    """Assemble the published payload from per-variant metric dicts.

    Each ``results`` entry must carry at least ``key``, ``name``, ``detail``,
    ``pass_rate`` and ``quality_mean``. The ``full`` variant is the reference; every
    other variant gets a ``quality_delta`` (its quality minus full's). A negative
    delta means removing that component *hurt* decision quality — i.e. the component
    earns its keep on this eval set.
    """
    full = next((r for r in results if r["key"] == "full"), None)
    base_quality = full["quality_mean"] if full else None

    variants = []
    for r in results:
        v = dict(r)
        if base_quality is None or r["key"] == "full":
            v["quality_delta"] = None
        else:
            v["quality_delta"] = round(r["quality_mean"] - base_quality, 3)
        variants.append(v)

    return {
        "generated_at": generated_at,
        "judge_model": judge_model,
        "scenarios": scenarios,
        "variants": variants,
    }
