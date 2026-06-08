from src.data_sources.market_data import MarketDataClient
from src.data_sources.news import NewsClient
from src.models.portfolio import Position
from src.utils.logger import get_logger

logger = get_logger(__name__)

WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "JPM", "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD",
]


class ResearchAgent:
    def analyze(
        self,
        holdings: list[Position],
        market_data: MarketDataClient,
        news_client: NewsClient,
    ) -> dict:
        logger.info("Running market research")

        held_symbols = [p.symbol for p in holdings]
        all_symbols = list(set(held_symbols + WATCHLIST))

        prices = market_data.get_prices(all_symbols)
        movers = market_data.get_top_movers(all_symbols, days=5)
        market_news = news_client.get_market_news(limit=5)

        holdings_news = {}
        for symbol in held_symbols[:5]:
            holdings_news[symbol] = news_client.get_stock_news(symbol, limit=3)

        return {
            "prices": prices,
            "top_movers": movers[:10],
            "market_news": [
                {"title": n["title"], "source": n.get("source", "")}
                for n in market_news
            ],
            "holdings_news": {
                sym: [{"title": n["title"]} for n in articles]
                for sym, articles in holdings_news.items()
            },
            "watchlist": WATCHLIST,
        }
