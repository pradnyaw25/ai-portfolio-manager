from datetime import date

from src.agents.risk_manager import RiskManagerAgent
from src.models.portfolio import PortfolioSnapshot


def test_rejects_low_confidence_trade():
    portfolio = PortfolioSnapshot(date=date.today(), cash=100000, positions=[])
    review = RiskManagerAgent().review(
        raw_trades=[{"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.2}],
        portfolio=portfolio,
        prices={"AAPL": 100.0},
    )

    assert review.approved == []
    assert len(review.rejected) == 1
    assert "below minimum" in review.rejected[0].reason


def test_low_confidence_hold_is_not_rejected():
    # A HOLD is a no-op, so the min-trade-confidence gate must not apply to it:
    # a low-confidence HOLD should be neither approved nor listed as a rejected trade.
    portfolio = PortfolioSnapshot(date=date.today(), cash=100000, positions=[])
    review = RiskManagerAgent().review(
        raw_trades=[{"symbol": "AAPL", "action": "HOLD", "shares": 0, "confidence": 0.50}],
        portfolio=portfolio,
        prices={"AAPL": 100.0},
    )

    assert review.approved == []
    assert review.rejected == []


def test_caps_trade_to_daily_turnover_limit():
    portfolio = PortfolioSnapshot(date=date.today(), cash=100000, positions=[])
    review = RiskManagerAgent().review(
        raw_trades=[{"symbol": "AAPL", "action": "BUY", "shares": 1000, "confidence": 0.9}],
        portfolio=portfolio,
        prices={"AAPL": 100.0},
    )

    assert len(review.approved) == 1
    assert review.approved[0].shares == 200


def test_normalizes_action_and_symbol():
    portfolio = PortfolioSnapshot(date=date.today(), cash=100000, positions=[])
    review = RiskManagerAgent().review(
        raw_trades=[{"symbol": "aapl", "action": "buy", "shares": "10", "confidence": "0.9"}],
        portfolio=portfolio,
        prices={"AAPL": 100.0},
    )

    assert len(review.approved) == 1
    assert review.approved[0].symbol == "AAPL"
    assert review.approved[0].action == "BUY"
