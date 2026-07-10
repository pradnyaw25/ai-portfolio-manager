"""Prerender the decision journal to static, indexable pages.

``public/decisions.html`` fetches ``decisions.jsonl`` client-side, so every decision
the fund has ever made collapses into a single URL with no server-rendered text.
Googlebot does run JS, but on a deferred second pass — the richest content on the
site is the content search engines are least likely to see.

This module emits one page per trading *day* — full debate, cash thesis, and trades
as real HTML — plus a ``/decisions/`` index and the site ``sitemap.xml``.

One page per date, not per run: the journal holds one row per run, and a single day
can carry many runs (re-runs, dev churn). The last run of a date is that day's
decision; earlier rows are superseded and are not published.
"""

import json
import re
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from src.config import DATA_DIR, WATCHLIST
from src.utils.logger import get_logger

logger = get_logger(__name__)

PUBLIC_DIR = Path("public")
SITE = "https://glasshousefund.com"

# Pages that exist as hand-authored files. Dynamic ones get the latest decision date
# as lastmod; the two static ones get none, which is valid and avoids daily churn.
STATIC_PAGES: list[tuple[str, str, str, bool]] = [
    # (path, changefreq, priority, dynamic)
    ("", "daily", "1.0", True),
    ("dashboard.html", "daily", "0.9", True),
    ("decisions.html", "daily", "0.8", True),
    ("predictions.html", "daily", "0.9", True),
    ("engineering.html", "monthly", "0.7", False),
    ("about.html", "monthly", "0.7", False),
]

_BRAND_SVG = (
    '<svg class="brand-mark" viewBox="0 0 48 48" fill="none" aria-hidden="true">'
    '<g stroke="currentColor" stroke-linejoin="round" stroke-linecap="round">'
    '<path d="M24 5 L43 21 L43 43 L5 43 L5 21 Z" stroke-width="2.4"/>'
    '<path d="M5 21 L43 21" stroke-width="2"/><path d="M24 5 L24 21" stroke-width="1.6"/>'
    '<path d="M16 21 L16 43 M32 21 L32 43" stroke-width="1.6"/>'
    '<path d="M5 32 L43 32" stroke-width="1.6"/></g></svg>'
)

