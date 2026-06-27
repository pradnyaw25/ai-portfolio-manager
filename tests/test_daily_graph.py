from src.models.run_state import PortfolioRunState
from src.workflows.daily_graph import build_daily_cycle_graph, create_initial_state


def test_create_initial_state_has_typed_run_state():
    state = create_initial_state()

    assert isinstance(state["run"], PortfolioRunState)
    assert state["run"].run_id.startswith("run_")
    assert state["run"].started_at.endswith("Z")


def test_daily_cycle_graph_compiles():
    graph = build_daily_cycle_graph()

    assert graph is not None
