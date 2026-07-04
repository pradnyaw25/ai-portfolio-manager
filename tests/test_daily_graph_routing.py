"""P1-2: conditional routing — skip execution when there are no trades, and
record diagnostics for the branch conditions."""

from types import SimpleNamespace

from src import config
from src.workflows import daily_graph
from src.workflows.daily_graph import (
    build_daily_cycle_graph,
    create_initial_state,
    route_after_rebalance,
)


def _mock_cycle(monkeypatch, *, approved, decision_trades=None, memory_status="ok"):
    """Mock every step so the compiled graph runs end to end in-memory."""
    # Force "market open" so the execution gate doesn't interfere with routing tests.
    monkeypatch.setattr(daily_graph, "is_regular_market_hours", lambda: True)
    snap = SimpleNamespace(total_value=1_000_000.0, cash_pct=0.1)
    engine = SimpleNamespace(get_snapshot=lambda: snap)
    memres = SimpleNamespace(status=memory_status, error=None)
    ingestion = SimpleNamespace(status="ok", errors=[], to_dict=lambda: {"status": "ok"})
    calls: list[str] = []

    def record(name, ret):
        def fn(*args, **kwargs):
            calls.append(name)
            return ret
        return fn

    returns = {
        "load_portfolio": ("p", "t", engine),
        "create_clients": ("m", "n", "b"),
        "mark_to_market_and_score_predictions": None,
        "build_research_context": ({}, {}),
        "retrieve_memory_context": (memres, [], {}),
        "run_research_followup": {"brief": "b", "tool_calls": []},
        "decide_trades": {"trades": decision_trades or []},
        "run_grounding_check": {"status": "ok", "grounded": True, "issues": []},
        "review_risk": SimpleNamespace(approved=approved),
        "check_rebalance": (SimpleNamespace(), list(approved)),
        "execute_trades": [SimpleNamespace(symbol="AAPL")],
        "track_buy_predictions": None,
        "journal_run": None,
        "save_portfolio_and_performance": None,
        "generate_report_and_tweet": ("# report", "tweet"),
        "build_run_status": {"status": "success", "warnings": []},
        "export_public_artifacts": None,
        "publish_tweet": SimpleNamespace(),
        "update_tweet_publish_status": None,
        "ingest_run_memory": ingestion,
        "export_run_status": None,
    }
    for name, ret in returns.items():
        monkeypatch.setattr(daily_graph.steps, name, record(name, ret))
    return calls


def test_route_after_rebalance_branches(monkeypatch):
    monkeypatch.setattr(daily_graph, "is_regular_market_hours", lambda: True)
    assert route_after_rebalance({"run": SimpleNamespace(errors=["x"], approved_trades=[])}) == "failed"
    skip_state = SimpleNamespace(errors=[], approved_trades=[], diagnostics={})
    assert route_after_rebalance({"run": skip_state}) == "skip_execution"
    assert skip_state.diagnostics["execution"].startswith("skipped")
    go = SimpleNamespace(errors=[], approved_trades=["A"], diagnostics={})
    assert route_after_rebalance({"run": go}) == "execute"


def test_route_skips_execution_when_market_closed(monkeypatch):
    monkeypatch.setattr(config, "EXECUTE_OUTSIDE_MARKET_HOURS", False)
    monkeypatch.setattr(daily_graph, "is_regular_market_hours", lambda: False)
    state = SimpleNamespace(errors=[], approved_trades=["A", "B"], diagnostics={})
    assert route_after_rebalance({"run": state}) == "skip_execution"
    assert "market closed" in state.diagnostics["execution"]


def test_route_executes_when_market_closed_but_overridden(monkeypatch):
    monkeypatch.setattr(config, "EXECUTE_OUTSIDE_MARKET_HOURS", True)
    monkeypatch.setattr(daily_graph, "is_regular_market_hours", lambda: False)
    state = SimpleNamespace(errors=[], approved_trades=["A"], diagnostics={})
    assert route_after_rebalance({"run": state}) == "execute"


def test_no_approved_trades_skips_execution_but_still_exports(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", True)
    calls = _mock_cycle(monkeypatch, approved=[])

    run = build_daily_cycle_graph().invoke(create_initial_state())["run"]

    assert not run.errors
    assert "execute_trades" not in calls
    assert "track_buy_predictions" not in calls
    assert "journal_run" in calls  # rejoined the tail
    assert run.run_status["status"] == "success"
    assert run.diagnostics["execution"].startswith("skipped")
    assert run.run_status["diagnostics"]["execution"].startswith("skipped")


def test_approved_trades_run_through_execution(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", True)
    calls = _mock_cycle(monkeypatch, approved=["A", "B"])

    run = build_daily_cycle_graph().invoke(create_initial_state())["run"]

    assert "execute_trades" in calls and "track_buy_predictions" in calls
    assert "execution" not in run.diagnostics


def test_empty_decision_and_memory_unavailable_are_diagnosed(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", True)
    _mock_cycle(monkeypatch, approved=[], decision_trades=[], memory_status="unavailable")

    run = build_daily_cycle_graph().invoke(create_initial_state())["run"]

    assert run.diagnostics["decision"].startswith("empty")
    assert run.diagnostics["memory"].startswith("unavailable")
    assert run.run_status["diagnostics"]["memory"].startswith("unavailable")