_CSS = """
:root { color-scheme: light dark;
  --bg:#e9ecdf; --surface:#f3f5ec; --surface-subtle:#e1e5d4; --border:#cdd4bd;
  --border-strong:#b4bd9f; --text:#191c11; --muted:#5e6851; --muted-strong:#3f4834;
  --positive:#4d6a2c; --positive-bg:#dde7ca; --negative:#9c3a30; --negative-bg:#f0dbd6;
  --accent:#5f6b45; --ink:#12140d; --shadow:0 12px 34px rgba(18,20,13,.10);
  --row-border:#dde2d0; --panel-subtle:#eef1e6; }
:root[data-theme="dark"] {
  --bg:#12140d; --surface:#1b1e14; --surface-subtle:#24281a; --border:#343a28;
  --border-strong:#4a5138; --text:#e4e8d5; --muted:#99a487; --muted-strong:#c3ccb1;
  --positive:#a6c07f; --positive-bg:#1b2712; --negative:#e59a90; --negative-bg:#2f1a16;
  --accent:#aeba90; --ink:#f1f4e7; --shadow:0 16px 42px rgba(0,0,0,.40);
  --row-border:#2a2f1f; --panel-subtle:#15170f; }
* { box-sizing:border-box; }
body { margin:0; min-width:320px; background:var(--bg); color:var(--text);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.6; }
a { color:inherit; }
.shell { width:min(860px, calc(100% - 32px)); margin:0 auto; padding:22px 0 60px; }
.topbar { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:34px; }
.brand { display:flex; align-items:center; gap:10px; font-weight:800; color:var(--ink); text-decoration:none; }
.brand-mark { display:block; width:30px; height:30px; color:var(--ink); flex:none; }
.nav { display:flex; gap:4px; flex-wrap:wrap; }
.nav a { display:inline-flex; align-items:center; min-height:34px; padding:0 12px; border-radius:6px;
  color:var(--muted-strong); font-size:14px; font-weight:700; text-decoration:none; white-space:nowrap; }
.nav a.active { background:var(--ink); color:var(--bg); }
.nav a:hover:not(.active) { background:var(--surface-subtle); }
.eyebrow { color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.1em;
  text-transform:uppercase; margin-bottom:12px; }
h1 { margin:0 0 10px; color:var(--ink); font-size:clamp(26px,4.4vw,40px); line-height:1.08; letter-spacing:-.02em; }
h2 { color:var(--ink); font-size:19px; margin:34px 0 8px; }
h3 { color:var(--ink); font-size:15px; margin:0 0 6px; }
p { margin:0 0 12px; }
.lede { color:var(--muted-strong); font-size:17px; max-width:64ch; margin:0 0 10px; }
.facts { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0 8px; }
.pill { border:1px solid var(--border-strong); border-radius:999px; background:var(--panel-subtle);
  padding:3px 11px; font-size:12.5px; font-weight:700; color:var(--muted-strong); }
.card { border:1px solid var(--border); border-radius:12px; background:var(--surface);
  box-shadow:var(--shadow); padding:18px 20px; margin-bottom:12px; }
.trade { border:1px solid var(--border); border-left:4px solid var(--positive); border-radius:8px;
  background:var(--surface); padding:12px 14px; margin-bottom:10px; }
.trade.sell { border-left-color:var(--negative); }
.trade.rejected { border-left-color:var(--muted); opacity:.85; }
.trade .head { color:var(--ink); font-weight:800; font-size:15px; }
.conf { border-radius:5px; background:var(--positive-bg); color:var(--positive);
  padding:1px 7px; font-size:12px; font-weight:800; margin-left:6px; }
.calls-wrap { overflow-x:auto; margin:6px 0 12px; }
.calls { width:100%; border-collapse:collapse; font-size:13.5px; }
.calls th { text-align:left; font-size:11.5px; text-transform:uppercase; letter-spacing:.05em;
  color:var(--muted); font-weight:800; padding:6px 12px 6px 0; border-bottom:1px solid var(--border); white-space:nowrap; }
.calls td { padding:7px 12px 7px 0; border-bottom:1px solid var(--row-border); vertical-align:top; }
.calls td.sym { font-weight:800; color:var(--ink); white-space:nowrap; }
.dir { display:inline-block; border-radius:5px; padding:1px 7px; font-size:12px; font-weight:800; white-space:nowrap; }
.dir.up { background:var(--positive-bg); color:var(--positive); }
.dir.down { background:var(--negative-bg); color:var(--negative); }
.tag { display:inline-block; border:1px solid var(--border-strong); border-radius:999px;
  padding:0 8px; font-size:11px; font-weight:800; color:var(--muted-strong); white-space:nowrap; }
.muted { color:var(--muted); }
ul { margin:6px 0 0; padding-left:20px; }
li { margin-bottom:4px; }
.role { font-size:11.5px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; color:var(--accent); }
.shead { display:flex; flex-wrap:wrap; align-items:center; gap:8px; color:var(--ink); font-weight:800; font-size:14px; }
.shead a { text-decoration:none; }
.shead a:hover { text-decoration:underline; }
.sym-link { color:inherit; text-decoration:none; border-bottom:1px dotted var(--border-strong); }
.sym-link:hover { border-bottom-color:currentColor; }
.pager { display:flex; justify-content:space-between; gap:12px; margin-top:40px;
  border-top:1px solid var(--row-border); padding-top:16px; font-size:14px; font-weight:700; }
.dlist { list-style:none; margin:0; padding:0; }
.dlist li { border-bottom:1px solid var(--row-border); padding:12px 0; margin:0; }
.dlist a { color:var(--ink); font-weight:800; text-decoration:none; font-size:16px; }
.dlist a:hover { text-decoration:underline; }
.dlist .sub { color:var(--muted); font-size:13.5px; }
footer { margin-top:48px; border-top:1px solid var(--row-border); padding-top:16px;
  color:var(--muted); font-size:13px; }
@media (max-width:560px) {
  .topbar { flex-direction:column; align-items:flex-start; gap:12px; }
  .nav a { padding:0 9px; font-size:13px; }
}
"""

