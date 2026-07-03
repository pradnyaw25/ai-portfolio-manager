"""P2-2 record expansion: horizon/thesis on creation, alpha on scoring."""

from datetime import date, timedelta
from types import SimpleNamespace

from src.storage import prediction_store
from src.scoring.prediction_scorer import PredictionScorer


def test_create_from_trade_adds_horizon_and_thesis(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    trade = SimpleNamespace(symbol="AAPL", price=200.0, run_id="run_1", reasoning="oversold bounce")

    record = prediction_store.PredictionStore().create_from_trade(trade, confidence=0.7, spy_price=500.0)

    assert record["thesis"] == "oversold bounce"
    assert record["horizon_days"] == 30
    assert record["due_date"] == (date.today() + timedelta(days=30)).isoformat()


def test_create_from_trade_tolerates_missing_reasoning(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    trade = SimpleNamespace(symbol="AAPL", price=200.0, run_id="run_1")  # no reasoning attr

    record = prediction_store.PredictionStore().create_from_trade(trade, confidence=0.7, spy_price=500.0)
    assert record["thesis"] == ""


def test_scorer_records_benchmark_relative_alpha(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    store = prediction_store.PredictionStore()
    store.save({
        "id": "p1", "symbol": "AAPL", "prediction": "AAPL will outperform SPY over 30 days",
        "confidence": 0.7, "start_price": 100.0, "spy_start_price": 100.0,
        "due_date": yesterday, "status": "open", "result": None,
    })

    # AAPL +10%, SPY +4% → alpha +6%.
    prices = {"AAPL": 110.0, "SPY": 104.0}
    market_data = SimpleNamespace(get_price=lambda s: prices[s])
    scored = PredictionScorer().score_due_predictions(market_data)

    assert len(scored) == 1
    result = scored[0]["result"]
    assert result["alpha"] == round(0.10 - 0.04, 4)
    assert result["outperformed"] is True
