"""Ambient run context for attributing LLM calls to a daily run.

The daily cycle sets the current ``run_id`` once at the start; the gateway reads
it when logging each call, so per-run cost/latency can be aggregated without
threading ``run_id`` through every agent signature. Nodes run in the main thread
(sequential graph), so the contextvar propagates into gateway calls.
"""

import contextvars

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)


def set_run_id(run_id: str | None) -> None:
    _run_id.set(run_id)


def get_run_id() -> str | None:
    return _run_id.get()
