#!/usr/bin/env python3
"""Run offline memory retrieval evaluation fixtures."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DATA_DIR
from src.memory.evals import evaluate_memory_retrieval, load_memory_eval_scenarios
from src.memory.retriever import _filter_memories

DEFAULT_FIXTURE = Path("tests/fixtures/memory_evals/retrieval_scenarios.json")
DEFAULT_OUTPUT = DATA_DIR / "memory_eval_latest.json"


class FixtureMemoryRetriever:
    def __init__(self, documents: list[dict]):
        self.memories = [_normalize_memory(document) for document in documents]

    def retrieve_grouped(
        self,
        *,
        query: str,
        symbols: list[str] | None = None,
        k_per_group: int = 4,
    ) -> dict[str, list[dict]]:
        symbols = [symbol.upper() for symbol in symbols or []]
        return {
            "symbol_theses": _filter_memories(
                self.memories,
                memory_types={"thesis", "report_summary"},
                symbols=symbols,
                limit=k_per_group,
            ),
            "risk_lessons": _filter_memories(
                self.memories,
                memory_types={"risk_lesson", "mistake"},
                limit=k_per_group,
            ),
            "recent_trades": _filter_memories(
                self.memories,
                memory_types={"trade"},
                symbols=symbols,
                limit=k_per_group,
            ),
            "macro_context": _filter_memories(
                self.memories,
                memory_types={"macro_regime", "report_summary"},
                limit=k_per_group,
            ),
        }


def main() -> int:
    args = parse_args()
    scenarios = load_memory_eval_scenarios(args.fixture)
    result = evaluate_memory_retrieval(
        scenarios,
        retriever_factory=lambda scenario: FixtureMemoryRetriever(scenario.documents),
    )
    payload = {
        "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "fixture": str(args.fixture),
        **result.to_dict(),
    }
    print(json.dumps(payload, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    return 0 if result.passed else 1


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "fixture",
        nargs="?",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Memory eval fixture path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Write the latest eval summary for public memory health exports.",
    )
    parser.add_argument(
        "--no-output",
        action="store_const",
        const=None,
        dest="output",
        help="Only print the eval result.",
    )
    return parser.parse_args()


def _normalize_memory(document: dict) -> dict:
    symbols = document.get("symbols") or []
    return {
        "id": document.get("id"),
        "type": document.get("type") or document.get("memory_type"),
        "content": document.get("content", ""),
        "metadata": document,
        "symbols": [str(symbol).upper() for symbol in symbols],
        "date": document.get("date"),
        "source_type": document.get("source_type"),
        "source_id": document.get("source_id"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
