#!/usr/bin/env python3
"""Compare LLM strong-tier models on the decision eval set (roadmap V1-2).

The system routes "strong" (portfolio-manager synthesis, judges) and "cheap"
(analysts, summaries) tiers to separate models. Historically both defaulted to
``gpt-4o-mini`` — so every agent was the same cheap model in a different hat. This
harness measures whether promoting the *strong* tier to a frontier model is worth
it, with data instead of vibes.

For each candidate strong-tier model it runs the golden eval scenarios through the
portfolio manager (analysts stay on the cheap tier), holding the prompt, scenarios,
and temperature constant, and measures:

  * pass_rate  — structural deterministic scorers (judge-free)
  * quality    — mean rubric score from a SINGLE fixed judge model, so only the
                 decision-maker's model varies (src/scoring/decision_quality.py)
  * cost / latency — from the gateway's per-call log, isolated per candidate by run_id

Prints a comparison table and writes data/model_comparison.json. Needs OPENAI_API_KEY.

    make eval-compare
    python scripts/compare_strong_model.py --candidates gpt-4o-mini,gpt-4o --judge gpt-4o
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.runner import default_decide
from evals.scenarios import SCENARIOS
from evals.scorers import DETERMINISTIC_SCORERS
from src import config
from src.config import DATA_DIR, validate_config
from src.llm.context import set_run_id
from src.llm.cost import summarize_run_cost
from src.scoring.decision_quality import score_decision_quality
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_CANDIDATES = ["gpt-4o-mini", "gpt-4o"]
DEFAULT_JUDGE = "gpt-4o"
COMPARISON_OUTPUT = DATA_DIR / "model_comparison.json"


def _context_for(scenario) -> dict:
    return {
        "portfolio": scenario.portfolio,
        "market_context": scenario.research,
        "benchmark": scenario.benchmark,
        "memory": scenario.memory,
    }


def _run_candidate(model: str, judge_model: str, stamp: str) -> dict:
    """Run every scenario under ``model``, grade each decision with the fixed
    ``judge_model``, and return per-candidate metrics. Restores config on exit."""
    original_strong = config.LLM_STRONG_MODEL

    # Phase 1 — decisions under the candidate model (analysts stay cheap).
    pm_run = f"cmp-pm-{model}-{stamp}"
    config.LLM_STRONG_MODEL = model
    decisions: list[tuple] = []
    passed = 0
    set_run_id(pm_run)
    try:
        for scenario in SCENARIOS:
            decision = default_decide(scenario)
            deterministic = [scorer(decision, scenario) for scorer in DETERMINISTIC_SCORERS]
            if all(s.passed for s in deterministic):
                passed += 1
            decisions.append((scenario, decision))
    finally:
        set_run_id(None)
    pm_cost = summarize_run_cost(pm_run)

    # Phase 2 — grade every decision with the SAME fixed judge, so the score
    # reflects the decision-maker, not the grader. Judge cost uses a separate
    # run_id and is excluded from the candidate's operational cost.
    judge_run = f"cmp-judge-{model}-{stamp}"
    config.LLM_STRONG_MODEL = judge_model
    qualities: list[float] = []
    set_run_id(judge_run)
    try:
        for scenario, decision in decisions:
            qualities.append(score_decision_quality(decision, _context_for(scenario)).overall)
    finally:
        set_run_id(None)
        config.LLM_STRONG_MODEL = original_strong

    n = len(decisions) or 1
    return {
        "model": model,
        "scenarios": len(decisions),
        "pass_rate": round(passed / n, 3),
        "quality_mean": round(sum(qualities) / n, 3),
        "cost_usd": round(pm_cost["cost_usd"], 6),
        "cost_per_scenario": round(pm_cost["cost_usd"] / n, 6),
        "latency_ms_per_scenario": round(pm_cost["latency_ms"] / n, 1),
        "calls": pm_cost["calls"],
    }


def _print_table(rows: list[dict], judge: str) -> None:
    headers = ["model", "pass_rate", "quality/5", "cost $", "$/scenario", "ms/scenario"]
    keys = ["model", "pass_rate", "quality_mean", "cost_usd", "cost_per_scenario", "latency_ms_per_scenario"]
    widths = [max(len(h), *(len(f"{r[k]}") for r in rows)) for h, k in zip(headers, keys)]

    def line(cells):
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))

    print(f"\nStrong-tier model comparison (fixed judge: {judge}, temp=0)\n")
    print(line(headers))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line([r[k] for k in keys]))

    if len(rows) >= 2:
        base, top = rows[0], rows[-1]
        dq = top["quality_mean"] - base["quality_mean"]
        dc = top["cost_usd"] - base["cost_usd"]
        print(
            f"\nDelta {base['model']} -> {top['model']}: "
            f"quality {dq:+.3f}/5, cost {dc:+.6f} $ "
            f"({'+' if dc >= 0 else ''}{(top['cost_usd'] / base['cost_usd'] - 1) * 100:.0f}%)"
            if base["cost_usd"]
            else f"\nDelta {base['model']} -> {top['model']}: quality {dq:+.3f}/5"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        default=",".join(DEFAULT_CANDIDATES),
        help="comma-separated strong-tier models to compare (cheapest first)",
    )
    parser.add_argument(
        "--judge", default=DEFAULT_JUDGE, help="fixed judge model used to grade every candidate"
    )
    args = parser.parse_args()

    validate_config()
    config.LLM_TEMPERATURE = 0.0  # deterministic decisions for a fair comparison

    candidates = [m.strip() for m in args.candidates.split(",") if m.strip()]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    rows = []
    for model in candidates:
        logger.info("Comparing strong-tier model: %s", model)
        try:
            rows.append(_run_candidate(model, args.judge, stamp))
        except Exception as exc:  # a model that's unavailable/errors shouldn't kill the run
            logger.warning("Skipping %s — comparison failed: %s", model, exc)

    if not rows:
        print("No candidates completed successfully.")
        return 1

    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "judge_model": args.judge,
        "scenarios": len(SCENARIOS),
        "results": rows,
    }
    COMPARISON_OUTPUT.write_text(json.dumps(payload, indent=2))

    _print_table(rows, args.judge)
    print(f"\nSaved {COMPARISON_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
