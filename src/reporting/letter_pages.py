"""Prerender the weekly investor letters to static, indexable pages.

The letter agent only ever wrote ``public/investor_letter.{json,md}`` — a single
file overwritten every week, so the fund's most considered, human-readable content
(a grounded, dated market letter) left no durable, crawlable footprint. This module
emits one page per week — ``/letters/YYYY-MM-DD.html`` — plus a ``/letters/`` index,
mirroring ``decision_pages`` (whose chrome, CSS, and helpers it reuses).

Source of truth is ``InvestorLetterStore`` (``data/investor_letters.jsonl``), which
upserts one row per ``week_end``. Pages are regenerated every daily cycle from that
committed store, so they stay in sync without a bespoke build step.
"""

from pathlib import Path
from typing import Any

from src.reporting.decision_pages import (
    PUBLIC_DIR,
    SITE,
    _fmt_date,
    _money,
    _shell,
    _symbol_link,
)
from src.storage.investor_letter_store import InvestorLetterStore
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _pct(value: Any, *, signed: bool = True) -> str | None:
    """Stored decimal (0.0071) -> "+0.71%". None/non-numeric -> None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{value * 100:{'+' if signed else ''}.2f}%"


def _week_range(entry: dict) -> str:
    start = entry.get("week_start")
    end = entry.get("week_end")
    if start and end:
        return f"{_fmt_date(start)} – {_fmt_date(end)}"
    return _fmt_date(end or "")


def _bullets(items: list[str]) -> str:
    kept = [str(i).strip() for i in (items or []) if str(i).strip() and str(i).strip() != "None"]
    if not kept:
        return '<p class="muted">None.</p>'
    return "<ul>" + "".join(f"<li>{_escape_symbols(i)}</li>" for i in kept) + "</ul>"


# A winners/losers line is prose like "META +17.48%"; link the leading ticker to its
# hub without disturbing the rest of the string.
def _escape_symbols(text: str) -> str:
    from html import escape

    parts = str(text).split(" ", 1)
    head = parts[0]
    if head.isupper() and head.isalpha() and 1 <= len(head) <= 5:
        rest = f" {escape(parts[1])}" if len(parts) > 1 else ""
        return f"{_symbol_link(head)}{rest}"
    return escape(str(text))


def _facts_pills(facts: dict) -> str:
    pills = []
    ret = _pct(facts.get("return_pct"))
    if ret is not None:
        pills.append(f'<span class="pill">Return {ret}</span>')
    bench = _pct(facts.get("benchmark_return_pct"))
    if bench is not None:
        pills.append(f'<span class="pill">S&amp;P 500 {bench}</span>')
    alpha = _pct(facts.get("alpha"))
    if alpha is not None:
        pills.append(f'<span class="pill">Alpha {alpha}</span>')
    if facts.get("end_value") is not None:
        pills.append(f'<span class="pill">Portfolio {_money(facts["end_value"])}</span>')
    return f'<div class="facts">{"".join(pills)}</div>' if pills else ""


def _render_trades(facts: dict) -> str:
    """The week's trades as chips, each ticker linked to its hub. Real crawlable
    entity signal ("the AI fund bought AAPL the week of ...")."""
    trades = facts.get("trades") or []
    if not trades:
        return ""
    chips = []
    for t in trades:
        action = str(t.get("action", "?")).upper()
        shares = t.get("shares", 0)
        cls = "down" if action == "SELL" else "up"
        chips.append(
            f'<span class="dir {cls}">{action} {shares} {_symbol_link(t.get("symbol"))}</span>'
        )
    return (
        "<h2>Trades this week</h2>"
        '<div class="facts" style="gap:6px">' + " ".join(chips) + "</div>"
    )


def _section(heading: str, text: Any) -> str:
    from html import escape

    if not text:
        return ""
    return f"<h2>{escape(heading)}</h2><p>{escape(str(text))}</p>"


def render_letter_page(entry: dict, *, prev: dict | None, next_: dict | None) -> str:
    from html import escape

    letter = entry.get("letter") or {}
    facts = entry.get("facts") or {}
    week_end = entry.get("week_end", "")
    span = _week_range(entry)

    headline = str(letter.get("headline") or "").strip()
    ret = _pct(facts.get("return_pct"))
    title = headline or (
        f"AI fund weekly letter — {span}" if span else "AI fund weekly letter"
    )
    desc = (
        (str(letter.get("performance") or "").strip() or headline)
        or f"The AI fund's investor letter for the week of {span}."
    )[:300]

    pager_prev = (
        f'<a href="{prev["week_end"]}.html">← {_week_range(prev)}</a>' if prev else ""
    )
    pager_next = (
        f'<a href="{next_["week_end"]}.html">{_week_range(next_)} →</a>' if next_ else ""
    )

    body = f"""    <div class="eyebrow">Investor letter</div>
    <h1>{escape(headline or title)}</h1>
    <p class="lede">Week of {escape(span)}{f" · {ret} return" if ret else ""}.</p>
    {_facts_pills(facts)}
    {_section("Performance", letter.get("performance"))}
    <h2>Winners</h2>
    {_bullets(letter.get("winners") or [])}
    <h2>Losers</h2>
    {_bullets(letter.get("losers") or [])}
    {_section("Portfolio changes", letter.get("portfolio_changes"))}
    {_render_trades(facts)}
    {_section("Outlook", letter.get("outlook"))}
    <div class="pager">
      <span>{pager_prev}</span>
      <span>{pager_next}</span>
    </div>
