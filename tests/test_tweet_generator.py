from datetime import date, datetime

from src.agents.tweet_generator import TweetGeneratorAgent
from src.models.portfolio import PortfolioSnapshot, Position
from src.models.trade import Trade, TradeAction


def _agent():
    # Bypass __init__ so we don't read the prompt file — we only exercise helpers.
    return TweetGeneratorAgent.__new__(TweetGeneratorAgent)


def test_clean_tweet_removes_repetitive_disclaimer_lines():
    tweet = _agent()._clean_tweet(
        """Trimmed tech and kept cash near 30%.

Simulated portfolio. Not investment advice."""
    )
    assert tweet == "Trimmed tech and kept cash near 30%."


def _portfolio():
    return PortfolioSnapshot(
        date=date.today(), cash=270_000, positions=[Position("MSFT", 1750, 400, 400)]
    )


def test_context_includes_trade_reasoning_not_cash_or_position_count():
    trades = [Trade(datetime(2026, 7, 9), "AAPL", TradeAction.BUY, 10, 312.0)]
    decisions = {
        "outlook": "NEUTRAL",
        "trades": [{"symbol": "AAPL", "action": "BUY", "reason": "buyback pace and services margin"}],
        "market_calls": [],
    }
    ctx = _agent()._build_context(_portfolio(), trades, decisions)

    assert "BUY AAPL" in ctx
    assert "buyback pace and services margin" in ctx  # the WHY is fed to the model
    # The boring facts are deliberately absent.
    assert "positions" not in ctx.lower()
    assert "27.0%" not in ctx and "cash" not in ctx.lower()


def test_context_surfaces_sharpest_calls_with_direction():
    decisions = {
        "market_calls": [
            {"symbol": "NVDA", "direction": "UNDERPERFORM", "confidence": 0.7, "thesis": "stretched multiple"},
            {"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.65, "thesis": "momentum"},
            {"symbol": "PG", "direction": "OUTPERFORM", "confidence": 0.5, "thesis": "defensive"},
        ],
    }
    ctx = _agent()._build_context(_portfolio(), [], decisions)

    # Highest-conviction call first, with a plain-English direction and the thesis.
    assert "NVDA: lag the S&P 500" in ctx
    assert "70% conviction" in ctx
    assert "stretched multiple" in ctx
    assert "AAPL: beat the S&P 500" in ctx
    # No trades today reads as a hold, not a status dump.
    assert "the fund held" in ctx


def test_context_handles_no_decisions_gracefully():
    ctx = _agent()._build_context(_portfolio(), [], {})
    assert "the fund held" in ctx
    assert "positions" not in ctx.lower()
