"""Journalling the articles a run actually read.

The researcher has always fetched news normalized to {title, link, published, source}
and put it in the PM prompt, but nothing persisted it — so every decision page cited
zero sources while the reasoning on it was demonstrably news-driven. These cover the
flattening that makes the pages auditable.

Note this accrues FORWARD only: runs journalled before the field existed have no
sources and cannot be backfilled, since there is no record of what they read.
"""

from src.main import MAX_JOURNALLED_SOURCES, collect_news_sources


def _article(n, link=None):
    return {
        "title": f"Headline {n}",
        "link": link or f"https://news.example.com/{n}",
        "source": "Reuters",
        "published": "2026-08-07",
    }


def test_market_and_symbol_news_are_flattened_with_their_symbol():
    sources = collect_news_sources(
        {
            "market_news": [_article("mkt")],
            "symbol_news": {"aapl": [_article("a1")]},
        }
    )

    assert [s["symbol"] for s in sources] == [None, "AAPL"]
    assert sources[0]["title"] == "Headline mkt"
    assert sources[1]["link"] == "https://news.example.com/a1"
    assert sources[1]["source"] == "Reuters"


def test_the_same_article_across_symbols_is_recorded_once():
    """Wire stories routinely match several tickers; the page shouldn't repeat them."""
    shared = _article("shared")
    sources = collect_news_sources(
        {"symbol_news": {"AAPL": [shared], "MSFT": [dict(shared)]}}
    )

    assert len(sources) == 1


def test_articles_without_a_link_or_title_are_dropped():
    """A source with no link can't be cited; one with no title can't be read."""
    sources = collect_news_sources(
        {
            "market_news": [
                {"title": "No link", "link": ""},
                {"title": "", "link": "https://news.example.com/x"},
                _article("good"),
            ]
        }
    )

    assert [s["title"] for s in sources] == ["Headline good"]


def test_source_count_is_capped():
    """decisions.jsonl is already the largest file in data/ and is served whole."""
    sources = collect_news_sources(
        {"market_news": [_article(i) for i in range(MAX_JOURNALLED_SOURCES + 20)]}
    )

    assert len(sources) == MAX_JOURNALLED_SOURCES


def test_missing_or_empty_research_is_safe():
    assert collect_news_sources({}) == []
    assert collect_news_sources({"market_news": None, "symbol_news": None}) == []


def test_malformed_entries_do_not_crash_the_journal():
    """News comes from an external API that degrades to junk on error."""
    sources = collect_news_sources(
        {"market_news": ["not a dict", None, 42, _article("ok")]}
    )

    assert [s["title"] for s in sources] == ["Headline ok"]
