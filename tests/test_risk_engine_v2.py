"""P5-2 Risk Engine V2: sector limits + stop-loss/take-profit exits."""

from datetime import date
from types import SimpleNamespace

from src.agents.risk_events import generate_risk_events
from src.agents.risk_manager import RiskManagerAgent
from src.main import review_risk
from src.models.portfolio import Position, PortfolioSnapshot
from src.storage import decision_store
from src.storage.decision_store import DecisionStore


def _snapshot(cash, positions):
    return PortfolioSnapshot(date=date.today(), cash=cash, positions=positions)


def _pos(symbol, shares, avg_cost, current_price):
    return Position(symbol=symbol, shares=shares, avg_cost=avg_cost, current_price=current_price)


# ---- stop-loss / take-profit generation -------------------------------------

def test_stop_loss_generates_system_sell():
    portfolio = _snapshot(0, [_pos("AAPL", 100, 200.0, 160.0)])  # -20%
    events = generate_risk_events(portfolio)
    assert len(events) == 1
    event = events[0]
    assert event["symbol"] == "AAPL"
    assert event["action"] == "SELL"
    assert event["shares"] == 100
    assert event["origin"] == "system"
    assert event["risk_event"] == "stop_loss"
    assert event["confidence"] == 1.0


def test_take_profit_generates_system_sell():
    portfolio = _snapshot(0, [_pos("NVDA", 50, 100.0, 150.0)])  # +50%
    events = generate_risk_events(portfolio)
    assert [e["risk_event"] for e in events] == ["take_profit"]
    assert events[0]["shares"] == 50


def test_position_within_band_generates_no_event():
    portfolio = _snapshot(0, [_pos("MSFT", 10, 400.0, 420.0)])  # +5%
    assert generate_risk_events(portfolio) == []


def test_thresholds_are_configurable_and_boundary_exclusive():
    portfolio = _snapshot(0, [_pos("AAPL", 10, 100.0, 90.0)])  # exactly -10%
    assert generate_risk_events(portfolio, stop_loss_pct=0.10) != []
    assert generate_risk_events(portfolio, stop_loss_pct=0.15) == []


def test_zero_cost_basis_position_is_skipped():
    portfolio = _snapshot(0, [_pos("AAPL", 10, 0.0, 90.0)])
    assert generate_risk_events(portfolio) == []


# ---- sector-concentration cap -----------------------------------------------

def test_buy_capped_to_sector_limit():
    # 100% turnover so only the sector cap binds. IT limit = 40% * 1,000,000.
    portfolio = _snapshot(1_000_000, [])
    review = RiskManagerAgent().review(
        raw_trades=[{"symbol": "AAPL", "action": "BUY", "shares": 6000, "confidence": 0.9}],
        portfolio=portfolio,
        prices={"AAPL": 100.0},
        turnover_override=1.0,
    )
    assert len(review.approved) == 1
    assert review.approved[0].shares == 4000  # 400,000 / 100


def test_second_same_sector_buy_accumulates_toward_limit():
    portfolio = _snapshot(1_000_000, [])
    review = RiskManagerAgent().review(
        raw_trades=[
            {"symbol": "AAPL", "action": "BUY", "shares": 3000, "confidence": 0.9},
            {"symbol": "MSFT", "action": "BUY", "shares": 3000, "confidence": 0.9},
        ],
        portfolio=portfolio,
        prices={"AAPL": 100.0, "MSFT": 100.0},
        turnover_override=1.0,
    )
    # AAPL uses 300k of the 400k IT budget; MSFT capped to the remaining 100k.
    assert [t.shares for t in review.approved] == [3000, 1000]


def test_buy_rejected_when_sector_already_over_limit():
    # Existing IT exposure (80k) already exceeds the IT limit (40% * 180k = 72k).
    portfolio = _snapshot(100_000, [_pos("AAPL", 400, 200.0, 200.0)])
    review = RiskManagerAgent().review(
        raw_trades=[{"symbol": "MSFT", "action": "BUY", "shares": 10, "confidence": 0.9}],
        portfolio=portfolio,
        prices={"MSFT": 100.0, "AAPL": 200.0},
        turnover_override=1.0,
    )
    assert review.approved == []
    assert "sector concentration" in review.rejected[0].reason


def test_sell_is_not_sector_capped():
    portfolio = _snapshot(0, [_pos("AAPL", 5000, 100.0, 100.0)])
    review = RiskManagerAgent().review(
        raw_trades=[{"symbol": "AAPL", "action": "SELL", "shares": 5000, "confidence": 0.9}],
        portfolio=portfolio,
        prices={"AAPL": 100.0},
        turnover_override=1.0,
    )
    assert len(review.approved) == 1
    assert review.approved[0].shares == 5000


# ---- pipeline integration ----------------------------------------------------

def test_review_risk_injects_system_exit_and_supersedes_llm_trade():
    snapshot = _snapshot(50_000, [_pos("AAPL", 100, 200.0, 160.0)])  # AAPL -20% → stop-loss
    engine = SimpleNamespace(get_snapshot=lambda: snapshot)
    decisions = {"trades": [{"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.9}]}

    review = review_risk(decisions, engine, prices={"AAPL": 160.0})

    # The LLM's AAPL buy is dropped; the system stop-loss SELL is approved instead.
    assert [e["risk_event"] for e in review.risk_events] == ["stop_loss"]
    aapl = [t for t in review.approved if t.symbol == "AAPL"]
    assert len(aapl) == 1
    assert aapl[0].action == "SELL"
    assert aapl[0].origin == "system"


def test_decision_journal_records_risk_events(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_store, "DECISIONS_FILE", tmp_path / "decisions.jsonl")
    DecisionStore().save(
        portfolio=_snapshot(100_000, []),
        raw_decision={"summary": "exit"},
        approved=[],
        rejected=[],
        executed=[],
        risk_events=[{"symbol": "AAPL", "action": "SELL", "origin": "system",
                      "risk_event": "stop_loss"}],
        run_id="run_1",
    )
    row = DecisionStore().load_all()[0]
    assert row["risk_events"][0]["origin"] == "system"
    assert row["risk_events"][0]["risk_event"] == "stop_loss"
