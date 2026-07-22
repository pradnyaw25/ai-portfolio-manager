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


def test_publish_receipts_node_publishes_on_the_morning_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_graph.steps,
        "publish_receipts_tweet",
        lambda scored, run_id, run_status: calls.append((scored, run_id)),
    )
    # 14:47 UTC — the morning run.
    run = PortfolioRunState(run_id="run_x", started_at="2026-07-22T14:47:00Z")
    run.scored_predictions = [{"symbol": "AAPL", "result": {"correct": True}}]

    daily_graph.publish_receipts_tweet_node({"run": run})

    assert len(calls) == 1
    assert calls[0][1] == "run_x"


def test_publish_receipts_node_skips_on_the_afternoon_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_graph.steps,
        "publish_receipts_tweet",
        lambda *a, **k: calls.append(a),
    )
    # 19:47 UTC — the afternoon run; receipts post on the morning run only.
    run = PortfolioRunState(run_id="run_pm", started_at="2026-07-22T19:47:00Z")
    run.scored_predictions = [{"symbol": "AAPL", "result": {"correct": True}}]

    daily_graph.publish_receipts_tweet_node({"run": run})

    assert calls == []
    assert "morning run only" in run.diagnostics["receipts"]


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


def test_is_morning_run_splits_the_two_daily_runs():
    # Daily cycle runs at 14:47 and 19:47 UTC; cutoff hour 17 separates them.
    assert daily_graph._is_morning_run("2026-07-22T14:47:00Z") is True
    assert daily_graph._is_morning_run("2026-07-22T19:47:00Z") is False
    # Unparseable timestamps default to morning (never silently drop receipts).
    assert daily_graph._is_morning_run("not-a-date") is True


def test_publish_spotlight_node_publishes_on_the_afternoon_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_graph.steps,
        "publish_spotlight_tweet",
        lambda decisions, research, forward, run_id, run_status: calls.append(run_id),
    )
    run = PortfolioRunState(run_id="run_pm", started_at="2026-07-22T19:47:00Z")
    run.decisions = {"market_calls": [{"symbol": "MU", "confidence": 0.7}]}

    daily_graph.publish_spotlight_tweet_node({"run": run})

    assert calls == ["run_pm"]


def test_publish_spotlight_node_skips_on_the_morning_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_graph.steps, "publish_spotlight_tweet", lambda *a, **k: calls.append(a)
    )
    run = PortfolioRunState(run_id="run_am", started_at="2026-07-22T14:47:00Z")
    run.decisions = {"market_calls": [{"symbol": "MU", "confidence": 0.7}]}

    daily_graph.publish_spotlight_tweet_node({"run": run})

    assert calls == []
    assert "afternoon run" in run.diagnostics["spotlight"]
