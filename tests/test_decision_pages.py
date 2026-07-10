import xml.etree.ElementTree as ET

from src.reporting import decision_pages

SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _entry(date_str, *, created_at, summary="Summary text.", trades=None, debate=None, **extra):
    row = {
        "date": date_str,
        "created_at": created_at,
        "run_id": f"run_{created_at}",
        "portfolio": {"total_value": 1_000_000, "cash": 100_000, "cash_pct": 0.1},
        "raw_decision": {
            "outlook": "NEUTRAL",
            "summary": summary,
            "trades": trades or [],
            "debate": debate or {},
        },
        "approved_trades": [],
        "rejected_trades": [],
        "executed_trades": [],
        "grounding": {"status": "ok"},
    }
    row.update(extra)
    return row


def test_latest_per_date_keeps_only_the_last_run_of_each_day():
    rows = [
        _entry("2026-06-13", created_at="2026-06-13T01:00:00Z", summary="first"),
        _entry("2026-06-13", created_at="2026-06-13T09:00:00Z", summary="last"),
        _entry("2026-06-12", created_at="2026-06-12T05:00:00Z", summary="prior day"),
    ]
    entries = decision_pages.latest_per_date(rows)

    assert [e["date"] for e in entries] == ["2026-06-12", "2026-06-13"]  # oldest first
    assert entries[1]["raw_decision"]["summary"] == "last"


def test_latest_per_date_skips_unpublishable_rows():
    rows = [
        _entry("2026-06-11", created_at="2026-06-11T01:00:00Z"),
        {"date": "2026-06-12", "created_at": "x"},  # no raw_decision
        {"created_at": "y", "raw_decision": {}},  # no date
    ]
    assert [e["date"] for e in decision_pages.latest_per_date(rows)] == ["2026-06-11"]


def test_page_renders_debate_and_trades_as_server_side_text():
    entry = _entry(
        "2026-07-07",
        created_at="2026-07-07T12:00:00Z",
        summary="Bought Apple.",
        trades=[{"symbol": "AAPL", "action": "BUY", "reason": "Buybacks", "risks": ["Volatility"]}],
        debate={
            "bull": {"thesis": "Momentum is strong", "key_points": ["Buyback program"], "conviction": 0.8},
            "bear": {"thesis": "Valuation is stretched", "key_points": []},
        },
        approved_trades=[
            {"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.85, "reasoning": "Buybacks"}
        ],
        executed_trades=[{"symbol": "AAPL", "action": "BUY", "shares": 10, "price": 312.83}],
    )
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)

    # The whole point: this text exists without running JavaScript.
    assert "Momentum is strong" in html
    assert "Valuation is stretched" in html
    assert "Buyback program" in html
    assert "Volatility" in html
    assert 'BUY 10 <a class="sym-link" href="../symbols/AAPL.html">AAPL</a>' in html  # ticker links to its hub
    assert "filled at $313" in html
    assert "conviction 0.80" in html

    # SEO surface
    assert '<link rel="canonical" href="https://glasshousefund.com/decisions/2026-07-07.html" />' in html
    assert 'property="og:url" content="https://glasshousefund.com/decisions/2026-07-07.html"' in html
    assert "<title>AI fund buys AAPL — July 7, 2026</title>" in html
    assert 'name="description" content="BUY AAPL.' in html


def test_page_escapes_html_in_model_output():
    entry = _entry(
        "2026-07-07",
        created_at="2026-07-07T12:00:00Z",
        summary='<script>alert("xss")</script>',
        debate={"bull": {"thesis": "a < b & c", "key_points": ["<img src=x>"]}},
    )
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html
    assert "a &lt; b &amp; c" in html
    assert "&lt;img src=x&gt;" in html


def test_page_handles_a_day_with_no_trades_and_no_debate():
    entry = _entry("2026-06-29", created_at="2026-06-29T12:00:00Z", summary="Held.")
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)

    assert "No trades this day — the fund held." in html
    assert "The debate" not in html  # section omitted rather than left empty
    assert "The fund held — no trades." in html  # description fallback


