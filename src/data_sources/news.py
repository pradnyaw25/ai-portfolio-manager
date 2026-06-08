import requests
import feedparser
from src.config import NEWS_API_KEY
from src.utils.logger import get_logger

logger = get_logger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


class NewsClient:
    def get_stock_news(self, symbol: str, limit: int = 5) -> list[dict]:
        try:
            feed = feedparser.parse(GOOGLE_NEWS_RSS.format(query=f"{symbol}+stock"))
            articles = []
            for entry in feed.entries[:limit]:
                articles.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": entry.get("source", {}).get("title", ""),
                })
            return articles
        except Exception as e:
            logger.warning("Failed to fetch news for %s: %s", symbol, e)
            return []

    def get_market_news(self, limit: int = 10) -> list[dict]:
        return self.get_stock_news("stock+market", limit=limit)

    def get_news_via_api(self, query: str, limit: int = 5) -> list[dict]:
        if not NEWS_API_KEY:
            logger.warning("NEWS_API_KEY not set, skipping API news")
            return []
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "sortBy": "publishedAt",
            "pageSize": limit,
            "apiKey": NEWS_API_KEY,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json().get("articles", [])
        except Exception as e:
            logger.warning("NewsAPI request failed: %s", e)
            return []
