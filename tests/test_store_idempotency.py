"""P0-3: re-running a run_id must not duplicate trades, decisions, or predictions.

Acceptance: running the daily cycle twice with the same run_id produces identical
files/rows. These tests exercise the three append-based stores directly at the
run-batch level.
"""

from datetime import date
from types import SimpleNamespace

from src.models.portfolio import PortfolioSnapshot
from src.models.trade import Trade, TradeAction
from src.storage import decision_store, prediction_store, trade_store
from src.storage.decision_store import DecisionStore
from src.storage.prediction_store import PredictionStore
from src.storage.trade_store import TradeStore


def _trade(symbol, action, shares, price, run_id):
    return Trade(
        date=date(2024, 6, 1),
        symbol=symbol,
        action=action,
        shares=shares,
        price=price,
        reasoning="t",
        run_id=run_id,
    )


def test_trade_save_run_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_store, "TRADES_FILE", tmp_path / "trades.csv")
    store = TradeStore()
    batch = [
        _trade("AAPL", TradeAction.BUY, 10, 180.0, "run_1"),
        _trade("MSFT", TradeAction.BUY, 5, 400.0, "run_1"),
    ]

    store.save_run("run_1", batch)
    first = (tmp_path / "trades.csv").read_text()
    store.save_run("run_1", batch)  # re-run same run_id
    second = (tmp_path / "trades.csv").read_text()

    assert first == second
    assert len(store.load_all()) == 2


def test_trade_save_run_keeps_same_symbol_action_collision(tmp_path, monkeypatch):
    """A PM buy + a rebalance top-up for the same symbol are both preserved."""
    monkeypatch.setattr(trade_store, "TRADES_FILE", tmp_path / "trades.csv")
    store = TradeStore()
    batch = [
        _trade("AAPL", TradeAction.BUY, 10, 180.0, "run_1"),
        _trade("AAPL", TradeAction.BUY, 3, 181.0, "run_1"),
    ]

    store.save_run("run_1", batch)
    store.save_run("run_1", batch)

    rows = store.load_all()
    assert len(rows) == 2
    assert {r["shares"] for r in rows} == {"10", "3"}


def test_trade_save_run_preserves_other_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_store, "TRADES_FILE", tmp_path / "trades.csv")
    store = TradeStore()
    store.save_run("run_1", [_trade("AAPL", TradeAction.BUY, 10, 180.0, "run_1")])
    store.save_run("run_2", [_trade("MSFT", TradeAction.BUY, 5, 400.0, "run_2")])

    store.save_run("run_1", [_trade("AAPL", TradeAction.BUY, 10, 180.0, "run_1")])

    rows = store.load_all()
    assert len(rows) == 2
    assert {r["run_id"] for r in rows} == {"run_1", "run_2"}


def test_trade_save_run_empty_clears_prior_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_store, "TRADES_FILE", tmp_path / "trades.csv")
    store = TradeStore()
    store.save_run("run_1", [_trade("AAPL", TradeAction.BUY, 10, 180.0, "run_1")])
    store.save_run("run_1", [])  # re-run produced no trades

    assert store.load_all() == []


def _save_decision(store, run_id):
    store.save(
        portfolio=PortfolioSnapshot(date=date.today(), cash=100000, positions=[]),
        raw_decision={"summary": "hold"},
        approved=[],
        rejected=[],
        executed=[],
        run_id=run_id,
    )


def test_decision_save_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_store, "DECISIONS_FILE", tmp_path / "decisions.jsonl")
    store = DecisionStore()

    _save_decision(store, "run_1")
    _save_decision(store, "run_1")  # re-run same run_id

    rows = store.load_all()
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run_1"


def test_decision_save_preserves_other_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_store, "DECISIONS_FILE", tmp_path / "decisions.jsonl")
    store = DecisionStore()

    _save_decision(store, "run_1")
    _save_decision(store, "run_2")
    _save_decision(store, "run_1")  # re-run run_1

    rows = store.load_all()
    assert len(rows) == 2
    assert {r["run_id"] for r in rows} == {"run_1", "run_2"}


def test_prediction_create_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    store = PredictionStore()
    trade = SimpleNamespace(symbol="AAPL", price=200.0, run_id="run_1", reasoning="x")

    first = store.create_from_trade(trade, confidence=0.7, spy_price=500.0)
    second = store.create_from_trade(trade, confidence=0.7, spy_price=500.0)

    entries = store.load_all()
    assert len(entries) == 1
    assert first["id"] == second["id"]  # deterministic id


def test_prediction_distinct_symbols_coexist(tmp_path, monkeypatch):
    monkeypatch.setattr(prediction_store, "PREDICTIONS_FILE", tmp_path / "predictions.jsonl")
    store = PredictionStore()
    aapl = SimpleNamespace(symbol="AAPL", price=200.0, run_id="run_1", reasoning="x")
    msft = SimpleNamespace(symbol="MSFT", price=400.0, run_id="run_1", reasoning="y")

    store.create_from_trade(aapl, confidence=0.7, spy_price=500.0)
    store.create_from_trade(msft, confidence=0.7, spy_price=500.0)
    store.create_from_trade(aapl, confidence=0.7, spy_price=500.0)  # re-run AAPL

    entries = store.load_all()
    assert len(entries) == 2
    assert {e["symbol"] for e in entries} == {"AAPL", "MSFT"}