def test_market_calls_render_direction_and_traded_tag():
    entry = _entry(
        "2026-07-08",
        created_at="2026-07-08T12:00:00Z",
        summary="Bought Apple, watching the rest.",
        executed_trades=[{"symbol": "AAPL", "action": "BUY", "shares": 10, "price": 200.0}],
    )
    entry["raw_decision"]["market_calls"] = [
        {"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.7, "thesis": "buyback momentum"},
        {"symbol": "NVDA", "direction": "UNDERPERFORM", "confidence": 0.55, "thesis": "stretched multiple"},
        {"symbol": "JNJ", "direction": "OUTPERFORM", "confidence": 0.6, "thesis": "defensive"},
    ]
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)

    assert "<h2>Market calls</h2>" in html
    assert "Outperform SPY" in html and "Underperform SPY" in html
    assert "buyback momentum" in html and "stretched multiple" in html
    # AAPL was bought → tagged; NVDA/JNJ were only called, not traded.
    aapl_row = html.split(">AAPL<", 1)[1].split("</tr>", 1)[0]
    nvda_row = html.split(">NVDA<", 1)[1].split("</tr>", 1)[0]
    assert "traded" in aapl_row
    assert "traded" not in nvda_row
    # Highest-confidence call (AAPL 0.70) is listed before the lower ones.
    assert html.index(">AAPL<") < html.index(">JNJ<") < html.index(">NVDA<")
    assert "3 calls (2 outperform, 1 underperform); 1 became trades" in html


def test_market_calls_section_omitted_when_absent():
    entry = _entry("2026-06-29", created_at="2026-06-29T12:00:00Z", summary="Held.")
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)
    assert "Market calls" not in html  # legacy rows carry no calls — no empty section


def test_market_call_thesis_is_escaped():
    entry = _entry("2026-07-08", created_at="2026-07-08T12:00:00Z")
    entry["raw_decision"]["market_calls"] = [
        {"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.7, "thesis": "<b>a & b</b>"}
    ]
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)
    assert "<b>a & b</b>" not in html
    assert "&lt;b&gt;a &amp; b&lt;/b&gt;" in html


def test_pager_links_neighbouring_days():
    a = _entry("2026-07-01", created_at="2026-07-01T00:00:00Z")
    b = _entry("2026-07-02", created_at="2026-07-02T00:00:00Z")
    c = _entry("2026-07-03", created_at="2026-07-03T00:00:00Z")

    html = decision_pages.render_decision_page(b, prev=a, next_=c)
    assert 'href="2026-07-01.html">← July 1, 2026' in html
    assert 'href="2026-07-03.html">July 3, 2026 →' in html

    first = decision_pages.render_decision_page(a, prev=None, next_=b)
    assert "←" not in first


def test_rejected_trades_are_shown_with_their_reason():
    entry = _entry(
        "2026-07-07",
        created_at="2026-07-07T12:00:00Z",
        rejected_trades=[{"symbol": "PG", "action": "BUY", "shares": 20, "reason": "missing market price"}],
    )
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)
    assert 'BUY 20 <a class="sym-link" href="../symbols/PG.html">PG</a>' in html
    assert "Rejected by the risk engine: missing market price" in html


def test_sitemap_is_valid_xml_and_covers_every_page():
    entries = [
        _entry("2026-07-06", created_at="2026-07-06T00:00:00Z", debate={"bull": {"thesis": "x"}}),
        _entry("2026-07-07", created_at="2026-07-07T00:00:00Z", debate={"bull": {"thesis": "x"}}),
    ]
    xml = decision_pages.build_sitemap(entries)
    root = ET.fromstring(xml)
    locs = [e.text for e in root.findall(".//s:loc", SITEMAP_NS)]

    assert "https://glasshousefund.com/" in locs
    assert "https://glasshousefund.com/engineering.html" in locs
    assert "https://glasshousefund.com/decisions/" in locs
    assert "https://glasshousefund.com/decisions/2026-07-07.html" in locs
    assert "https://glasshousefund.com/decisions/2026-07-06.html" in locs
    assert len(locs) == len(set(locs)), "sitemap must not repeat a URL"
    # No stale /architecture.html, which was renamed to /engineering.html.
    assert not any("architecture" in loc for loc in locs)


