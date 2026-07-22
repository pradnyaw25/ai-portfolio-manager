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
