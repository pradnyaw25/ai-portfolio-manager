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


def test_create_from_trade_keeps_one_open_prediction_per_symbol(tmp_path, monkeypatch):
    # Buying the same symbol on a later run (or with no run_id) must not open a
    # second overlapping prediction — the original open bet stays.
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    store = prediction_store.PredictionStore()

    first = store.create_from_trade(
        SimpleNamespace(symbol="AAPL", price=200.0, run_id="run_1"), confidence=0.7, spy_price=500.0
    )
    # second BUY, different run (and even a null run_id) → no duplicate
    second = store.create_from_trade(
        SimpleNamespace(symbol="AAPL", price=210.0, run_id=None), confidence=0.9, spy_price=505.0
    )

    open_aapl = [p for p in store.load_all() if p["symbol"] == "AAPL"]
    assert len(open_aapl) == 1
    assert second["id"] == first["id"]
    assert second["start_price"] == 200.0  # the original bet, not the later one


def test_create_from_trade_reopens_after_prior_resolves(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    store = prediction_store.PredictionStore()
    store.create_from_trade(SimpleNamespace(symbol="AAPL", price=200.0, run_id="run_1"), 0.7, 500.0)

    # resolve the first, then a new BUY should open a fresh prediction
    entries = store.load_all()
    entries[0]["status"] = "scored"
    store.save_all(entries)

    store.create_from_trade(SimpleNamespace(symbol="AAPL", price=210.0, run_id="run_2"), 0.8, 505.0)
    assert len(store.load_open()) == 1
    assert len(store.load_all()) == 2


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
    # Legacy row (no direction) is an implicit outperform call → correct.
    assert result["correct"] is True


def test_create_call_records_direction_horizon_and_trade_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    store = prediction_store.PredictionStore()

    rec = store.create_call(
        run_id="run_1", symbol="NVDA", direction="underperform", confidence=0.55,
        thesis="stretched multiple", start_price=100.0, spy_price=500.0,
        horizon=5, became_trade=False,
    )

    assert rec["direction"] == "UNDERPERFORM"
    assert "underperform SPY over 5 days" in rec["prediction"]
    assert rec["horizon_days"] == 5
    assert rec["confidence"] == 0.55
    assert rec["became_trade"] is False
    assert rec["due_date"] == (date.today() + timedelta(days=5)).isoformat()


def test_create_call_independent_per_horizon_but_no_stacking(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    store = prediction_store.PredictionStore()

    def call(run_id, horizon):
        return store.create_call(
            run_id=run_id, symbol="AAPL", direction="OUTPERFORM", confidence=0.7,
            thesis="", start_price=200.0, spy_price=500.0, horizon=horizon,
        )

    first_5 = call("run_1", 5)
    first_30 = call("run_1", 30)
    # 5d and 30d for the same name coexist — independent windows, distinct ids.
    assert first_5 is not None and first_30 is not None
    assert first_5["id"] != first_30["id"]
    assert len(store.load_open()) == 2

    # A later run must not stack a second open 5d bet while the first is unresolved.
    assert call("run_2", 5) is None
    assert len(store.load_open()) == 2

    # Once the 5d resolves, a fresh 5d window opens; the 30d is untouched.
    entries = store.load_all()
    for e in entries:
        if e["horizon_days"] == 5:
            e["status"] = "scored"
    store.save_all(entries)
    assert call("run_3", 5) is not None
    assert len(store.load_open()) == 2  # new 5d + still-open 30d


def test_scorer_marks_underperform_call_correct(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    store = prediction_store.PredictionStore()
    store.save({
        "id": "u1", "symbol": "NVDA", "direction": "UNDERPERFORM",
        "prediction": "NVDA will underperform SPY over 5 days", "confidence": 0.6,
        "start_price": 100.0, "spy_start_price": 100.0,
        "horizon_days": 5, "due_date": yesterday, "status": "open", "result": None,
    })

    # NVDA +2%, SPY +5% → NVDA underperformed → the underperform call is CORRECT.
    prices = {"NVDA": 102.0, "SPY": 105.0}
    market_data = SimpleNamespace(get_price=lambda s: prices[s])
    scored = PredictionScorer().score_due_predictions(market_data)

    assert len(scored) == 1
    result = scored[0]["result"]
    assert result["outperformed"] is False
    assert result["correct"] is True