"""
    return _shell(
        title=title,
        description=desc,
        canonical=f"{SITE}/letters/{week_end}.html",
        body=body,
        active="",
    )


def render_index(entries: list[dict]) -> str:
    from html import escape

    items = []
    for e in reversed(entries):  # newest first
        letter = e.get("letter") or {}
        facts = e.get("facts") or {}
        headline = str(letter.get("headline") or "Weekly letter").strip()
        ret = _pct(facts.get("return_pct"))
        sub = _week_range(e) + (f" · {ret} return" if ret else "")
        items.append(
            f'<li><a href="{e["week_end"]}.html">{escape(headline)}</a>'
            f'<div class="sub">{escape(sub)}</div></li>'
        )
    body = f"""    <div class="eyebrow">Investor letters</div>
    <h1>Weekly investor letters</h1>
    <p class="lede">Every week, the AI fund writes a grounded letter to its investors:
    what it earned versus the S&amp;P 500, its winners and losers, what it traded, and
    its outlook. {len(entries)} letter{"" if len(entries) == 1 else "s"} published.</p>
    <ul class="dlist">{"".join(items)}</ul>
"""
    return _shell(
        title="Weekly investor letters — Glasshouse Fund",
        description=(
            "Every weekly investor letter from an autonomous AI fund: performance vs the "
            "S&P 500, winners and losers, trades, and outlook — one page per week."
        ),
        canonical=f"{SITE}/letters/",
        body=body,
    )


def load_letters(store: InvestorLetterStore | None = None) -> list[dict]:
    """All published letters, oldest to newest (as the store keeps them)."""
    rows = (store or InvestorLetterStore()).load()
    return sorted(rows, key=lambda r: str(r.get("week_end", "")))


def export(
    letters: list[dict] | None = None,
    public_dir: Path | None = None,
) -> list[str]:
    """Write /letters/*.html and /letters/index.html. Returns the week_ends published.

    An index is always written (even with zero letters) so ``/letters/`` never 404s
    for a crawler that reaches it before the first letter lands."""
    public_dir = public_dir or PUBLIC_DIR
    entries = letters if letters is not None else load_letters()

    out_dir = public_dir / "letters"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, entry in enumerate(entries):
        prev = entries[i - 1] if i > 0 else None
        next_ = entries[i + 1] if i + 1 < len(entries) else None
        (out_dir / f"{entry['week_end']}.html").write_text(
            render_letter_page(entry, prev=prev, next_=next_)
        )

    (out_dir / "index.html").write_text(render_index(entries))
    logger.info("Prerendered %d investor-letter pages", len(entries))
    return [e["week_end"] for e in entries]
