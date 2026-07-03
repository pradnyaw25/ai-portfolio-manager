"""Aggregate per-run LLM cost/latency from the gateway's call log."""

import json
from pathlib import Path

from src.config import LLM_CALL_LOG


def _zero() -> dict:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": 0.0,
    }


def summarize_run_cost(run_id: str | None, *, path: Path | None = None) -> dict:
    """Sum tokens, cost, and latency across all LLM calls tagged with ``run_id``."""
    path = path or LLM_CALL_LOG
    summary = _zero()
    if run_id is None or not path.exists():
        return summary

    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("run_id") != run_id:
            continue
        summary["calls"] += 1
        summary["prompt_tokens"] += record.get("prompt_tokens", 0)
        summary["completion_tokens"] += record.get("completion_tokens", 0)
        summary["cost_usd"] += record.get("est_cost_usd", 0.0)
        summary["latency_ms"] += record.get("latency_ms", 0.0)

    summary["cost_usd"] = round(summary["cost_usd"], 6)
    summary["latency_ms"] = round(summary["latency_ms"], 1)
    return summary
