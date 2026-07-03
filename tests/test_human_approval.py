"""Tests for the human-in-the-loop approval gate (P1-3).

The gate blocks inline (no LangGraph interrupt/checkpointer), so tests drive it
by stubbing `prompt_for_approval` and asserting how the node and the full graph
treat the approved-trade set.
"""

from types import SimpleNamespace

from src import config
from src.models.run_state import PortfolioRunState
from src.workflows import daily_graph
from src.workflows.daily_graph import (
    build_daily_cycle_graph,
    create_initial_state,
    human_approval_node,
    prompt_for_approval,
)


def _state(trades):
    run = PortfolioRunState(run_id="run_test", started_at="2026-01-01T00:00:00Z")
    run.approved_trades = list(trades)
    return {"run": run}


# -- node logic --------------------------------------------------------------


def test_auto_approve_passes_through(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", True)
    trades = ["t1", "t2"]

    run = human_approval_node(_state(trades))["run"]

    assert run.approved_trades == trades
    assert run.human_review == {"decision": "auto_approved", "pending": 2}


def test_manual_mode_with_no_trades_does_not_prompt(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", False)

    def _fail(*_):
        raise AssertionError("should not prompt when there are no trades")

    monkeypatch.setattr(daily_graph, "prompt_for_approval", _fail)

    run = human_approval_node(_state([]))["run"]
    assert run.human_review == {"decision": "auto_approved", "pending": 0}


def test_reject_clears_all_trades(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", False)
    monkeypatch.setattr(
        daily_graph, "prompt_for_approval",
        lambda pending: {"action": "reject", "reason": "too risky"},
    )

    run = human_approval_node(_state(["t1", "t2"]))["run"]

    assert run.approved_trades == []
    assert run.human_review == {"decision": "reject", "reason": "too risky"}


def test_edit_keeps_only_selected_indices(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", False)
    monkeypatch.setattr(
        daily_graph, "prompt_for_approval",
        lambda pending: {"action": "edit", "approved_indices": [0, 2]},
    )

    run = human_approval_node(_state(["t0", "t1", "t2"]))["run"]

    assert run.approved_trades == ["t0", "t2"]
    assert run.human_review == {"decision": "edit", "kept": 2, "original": 3}


def test_approve_keeps_all_trades(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", False)
    monkeypatch.setattr(daily_graph, "prompt_for_approval", lambda pending: {"action": "approve"})
    trades = ["t1", "t2"]

    run = human_approval_node(_state(trades))["run"]

    assert run.approved_trades == trades
    assert run.human_review == {"decision": "approve", "approved": 2}


# -- inline prompt parsing ---------------------------------------------------


def test_prompt_approve(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "a")
    assert prompt_for_approval([]) == {"action": "approve"}


def test_prompt_reject_with_reason(monkeypatch):
    answers = iter(["r", "too risky"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    assert prompt_for_approval([{"symbol": "AAPL"}]) == {"action": "reject", "reason": "too risky"}


def test_prompt_edit_indices(monkeypatch):
    answers = iter(["e", "0,2"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    assert prompt_for_approval([]) == {"action": "edit", "approved_indices": [0, 2]}


def test_prompt_falls_back_to_reject_without_tty(monkeypatch):
    def _raise(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    assert prompt_for_approval([]) == {"action": "reject", "reason": "no interactive approver"}


# -- full compiled graph: gate is wired between rebalance and execution ------


def _mock_full_cycle(monkeypatch, approved):
    snap = SimpleNamespace(total_value=1_000_000.0, cash_pct=0.1)
    engine = SimpleNamespace(get_snapshot=lambda: snap)
    memres = SimpleNamespace(status="ok", error=None)
    ingestion = SimpleNamespace(status="ok", errors=[], to_dict=lambda: {"status": "ok"})
    executed: dict = {}

    returns = {
        "load_portfolio": ("p", "t", engine),
        "create_clients": ("m", "n", "b"),
        "mark_to_market_and_score_predictions": None,
        "build_research_context": ({}, {}),
        "retrieve_memory_context": (memres, [], {}),
        "run_research_followup": {"brief": "b", "tool_calls": []},
        "decide_trades": {"trades": []},
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

    def make(name, ret):
        def fn(*args, **kwargs):
            if name == "execute_trades":
                # positional: (engine, approved_trades, market_data, trade_store, run_id)
                executed["approved"] = args[1]
            return ret
        return fn

    for name, ret in returns.items():
        monkeypatch.setattr(daily_graph.steps, name, make(name, ret))
    return executed


def test_full_graph_reject_vetoes_execution(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", False)
    monkeypatch.setattr(
        daily_graph, "prompt_for_approval", lambda pending: {"action": "reject", "reason": "no"}
    )
    executed = _mock_full_cycle(monkeypatch, ["A", "B"])

    result = build_daily_cycle_graph().invoke(create_initial_state())
    run = result["run"]

    assert not run.errors
    assert executed["approved"] == []  # nothing reached execution
    assert run.run_status["human_review"]["decision"] == "reject"


def test_full_graph_edit_executes_only_subset(monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", False)
    monkeypatch.setattr(
        daily_graph,
        "prompt_for_approval",
        lambda pending: {"action": "edit", "approved_indices": [1]},
    )
    executed = _mock_full_cycle(monkeypatch, ["A", "B", "C"])

    result = build_daily_cycle_graph().invoke(create_initial_state())
    run = result["run"]

    assert executed["approved"] == ["B"]
    assert run.run_status["human_review"] == {"decision": "edit", "kept": 1, "original": 3}
