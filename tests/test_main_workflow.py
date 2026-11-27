from dataclasses import dataclass
from datetime import date

from src.main import (
    build_failure_run_status,
    build_run_status,
    extract_memory_symbols,
    extract_prices,
)
from src.models.portfolio import PortfolioSnapshot


@dataclass
class MemoryResult:
    status: str
    error: str | None = None


def test_extract_prices_filters_missing_and_invalid_prices():
    research = {
        "symbols": [
            {"symbol": "AAPL", "price": 200.0},
            {"symbol": "MSFT", "price": None},
            {"symbol": "NVDA", "price": 0},
        ]
    }

    assert extract_prices(research) == {"AAPL": 200.0}


def test_extract_memory_symbols_combines_holdings_and_context_symbols():
    research = {
        "holdings": [{"symbol": "aapl"}, {"symbol": "msft"}],
        "symbols": [
            {"symbol": "AAPL"},
            {"symbol": "NVDA"},
            {"symbol": "^VIX"},
        ],
    }

    assert extract_memory_symbols(research) == ["AAPL", "MSFT", "NVDA", "^VIX"]


def test_build_run_status_records_memory_warning():
    snapshot = PortfolioSnapshot(date=date.today(), cash=25000, positions=[])
    status = build_run_status(
        run_id="run_123",
        started_at="2024-06-01T12:00:00Z",
        memory_result=MemoryResult(status="unavailable", error="qdrant offline"),
        memory_context=[],
        trades=[],
        snapshot=snapshot,
    )

    assert status["run_id"] == "run_123"
    assert status["status"] == "success"
    assert status["memory_status"] == "unavailable"
    assert status["memory_error"] == "qdrant offline"
    assert status["memory_chunks"] == 0
    assert status["trades_executed"] == 0
    assert status["warnings"] == ["Memory unavailable: qdrant offline"]
    assert status["portfolio_value"] == 25000
    # LLM cost summary is always present (zeros when no calls are logged for the run).
    assert set(status["llm"]) == {"calls", "prompt_tokens", "completion_tokens", "cost_usd", "latency_ms"}


def test_run_status_records_the_slot_the_workflow_supplied(monkeypatch):
    """The run-health watchdog and the already-served check read `slot` back, so it
    must be the slot the cron fired for, never a guess from the start hour."""
    from src import config

    monkeypatch.setattr(config, "RUN_SLOT", "morning")
    monkeypatch.setattr(config, "RUN_SLOT_TIME", "14:40")
    monkeypatch.setattr(config, "RUN_CRON", "40 4,6,8,10,12 * * 1-5")
    monkeypatch.setattr(config, "RUN_FIRED_AT", "2026-11-20T13:10:00Z")
    monkeypatch.setattr(config, "RUN_SCHEDULER_DELAY_MIN", 510)
    snapshot = PortfolioSnapshot(date=date.today(), cash=25000, positions=[])

    status = build_run_status(
        run_id="run_123",
        started_at="2026-11-20T18:35:00Z",  # landed after the cutoff: still morning
        memory_result=MemoryResult(status="ok"),
        memory_context=[],
        trades=[],
        snapshot=snapshot,
    )
    failure = build_failure_run_status(
        run_id="run_123", started_at="2026-11-20T18:35:00Z", failed_step="x", errors=["boom"]
    )

    for row in (status, failure):
        assert row["slot"] == "morning"
        assert row["schedule"] == {
            "slot_time": "14:40",
            "cron": "40 4,6,8,10,12 * * 1-5",
            "fired_at": "2026-11-20T13:10:00Z",
            "scheduler_delay_min": 510,
        }


def test_run_status_has_no_slot_outside_the_scheduler(monkeypatch):
    from src import config

    for name in ("RUN_SLOT", "RUN_SLOT_TIME", "RUN_CRON", "RUN_FIRED_AT", "RUN_SCHEDULER_DELAY_MIN"):
        monkeypatch.setattr(config, name, None)
    status = build_failure_run_status(run_id="r", started_at="2026-11-20T18:35:00Z", failed_step=None, errors=[])

    assert status["slot"] is None
    assert status["schedule"] is None


