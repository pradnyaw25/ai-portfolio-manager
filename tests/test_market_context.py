"""Market context: news follows signal (held + biggest unheld movers), not just ownership."""

from types import SimpleNamespace

import pandas as pd

from src.research import market_context as mc
from src.research.market_context import MarketContextBuilder


class _FakeMarketData:
    def __init__(self, returns):
        # returns: symbol -> (ret_5d, ret_30d); unmapped symbols are flat.
        self._returns = returns

    def get_prices(self, symbols):
        return {s: 100.0 for s in symbols}

    def get_history(self, symbol, days):
        r5, r30 = self._returns.get(symbol, (0.0, 0.0))
        ret = r5 if days <= 7 else r30
        return pd.DataFrame({"Close": [100.0, 100.0 * (1 + ret)]})


class _FakeNews:
    def __init__(self):
        self.fetched = []

    def get_market_news(self, limit=5):
        return []

    def get_stock_news(self, symbol, limit=3):
        self.fetched.append(symbol)
        return [{"title": f"{symbol} headline"}]


def _snapshot(held):
    positions = [
        SimpleNamespace(
            symbol=s, shares=1, avg_cost=100.0, current_price=100.0, market_value=100.0, return_pct=0.0
        )
        for s in held
    ]
    return SimpleNamespace(positions=positions, total_value=1_000_000, cash=500_000, cash_pct=0.5)


def test_news_covers_held_and_biggest_unheld_movers(monkeypatch):
    monkeypatch.setattr(mc, "WATCHLIST_NEWS_LIMIT", 2)
    # CRWV/IREN are unheld watchlist names with big moves; AAPL is held; MU is flat.
    md = _FakeMarketData({"CRWV": (-0.13, -0.28), "IREN": (-0.04, -0.34)})
    news = _FakeNews()

    ctx = MarketContextBuilder().build(_snapshot(["AAPL"]), md, news).to_dict()

    # the field is now symbol_news, and it carries news for the held name...
    assert "AAPL" in ctx["symbol_news"]
    # ...AND the two biggest unheld movers, so a case can be made to initiate them.
    assert "CRWV" in ctx["symbol_news"]
    assert "IREN" in ctx["symbol_news"]
    # benchmarks never get per-symbol news
    assert "SPY" not in ctx["symbol_news"]
    # a flat, unremarkable unheld name does not crowd out the movers (budget = 2)
    assert "MU" not in ctx["symbol_news"]


def test_no_movers_when_nothing_moves(monkeypatch):
    monkeypatch.setattr(mc, "WATCHLIST_NEWS_LIMIT", 0)
    md = _FakeMarketData({})
    news = _FakeNews()

    ctx = MarketContextBuilder().build(_snapshot(["AAPL"]), md, news).to_dict()

    # only the held name gets news when the mover budget is zero
    assert set(ctx["symbol_news"]) == {"AAPL"}
