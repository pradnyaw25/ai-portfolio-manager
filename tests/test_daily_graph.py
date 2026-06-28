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
