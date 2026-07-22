from src.models.run_state import PortfolioRunState
from src.workflows import daily_graph
from src.workflows.daily_graph import build_daily_cycle_graph, create_initial_state


def test_create_initial_state_has_typed_run_state():
    state = create_initial_state()

    assert isinstance(state["run"], PortfolioRunState)
    assert state["run"].run_id.startswith("run_")
    assert state["run"].started_at.endswith("Z")


def test_daily_cycle_graph_compiles():
    graph = build_daily_cycle_graph()

    assert graph is not None


def test_daily_cycle_graph_routes_failures_to_run_status(monkeypatch):
    exported = []

    def fail_load_portfolio():
        raise RuntimeError("portfolio store unavailable")

    monkeypatch.setattr(daily_graph.steps, "load_portfolio", fail_load_portfolio)
    monkeypatch.setattr(
        daily_graph.steps,
        "export_run_status",
        lambda status: exported.append(status),
    )

    result = build_daily_cycle_graph().invoke(create_initial_state())
    run = result["run"]

    assert run.failed_step == "load_portfolio"
    assert run.errors == ["load_portfolio: portfolio store unavailable"]
    assert run.run_status["status"] == "failed"
    assert run.run_status["failed_step"] == "load_portfolio"
    assert exported == [run.run_status]


def test_publish_receipts_node_publishes_when_predictions_resolved(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_graph.steps,
        "publish_receipts_tweet",
        lambda scored, run_id, run_status: calls.append((scored, run_id)),
    )
    run = PortfolioRunState(run_id="run_x", started_at="2026-07-22T00:00:00Z")
    run.scored_predictions = [{"symbol": "AAPL", "result": {"correct": True}}]

    daily_graph.publish_receipts_tweet_node({"run": run})

    assert len(calls) == 1
    assert calls[0][1] == "run_x"


def test_publish_receipts_node_still_calls_step_with_empty_list(monkeypatch):
    # The step itself no-ops on an empty list; the node always delegates.
    calls = []
    monkeypatch.setattr(
        daily_graph.steps,
        "publish_receipts_tweet",
        lambda scored, run_id, run_status: calls.append(scored),
    )
    run = PortfolioRunState(run_id="run_y", started_at="2026-07-22T00:00:00Z")

    daily_graph.publish_receipts_tweet_node({"run": run})

    assert calls == [[]]


def test_publish_receipts_node_skips_on_resume_when_already_published(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_graph.steps,
        "publish_receipts_tweet",
        lambda *a, **k: calls.append(a),
    )

    class DoneProgress:
        def phase_done(self, run_id, phase):
            return phase == "publish_receipts"

    run = PortfolioRunState(run_id="run_z", started_at="2026-07-22T00:00:00Z")
    run.resumed = True
    run.progress = DoneProgress()
    run.scored_predictions = [{"symbol": "AAPL", "result": {"correct": True}}]

    daily_graph.publish_receipts_tweet_node({"run": run})

    assert calls == []  # skipped, no repost
    assert "skipped on resume" in run.diagnostics["receipts"]
