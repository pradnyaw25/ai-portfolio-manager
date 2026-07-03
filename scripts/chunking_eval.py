#!/usr/bin/env python3
"""Run the chunked-vs-unchunked retrieval eval and print the before/after delta.

Offline and deterministic (in-memory Qdrant + hashing embedder), so it runs in CI
with no API key. Exits non-zero if chunking fails to improve retrieval — a guard
against regressions in the chunker or retriever.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DATA_DIR
from src.memory.retrieval_eval import load_chunking_scenarios, run_chunking_eval

DEFAULT_FIXTURE = Path("tests/fixtures/memory_evals/chunking_scenarios.json")
DEFAULT_OUTPUT = DATA_DIR / "chunking_eval_latest.json"


def main() -> int:
    args = parse_args()
    scenarios = load_chunking_scenarios(args.fixture)
    result = run_chunking_eval(scenarios, k=args.k)
    payload = {"fixture": str(args.fixture), **result.to_dict()}

    print(json.dumps(payload, indent=2))
    print(
        f"\nRetrieval eval over {result.chunked.num_scenarios} scenarios (k={result.k}):\n"
        f"  unchunked  hit@1={result.unchunked.hit_at_1:.2f}  "
        f"MRR={result.unchunked.mrr:.3f}  recall@{result.k}={result.unchunked.recall_at_k:.2f}\n"
        f"  chunked    hit@1={result.chunked.hit_at_1:.2f}  "
        f"MRR={result.chunked.mrr:.3f}  recall@{result.k}={result.chunked.recall_at_k:.2f}\n"
        f"  improvement hit@1={result.improvement['hit_at_1']:+.2f}  "
        f"MRR={result.improvement['mrr']:+.3f}  "
        f"recall={result.improvement['recall_at_k']:+.2f}"
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))

    # Chunking must strictly improve ranking; otherwise fail the gate.
    return 0 if result.improvement["mrr"] > 0 else 1


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("-k", type=int, default=5, help="Top-k results to score.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-output", action="store_const", const=None, dest="output",
        help="Only print the result.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
