"""Weekly investor letter: an AI-written summary of the fund's week.

Computes the week's facts deterministically (performance vs benchmark,
winners/losers, trades), asks the model to write a letter grounded in exactly
those facts, runs the shared grounding check before anything is published, and —
only if grounded — records the letter (idempotent per week) and exports it to the
dashboard. Optional X-thread posting is gated behind ``POST_INVESTOR_LETTER`` and
off by default.
"""

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.config import DATA_DIR, POST_INVESTOR_LETTER
from src.llm import complete_structured
from src.llm.schemas import InvestorLetterResponse
from src.scoring.grounding import check_grounding
from src.storage.investor_letter_store import InvestorLetterStore
from src.storage.portfolio_store import PortfolioStore
from src.storage.trade_store import TradeStore
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROMPT_VERSION = "investor_letter/v1"
WINDOW_DAYS = 7
PERFORMANCE_FILE = DATA_DIR / "portfolio_history.csv"
BENCHMARK_FILE = DATA_DIR / "benchmark_history.csv"
PUBLIC_DIR = Path("public")


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _window_return(rows: list[dict], value_key: str) -> tuple[float | None, float | None, float | None]:
    if not rows:
        return None, None, None
    start = float(rows[0][value_key])
    end = float(rows[-1][value_key])
    ret = round(end / start - 1, 4) if start else None
    return round(start, 2), round(end, 2), ret


def _week_return(market_data: Any, symbol: str) -> float | None:
    """This holding's return over the letter's window, or None if unavailable.

    Defensive by design: the letter must still publish when a price fetch fails. A
    None here degrades the ranking to since-entry, it does not block the letter.
    """
    if market_data is None:
        return None
    try:
        # Calendar days, so ask for more than the 7-day window to clear the weekend
        # and still land at least two trading sessions.
        history = market_data.get_history(symbol, days=WINDOW_DAYS + 4)
        if history is None or history.empty or len(history) < 2:
            return None
        start = float(history["Close"].iloc[0])
        end = float(history["Close"].iloc[-1])
        if start <= 0:
            return None
        return round(end / start - 1, 4)
    except Exception as exc:  # noqa: BLE001 — a bad symbol must not kill the letter
        logger.warning("Weekly return unavailable for %s: %s", symbol, exc)
        return None


def gather_letter_facts(
    week_end: str,
    *,
    portfolio_store: Any = None,
    trade_store: Any = None,
    performance_rows: list[dict] | None = None,
    benchmark_rows: list[dict] | None = None,
    market_data: Any = None,
) -> dict:
    """Build the deterministic fact base the letter must be grounded in.

    ``market_data`` supplies each holding's return *over the letter's week*. Without
    it the per-position numbers are since-entry only, which is why they must never be
    presented as weekly moves — see ``return_since_entry_pct`` below.
    """
    week_start = (date.fromisoformat(week_end) - timedelta(days=WINDOW_DAYS - 1)).isoformat()

    def _in_window(day: str) -> bool:
        return bool(day) and week_start <= day <= week_end

    perf = performance_rows if performance_rows is not None else _read_csv(PERFORMANCE_FILE)
    perf_window = [r for r in perf if _in_window(str(r.get("date", "")))]
    start_value, end_value, return_pct = _window_return(perf_window, "total_value")

    bench = benchmark_rows if benchmark_rows is not None else _read_csv(BENCHMARK_FILE)
    spy_window = [r for r in bench if r.get("symbol") == "SPY" and _in_window(str(r.get("date", "")))]
    _, _, benchmark_return_pct = _window_return(spy_window, "price")

    snapshot = (portfolio_store or PortfolioStore()).load()
    positions = []
    if snapshot is not None:
        positions = sorted(
            (
                {
                    "symbol": p.symbol,
                    # Named, not bare "return_pct". This field is cumulative P&L since
                    # the position was opened — it is NOT a weekly move. The letter is
                    # a weekly letter, and under the old bare name the writer read it
                    # as one: the 2026-08-02 letter said "the fund rose 0.30% this
                    # week" and then "MA led with a 17.77% gain", which a reader can
                    # only take as a weekly figure. The grounding judge passed it
                    # because the number was faithfully grounded — in a mislabelled
                    # fact. Self-describing keys are the fix.
                    "return_since_entry_pct": round(p.return_pct, 4),
                    "week_return_pct": _week_return(market_data, p.symbol),
                    "market_value": round(p.market_value, 2),
                }
                for p in snapshot.positions
            ),
            key=lambda x: (
                x["week_return_pct"]
                if x["week_return_pct"] is not None
                else x["return_since_entry_pct"]
            ),
            reverse=True,
        )

    # Rank on the week when we have it — this is a weekly letter — and fall back to
    # since-entry only when the price fetch failed. Either way both numbers travel
    # with the position, so the writer can never mistake one for the other.
    def _rank(p: dict) -> float | None:
        return (
            p["week_return_pct"]
            if p["week_return_pct"] is not None
            else p["return_since_entry_pct"]
        )

    trades = [
        {
            "date": t.get("date"),
            "symbol": t.get("symbol"),
            "action": t.get("action"),
            "shares": t.get("shares"),
        }
        for t in (trade_store or TradeStore()).load_all()
        if _in_window(str(t.get("date", "")))
    ]

    return {
        "week_start": week_start,
        "week_end": week_end,
        "start_value": start_value,
        "end_value": end_value,
        "return_pct": return_pct,
        "benchmark_return_pct": benchmark_return_pct,
        "alpha": round(return_pct - benchmark_return_pct, 4)
        if return_pct is not None and benchmark_return_pct is not None
        else None,
        "winners": [p for p in positions if (_rank(p) or 0) > 0][:3],
        "losers": [p for p in positions if (_rank(p) or 0) < 0][-3:],
        "positions": positions,
        "trades": trades,
    }