_THEME_SCRIPT = """
(function () {
  try {
    var stored = localStorage.getItem("ai-portfolio-theme");
    var theme = (stored === "light" || stored === "dark")
      ? stored
      : (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {}
})();
"""


def _fmt_date(iso: str) -> str:
    """2026-07-07 -> July 7, 2026. Falls back to the raw string if unparseable."""
    try:
        return date.fromisoformat(iso).strftime("%B %-d, %Y")
    except ValueError:
        return iso


def _money(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _is_substantial(entry: dict) -> bool:
    """Whether a day's page clears the bar to be indexed: it has a real debate, at
    least one trade, or a market-calls table. Thin backfill days (no debate, no
    trades, no calls) are kept as permalinks for the audit trail but marked
    noindex and left out of the sitemap, so a handful of near-empty stubs don't
    dilute the crawlable corpus."""
    rd = entry.get("raw_decision") or {}
    debate = rd.get("debate") or {}
    has_debate = any(
        isinstance(debate.get(role), dict) and debate[role].get("thesis")
        for role in ("bull", "bear", "risk")
    )
    has_trade = bool(entry.get("approved_trades") or entry.get("executed_trades"))
    has_calls = bool(rd.get("market_calls"))
    return has_debate or has_trade or has_calls


def _shell(
    *, title: str, description: str, canonical: str, body: str, active: str = "", robots: str = ""
) -> str:
    """Wrap page content in the site chrome. All decision pages sit one level deep,
    so sibling links are prefixed with ``../``."""

    def nav(href: str, label: str) -> str:
        cls = ' class="active"' if href == active else ""
        return f'<a{cls} href="../{href}">{escape(label)}</a>'

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <title>{escape(title)}</title>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script>{_THEME_SCRIPT}</script>
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-MCDDGJ3XEC"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-MCDDGJ3XEC');
  </script>
  <link rel="icon" href="../favicon.svg" type="image/svg+xml" />
  <link rel="canonical" href="{escape(canonical)}" />{f'''
  <meta name="robots" content="{escape(robots)}" />''' if robots else ""}
  <meta name="description" content="{escape(description)}" />
  <meta name="author" content="Pradnya Wakchaure" />
  <meta property="og:type" content="article" />
  <meta property="og:url" content="{escape(canonical)}" />
  <meta property="og:title" content="{escape(title)}" />
  <meta property="og:description" content="{escape(description)}" />
  <meta property="og:image" content="{SITE}/og-cover.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:site" content="@GlassHouseFund" />
  <style>{_CSS}</style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <a class="brand" href="../index.html">{_BRAND_SVG}<span>Glasshouse Fund</span></a>
      <nav class="nav" aria-label="Site navigation">
        {nav("dashboard.html", "Dashboard")}
        {nav("decisions.html", "Decision Journal")}
        {nav("predictions.html", "Prediction Accuracy")}
        {nav("engineering.html", "Engineering")}
        {nav("about.html", "About")}
      </nav>
    </div>
{body}
    <footer>
      Paper trading — simulated capital, not investment advice.
      · <a href="../decisions.html">Decision journal</a>
      · <a href="../decisions/">By day</a>
      · <a href="../symbols/">By symbol</a>
    </footer>
  </div>
</body>
</html>
"""


# A plain equity ticker (1–5 caps). Excludes things like ^VIX that can't be a page.
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _symbol_link(symbol, *, prefix: str = "../symbols/") -> str:
    """Wrap a ticker in a link to its hub page. Every symbol that ever renders also
    gets a hub (see export), so these never 404. Non-tickers pass through as text."""
    sym = str(symbol or "").upper()
    if _TICKER_RE.match(sym):
        return f'<a class="sym-link" href="{prefix}{sym}.html">{escape(sym)}</a>'
    return escape(str(symbol or "?"))


def _trade_summary(entry: dict) -> str:
    """'BUY AAPL, SELL NVDA' — used in descriptions."""
    trades = entry.get("executed_trades") or entry.get("approved_trades") or []
    parts = [f"{t.get('action', '?')} {t.get('symbol', '?')}" for t in trades]
    return ", ".join(dict.fromkeys(parts))


def _title_phrase(entry: dict) -> str:
    """The entity-rich part of the title: 'buys AAPL', 'buys AAPL, sells NVDA'.

    A date beats nobody's search; the traded symbols are the strongest on-page
    signal. Empty on hold days (the title falls back to a plain 'decision')."""
    trades = entry.get("executed_trades") or entry.get("approved_trades") or []
    buys: list[str] = []
    sells: list[str] = []
    for t in trades:
        action = str(t.get("action", "")).upper()
        symbol = str(t.get("symbol", "")).upper()
        if not symbol:
            continue
        if action == "BUY" and symbol not in buys:
            buys.append(symbol)
        elif action == "SELL" and symbol not in sells:
            sells.append(symbol)
    parts = []
    if buys:
        parts.append("buys " + ", ".join(buys[:3]))
    if sells:
        parts.append("sells " + ", ".join(sells[:3]))
    return ", ".join(parts)


def _render_trades(entry: dict) -> str:
    """Merge the risk-approved trades (confidence, reasoning) with the LLM's raw
    proposal (risks) and the execution record (fill price)."""
    raw = {(t.get("symbol"), t.get("action")): t for t in (entry["raw_decision"].get("trades") or [])}
    executed = {(t.get("symbol"), t.get("action")): t for t in (entry.get("executed_trades") or [])}
    approved = entry.get("approved_trades") or []

    out = []
    for t in approved:
        key = (t.get("symbol"), t.get("action"))
        action = t.get("action", "?")
        symbol = t.get("symbol", "?")
        shares = t.get("shares", 0)
        conf = t.get("confidence") or 0
        reason = t.get("reasoning") or raw.get(key, {}).get("reason") or ""
        risks = raw.get(key, {}).get("risks") or []
        fill = executed.get(key, {}).get("price")

        cls = "trade sell" if action == "SELL" else "trade"
        head = f"{escape(action)} {escape(str(shares))} {_symbol_link(symbol)}"
        bits = [f'<span class="conf">{conf * 100:.0f}%</span>'] if conf else []
        if fill is not None:
            bits.append(f'<span class="muted"> · filled at {_money(fill)}</span>')
        risk_html = ""
        if risks:
            items = "".join(f"<li>{escape(str(r))}</li>" for r in risks)
            risk_html = f'<div class="muted" style="margin-top:6px">Risks the AI named</div><ul>{items}</ul>'
        out.append(
            f'<div class="{cls}"><div class="head">{head}{"".join(bits)}</div>'
            f"<p style=\"margin:6px 0 0\">{escape(reason)}</p>{risk_html}</div>"
        )

    for t in entry.get("rejected_trades") or []:
        # HOLDs are no-ops, not trades; older entries wrongly logged low-confidence
        # HOLDs as "rejected" — skip them so the page shows only real blocked trades.
        if str(t.get("action", "")).upper() == "HOLD":
            continue
        head = f"{escape(t.get('action', '?'))} {escape(str(t.get('shares', 0)))} {_symbol_link(t.get('symbol'))}"
        out.append(
            f'<div class="trade rejected"><div class="head">{head}</div>'
            f'<p class="muted" style="margin:6px 0 0">Rejected by the risk engine: '
            f"{escape(str(t.get('reason', 'unspecified')))}</p></div>"
        )

    if not out:
        return '<p class="muted">No trades this day — the fund held.</p>'
    return "".join(out)


def _render_market_calls(entry: dict) -> str:
    """The fund's directional beat/lag-SPY call on every researched name — traded or
    not — with confidence and thesis. This is the calibration record, and it adds real
    crawlable text on days the fund barely traded. ``became_trade`` is derived from the
    day's executed BUYs, so the names the fund actually bet on are visibly tagged."""
    calls = entry["raw_decision"].get("market_calls") or []
    if not calls:
        return ""

    bought = {
        t.get("symbol")
        for t in (entry.get("executed_trades") or [])
        if str(t.get("action", "")).upper() == "BUY"
    }

    def _conf(call: dict) -> float:
        try:
            return float(call.get("confidence") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _is_outperform(call: dict) -> bool:
        return str(call.get("direction") or "OUTPERFORM").upper() != "UNDERPERFORM"

    rows = []
    for call in sorted(calls, key=_conf, reverse=True):
        symbol = str(call.get("symbol") or "?").upper()
        outperform = _is_outperform(call)
        conf = _conf(call)
        conf_html = f"{conf * 100:.0f}%" if conf else "—"
        traded = (
            '<span class="tag" title="The fund opened or added this position">traded</span>'
            if symbol in bought
            else ""
        )
        rows.append(
            f'<tr><td class="sym">{_symbol_link(symbol)}</td>'
            f'<td><span class="dir {"up" if outperform else "down"}">'
            f'{"Outperform" if outperform else "Underperform"} SPY</span></td>'
            f"<td>{conf_html}</td><td>{traded}</td>"
            f'<td class="muted">{escape(str(call.get("thesis") or ""))}</td></tr>'
        )

    n_out = sum(1 for c in calls if _is_outperform(c))
    n_traded = len(bought & {str(c.get("symbol") or "").upper() for c in calls})
    intro = (
        "A directional call — beat or lag the S&amp;P 500 over the horizon — on every "
        f"researched name, whether or not the fund traded it. {len(calls)} calls "
        f"({n_out} outperform, {len(calls) - n_out} underperform); {n_traded} became trades. "
        "These are the fund's calibration record."
    )
    return (
        "<h2>Market calls</h2>"
        f'<p class="muted">{intro}</p>'
        '<div class="calls-wrap"><table class="calls">'
        "<thead><tr><th>Symbol</th><th>Call</th><th>Conf.</th><th></th><th>Why</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_debate(debate: dict) -> str:
    if not debate:
        return ""
    blocks = []
    for role in ("bull", "bear", "risk"):
        case = debate.get(role)
        if not isinstance(case, dict) or not case.get("thesis"):
            continue
        conviction = case.get("conviction")
        conv = (
            f' <span class="muted">· conviction {float(conviction):.2f}</span>'
            if isinstance(conviction, int | float)
            else ""
        )
        points = "".join(f"<li>{escape(str(p))}</li>" for p in (case.get("key_points") or []))
        blocks.append(
            f'<div class="card"><div class="role">{escape(role)} case{conv}</div>'
            f"<p>{escape(str(case['thesis']))}</p>"
            f"{f'<ul>{points}</ul>' if points else ''}</div>"
        )
    if not blocks:
        return ""
    return "<h2>The debate</h2>" + "".join(blocks)


def _section(heading: str, text) -> str:
    if not text:
        return ""
    return f"<h2>{escape(heading)}</h2><p>{escape(str(text))}</p>"


def render_decision_page(entry: dict, *, prev: dict | None, next_: dict | None) -> str:
    iso = entry["date"]
    pretty = _fmt_date(iso)
    rd = entry["raw_decision"]
    portfolio = entry.get("portfolio") or {}
    summary = rd.get("summary") or ""
    trades = _trade_summary(entry)

    phrase = _title_phrase(entry)
    title = f"AI fund {phrase} — {pretty}" if phrase else f"AI fund decision — {pretty}"
    desc = (
        f"{trades}. {summary}"[:300]
        if trades
        else f"The fund held — no trades. {summary}"[:300]
    ) or f"What an autonomous AI fund decided on {pretty}, and why."

    facts = [f'<span class="pill">Outlook: {escape(str(rd.get("outlook") or "—"))}</span>']
    if portfolio.get("total_value") is not None:
        facts.append(f'<span class="pill">Portfolio {_money(portfolio["total_value"])}</span>')
    if portfolio.get("cash_pct") is not None:
        facts.append(f'<span class="pill">Cash {float(portfolio["cash_pct"]) * 100:.1f}%</span>')
    grounding = (entry.get("grounding") or {}).get("status")
    if grounding:
        facts.append(f'<span class="pill">Grounding: {escape(str(grounding))}</span>')

    body = f"""    <div class="eyebrow">Decision journal</div>
    <h1>{escape(title)}</h1>
    <p class="lede">{escape(summary)}</p>
    <div class="facts">{"".join(facts)}</div>
    <h2>Trades</h2>
    {_render_trades(entry)}
    {_render_market_calls(entry)}
    {_render_debate(rd.get("debate") or {})}
    {_section("Bear case response", rd.get("bear_case_response"))}
    {_section("Market summary", rd.get("market_summary"))}
    {_section("Portfolio assessment", rd.get("portfolio_assessment"))}
    {_section("Risk assessment", rd.get("risk_assessment"))}
    {_section("Cash thesis", entry.get("cash_thesis") or rd.get("cash_thesis"))}
    <div class="pager">
      <span>{f'<a href="{prev["date"]}.html">← {_fmt_date(prev["date"])}</a>' if prev else ""}</span>
      <span>{f'<a href="{next_["date"]}.html">{_fmt_date(next_["date"])} →</a>' if next_ else ""}</span>
    </div>
"""
    return _shell(
        title=title,
        description=desc,
        canonical=f"{SITE}/decisions/{iso}.html",
        body=body,
        active="decisions.html",
        robots="" if _is_substantial(entry) else "noindex,follow",
    )


def render_index(entries: list[dict]) -> str:
    items = []
    for e in reversed(entries):  # newest first
        trades = _trade_summary(e) or "held — no trades"
        summary = (e["raw_decision"].get("summary") or "")[:160]
        items.append(
            f'<li><a href="{e["date"]}.html">{escape(_fmt_date(e["date"]))}</a>'
            f'<div class="sub">{escape(trades)} — {escape(summary)}</div></li>'
        )
    body = f"""    <div class="eyebrow">Decision journal</div>
    <h1>Every decision, by day</h1>
    <p class="lede">One page per trading day: the trades, the bull/bear/risk debate behind
    them, and the cash thesis. {len(entries)} days published.</p>
    <ul class="dlist">{"".join(items)}</ul>
"""
    return _shell(
        title="Decisions by day — Glasshouse Fund",
        description=(
            "Every trading day's decision from an autonomous AI fund, as its own page: "
            "trades, the bull/bear/risk debate, and the cash thesis."
        ),
        canonical=f"{SITE}/decisions/",
        body=body,
        active="decisions.html",
    )


# --- Symbol hub pages -----------------------------------------------------------
# One page per ticker aggregating every decision that touched it, newest first. The
# entity query we care about ("why did an AI fund sell NVDA") is served by neither a
# date page nor the journal; a hub gets *richer* as the corpus grows where a per-day
# stub would get thinner. A hub is generated for every universe ticker (and any ever
# touched) so a symbol link never 404s; ones with no decisions yet are noindexed
# placeholders that the daily pipeline fills over time.

def _symbol_touches(entries: list[dict]) -> dict[str, list[dict]]:
    """symbol -> per-day touches (newest first). Each touch records the day's trades
    of that symbol and/or the day's directional market call on it. ``entries`` is
    oldest-to-newest (as ``latest_per_date`` returns)."""
    touches: dict[str, list[dict]] = {}
    for entry in entries:
        rd = entry.get("raw_decision") or {}
        iso = entry["date"]
        day_trades: dict[str, list[dict]] = {}
        for t in (entry.get("executed_trades") or entry.get("approved_trades") or []):
            sym = str(t.get("symbol", "")).upper()
            if sym:
                day_trades.setdefault(sym, []).append(t)
        day_calls: dict[str, dict] = {}
        for call in rd.get("market_calls") or []:
            sym = str(call.get("symbol", "")).upper()
            if sym:
                day_calls[sym] = call
        for sym in set(day_trades) | set(day_calls):
            touches.setdefault(sym, []).append(
                {"date": iso, "trades": day_trades.get(sym, []), "call": day_calls.get(sym)}
            )
    for sym in touches:
        touches[sym].reverse()  # newest first
    return touches


def _conf_suffix(value) -> str:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return ""
    return f" · {pct * 100:.0f}%" if pct else ""


def render_symbol_page(symbol: str, touches: list[dict]) -> str:
    n_days = len(touches)
    n_trades = sum(1 for t in touches if t["trades"])
    title = f"{symbol}: every AI fund decision — Glasshouse Fund"
    desc = (
        f"Every trade and directional call an autonomous AI fund made on {symbol}, "
        f"newest first — {n_days} decision days, {n_trades} with a trade — each with its reasoning."
    )[:300]

    cards = []
    for t in touches:
        iso = t["date"]
        bits = []
        for tr in t["trades"]:
            action = str(tr.get("action", "?")).upper()
            shares = tr.get("shares", 0)
            cls = "down" if action == "SELL" else "up"
            bits.append(
                f'<span class="dir {cls}">{escape(action)} {escape(str(shares))}'
                f'{_conf_suffix(tr.get("confidence"))}</span>'
            )
        thesis = ""
        call = t["call"]
        if call:
            outperform = str(call.get("direction") or "OUTPERFORM").upper() != "UNDERPERFORM"
            bits.append(
                f'<span class="dir {"up" if outperform else "down"}">'
                f'Call: {"Outperform" if outperform else "Underperform"} SPY'
                f'{_conf_suffix(call.get("confidence"))}</span>'
            )
            thesis = str(call.get("thesis") or "")
        thesis_html = f'<p style="margin:6px 0 0">{escape(thesis)}</p>' if thesis else ""
        cards.append(
            f'<div class="card"><div class="shead">'
            f'<a href="../decisions/{iso}.html">{escape(_fmt_date(iso))}</a> '
            f'{" ".join(bits)}</div>{thesis_html}</div>'
        )

    if cards:
        lede = (
            f"Every trade and directional call the AI fund has made on {escape(symbol)}, "
            "newest first, each linked to that day's full decision."
        )
        facts = (
            f'<div class="facts"><span class="pill">{n_days} decision days</span>'
            f'<span class="pill">{n_trades} with a trade</span></div>'
        )
        content = "".join(cards)
    else:
        # A hub with no decisions yet — kept as a stable link target (never 404s) and
        # noindexed until it has content. Filled by the daily pipeline as the fund
        # acts on this name; more content can be added here later.
        lede = (
            f"The AI fund hasn't traded or made a directional call on {escape(symbol)} yet. "
            "When it does, every decision will appear here — newest first."
        )
        facts = '<div class="facts"><span class="pill">No decisions yet</span></div>'
        content = '<p class="muted">Nothing to show for this ticker yet.</p>'

    body = f"""    <div class="eyebrow">Symbol history</div>
    <h1>{escape(symbol)} — every decision the fund made</h1>
    <p class="lede">{lede}</p>
    {facts}
    {content}
    <div class="pager">
      <span><a href="./">← All symbols</a></span>
      <span><a href="../decisions/">Decisions by day →</a></span>
    </div>
"""
    return _shell(
        title=title,
        description=desc,
        canonical=f"{SITE}/symbols/{symbol}.html",
        body=body,
        robots="" if cards else "noindex,follow",
    )


def render_symbol_index(rows: list[tuple[str, int, int]]) -> str:
    """rows: (symbol, n_days, n_trades), already sorted for display."""

    def sub(n_days: int, n_trades: int) -> str:
        if not n_days:
            return "No decisions yet"
        return f"{n_days} decision days · {n_trades} with a trade"

    items = "".join(
        f'<li><a href="{escape(sym)}.html">{escape(sym)}</a>'
        f'<div class="sub">{sub(n_days, n_trades)}</div></li>'
        for sym, n_days, n_trades in rows
    )
    body = f"""    <div class="eyebrow">By symbol</div>
    <h1>Every stock in the fund's universe</h1>
    <p class="lede">One page per ticker, aggregating every decision the AI fund made on it —
    trades and directional calls — newest first. {len(rows)} symbols.</p>
    <ul class="dlist">{items}</ul>
"""
    return _shell(
        title="Symbols — Glasshouse Fund",
        description=(
            "Every stock an autonomous AI fund has traded or made a directional call on, "
            "one page each, aggregating its full decision history."
        ),
        canonical=f"{SITE}/symbols/",
        body=body,
    )


def _created_at(row: dict) -> datetime:
    """Parse a row's ``created_at`` to an aware UTC datetime for comparison.

    Comparing the raw strings lexicographically is correct only while every row is
    fixed-width UTC (``...Z``); the moment one carries an offset (``+05:30``) string
    ordering picks the wrong run. Parse to a real instant so the last run always
    wins. Unparseable/missing timestamps sort first (treated as oldest)."""
    raw = str(row.get("created_at") or "")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def latest_per_date(rows: list[dict]) -> list[dict]:
    """One entry per date — the last run of that date — sorted oldest to newest.

    A date can hold many runs; only the final one is that day's decision. Rows
    without a date, or without a raw_decision, are not publishable.
    """
    by_date: dict[str, dict] = {}
    for row in rows:
        iso = row.get("date")
        if not iso or not row.get("raw_decision"):
            continue
        current = by_date.get(iso)
        if current is None or _created_at(row) >= _created_at(current):
            by_date[iso] = row
    return [by_date[d] for d in sorted(by_date)]


def build_sitemap(entries: list[dict], symbols: list[str] | None = None) -> str:
    """Generate sitemap.xml from the real page set. Replaces the hand-written file,
    which went stale the moment decision pages started being emitted.

    ``symbols`` is the set of tickers that earned a hub page (see export)."""
    latest = entries[-1]["date"] if entries else None

    def url(loc: str, changefreq: str, priority: str, lastmod: str | None) -> str:
        mod = f"\n    <lastmod>{lastmod}</lastmod>" if lastmod else ""
        return (
            f"  <url>\n    <loc>{loc}</loc>{mod}\n"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n  </url>"
        )

    parts = [
        url(f"{SITE}/{path}", freq, pri, latest if dynamic else None)
        for path, freq, pri, dynamic in STATIC_PAGES
    ]
    parts.append(url(f"{SITE}/decisions/", "daily", "0.8", latest))
    # Only index substantial days; thin backfill stubs are noindexed permalinks and
    # stay out of the sitemap until they clear the bar (see _is_substantial).
    for e in reversed(entries):
        if _is_substantial(e):
            parts.append(url(f"{SITE}/decisions/{e['date']}.html", "yearly", "0.6", e["date"]))

    if symbols:
        parts.append(url(f"{SITE}/symbols/", "weekly", "0.6", latest))
        for sym in sorted(symbols):
            parts.append(url(f"{SITE}/symbols/{sym}.html", "weekly", "0.5", latest))

    body = "\n".join(parts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- Generated by src/reporting/decision_pages.py at export time. Do not edit by hand. -->\n"
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n"
    )


def load_decisions(path: Path | None = None) -> list[dict]:
    path = path or DATA_DIR / "decisions.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def export(rows: list[dict] | None = None, public_dir: Path | None = None) -> list[str]:
    """Write /decisions/*.html, /decisions/index.html, /symbols/*.html and sitemap.xml.
    Returns the decision dates published."""
    public_dir = public_dir or PUBLIC_DIR
    entries = latest_per_date(rows if rows is not None else load_decisions())

    out_dir = public_dir / "decisions"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, entry in enumerate(entries):
        prev = entries[i - 1] if i > 0 else None
        next_ = entries[i + 1] if i + 1 < len(entries) else None
        page = render_decision_page(entry, prev=prev, next_=next_)
        (out_dir / f"{entry['date']}.html").write_text(page)

    (out_dir / "index.html").write_text(render_index(entries))

    # Symbol hubs: one page per ticker in the universe OR ever touched, so a link on
    # any symbol mention always resolves (never 404s). Symbols with no decisions yet
    # get a noindexed placeholder page; the daily pipeline fills them as the fund acts.
    touches = _symbol_touches(entries)
    hub_symbols = sorted(s for s in set(WATCHLIST) | set(touches) if _TICKER_RE.match(s))
    sym_dir = public_dir / "symbols"
    sym_dir.mkdir(parents=True, exist_ok=True)
    for sym in hub_symbols:
        (sym_dir / f"{sym}.html").write_text(render_symbol_page(sym, touches.get(sym, [])))
    index_rows = sorted(
        ((s, len(touches.get(s, [])), sum(1 for x in touches.get(s, []) if x["trades"])) for s in hub_symbols),
        key=lambda r: (-r[1], -r[2], r[0]),
    )
    (sym_dir / "index.html").write_text(render_symbol_index(index_rows))

    # Only non-empty hubs go in the sitemap; empty placeholders stay noindexed.
    indexable = [s for s in hub_symbols if touches.get(s)]
    (public_dir / "sitemap.xml").write_text(build_sitemap(entries, symbols=indexable))

    logger.info(
        "Prerendered %d decision pages, %d symbol hubs (%d with content)",
        len(entries), len(hub_symbols), len(indexable),
    )
    return [e["date"] for e in entries]
