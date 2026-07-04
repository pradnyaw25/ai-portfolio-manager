import feedparser
import requests

from src.config import NEWS_API_KEY, PREFER_NEWSAPI
from src.utils.logger import get_logger

logger = get_logger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
NEWSAPI_URL = "https://newsapi.org/v2/everything"


class NewsClient:
    """Fetches news, normalized to ``{title, link, published, source, provider}``.

    Defaults to the keyless, real-time Google News RSS feed. NewsAPI.org is used
    only as a fallback when RSS returns nothing (and a key is set) — unless
    ``PREFER_NEWSAPI`` is set, which flips the order (better on a paid plan).
    """

    def __init__(
        self,
        api_key: str = NEWS_API_KEY,
        prefer_newsapi: bool = PREFER_NEWSAPI,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.prefer_newsapi = prefer_newsapi
        self.session = session or requests.Session()

    def get_stock_news(self, symbol: str, limit: int = 5) -> list[dict]:
        return self._fetch(newsapi_query=f"{symbol} stock", rss_query=f"{symbol}+stock", limit=limit)

    def get_market_news(self, limit: int = 10) -> list[dict]:
        return self._fetch(newsapi_query="stock market", rss_query="stock+market", limit=limit)

    def _fetch(self, *, newsapi_query: str, rss_query: str, limit: int) -> list[dict]:
        if self.api_key and self.prefer_newsapi:
            return self._fetch_newsapi(newsapi_query, limit) or self._fetch_rss(rss_query, limit)
        # RSS-first (default): fall back to NewsAPI only when RSS is empty and keyed.
        articles = self._fetch_rss(rss_query, limit)
        if not articles and self.api_key:
            articles = self._fetch_newsapi(newsapi_query, limit)
        return articles

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
