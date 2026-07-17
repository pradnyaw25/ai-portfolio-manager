import xml.etree.ElementTree as ET

from src.reporting import decision_pages, letter_pages
from src.storage.investor_letter_store import InvestorLetterStore

SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _letter(week_end, week_start, *, headline="Steady week", return_pct=0.0071, **overrides):
    record = {
        "week_end": week_end,
        "week_start": week_start,
        "letter": {
            "headline": headline,
            "performance": "The portfolio returned 0.71%, beating the S&P 500's 0.44%.",
            "winners": ["META +17.48%", "V +9.37%"],
            "losers": ["None"],
            "portfolio_changes": "Added 55 shares of AAPL and trimmed NVDA by 100.",
            "outlook": "Cautious optimism on selective tech exposure.",
        },
        "facts": {
            "week_start": week_start,
            "week_end": week_end,
            "start_value": 1_022_983.05,
            "end_value": 1_030_219.66,
            "return_pct": return_pct,
            "benchmark_return_pct": 0.0044,
            "alpha": 0.0027,
            "winners": [{"symbol": "META", "return_pct": 0.1748}],
            "losers": [],
            "positions": [],
            "trades": [
                {"date": week_end, "symbol": "AAPL", "action": "BUY", "shares": 55},
                {"date": week_end, "symbol": "NVDA", "action": "SELL", "shares": 100},
            ],
        },
        "markdown": "# Steady week\n",
        "grounding": {"status": "ok"},
    }
    record.update(overrides)
    return record


def test_render_letter_page_has_headline_percent_and_symbol_links():
    page = letter_pages.render_letter_page(_letter("2026-07-12", "2026-07-06"), prev=None, next_=None)

    assert "Steady week" in page
    assert "+0.71%" in page  # decimal 0.0071 rendered as a signed percent
    assert "Alpha +0.27%" in page
    assert "$1,030,220" in page  # end_value formatted as money
    # Winner line "META +17.48%" links the leading ticker to its hub.
    assert 'href="../symbols/META.html"' in page
    # Trades link their tickers too.
    assert 'href="../symbols/AAPL.html"' in page
    assert "BUY 55" in page and "SELL 100" in page
    assert '<link rel="canonical" href="https://glasshousefund.com/letters/2026-07-12.html"' in page


def test_render_letter_page_pager_links_prev_and_next():
    prev = _letter("2026-07-05", "2026-06-29", headline="Prior week")
    nxt = _letter("2026-07-19", "2026-07-13", headline="Next week")
    page = letter_pages.render_letter_page(_letter("2026-07-12", "2026-07-06"), prev=prev, next_=nxt)

    assert 'href="2026-07-05.html">←' in page
    assert 'href="2026-07-19.html">' in page


def test_export_writes_pages_and_index(tmp_path):
    letters = [_letter("2026-07-05", "2026-06-29"), _letter("2026-07-12", "2026-07-06")]
    week_ends = letter_pages.export(letters=letters, public_dir=tmp_path)

    assert week_ends == ["2026-07-05", "2026-07-12"]
    assert (tmp_path / "letters" / "2026-07-05.html").exists()
    assert (tmp_path / "letters" / "2026-07-12.html").exists()
    index = (tmp_path / "letters" / "index.html").read_text()
    assert "2 letters published" in index
    assert 'href="2026-07-12.html"' in index


def test_export_writes_index_even_with_no_letters(tmp_path):
    week_ends = letter_pages.export(letters=[], public_dir=tmp_path)

    assert week_ends == []
    assert (tmp_path / "letters" / "index.html").exists()
    assert not list((tmp_path / "letters").glob("2026-*.html"))


def test_export_reads_from_store(tmp_path):
    store = InvestorLetterStore(path=tmp_path / "investor_letters.jsonl")
    store.record(_letter("2026-07-12", "2026-07-06"))
    loaded = letter_pages.load_letters(store)

    assert [r["week_end"] for r in loaded] == ["2026-07-12"]


def test_sitemap_includes_letter_pages():
    entries = [
        {"date": "2026-07-10", "raw_decision": {"market_calls": [{"symbol": "AAPL"}]},
         "approved_trades": [], "executed_trades": []},
    ]
    xml = decision_pages.build_sitemap(entries, symbols=[], letters=["2026-07-05", "2026-07-12"])
    root = ET.fromstring(xml)
    locs = {u.find("s:loc", SITEMAP_NS).text for u in root.findall("s:url", SITEMAP_NS)}

    assert "https://glasshousefund.com/letters/" in locs
    assert "https://glasshousefund.com/letters/2026-07-12.html" in locs
    assert "https://glasshousefund.com/letters/2026-07-05.html" in locs


def test_sitemap_omits_letters_when_none():
    entries = [
        {"date": "2026-07-10", "raw_decision": {"market_calls": [{"symbol": "AAPL"}]},
         "approved_trades": [], "executed_trades": []},
    ]
    xml = decision_pages.build_sitemap(entries, symbols=[], letters=None)

    assert "/letters/" not in xml
