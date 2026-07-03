"""P1-2 (2/2): durable progress store + idempotency-based resume."""

from types import SimpleNamespace

from src import config
from src.storage.run_progress_store import RunProgressStore
from src.workflows import daily_graph
from src.workflows.daily_graph import run_daily_cycle_graph


# ---- RunProgressStore --------------------------------------------------------

def _store(tmp_path):
    return RunProgressStore(path=tmp_path / "progress.db")


def test_start_and_finish_tracks_unfinished(tmp_path):
    store = _store(tmp_path)
    store.start_run("run_a", "2026-06-28T10:00:00Z")
    assert store.latest_unfinished()["run_id"] == "run_a"
    store.finish_run("run_a", "completed")
    assert store.latest_unfinished() is None


def test_marks_and_reports_completed_phases(tmp_path):
    store = _store(tmp_path)
    store.start_run("run_a", "t")
    store.mark_phase("run_a", "decide_trades")
    store.mark_phase("run_a", "decide_trades")  # idempotent
    store.mark_phase("run_a", "execute_trades")
    assert store.completed_phases("run_a") == {"decide_trades", "execute_trades"}
    assert store.phase_done("run_a", "execute_trades")
    assert not store.phase_done("run_a", "journal_run")


def test_latest_unfinished_picks_most_recent_running(tmp_path):
    store = _store(tmp_path)
    store.start_run("old", "2026-06-20T00:00:00Z")
    store.start_run("new", "2026-06-27T00:00:00Z")
    store.finish_run("old", "completed")
    assert store.latest_unfinished()["run_id"] == "new"


# ---- resume through the graph ------------------------------------------------

def _mock_full_cycle(monkeypatch):
    snap = SimpleNamespace(total_value=1_000_000.0, cash_pct=0.1)
    engine = SimpleNamespace(get_snapshot=lambda: snap)
    memres = SimpleNamespace(status="ok", error=None)
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
        "decide_trades": {"trades": [{"symbol": "AAPL"}]},
        "run_grounding_check": {"status": "ok", "grounded": True, "issues": []},
        "review_risk": SimpleNamespace(approved=["A"]),
        "check_rebalance": (SimpleNamespace(), ["A"]),
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
        "record_run_history": None,
    }
    for name, ret in returns.items():
        monkeypatch.setattr(daily_graph.steps, name, record(name, ret))
    return calls


def test_resume_reuses_unfinished_run_id_and_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", True)
    store = _store(tmp_path)
    store.start_run("run_prev", "2026-06-28T09:00:00Z")  # a run that "died" mid-way

    calls = _mock_full_cycle(monkeypatch)
    final = run_daily_cycle_graph(resume=True, progress=store)

    assert final.run_id == "run_prev"
    assert final.resumed is True
    assert store.latest_unfinished() is None  # marked completed
    assert "execute_trades" in calls


def test_resume_skips_already_published_tweet(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", True)
    store = _store(tmp_path)
    store.start_run("run_prev", "2026-06-28T09:00:00Z")
    store.mark_phase("run_prev", "publish_tweet")  # tweet already went out before the crash

    calls = _mock_full_cycle(monkeypatch)
    final = run_daily_cycle_graph(resume=True, progress=store)

    assert "publish_tweet" not in calls  # not re-posted
    assert final.diagnostics["tweet"].startswith("skipped on resume")


def test_resume_without_unfinished_starts_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUTO_APPROVE", True)
    store = _store(tmp_path)  # empty — nothing unfinished

    _mock_full_cycle(monkeypatch)
    final = run_daily_cycle_graph(resume=True, progress=store)

    assert final.resumed is False
    assert final.run_id  # a fresh id was generated