def has_letter_material(facts: dict) -> bool:
    return bool(facts.get("positions") or facts.get("trades") or facts.get("end_value"))


# Ratio-valued fact keys. Stored as decimals (0.0231) but shown to the model — and to
# the grounding judge — as percent strings ("2.31%").
_PERCENT_KEYS = ("return_pct", "benchmark_return_pct", "alpha")
_POSITION_LISTS = ("winners", "losers", "positions")
# Ratio fields inside each position dict. Both must be formatted, or the writer sees
# one number as "1.20%" and its neighbour as 0.1777 and the grounding judge sees a
# unit mismatch — the exact failure that blocked every letter before 464b801.
_POSITION_PERCENT_KEYS = ("week_return_pct", "return_since_entry_pct")


def _as_percent(value: Any) -> Any:
    """0.0231 -> "2.31%". Non-numerics (incl. None) pass through untouched."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return f"{value * 100:.2f}%"


def format_facts_for_prompt(facts: dict) -> dict:
    """Present the fact base in the same units the letter's prose will use.

    The letter is written in percent ("2.31%") while the facts are decimals
    (0.0231). The grounding judge sees both and, despite being told that units are
    equivalent phrasing, has classified the difference as a *material* fabrication —
    blocking every letter ever generated. Rather than argue with the judge, we remove
    the discrepancy: agent and judge are handed identical, already-formatted numbers,
    so there is nothing left to reconcile.

    The canonical decimal facts are what get *stored*; this view is prompt-only.
    """
    display = dict(facts)
    for key in _PERCENT_KEYS:
        display[key] = _as_percent(display.get(key))
    for key in _POSITION_LISTS:
        display[key] = [
            {**p, **{k: _as_percent(p.get(k)) for k in _POSITION_PERCENT_KEYS if k in p}}
            for p in (display.get(key) or [])
        ]
    return display


class InvestorLetterAgent:
    def write(self, facts: dict) -> InvestorLetterResponse:
        prompt = (
            "You are the portfolio manager of an AI-run paper fund writing this week's "
            "investor letter. Write in a candid, professional voice. Use ONLY the facts "
            "below — every number you state must come from them; do not invent prices, "
            "returns, or events. Percentages are already formatted (e.g. \"2.31%\"); quote "
            "them as given, do not convert or recompute them.\n\n"
            "Each position carries TWO different returns and they must not be "
            "confused:\n"
            "  * week_return_pct — how the name moved THIS WEEK. Use this whenever you "
            "describe the week's winners, losers or moves.\n"
            "  * return_since_entry_pct — cumulative P&L since the position was first "
            "opened, often many weeks ago. NEVER describe it as a weekly move. If you "
            "mention it, say explicitly that it is since the position was opened.\n"
            "If week_return_pct is null the weekly move is unknown for that name — say "
            "nothing about how it moved this week.\n\n"
            f"WEEK FACTS:\n{json.dumps(facts, default=str)}\n\n"
            'Return JSON: {"headline": "...", "performance": "...", '
            '"winners": ["..."], "losers": ["..."], "portfolio_changes": "...", '
            '"outlook": "..."}. Keep each field concise.'
        )
        return complete_structured(
            [{"role": "user", "content": prompt}],
            InvestorLetterResponse,
            tier="strong",
            prompt_version=PROMPT_VERSION,
        )


def render_letter_markdown(letter: InvestorLetterResponse, facts: dict) -> str:
    def _bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- None"

    return (
        f"# {letter.headline or 'Weekly Investor Letter'}\n\n"
        f"*Week of {facts['week_start']} to {facts['week_end']}*\n\n"
        f"## Performance\n\n{letter.performance}\n\n"
        f"## Winners\n\n{_bullets(letter.winners)}\n\n"
        f"## Losers\n\n{_bullets(letter.losers)}\n\n"
        f"## Portfolio Changes\n\n{letter.portfolio_changes}\n\n"
        f"## Outlook\n\n{letter.outlook}\n"
    )


def letter_to_thread(letter: InvestorLetterResponse, facts: dict) -> list[str]:
    """Split the letter into tweet-sized posts for the optional X thread."""
    parts = [
        f"📈 Weekly letter — week of {facts['week_end']}\n{letter.headline}".strip(),
        letter.performance,
        ("Portfolio changes: " + letter.portfolio_changes) if letter.portfolio_changes else "",
        ("Outlook: " + letter.outlook) if letter.outlook else "",
    ]
    return [p.strip()[:280] for p in parts if p and p.strip()]


def generate_weekly_letter(
    *,
    week_end: str | None = None,
    agent: InvestorLetterAgent | None = None,
    judge: Any = None,
    portfolio_store: Any = None,
    trade_store: Any = None,
    performance_rows: list[dict] | None = None,
    benchmark_rows: list[dict] | None = None,
    market_data: Any = None,
    letter_store: InvestorLetterStore | None = None,
    tweet_publisher: Any = None,
    post_letter: bool = POST_INVESTOR_LETTER,
    public_dir: Path = PUBLIC_DIR,
) -> dict:
    """Generate → ground → (publish | block) the week's letter. Idempotent per week."""
    week_end = week_end or date.today().isoformat()
    agent = agent or InvestorLetterAgent()

    facts = gather_letter_facts(
        week_end,
        portfolio_store=portfolio_store,
        trade_store=trade_store,
        performance_rows=performance_rows,
        benchmark_rows=benchmark_rows,
        # NOT defaulted to a live client here: this function is exercised by unit
        # tests, and constructing one would make them hit yfinance for real. The
        # weekly entry point (scripts/weekly_letter.py) injects the live client.
        market_data=market_data,
    )
    if not has_letter_material(facts):
        logger.info("No portfolio activity for week ending %s — skipping letter", week_end)
        return {"status": "skipped", "week_end": week_end}

    # One formatted view, shared by writer and auditor: whatever units the letter is
    # written against are the units it is judged against.
    display_facts = format_facts_for_prompt(facts)
    letter = agent.write(display_facts)

    # Grounding gate: the letter's claims are checked against the week's facts
    # BEFORE anything is published. A flagged letter is blocked, never published.
    grounding = check_grounding(
        letter.model_dump(),
        research=display_facts,
        memory=[],
        portfolio=display_facts["positions"],
        judge=judge,
    )
    if grounding.status == "flagged":
        logger.warning("Investor letter blocked by grounding: %s", grounding.issues)
        return {
            "status": "blocked_grounding",
            "week_end": week_end,
            "grounding": grounding.to_dict(),
        }

    markdown = render_letter_markdown(letter, facts)
    record = {
        "week_end": week_end,
        "week_start": facts["week_start"],
        "letter": letter.model_dump(),
        "facts": facts,
        "markdown": markdown,
        "grounding": grounding.to_dict(),
    }
    (letter_store or InvestorLetterStore()).record(record)
    _export_to_dashboard(record, public_dir)
    _export_letter_pages(letter_store, public_dir)

    tweeted = _maybe_post_thread(letter, facts, post_letter, tweet_publisher)
    return {
        "status": "published",
        "week_end": week_end,
        "grounding": grounding.to_dict(),
        "tweeted": tweeted,
    }


