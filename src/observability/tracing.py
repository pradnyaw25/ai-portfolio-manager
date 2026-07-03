"""Optional Langfuse tracing.

Enabled only when ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set.
When disabled (the default, and always in CI/tests), every entry point here is a
cheap no-op. Every Langfuse call is wrapped so a tracing failure never breaks a
daily run — observability is best-effort.

Usage:
    with tracing.trace_run(run_id):      # one root span (the trace) per run
        ...
        with tracing.span("decide_trades"):   # a child span per graph node
            ...
    tracing.record_generation(...)       # an LLM generation under the current span
"""

import contextlib

from src import config
from src.utils.logger import get_logger

logger = get_logger(__name__)

_client = None
_resolved = False


def _client_or_none():
    """Lazily construct the Langfuse client once; return None when disabled."""
    global _client, _resolved
    if _resolved:
        return _client
    _resolved = True

    if not (config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY):
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            host=config.LANGFUSE_HOST,
        )
        logger.info("Langfuse tracing enabled (host=%s)", config.LANGFUSE_HOST)
    except Exception as exc:  # missing package, bad config, etc.
        logger.warning("Langfuse unavailable — tracing disabled: %s", exc)
        _client = None
    return _client


def tracing_enabled() -> bool:
    return _client_or_none() is not None


def _reset_for_tests() -> None:
    """Force re-resolution of the client (used by tests that toggle config)."""
    global _client, _resolved
    _client = None
    _resolved = False


@contextlib.contextmanager
def _observation(name: str, metadata: dict | None = None):
    """A best-effort ``span`` observation; passthrough when tracing is disabled."""
    client = _client_or_none()
    if client is None:
        yield
        return

    cm = None
    try:
        cm = client.start_as_current_observation(name=name, as_type="span", metadata=metadata)
        cm.__enter__()
    except Exception as exc:
        logger.debug("Langfuse span '%s' failed to start: %s", name, exc)
        cm = None
    try:
        yield
    finally:
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception as exc:
                logger.debug("Langfuse span '%s' failed to close: %s", name, exc)


def span(name: str, **metadata):
    """Context manager for a child span (e.g. a graph node)."""
    return _observation(name, metadata or None)


@contextlib.contextmanager
def trace_run(run_id: str):
    """Root span for a whole daily run; flushes on exit."""
    client = _client_or_none()
    if client is None:
        yield
        return
    try:
        with _observation("daily_cycle", {"run_id": run_id}):
            yield
    finally:
        try:
            client.flush()
        except Exception as exc:
            logger.debug("Langfuse flush failed: %s", exc)


def record_generation(
    *,
    name: str,
    model: str,
    input,
    output,
    prompt_tokens: int,
    completion_tokens: int,
    cost: float,
    latency_ms: float,
) -> None:
    """Record one LLM generation under the current span. No-op when disabled."""
    client = _client_or_none()
    if client is None:
        return
    try:
        observation = client.start_observation(
            name=name,
            as_type="generation",
            model=model,
            input=input,
            output=output,
            usage_details={"input": prompt_tokens, "output": completion_tokens},
            cost_details={"total": cost},
            metadata={"latency_ms": latency_ms},
        )
        observation.end()
    except Exception as exc:
        logger.debug("Langfuse generation '%s' failed: %s", name, exc)
