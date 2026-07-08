"""Full-cycle integration test for the LangGraph daily runner.

Mocks every side-effecting step function and drives the whole graph, asserting
the pipeline runs all nodes in order and threads state through to a success
run_status. This locks the graph's end-to-end behavior now that it is the sole
runner (the legacy linear runner in src/main.py was removed in P1-1).
"""

from types import SimpleNamespace

from src.workflows import daily_graph
from src.workflows.daily_graph import build_daily_cycle_graph, create_initial_state

EXPECTED_ORDER = [
    "load_portfolio",
    "create_clients",
    "mark_to_market",
    "build_research_context",
    "retrieve_memory",
    "research_followup",
    "decide_trades",
    "check_grounding",
    "review_risk",
    "check_rebalance",
    "execute_trades",
    "track_predictions",
    "journal_run",
    "save_portfolio",
    "generate_outputs",
    "build_run_status",
    "export_public_artifacts",
    "publish_tweet",
    "update_tweet_publish_status",
    "ingest_run_memory",
    "export_run_status",
]


def test_graph_runs_full_pipeline_in_order(monkeypatch):
    monkeypatch.setattr(daily_graph, "is_regular_market_hours", lambda: True)
    calls: list[str] = []

    def record(name, ret=None):
        def fn(*args, **kwargs):
            calls.append(name)
            return ret
        return fn

    snapshot = SimpleNamespace(total_value=1_000_000.0)
    engine = SimpleNamespace(get_snapshot=lambda: snapshot)
    trades = [SimpleNamespace(symbol="AAPL")]
    risk_review = SimpleNamespace(approved=[])
    memory_result = SimpleNamespace(status="ok", error=None)
    ingestion = SimpleNamespace(status="ok", errors=[], to_dict=lambda: {"status": "ok"})

    patches = {
        "load_portfolio": ("pstore", "tstore", engine),
        "create_clients": ("md", "news", "bench"),
        "mark_to_market_and_score_predictions": None,
        "build_research_context": ({"research": True}, {"AAPL": 200.0}),
        "retrieve_memory_context": (memory_result, [], {}),
        "run_research_followup": {"brief": "brief", "tool_calls": []},
        "decide_trades": {"trades": []},
        "run_grounding_check": {"status": "ok", "grounded": True, "issues": []},
        "review_risk": risk_review,
        # Non-empty approved trades so the graph routes through the execution path.
        "check_rebalance": (SimpleNamespace(), trades),
        "execute_trades": trades,
        "record_market_calls": None,
        "journal_run": None,
        "save_portfolio_and_performance": None,
        "generate_report_and_tweet": ("# report", "tweet text"),
        "build_run_status": {"status": "success", "warnings": []},
        "export_public_artifacts": None,
        "publish_tweet": SimpleNamespace(),
        "update_tweet_publish_status": None,
        "ingest_run_memory": ingestion,
        "export_run_status": None,
    }
    # Map the underlying step-function name to the label recorded in `calls`,
    # so the assertion reads in node terms.
    labels = {
        "mark_to_market_and_score_predictions": "mark_to_market",
        "retrieve_memory_context": "retrieve_memory",
        "run_research_followup": "research_followup",
        "run_grounding_check": "check_grounding",
        "check_rebalance": "check_rebalance",
        "record_market_calls": "track_predictions",
        "save_portfolio_and_performance": "save_portfolio",
        "generate_report_and_tweet": "generate_outputs",
    }
    for fn_name, ret in patches.items():
        label = labels.get(fn_name, fn_name)
        monkeypatch.setattr(daily_graph.steps, fn_name, record(label, ret))

    result = build_daily_cycle_graph().invoke(create_initial_state())
    run = result["run"]

    assert not run.errors
    assert run.run_status["status"] == "success"
    assert run.trades == trades
    assert calls == EXPECTED_ORDER
