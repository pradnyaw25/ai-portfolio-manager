"""RebalanceChecker: don't redeploy cash into names sold this cycle.

The deployment step is LLM-driven and its risk review does real sizing/sector math,
so these tests stub the LLM (to propose a rebuy of a just-sold name) and pass the
risk review through unchanged — isolating the just-sold exclusion itself.
"""

from datetime import date

from src.agents import rebalance_checker as rc
from src.agents.rebalance_checker import RebalanceChecker
from src.agents.risk_manager import RiskReview
from src.llm.schemas import RebalanceResponse
from src.models.portfolio import PortfolioSnapshot, Position
from src.models.prediction import TradePrediction


class _PassthroughRisk:
    """Approve every proposed trade unchanged, so the test isolates the exclusion
    rather than the risk manager's sizing/sector caps."""

    def review(self, raw_trades, portfolio, prices, turnover_override=None):
        approved = [
            TradePrediction(
                symbol=t["symbol"],
                action=t["action"],
                shares=int(t["shares"]),
                confidence=t.get("confidence", 0.7),
                reasoning=t.get("reason", ""),
            )
            for t in raw_trades
        ]
        return RiskReview(approved=approved, rejected=[])


def _research(symbols):
    """A research dict shaped like the real one.

    These tests used to pass ``{"watchlist": [...]}``. Nothing in production ever set
    that key — ``MarketContext`` emits ``symbols`` — so the fixture exercised a branch
    that never ran live while the real branch (an alphabetical ``[:20]`` truncation of
    the universe) went untested for two months. Build the fixture from ``symbols``, the
    key the researcher actually produces.
    """
    return {
        "symbols": [
            {"symbol": s, "price": 100.0, "return_5d": 0.01, "return_30d": 0.02}
            for s in symbols
        ],
        "market_news": [],
    }


def _portfolio_over_cash_target():
    # 30% cash; the $700k filler holding sets total value to $1.0M so the rebalance
    # actually triggers (excess above the 25% target clears the min-deploy floor).
    return PortfolioSnapshot(
        date=date.today(), cash=300_000, positions=[Position("MSFT", 1750, 400, 400)]
    )


def test_rebalance_does_not_rebuy_a_name_sold_this_cycle(monkeypatch):
    approved = [TradePrediction("NVDA", "SELL", 50, 0.9, "trim")]

    def fake_llm(*args, **kwargs):
        return RebalanceResponse(
            action="deploy",
            cash_thesis=None,
            trades=[
                {"symbol": "NVDA", "action": "BUY", "shares": 58, "confidence": 0.85, "reason": "x"},
                {"symbol": "AAPL", "action": "BUY", "shares": 100, "confidence": 0.80, "reason": "y"},
            ],
        )

    monkeypatch.setattr(rc, "complete_structured", fake_llm)
    monkeypatch.setattr(rc, "RiskManagerAgent", _PassthroughRisk)

    result = RebalanceChecker().check(
        portfolio=_portfolio_over_cash_target(),
        approved_trades=approved,
        prices={"NVDA": 140.0, "AAPL": 200.0},
        research=_research(["NVDA", "AAPL"]),
    )

    symbols = {t.symbol for t in result.extra_trades}
    assert "NVDA" not in symbols  # the just-sold name is not rebought
    assert "AAPL" in symbols  # a clean deployment still goes through


def test_rebalance_prompt_names_the_sold_symbols_as_excluded(monkeypatch):
    approved = [TradePrediction("NVDA", "SELL", 50, 0.9, "trim")]
    captured = {}

    def fake_llm(messages, *args, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return RebalanceResponse(
            action="deploy",
            cash_thesis=None,
            trades=[{"symbol": "AAPL", "action": "BUY", "shares": 100, "confidence": 0.8, "reason": "y"}],
        )

    monkeypatch.setattr(rc, "complete_structured", fake_llm)
    monkeypatch.setattr(rc, "RiskManagerAgent", _PassthroughRisk)

    RebalanceChecker().check(
        portfolio=_portfolio_over_cash_target(),
        approved_trades=approved,
        prices={"NVDA": 140.0, "AAPL": 200.0},
        research=_research(["NVDA", "AAPL"]),
    )

    assert "EXCLUSION" in captured["prompt"]
    assert "NVDA" in captured["prompt"].split("EXCLUSION", 1)[1][:100]
    # The sold name is not offered in the candidate price menu either.
    prices_block = captured["prompt"].split("Available prices:", 1)[1]
    assert "NVDA" not in prices_block


def _capture_prompt(monkeypatch, research, prices):
    captured = {}

    def fake_llm(messages, *args, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return RebalanceResponse(action="hold_cash", cash_thesis="waiting", trades=[])

    monkeypatch.setattr(rc, "complete_structured", fake_llm)
    monkeypatch.setattr(rc, "RiskManagerAgent", _PassthroughRisk)
    RebalanceChecker().check(
        portfolio=_portfolio_over_cash_target(),
        approved_trades=[],
        prices=prices,
        research=research,
    )
    return captured["prompt"]


def test_candidate_menu_is_not_truncated(monkeypatch):
    """The whole researched universe must reach the prompt, not an alphabetical slice.

    The old code fell back to ``list(prices.keys())[:20]``, which cut the 14
    alphabetically-last names out of the fund's reach entirely — including XOM, the
    name the PM was most often bullish on while unheld, and held names (NVDA, UNH, V)
    that then couldn't even be topped up.
    """
    universe = [
        "AAPL", "AMD", "AMZN", "APLD", "ASML", "AVGO", "BE", "CAT", "CORZ", "CRWV",
        "GLW", "GOOGL", "HD", "INTC", "IREN", "JNJ", "JPM", "MA", "META", "MSFT",
        "MU", "NVDA", "ORCL", "PG", "SNDK", "TSLA", "TSM", "UNH", "V", "WMT", "XOM",
    ]
    prices = {s: 100.0 for s in universe}
    prompt = _capture_prompt(monkeypatch, _research(universe), prices)

    menu = prompt.split("Available prices:", 1)[1]
    missing = [s for s in universe if f'"{s}"' not in menu]
    assert not missing, f"symbols dropped from the candidate menu: {missing}"


def test_benchmarks_are_not_offered_as_buys(monkeypatch):
    """SPY/QQQ/^VIX are priced for comparison, not investable — ^VIX especially."""
    universe = ["AAPL", "SPY", "QQQ", "^VIX"]
    prompt = _capture_prompt(
        monkeypatch, _research(universe), {s: 100.0 for s in universe}
    )

    menu = prompt.split("Available prices:", 1)[1]
    for benchmark in ("SPY", "QQQ", "^VIX"):
        assert f'"{benchmark}"' not in menu
    assert '"AAPL"' in menu


def test_unheld_names_are_labelled_as_buyable(monkeypatch):
    """The old prompt rendered a literal 'Watchlist: []' — telling the model there
    were no candidates at all. The unheld names must be named explicitly."""
    universe = ["MSFT", "XOM", "ORCL"]
    prompt = _capture_prompt(
        monkeypatch, _research(universe), {s: 100.0 for s in universe}
    )

    # MSFT is the held filler position; XOM and ORCL are not held.
    line = next(ln for ln in prompt.splitlines() if "do not currently hold" in ln)
    assert "XOM" in line and "ORCL" in line
    assert "MSFT" not in line
