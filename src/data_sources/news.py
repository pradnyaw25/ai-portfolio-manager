import time

import feedparser
import requests

from src.config import NEWS_API_KEY, NEWS_MAX_RETRIES, PREFER_NEWSAPI
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
        sleep=None,
    ):
        self.api_key = api_key
        self.prefer_newsapi = prefer_newsapi
        self.session = session or requests.Session()
        # Injectable so tests exercise the retry path without real delays.
        self._sleep = sleep or time.sleep

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

    def _retrying(self, fetch, what: str):
        """Retry a raised error with exponential backoff; give up quietly after that.

        News is a catalyst source, not a price source: losing it degrades the quality
        of a decision rather than invalidating it, so exhausting the retries returns
        an empty list instead of failing the run. That is the opposite call from
        MarketDataClient, deliberately — see its module docstring.
        """
        attempt = 0
        while True:
            try:
                return fetch()
            except Exception as exc:  # noqa: BLE001
                if attempt >= NEWS_MAX_RETRIES:
                    logger.warning(
                        "%s failed after %d attempts: %s", what, attempt + 1, str(exc)[:150]
                    )
                    return None
                delay = 2.0**attempt
                logger.warning(
                    "%s error (attempt %d/%d), backing off %.1fs: %s",
                    what, attempt + 1, NEWS_MAX_RETRIES + 1, delay, str(exc)[:120],
                )
                self._sleep(delay)
                attempt += 1

    def _fetch_newsapi(self, query: str, limit: int) -> list[dict]:
        def call():
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
            return resp.json().get("articles", [])

        articles = self._retrying(call, f"NewsAPI request for {query!r}")
        if articles is None:
            return []
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

    def _fetch_rss(self, query: str, limit: int) -> list[dict]:
        feed = self._retrying(
            lambda: feedparser.parse(GOOGLE_NEWS_RSS.format(query=query)),
            f"RSS news fetch for {query!r}",
        )
        if feed is None:
            return []
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