def _export_to_dashboard(record: dict, public_dir: Path) -> None:
    public_dir.mkdir(exist_ok=True)
    (public_dir / "investor_letter.json").write_text(json.dumps(record, indent=2, default=str))
    (public_dir / "investor_letter.md").write_text(record["markdown"])


def _export_letter_pages(letter_store: InvestorLetterStore | None, public_dir: Path) -> None:
    """Prerender the dated /letters/*.html + index so a new letter is live the same
    run. The daily PublicExporter also regenerates these (and the sitemap) from the
    committed store; this just avoids a weekday's lag. Best-effort — the letter is
    already recorded, so a page-render failure must not fail the letter."""
    from src.reporting import letter_pages

    try:
        letter_pages.export(
            letters=letter_pages.load_letters(letter_store or InvestorLetterStore()),
            public_dir=public_dir,
        )
    except Exception as exc:  # noqa: BLE001 — page render must not fail a good letter
        logger.warning("Investor-letter page prerender skipped: %s", exc)


def _maybe_post_thread(letter, facts, post_letter, tweet_publisher) -> bool:
    if not post_letter:
        return False
    from src.social.twitter import TwitterPublisher

    publisher = tweet_publisher or TwitterPublisher()
    posted = False
    for post in letter_to_thread(letter, facts):
        result = publisher.publish(post)
        posted = posted or getattr(result, "posted", False)
    return posted
