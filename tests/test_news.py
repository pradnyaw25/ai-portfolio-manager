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


def _newsapi_payload(title="NA headline"):
    return {"articles": [
        {"title": title, "url": "http://x", "publishedAt": "2026-07-01", "source": {"name": "Reuters"}}
    ]}


def test_prefers_rss_by_default_even_with_key(monkeypatch):
    _stub_rss(monkeypatch, ["rss headline"])
    session = FakeSession(_newsapi_payload())  # would return NewsAPI if it were queried
    out = NewsClient(api_key="k", prefer_newsapi=False, session=session).get_stock_news("NVDA", limit=3)

    assert out[0]["title"] == "rss headline"
    assert out[0]["provider"] == "google_news_rss"
    assert session.calls == []  # NewsAPI never queried when RSS has results


def test_falls_back_to_newsapi_when_rss_empty(monkeypatch):
    _stub_rss(monkeypatch, [])  # RSS returns nothing
    out = NewsClient(api_key="k", prefer_newsapi=False, session=FakeSession(_newsapi_payload())).get_stock_news("NVDA")
    assert out[0]["provider"] == "newsapi"
    assert out[0]["source"] == "Reuters"


def test_no_newsapi_call_without_key(monkeypatch):
    _stub_rss(monkeypatch, [])  # even with empty RSS, no key → no NewsAPI, returns []
    session = FakeSession(_newsapi_payload())
    out = NewsClient(api_key="", session=session).get_market_news(limit=2)
    assert out == []
    assert session.calls == []


def test_prefer_newsapi_flag_uses_newsapi_first(monkeypatch):
    _stub_rss(monkeypatch, ["rss headline"])
    out = NewsClient(api_key="k", prefer_newsapi=True, session=FakeSession(_newsapi_payload())).get_stock_news("NVDA")
    assert out[0]["provider"] == "newsapi"


def test_prefer_newsapi_falls_back_to_rss_on_error(monkeypatch):
    _stub_rss(monkeypatch, ["rss backup"])
    out = NewsClient(api_key="k", prefer_newsapi=True, session=FakeSession(exc=RuntimeError("429"))).get_stock_news("AAPL")
    assert out[0]["provider"] == "google_news_rss"
