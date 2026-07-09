#!/usr/bin/env python3
"""Ablation harness: does the machinery (memory, debate) earn its keep? (V1-1)

The baselines (``make baselines``) answer "does the fund beat the market / a
random monkey?". This answers the deeper question: does each piece of the *system*
improve the decision? It runs the SAME ablation scenarios through the SAME decision
code three ways —

    full        retrieved memory + bull/bear/risk debate (the live fund)
    no_memory   retrieval disabled
    no_debate   single-shot PM, no debate

— holding the decision model, prompt, scenarios, and temperature constant, and for
each measures:

  * pass_rate     — structural deterministic scorers (judge-free)
  * quality_mean  — mean rubric score from a SINGLE fixed judge model, so the score
                    reflects the ablated component, not the grader
  * quality_delta — quality minus the full system's (negative ⇒ removing that
                    component hurt, i.e. it earns its keep)
  * cost / scenario — from the gateway's per-call log, isolated per variant by run_id

Writes data/ablation_comparison.json and public/ablation_comparison.json (the
dashboard panel reads the public copy). Needs OPENAI_API_KEY.

    make eval-ablate
    python scripts/compare_ablations.py --judge gpt-4o
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.ablation_scenarios import ABLATION_SCENARIOS
from evals.scorers import DETERMINISTIC_SCORERS
from src import config
from src.config import DATA_DIR, validate_config
from src.experiments.ablations import ABLATION_VARIANTS, build_ablation_payload, make_decide
from src.llm.context import set_run_id
from src.llm.cost import summarize_run_cost
from src.scoring.decision_quality import score_decision_quality
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_JUDGE = "gpt-4o"
ABLATION_FILENAME = "ablation_comparison.json"
PUBLIC_DIR = Path(__file__).parent.parent / "public"


def _context_for(scenario) -> dict:
    return {
        "portfolio": scenario.portfolio,
        "market_context": scenario.research,
        "benchmark": scenario.benchmark,
        "memory": scenario.memory,
    }


def _run_variant(variant: dict, judge_model: str, stamp: str) -> dict:
    """Run every scenario under one ablation, grade each decision with the fixed
    judge, and return the variant's metrics. Restores config on exit."""
    original_strong = config.LLM_STRONG_MODEL
    decide = make_decide(use_memory=variant["use_memory"], use_debate=variant["use_debate"])

    # Phase 1 — decisions under this ablation (decision model unchanged).
    pm_run = f"abl-pm-{variant['key']}-{stamp}"
    decisions: list[tuple] = []
    passed = 0
    set_run_id(pm_run)
    try:
        for scenario in ABLATION_SCENARIOS:
            try:
                decision = decide(scenario)
            except Exception as exc:  # a single stalled/failed call shouldn't drop the variant
                logger.warning("  scenario %s failed under %s: %s", scenario.name, variant["key"], exc)
                continue
            deterministic = [scorer(decision, scenario) for scorer in DETERMINISTIC_SCORERS]
            if all(s.passed for s in deterministic):
                passed += 1
            decisions.append((scenario, decision))
    finally:
        set_run_id(None)
    pm_cost = summarize_run_cost(pm_run)

    # Phase 2 — grade with the SAME fixed judge so the score reflects the ablated
    # component, not the grader. Judge cost is on a separate run_id and excluded.
    judge_run = f"abl-judge-{variant['key']}-{stamp}"
    config.LLM_STRONG_MODEL = judge_model
    per_scenario: dict[str, float] = {}
    qualities: list[float] = []
    set_run_id(judge_run)
    try:
        for scenario, decision in decisions:
            try:
                q = score_decision_quality(decision, _context_for(scenario)).overall
            except Exception as exc:  # a failed judge call shouldn't drop the variant
                logger.warning("  judging %s failed under %s: %s", scenario.name, variant["key"], exc)
                continue
            per_scenario[scenario.name] = round(q, 3)
            qualities.append(q)
    finally:
        set_run_id(None)
        config.LLM_STRONG_MODEL = original_strong

    n_decided = len(decisions) or 1
    n_judged = len(qualities) or 1
    return {
        "key": variant["key"],
        "name": variant["name"],
        "detail": variant["detail"],
        "scenarios": len(decisions),
        "pass_rate": round(passed / n_decided, 3),
        "quality_mean": round(sum(qualities) / n_judged, 3),
        "cost_usd": round(pm_cost["cost_usd"], 6),
        "cost_per_scenario": round(pm_cost["cost_usd"] / n_decided, 6),
        "per_scenario": per_scenario,
    }


def _print_table(payload: dict) -> None:
    rows = payload["variants"]
    headers = ["variant", "pass_rate", "quality/5", "Δ vs full", "$/scenario"]
    keys = ["name", "pass_rate", "quality_mean", "quality_delta", "cost_per_scenario"]

    def cell(r, k):
        v = r.get(k)
        if k == "quality_delta":
            return "—" if v is None else f"{v:+.3f}"
        return "" if v is None else str(v)

    widths = [max(len(h), *(len(cell(r, k)) for r in rows)) for h, k in zip(headers, keys)]

    def line(cells):
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))

    print(f"\nAblation comparison (fixed judge: {payload['judge_model']}, temp=0, "
          f"{payload['scenarios']} scenarios)\n")
    print(line(headers))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line([cell(r, k) for k in keys]))

    # Plain-English read of each ablation's delta.
    print()
    for r in rows:
        if r["key"] == "full" or r.get("quality_delta") is None:
            continue
        d = r["quality_delta"]
        if d < -0.05:
            verdict = f"removing it HURT quality by {abs(d):.3f}/5 — it earns its keep"
        elif d > 0.05:
            verdict = f"removing it IMPROVED quality by {d:.3f}/5 — it may be net-negative here"
        else:
            verdict = f"no material change ({d:+.3f}/5) on this eval set"
        print(f"  {r['name']}: {verdict}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--judge", default=DEFAULT_JUDGE, help="fixed judge model used to grade every variant"
    )
    args = parser.parse_args()

    validate_config()
    config.LLM_TEMPERATURE = 0.0  # deterministic decisions for a fair comparison

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results = []
    for variant in ABLATION_VARIANTS:
        logger.info("Running ablation variant: %s", variant["key"])
        try:
            results.append(_run_variant(variant, args.judge, stamp))
        except Exception as exc:  # one broken variant shouldn't sink the rest
            logger.warning("Skipping %s — variant failed: %s", variant["key"], exc)

    if not results:
        print("No variants completed successfully.")
        return 1

    payload = build_ablation_payload(
        results,
        generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        judge_model=args.judge,
        scenarios=len(ABLATION_SCENARIOS),
    )

    body = json.dumps(payload, indent=2)
    (DATA_DIR / ABLATION_FILENAME).write_text(body)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / ABLATION_FILENAME).write_text(body)

    _print_table(payload)
    print(f"\nSaved {DATA_DIR / ABLATION_FILENAME} and {PUBLIC_DIR / ABLATION_FILENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
