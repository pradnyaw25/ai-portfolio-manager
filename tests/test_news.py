"""NewsClient: prefer NewsAPI when keyed, fall back to the keyless RSS feed."""

from types import SimpleNamespace

from src.data_sources import news
from src.data_sources.news import NewsClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload=None, exc=None):
        self.payload = payload
        self.exc = exc
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        if self.exc:
            raise self.exc
        return FakeResponse(self.payload)


def _stub_rss(monkeypatch, titles):
    entries = [
        {"title": t, "link": "l", "published": "p", "source": {"title": "RSS"}} for t in titles
    ]
    monkeypatch.setattr(news.feedparser, "parse", lambda url: SimpleNamespace(entries=entries))


def test_prefers_newsapi_when_key_set(monkeypatch):
    _stub_rss(monkeypatch, ["rss-only"])
    payload = {"articles": [
        {"title": "NA headline", "url": "http://x", "publishedAt": "2026-07-01",
         "source": {"name": "Reuters"}}
    ]}
    session = FakeSession(payload)
    out = NewsClient(api_key="k", session=session).get_stock_news("NVDA", limit=3)

    assert out[0] == {
        "title": "NA headline", "link": "http://x", "published": "2026-07-01",
        "source": "Reuters", "provider": "newsapi",
    }
    assert "NVDA" in session.calls[0]["q"]  # queried NewsAPI


def test_falls_back_to_rss_without_key(monkeypatch):
    _stub_rss(monkeypatch, ["rss headline"])
    out = NewsClient(api_key="", session=FakeSession()).get_market_news(limit=2)
    assert out[0]["title"] == "rss headline"
    assert out[0]["provider"] == "google_news_rss"


def test_falls_back_to_rss_when_newsapi_errors(monkeypatch):
    _stub_rss(monkeypatch, ["rss backup"])
    out = NewsClient(api_key="k", session=FakeSession(exc=RuntimeError("429"))).get_stock_news("AAPL")
    assert out[0]["provider"] == "google_news_rss"


def test_falls_back_to_rss_when_newsapi_returns_nothing(monkeypatch):
    _stub_rss(monkeypatch, ["rss when empty"])
    out = NewsClient(api_key="k", session=FakeSession({"articles": []})).get_stock_news("AAPL")
    assert out[0]["provider"] == "google_news_rss"