def test_sitemap_lastmod_uses_each_decision_date():
    entries = [
        _entry("2026-07-06", created_at="x", debate={"bull": {"thesis": "x"}}),
        _entry("2026-07-07", created_at="y", debate={"bull": {"thesis": "x"}}),
    ]
    root = ET.fromstring(decision_pages.build_sitemap(entries))

    for url in root.findall("s:url", SITEMAP_NS):
        loc = url.find("s:loc", SITEMAP_NS).text
        lastmod = url.find("s:lastmod", SITEMAP_NS)
        if loc.endswith("2026-07-06.html"):
            assert lastmod.text == "2026-07-06"
        if loc.endswith("engineering.html"):
            assert lastmod is None, "static pages carry no lastmod"


def test_sitemap_with_no_decisions_still_lists_static_pages():
    root = ET.fromstring(decision_pages.build_sitemap([]))
    locs = [e.text for e in root.findall(".//s:loc", SITEMAP_NS)]
    assert "https://glasshousefund.com/" in locs
    assert not any("/decisions/2" in loc for loc in locs)


def test_export_writes_pages_index_and_sitemap(tmp_path):
    rows = [
        _entry("2026-07-06", created_at="2026-07-06T00:00:00Z"),
        _entry("2026-07-07", created_at="2026-07-07T01:00:00Z", summary="superseded"),
        _entry("2026-07-07", created_at="2026-07-07T09:00:00Z", summary="final word"),
    ]
    dates = decision_pages.export(rows, public_dir=tmp_path)

    assert dates == ["2026-07-06", "2026-07-07"]
    assert (tmp_path / "decisions" / "2026-07-07.html").exists()
    assert (tmp_path / "decisions" / "index.html").exists()
    assert (tmp_path / "sitemap.xml").exists()

    page = (tmp_path / "decisions" / "2026-07-07.html").read_text()
    assert "final word" in page and "superseded" not in page

    index = (tmp_path / "decisions" / "index.html").read_text()
    assert index.index("2026-07-07.html") < index.index("2026-07-06.html"), "index is newest-first"

    ET.fromstring((tmp_path / "sitemap.xml").read_text())  # parses


def test_export_with_empty_journal_does_not_crash(tmp_path):
    assert decision_pages.export([], public_dir=tmp_path) == []
    assert (tmp_path / "decisions" / "index.html").exists()
    ET.fromstring((tmp_path / "sitemap.xml").read_text())


def test_latest_per_date_parses_offset_timestamps_not_strings():
    # run_late is 20:00Z; run_early is 01:00+05:30 == 19:30Z, so run_late is truly
    # the last run. Lexically "2026-07-08..." > "2026-07-07...", so a string compare
    # would wrongly pick run_early; parsing to real instants picks run_late.
    rows = [
        _entry("2026-07-07", created_at="2026-07-08T01:00:00+05:30", summary="earlier run"),
        _entry("2026-07-07", created_at="2026-07-07T20:00:00Z", summary="correct latest"),
    ]
    entries = decision_pages.latest_per_date(rows)
    assert len(entries) == 1
    assert entries[0]["raw_decision"]["summary"] == "correct latest"


def test_title_and_h1_carry_the_traded_symbols():
    entry = _entry(
        "2026-07-07",
        created_at="2026-07-07T12:00:00Z",
        approved_trades=[
            {"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.8},
            {"symbol": "NVDA", "action": "SELL", "shares": 5, "confidence": 0.7},
        ],
    )
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)
    assert "<title>AI fund buys AAPL, sells NVDA — July 7, 2026</title>" in html
    assert "<h1>AI fund buys AAPL, sells NVDA — July 7, 2026</h1>" in html


