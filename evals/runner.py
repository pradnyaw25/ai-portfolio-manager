"""Run the decision eval harness and gate on the results.

``python -m evals.runner`` runs the real agent against every golden scenario,
scores each decision, persists a per-run result (with model + prompt version),
and exits non-zero if any scenario fails — so it can gate prompt/schema changes
in CI. Tests inject a fake ``decide_fn``/``judge_fn`` to run without an API key.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime

from evals import grounding
from evals.scenarios import SCENARIOS
from evals.scorers import DETERMINISTIC_SCORERS, ScoreResult
from src.agents.debate import run_debate
from src.agents.portfolio_manager import PROMPT_VERSION, PortfolioManagerAgent
from src.config import DATA_DIR, LLM_STRONG_MODEL, validate_config
from src.utils.logger import get_logger

logger = get_logger(__name__)

EVAL_RESULTS_LOG = DATA_DIR / "eval_results.jsonl"


def default_decide(scenario):
    if getattr(scenario, "expects_debate", False):
        return run_debate(
            scenario.portfolio,
            scenario.research,
            scenario.benchmark,
            scenario.memory,
        )
    return PortfolioManagerAgent().decide(
        portfolio=scenario.portfolio,
        research=scenario.research,
        benchmark=scenario.benchmark,
        memory=scenario.memory,
    )


def run_evals(
    *,
    decide_fn=None,
    judge_fn=None,
    scenarios=SCENARIOS,
    use_grounding: bool = True,
    timestamp: str | None = None,
) -> dict:
    decide_fn = decide_fn or default_decide
    results = []

    for scenario in scenarios:
        try:
            decision = decide_fn(scenario)
        except Exception as exc:
            # A broken prompt/schema that fails to produce a valid decision fails here.
            results.append(
                {
                    "scenario": scenario.name,
                    "passed": False,
                    "scores": [asdict(ScoreResult("decide", False, str(exc)))],
                }
            )
            continue

        deterministic = [scorer(decision, scenario) for scorer in DETERMINISTIC_SCORERS]
        scores = list(deterministic)
        if use_grounding:
            # Grounding is an advisory signal (an LLM judge is inherently noisy), so
            # it is reported but does NOT gate — only the deterministic scorers do.
            scores.append(grounding.score_grounding(decision, scenario, judge=judge_fn))

        passed = all(s.passed for s in deterministic)
        results.append(
            {"scenario": scenario.name, "passed": passed, "scores": [asdict(s) for s in scores]}
        )

    return {
        "timestamp": timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "model": LLM_STRONG_MODEL,
        "prompt_version": PROMPT_VERSION,
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "results": results,
    }


def persist(summary: dict, *, path=EVAL_RESULTS_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(summary) + "\n")


def main() -> int:
    # Fail loudly on misconfiguration before spending API calls on the harness.
    validate_config()
    summary = run_evals()
    persist(summary)

    for result in summary["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        logger.info("[%s] %s", status, result["scenario"])
        for score in result["scores"]:
            if score["passed"]:
                continue
            # Grounding is advisory (does not gate); everything else is a hard failure.
            marker = "⚠ advisory" if score["name"] == "grounding" else "✗"
            logger.info("    %s %s: %s", marker, score["name"], score["detail"])

    passed, total = summary["passed"], summary["total"]
    print(
        f"\nDecision evals: {passed}/{total} scenarios passed "
        f"(model={summary['model']}, prompt={summary['prompt_version']})"
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
