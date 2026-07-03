import feedparser
import requests

from src.config import NEWS_API_KEY
from src.utils.logger import get_logger

logger = get_logger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
NEWSAPI_URL = "https://newsapi.org/v2/everything"


class NewsClient:
    """Fetches news, normalized to ``{title, link, published, source, provider}``.

    Prefers NewsAPI.org when ``NEWS_API_KEY`` is set (richer, structured), and
    falls back to the keyless Google News RSS feed when the key is absent or a
    NewsAPI request fails or returns nothing.
    """

    def __init__(self, api_key: str = NEWS_API_KEY, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()

    def get_stock_news(self, symbol: str, limit: int = 5) -> list[dict]:
        if self.api_key:
            articles = self._fetch_newsapi(f"{symbol} stock", limit)
            if articles:
                return articles
        return self._fetch_rss(f"{symbol}+stock", limit)

    def get_market_news(self, limit: int = 10) -> list[dict]:
        if self.api_key:
            articles = self._fetch_newsapi("stock market", limit)
            if articles:
                return articles
        return self._fetch_rss("stock+market", limit)

    def _fetch_newsapi(self, query: str, limit: int) -> list[dict]:
        try:
            resp = self.session.get(
                NEWSAPI_URL,
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": limit,
                    "apiKey": self.api_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            return [
                {
                    "title": a.get("title", ""),
                    "link": a.get("url", ""),
                    "published": a.get("publishedAt", ""),
                    "source": (a.get("source") or {}).get("name", ""),
                    "provider": "newsapi",
                }
                for a in articles[:limit]
            ]
        except Exception as exc:
            logger.warning("NewsAPI request failed for %r: %s — falling back to RSS", query, exc)
            return []

    def _fetch_rss(self, query: str, limit: int) -> list[dict]:
        try:
            feed = feedparser.parse(GOOGLE_NEWS_RSS.format(query=query))
            return [
                {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": (entry.get("source") or {}).get("title", ""),
                    "provider": "google_news_rss",
                }
                for entry in feed.entries[:limit]
            ]
        except Exception as exc:
            logger.warning("RSS news fetch failed for %r: %s", query, exc)
            return []
