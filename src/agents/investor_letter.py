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


def gather_letter_facts(
    week_end: str,
    *,
    portfolio_store: Any = None,
    trade_store: Any = None,
    performance_rows: list[dict] | None = None,
    benchmark_rows: list[dict] | None = None,
) -> dict:
    """Build the deterministic fact base the letter must be grounded in."""
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
                    "return_pct": round(p.return_pct, 4),
                    "market_value": round(p.market_value, 2),
                }
                for p in snapshot.positions
            ),
            key=lambda x: x["return_pct"],
            reverse=True,
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
        "winners": [p for p in positions if p["return_pct"] > 0][:3],
        "losers": [p for p in positions if p["return_pct"] < 0][-3:],
        "positions": positions,
        "trades": trades,
    }


def has_letter_material(facts: dict) -> bool:
    return bool(facts.get("positions") or facts.get("trades") or facts.get("end_value"))


class InvestorLetterAgent:
    def write(self, facts: dict) -> InvestorLetterResponse:
        prompt = (
            "You are the portfolio manager of an AI-run paper fund writing this week's "
            "investor letter. Write in a candid, professional voice. Use ONLY the facts "
            "below — every number you state must come from them; do not invent prices, "
            "returns, or events. Percentages are decimals (0.02 = 2%).\n\n"
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
    )
    if not has_letter_material(facts):
        logger.info("No portfolio activity for week ending %s — skipping letter", week_end)
        return {"status": "skipped", "week_end": week_end}

    letter = agent.write(facts)

    # Grounding gate: the letter's claims are checked against the week's facts
    # BEFORE anything is published. A flagged letter is blocked, never published.
    grounding = check_grounding(
        letter.model_dump(), research=facts, memory=[], portfolio=facts["positions"], judge=judge
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