def test_hold_day_title_falls_back_to_plain_decision():
    entry = _entry("2026-06-29", created_at="2026-06-29T12:00:00Z", summary="Held.")
    html = decision_pages.render_decision_page(entry, prev=None, next_=None)
    assert "<title>AI fund decision — June 29, 2026</title>" in html


def test_thin_page_is_noindexed_and_excluded_from_sitemap():
    thin = _entry("2026-06-12", created_at="2026-06-12T12:00:00Z", summary="Held, no debate.")
    rich = _entry(
        "2026-07-07",
        created_at="2026-07-07T12:00:00Z",
        approved_trades=[{"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.8}],
    )
    thin_html = decision_pages.render_decision_page(thin, prev=None, next_=None)
    rich_html = decision_pages.render_decision_page(rich, prev=None, next_=None)
    assert '<meta name="robots" content="noindex,follow" />' in thin_html
    assert 'name="robots"' not in rich_html  # substantial pages are indexable

    xml = decision_pages.build_sitemap([thin, rich])
    assert "https://glasshousefund.com/decisions/2026-07-07.html" in xml
    assert "2026-06-12.html" not in xml  # thin day stays out of the sitemap


def test_symbol_touches_orders_newest_first_across_trades_and_calls():
    e1 = _entry(
        "2026-07-01",
        created_at="2026-07-01T12:00:00Z",
        approved_trades=[{"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.8}],
    )
    e2 = _entry("2026-07-02", created_at="2026-07-02T12:00:00Z")
    e2["raw_decision"]["market_calls"] = [
        {"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.6, "thesis": "buybacks"}
    ]
    touches = decision_pages._symbol_touches([e1, e2])  # oldest-first input
    assert [t["date"] for t in touches["AAPL"]] == ["2026-07-02", "2026-07-01"]  # newest first
    assert touches["AAPL"][0]["call"]["thesis"] == "buybacks"
    assert touches["AAPL"][1]["trades"][0]["action"] == "BUY"


def test_non_ticker_symbols_get_no_hub_page(tmp_path):
    # ^VIX can't be a filename/URL and isn't tradable — it must not spawn a hub.
    e = _entry("2026-07-01", created_at="2026-07-01T12:00:00Z")
    e["raw_decision"]["market_calls"] = [
        {"symbol": "^VIX", "direction": "OUTPERFORM", "confidence": 0.5, "thesis": "x"}
    ]
    decision_pages.export([e], public_dir=tmp_path)
    assert not (tmp_path / "symbols" / "^VIX.html").exists()


def test_export_generates_a_hub_for_every_symbol_and_links_them(tmp_path):
    from src.config import WATCHLIST

    rows = [
        _entry(
            d,
            created_at=f"{d}T12:00:00Z",
            approved_trades=[{"symbol": "AAPL", "action": "BUY", "shares": 10, "confidence": 0.8}],
        )
        for d in ("2026-07-01", "2026-07-02")
    ]
    decision_pages.export(rows, public_dir=tmp_path)
    sym_dir = tmp_path / "symbols"

    # A touched symbol → real hub, indexable, in the sitemap.
    aapl = (sym_dir / "AAPL.html").read_text()
    assert "../decisions/2026-07-02.html" in aapl
    assert 'name="robots"' not in aapl

    # A universe symbol never touched → placeholder hub that still exists (no 404),
    # noindexed and kept out of the sitemap until it has content.
    untouched = next(s for s in WATCHLIST if s not in {"AAPL"})
    placeholder = (sym_dir / f"{untouched}.html").read_text()
    assert "hasn't traded or made a directional call" in placeholder
    assert '<meta name="robots" content="noindex,follow" />' in placeholder

    # Decision pages link each traded ticker to its hub.
    day = (tmp_path / "decisions" / "2026-07-01.html").read_text()
    assert 'href="../symbols/AAPL.html"' in day

    sitemap = (tmp_path / "sitemap.xml").read_text()
    assert "https://glasshousefund.com/symbols/AAPL.html" in sitemap
    assert f"/symbols/{untouched}.html" not in sitemap  # empty placeholder excluded
