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
    # 15:40 UTC — a morning run (cron 14:40 plus the usual scheduler delay).
    run = PortfolioRunState(run_id="run_x", started_at="2026-07-22T15:40:00Z")
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
    # 18:50 UTC — an afternoon run; receipts post on the morning run only.
    run = PortfolioRunState(run_id="run_pm", started_at="2026-07-22T18:50:00Z")
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
    # Runs start ~15:40-16:20 (morning) and ~18:50-19:30 (afternoon) after the
    # scheduler delay; cutoff hour 17 separates them across that whole spread.
    assert daily_graph._is_morning_run("2026-07-22T15:40:00Z") is True
    assert daily_graph._is_morning_run("2026-07-22T16:20:00Z") is True
    assert daily_graph._is_morning_run("2026-07-22T18:50:00Z") is False
    assert daily_graph._is_morning_run("2026-07-22T19:30:00Z") is False
    # Unparseable timestamps default to morning (never silently drop receipts).
    assert daily_graph._is_morning_run("not-a-date") is True


def test_publish_spotlight_node_publishes_on_the_afternoon_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_graph.steps,
        "publish_spotlight_tweet",
        lambda decisions, research, forward, run_id, run_status: calls.append(run_id),
    )
    run = PortfolioRunState(run_id="run_pm", started_at="2026-07-22T18:50:00Z")
    run.decisions = {"market_calls": [{"symbol": "MU", "confidence": 0.7}]}

    daily_graph.publish_spotlight_tweet_node({"run": run})

    assert calls == ["run_pm"]


def test_publish_spotlight_node_skips_on_the_morning_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        daily_graph.steps, "publish_spotlight_tweet", lambda *a, **k: calls.append(a)
    )
    run = PortfolioRunState(run_id="run_am", started_at="2026-07-22T15:40:00Z")
    run.decisions = {"market_calls": [{"symbol": "MU", "confidence": 0.7}]}

    daily_graph.publish_spotlight_tweet_node({"run": run})

    assert calls == []
    assert "afternoon run" in run.diagnostics["spotlight"]


# -- optional nodes ----------------------------------------------------------
#
# Regression cover for 2026-08-10: a 400 from the tool-calling research agent
# aborted the whole cycle, so the fund recorded no decision for the day. The
# research follow-up only augments the context, so its failure must degrade the
# run rather than end it.


def _raise(*args, **kwargs):
    raise RuntimeError("400 from the research agent")


def test_optional_node_failure_degrades_instead_of_aborting(monkeypatch):
    monkeypatch.setattr(daily_graph.steps, "run_research_followup", _raise)
    run = PortfolioRunState(run_id="run_opt", started_at="2026-08-10T15:40:00Z")

    node = daily_graph.guarded_node(
        "research_followup", daily_graph.research_followup_node, optional=True
    )
    result = node({"run": run})

    assert result["run"].errors == []
    assert result["run"].failed_step is None
    assert result["run"].warnings == ["research_followup: 400 from the research agent"]
    assert "degraded" in result["run"].diagnostics["research_followup"]
    # The cycle keeps going: no decision is lost to a failed enrichment.
    assert daily_graph.route_after_node({"run": result["run"]}) == "ok"


def test_optional_node_failure_leaves_the_phase_unmarked_for_resume(monkeypatch):
    monkeypatch.setattr(daily_graph.steps, "run_research_followup", _raise)
    marked = []
    run = PortfolioRunState(run_id="run_opt", started_at="2026-08-10T15:40:00Z")
    run.progress = type("_P", (), {"mark_phase": lambda self, *a: marked.append(a)})()

    node = daily_graph.guarded_node(
        "research_followup", daily_graph.research_followup_node, optional=True
    )
    node({"run": run})

    assert marked == []


def test_a_mandatory_node_still_aborts_the_run(monkeypatch):
    monkeypatch.setattr(daily_graph.steps, "run_research_followup", _raise)
    run = PortfolioRunState(run_id="run_req", started_at="2026-08-10T15:40:00Z")

    node = daily_graph.guarded_node(
        "research_followup", daily_graph.research_followup_node
    )
    result = node({"run": run})

    assert result["run"].failed_step == "research_followup"
    assert daily_graph.route_after_node({"run": result["run"]}) == "failed"


def test_trade_path_nodes_are_never_optional():
    # The bar for OPTIONAL_NODES: the fund must be able to decide without it.
    for node_name in (
        "decide_trades",
        "review_risk",
        "check_rebalance",
        "execute_trades",
        "journal_run",
        "save_portfolio",
    ):
        assert node_name not in daily_graph.OPTIONAL_NODES


def test_build_run_status_keeps_warnings_raised_earlier_in_the_run(monkeypatch):
    # The node used to overwrite run.warnings with the freshly built status, which
    # would have dropped a degraded optional node's warning before it reached
    # run_history — a silent degradation.
    monkeypatch.setattr(
        daily_graph.steps,
        "build_run_status",
        lambda **kwargs: {"status": "success", "warnings": ["late warning"]},
    )
    run = PortfolioRunState(run_id="run_w", started_at="2026-08-10T15:40:00Z")
    run.warnings.append("research_followup: 400 tool error")

    daily_graph.build_run_status_node({"run": run})

    assert run.warnings == ["research_followup: 400 tool error", "late warning"]
    assert run.run_status["warnings"] == run.warnings
