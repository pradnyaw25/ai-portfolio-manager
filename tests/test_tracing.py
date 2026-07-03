"""Tracing must be a safe no-op when disabled and never propagate Langfuse errors."""

from src import config
from src.observability import tracing


# -- disabled (default) ------------------------------------------------------


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(config, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(config, "LANGFUSE_SECRET_KEY", "")
    tracing._reset_for_tests()

    assert tracing.tracing_enabled() is False
    with tracing.trace_run("run_1"):
        with tracing.span("decide_trades"):
            pass
    # No client, so this is a no-op and must not raise.
    tracing.record_generation(
        name="v1", model="gpt-4o-mini", input=[], output="", prompt_tokens=1,
        completion_tokens=1, cost=0.0, latency_ms=1.0,
    )


# -- enabled with a fake client ---------------------------------------------


class _FakeObservationCM:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        self._calls.append("enter")
        return self

    def __exit__(self, *exc):
        self._calls.append("exit")
        return False


class _FakeGeneration:
    def __init__(self, calls):
        self._calls = calls

    def end(self):
        self._calls.append("gen_end")


class _FakeClient:
    def __init__(self):
        self.calls = []

    def start_as_current_observation(self, **kwargs):
        self.calls.append(("span", kwargs.get("name")))
        return _FakeObservationCM(self.calls)

    def start_observation(self, **kwargs):
        self.calls.append(("generation", kwargs.get("name"), kwargs.get("cost_details")))
        return _FakeGeneration(self.calls)

    def flush(self):
        self.calls.append("flush")


def test_span_and_generation_hit_the_client(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(tracing, "_client_or_none", lambda: client)

    with tracing.trace_run("run_1"):
        with tracing.span("decide_trades"):
            pass
        tracing.record_generation(
            name="pm/v1", model="gpt-4o-mini", input=[{"role": "user"}], output="{}",
            prompt_tokens=100, completion_tokens=20, cost=0.0012, latency_ms=500.0,
        )

    names = [c for c in client.calls if isinstance(c, tuple)]
    assert ("span", "daily_cycle") in names
    assert ("span", "decide_trades") in names
    assert ("generation", "pm/v1", {"total": 0.0012}) in names
    assert "gen_end" in client.calls
    assert "flush" in client.calls  # trace_run flushes on exit


def test_client_errors_never_propagate(monkeypatch):
    class _Boom:
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("langfuse down")

        def start_observation(self, **kwargs):
            raise RuntimeError("langfuse down")

        def flush(self):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(tracing, "_client_or_none", lambda: _Boom())

    # None of these should raise despite the client blowing up.
    with tracing.trace_run("run_1"):
        with tracing.span("node"):
            pass
    tracing.record_generation(
        name="v1", model="m", input=[], output="", prompt_tokens=1,
        completion_tokens=1, cost=0.0, latency_ms=1.0,
    )