def test_a_manual_dispatch_is_recorded_as_manual(monkeypatch):
    """So the watchdog never counts it as the afternoon run by its start hour, and the
    real afternoon fire never stands down because of it."""
    from src import config

    monkeypatch.setattr(config, "RUN_SLOT", "manual")
    for name in ("RUN_SLOT_TIME", "RUN_CRON", "RUN_FIRED_AT", "RUN_SCHEDULER_DELAY_MIN"):
        monkeypatch.setattr(config, name, None)
    status = build_failure_run_status(run_id="r", started_at="2026-11-20T19:00:00Z", failed_step=None, errors=[])

    assert status["slot"] == "manual"


def test_build_failure_run_status_records_failed_step_and_errors():
    snapshot = PortfolioSnapshot(date=date.today(), cash=25000, positions=[])
    status = build_failure_run_status(
        run_id="run_123",
        started_at="2024-06-01T12:00:00Z",
        failed_step="decide_trades",
        errors=["decide_trades: model unavailable"],
        warnings=["memory degraded"],
        snapshot=snapshot,
    )

    assert status["run_id"] == "run_123"
    assert status["status"] == "failed"
    assert status["failed_step"] == "decide_trades"
    assert status["errors"] == ["decide_trades: model unavailable"]
    assert status["warnings"] == ["memory degraded"]
    assert status["portfolio_value"] == 25000


def test_publish_receipts_tweet_noops_without_resolutions():
    import src.main as main

    run_status = {}
    assert main.publish_receipts_tweet([], "run_1", run_status) is None
    assert "receipts_publish" not in run_status


def test_publish_receipts_tweet_computes_record_and_publishes(monkeypatch):
    import src.main as main
    from src.social.twitter import TweetPublishResult

    scored = [{"symbol": "APLD", "prediction": "APLD will underperform SPY over 5 days",
               "direction": "UNDERPERFORM", "confidence": 0.7,
               "result": {"symbol_return": -0.055, "spy_return": 0.007,
                          "correct": True, "outperformed": False}}]

    # Store has 3 scored calls, 2 correct — the running record the tweet should cite.
    class FakeStore:
        def load_all(self):
            return [
                {"status": "scored", "result": {"correct": True}},
                {"status": "scored", "result": {"correct": True}},
                {"status": "scored", "result": {"correct": False}},
                {"status": "open", "result": None},
            ]

    monkeypatch.setattr("src.storage.prediction_store.PredictionStore", FakeStore)
    published = {}

    def fake_publish(text, run_id=None):
        published["text"] = text
        return TweetPublishResult(status="dry_run", posted=False, dry_run=True,
                                  text=text, run_id=run_id)

    monkeypatch.setattr(main, "publish_tweet_service", fake_publish)

    run_status = {}
    result = main.publish_receipts_tweet(scored, "run_1", run_status)

    assert result.status == "dry_run"
    assert "2/3 calls right" in published["text"]  # record computed via was_correct
    assert "$APLD" in published["text"]
    assert run_status["receipts_publish"]["text"] == published["text"]


def test_publish_spotlight_tweet_excludes_forward_symbol_and_publishes(monkeypatch):
    import src.main as main
    from src.social.twitter import TweetPublishResult

    decisions = {"market_calls": [
        {"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.8, "thesis": "momentum"},
        {"symbol": "MU", "direction": "OUTPERFORM", "confidence": 0.7, "thesis": "memory cycle"},
    ]}
    # No recent posts → nothing on cooldown.
    monkeypatch.setattr("src.social.cooldown.load_recent_posts", lambda *a, **k: [])
    published = {}

    def fake_publish(text, run_id=None):
        published["text"] = text
        return TweetPublishResult(status="dry_run", posted=False, dry_run=True,
                                  text=text, run_id=run_id)

    monkeypatch.setattr(main, "publish_tweet_service", fake_publish)

    run_status = {}
    # The forward tweet already led with AAPL, so the spotlight must pick MU.
    result = main.publish_spotlight_tweet(decisions, {}, "Bought AAPL today.", "run_1", run_status)

    assert result.status == "dry_run"
    assert "$MU" in published["text"] and "AAPL" not in published["text"]
    assert run_status["spotlight_publish"]["text"] == published["text"]


def test_publish_spotlight_tweet_noops_without_calls():
    import src.main as main
    run_status = {}
    assert main.publish_spotlight_tweet({"market_calls": []}, {}, "", "run_1", run_status) is None
    assert "spotlight_publish" not in run_status
