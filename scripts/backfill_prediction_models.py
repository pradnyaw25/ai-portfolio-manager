#!/usr/bin/env python3
"""Tag historical predictions with the model that made them.

Predictions started carrying a ``model`` field on 2026-08-08, when the fund moved
from ``gpt-4.1-mini`` to the gpt-5.6 family. Everything recorded before that is
untagged, which would make the before/after calibration comparison impossible —
the whole point of tagging.

The model is recovered from ``data/llm_calls.jsonl`` rather than inferred from the
config history: the gateway logs the *served* model per call with the run_id, so a
prediction's run_id maps to whichever model actually produced that decision. That
survives fallbacks and mid-period config changes, which a date-range guess would not.

Predictions whose run_id has no logged portfolio-manager call are left ``null``.
They are the earliest runs, before the call log existed. Guessing a model for them
from the config timeline would put unverified data into the calibration record,
which is exactly the kind of thing this project exists not to do.

Idempotent: re-running only fills rows that are still missing a model.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DATA_DIR

PREDICTIONS = DATA_DIR / "predictions.jsonl"
CALL_LOG = DATA_DIR / "llm_calls.jsonl"


def served_models(call_log: Path) -> dict[str, str]:
    """run_id -> the model that served that run's portfolio-manager call."""
    served: dict[str, str] = {}
    if not call_log.exists():
        return served
    for line in call_log.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("prompt_version", "")).startswith("portfolio_manager"):
            run_id, model = row.get("run_id"), row.get("model")
            if run_id and model:
                served[run_id] = model
    return served


def backfill(rows: list[dict], served: dict[str, str]) -> tuple[list[dict], Counter]:
    stats: Counter = Counter()
    for row in rows:
        if row.get("model"):
            stats["already tagged"] += 1
            continue
        model = served.get(row.get("run_id"))
        if model:
            row["model"] = model
            stats[f"tagged {model}"] += 1
        else:
            row.setdefault("model", None)
            stats["left null (no logged call)"] += 1
    return rows, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    args = parser.parse_args(argv)

    if not PREDICTIONS.exists():
        print("no predictions file", file=sys.stderr)
        return 1

    rows = [json.loads(line) for line in PREDICTIONS.read_text().splitlines() if line.strip()]
    served = served_models(CALL_LOG)
    rows, stats = backfill(rows, served)

    print(f"{len(rows)} predictions, {len(served)} runs resolvable from the call log")
    for key, count in sorted(stats.items()):
        print(f"  {key}: {count}")

    if not args.apply:
        print("\ndry run — pass --apply to write")
        return 0

    with open(PREDICTIONS, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    print(f"\nwrote {PREDICTIONS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
