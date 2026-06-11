from dataclasses import dataclass, asdict
from datetime import date

from src.models.portfolio import PortfolioSnapshot


WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "JPM", "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD",
]


@dataclass
class SymbolContext:
    symbol: str
    price: float | None
    return_5d: float | None
    return_30d: float | None


@dataclass
class MarketContext:
    date: str
    portfolio_value: float
    cash: float
    cash_pct: float
    holdings: list[dict]
    symbols: list[SymbolContext]
    market_news: list[dict]
    holdings_news: dict[str, list[dict]]

    def to_dict(self) -> dict:
        return asdict(self)


class MarketContextBuilder:
    def build(self, snapshot: PortfolioSnapshot, market_data, news_client) -> MarketContext:
        held_symbols = [p.symbol for p in snapshot.positions]
        symbols = sorted(set(held_symbols + WATCHLIST + ["SPY", "QQQ", "^VIX"]))

        prices = market_data.get_prices(symbols)

        symbol_contexts = []
        for symbol in symbols:
            symbol_contexts.append(
                SymbolContext(
                    symbol=symbol,
                    price=prices.get(symbol),
                    return_5d=self._safe_return(market_data, symbol, days=7),
                    return_30d=self._safe_return(market_data, symbol, days=35),
                )
            )

        market_news = news_client.get_market_news(limit=5)

        holdings_news = {}
        for symbol in held_symbols[:8]:
            holdings_news[symbol] = news_client.get_stock_news(symbol, limit=3)

        return MarketContext(
            date=date.today().isoformat(),
            portfolio_value=snapshot.total_value,
            cash=snapshot.cash,
            cash_pct=snapshot.cash_pct,
            holdings=[
                {
                    "symbol": p.symbol,
                    "shares": p.shares,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "return_pct": p.return_pct,
                }
                for p in snapshot.positions
            ],
            symbols=symbol_contexts,
            market_news=[
                {
                    "title": n.get("title", ""),
                    "source": n.get("source", ""),
                    "published": n.get("published", ""),
                }
                for n in market_news
            ],
            holdings_news={
                symbol: [
                    {
                        "title": article.get("title", ""),
                        "source": article.get("source", ""),
                        "published": article.get("published", ""),
                    }
                    for article in articles
                ]
                for symbol, articles in holdings_news.items()
            },
        )

    def _safe_return(self, market_data, symbol: str, days: int) -> float | None:
        try:
            hist = market_data.get_history(symbol, days=days)
            if hist.empty or len(hist) < 2:
                return None

            start_price = float(hist["Close"].iloc[0])
            end_price = float(hist["Close"].iloc[-1])

            if start_price <= 0:
                return None

            return (end_price / start_price) - 1
        except Exception:
            return None
