"""P5-3: weekly investor letter — facts, grounding gate, publish, idempotency."""

import json
import os
from datetime import date

import pytest

from src.agents.investor_letter import (
    _PERCENT_KEYS,
    format_facts_for_prompt,
    gather_letter_facts,
    generate_weekly_letter,
    letter_to_thread,
    render_letter_markdown,
)
from src.llm.schemas import InvestorLetterResponse
from src.models.portfolio import Position, PortfolioSnapshot
from src.scoring.grounding import GroundingVerdict
from src.storage.investor_letter_store import InvestorLetterStore

WEEK_END = "2026-06-28"  # window 2026-06-22 .. 2026-06-28

PERF = [
    {"date": "2026-06-15", "total_value": "900000"},   # before window
    {"date": "2026-06-22", "total_value": "1000000"},
    {"date": "2026-06-28", "total_value": "1030000"},  # +3% in window
]
BENCH = [
    {"date": "2026-06-22", "symbol": "SPY", "price": "500"},
    {"date": "2026-06-28", "symbol": "SPY", "price": "510"},  # +2%
]


def _portfolio():
    return PortfolioSnapshot(
        date=date(2026, 6, 28),
        cash=100_000,
        positions=[
            Position("NVDA", 100, 100.0, 150.0),   # +50%
            Position("AAPL", 50, 200.0, 220.0),    # +10%
            Position("MSFT", 20, 400.0, 320.0),    # -20%
        ],
    )


class FakeStore:
    def __init__(self, rows=None, snapshot=None):
        self._rows = rows or []
        self._snapshot = snapshot

    def load(self):
        return self._snapshot

    def load_all(self):
        return self._rows


class FakeAgent:
    def __init__(self, letter):
        self.letter = letter
        self.calls = 0

    def write(self, facts):
        self.calls += 1
        return self.letter


def _facts(**over):
    kwargs = dict(
        portfolio_store=FakeStore(snapshot=_portfolio()),
        trade_store=FakeStore(rows=[
            {"date": "2026-06-24", "symbol": "NVDA", "action": "BUY", "shares": "10"},
            {"date": "2026-06-10", "symbol": "TSLA", "action": "SELL", "shares": "5"},  # out of window
        ]),
        performance_rows=PERF,
        benchmark_rows=BENCH,
    )
    kwargs.update(over)
    return gather_letter_facts(WEEK_END, **kwargs)


def test_gather_facts_computes_returns_and_winners_losers():
    facts = _facts()
    assert facts["week_start"] == "2026-06-22"
    assert facts["return_pct"] == 0.03
    assert facts["benchmark_return_pct"] == 0.02
    assert facts["alpha"] == 0.01
    assert [w["symbol"] for w in facts["winners"]] == ["NVDA", "AAPL"]
    assert [x["symbol"] for x in facts["losers"]] == ["MSFT"]
    assert [t["symbol"] for t in facts["trades"]] == ["NVDA"]  # in-window only


def test_render_markdown_has_sections():
    letter = InvestorLetterResponse(headline="Steady week", performance="Up 3%.",
                                    winners=["NVDA led"], outlook="Constructive.")
    md = render_letter_markdown(letter, _facts())
    assert "# Steady week" in md
    assert "## Performance" in md and "## Outlook" in md


def test_thread_splits_and_caps_length():
    letter = InvestorLetterResponse(headline="H", performance="P" * 400, outlook="O")
    posts = letter_to_thread(letter, _facts())
    assert all(len(p) <= 280 for p in posts)
    assert len(posts) >= 2


def _letter():
    return InvestorLetterResponse(headline="Weekly update", performance="Portfolio +3% vs SPY +2%.",
                                  winners=["NVDA"], losers=["MSFT"], outlook="Cautiously optimistic.")


def _run(judge, tmp_path, **over):
    kwargs = dict(
        week_end=WEEK_END,
        agent=FakeAgent(_letter()),
        judge=judge,
        portfolio_store=FakeStore(snapshot=_portfolio()),
        trade_store=FakeStore(rows=[]),
        performance_rows=PERF,
        benchmark_rows=BENCH,
        letter_store=InvestorLetterStore(path=tmp_path / "letters.jsonl"),
        public_dir=tmp_path / "public",
    )
    kwargs.update(over)
    return generate_weekly_letter(**kwargs)


def test_grounded_letter_is_published_and_exported(tmp_path):
    result = _run(lambda decision, context: GroundingVerdict(grounded=True), tmp_path)
    assert result["status"] == "published"
    assert (tmp_path / "public" / "investor_letter.json").exists()
    assert (tmp_path / "public" / "investor_letter.md").exists()
    stored = InvestorLetterStore(path=tmp_path / "letters.jsonl").load()
    assert len(stored) == 1 and stored[0]["week_end"] == WEEK_END


def test_flagged_letter_is_blocked_before_publish(tmp_path):
    result = _run(
        lambda decision, context: GroundingVerdict(
            grounded=False, severity="material", issues=["made up a number"]),
        tmp_path,
    )
    assert result["status"] == "blocked_grounding"
    # Nothing published or stored.
    assert not (tmp_path / "public" / "investor_letter.json").exists()
    assert InvestorLetterStore(path=tmp_path / "letters.jsonl").load() == []


def test_publish_is_idempotent_per_week(tmp_path):
    judge = lambda decision, context: GroundingVerdict(grounded=True)
    _run(judge, tmp_path)
    _run(judge, tmp_path)  # same week again
    stored = InvestorLetterStore(path=tmp_path / "letters.jsonl").load()
    assert len(stored) == 1  # upserted, not duplicated


def test_skips_when_no_material(tmp_path):
    result = _run(
        lambda decision, context: GroundingVerdict(grounded=True),
        tmp_path,
        portfolio_store=FakeStore(snapshot=None),
        trade_store=FakeStore(rows=[]),
        performance_rows=[],
        benchmark_rows=[],
    )
    assert result["status"] == "skipped"


def test_x_thread_off_by_default_on_when_enabled(tmp_path):
    class FakePublisher:
        def __init__(self):
            self.posts = []

        def publish(self, text, **kwargs):
            self.posts.append(text)
            return type("R", (), {"posted": True})()

    judge = lambda decision, context: GroundingVerdict(grounded=True)

    pub_off = FakePublisher()
    r1 = _run(judge, tmp_path, tweet_publisher=pub_off, post_letter=False)
    assert r1["tweeted"] is False and pub_off.posts == []

    pub_on = FakePublisher()
    r2 = _run(judge, tmp_path, tweet_publisher=pub_on, post_letter=True)
    assert r2["tweeted"] is True and len(pub_on.posts) >= 1


# -- percent/decimal unit alignment ------------------------------------------
#
# The letter writes prose ("2.31%"); the facts are decimals (0.0231). The grounding
# judge, seeing both, called the difference a *material* fabrication and blocked
# every letter the system ever produced. The fix hands writer and judge the same
# formatted numbers. These tests pin that down.

# Window returns +2.31%; SPY +0.62%; alpha +1.69% — the real 2026-07-05 numbers.
PERF_231 = [
    {"date": "2026-06-29", "total_value": "1000000"},
    {"date": "2026-07-05", "total_value": "1023100"},
]
BENCH_062 = [
    {"date": "2026-06-29", "symbol": "SPY", "price": "500"},
    {"date": "2026-07-05", "symbol": "SPY", "price": "503.10"},
]


def test_every_numeric_fact_is_classified_as_ratio_or_non_ratio():
    """Class-level guard, not another instance fix.

    ``format_facts_for_prompt`` converts a hand-maintained whitelist of ratio keys.
    The bug this whole PR fixes recurs the moment a new ratio fact is added to
    ``gather_letter_facts`` and left off that whitelist: the judge sees ``0.10`` while
    the letter writes ``"10.42%"`` and blocks publication — silently, because no test
    covers a specific-but-undeclared key.

    So: walk a real fact base and require every number to be *declared*. A new numeric
    fact fails here until someone decides whether it is a ratio (add to ``_PERCENT_KEYS``
    / a position ``return_pct``) or a dollar/count (add to ``NON_RATIO`` below).
    """
    # Dollar amounts and share counts — numbers the judge should read as-is.
    NON_RATIO = {"start_value", "end_value", "market_value", "shares"}
    ratio_keys = set(_PERCENT_KEYS) | {"return_pct"}  # return_pct is the per-position ratio

    unclassified: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, bool):  # bools are not quantities
                    continue
                if isinstance(value, (int, float)):
                    if key not in ratio_keys and key not in NON_RATIO:
                        unclassified.append(f"{path}{key} = {value!r}")
                else:
                    walk(value, f"{path}{key}.")
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(_facts(), "")

    assert not unclassified, (
        "Unclassified numeric fact(s) in the letter fact base: "
        f"{unclassified}. Declare each as a ratio (percent-format it in "
        "format_facts_for_prompt) or a dollar/count (add its key to NON_RATIO), "
        "or the grounding judge will silently block the letter on a unit mismatch."
    )


def test_format_facts_renders_ratios_as_percent_strings():
    display = format_facts_for_prompt(_facts())
    assert display["return_pct"] == "3.00%"
    assert display["benchmark_return_pct"] == "2.00%"
    assert display["alpha"] == "1.00%"
    assert display["winners"][0]["return_pct"] == "50.00%"
    assert display["losers"][0]["return_pct"] == "-20.00%"
    # Non-ratio fields are untouched — a price stays a number.
    assert display["end_value"] == 1030000.0
    assert display["winners"][0]["market_value"] == 15000.0


def test_format_facts_passes_through_none_and_leaves_source_untouched():
    facts = _facts(performance_rows=[], benchmark_rows=[])
    display = format_facts_for_prompt(facts)
    assert display["return_pct"] is None and display["alpha"] is None
    # The canonical decimals are what get stored; formatting must not mutate them.
    facts = _facts()
    format_facts_for_prompt(facts)
    assert facts["return_pct"] == 0.03
    assert facts["winners"][0]["return_pct"] == 0.5


def test_agent_and_judge_receive_the_same_percent_formatted_facts(tmp_path):
    """The bug in one assertion: writer and auditor must not disagree on units."""
    seen = {}

    class CapturingAgent(FakeAgent):
        def write(self, facts):
            seen["agent"] = facts
            return super().write(facts)

    def capturing_judge(decision, context):
        seen["judge"] = context["market_context"]
        seen["judge_portfolio"] = context["portfolio"]
        return GroundingVerdict(grounded=True)

    _run(capturing_judge, tmp_path, agent=CapturingAgent(_letter()))

    assert seen["agent"]["return_pct"] == "3.00%"
    assert seen["judge"] == seen["agent"]  # identical view, no unit gap
    assert seen["judge_portfolio"][0]["return_pct"] == "50.00%"


def test_stored_facts_remain_canonical_decimals(tmp_path):
    """Prompt formatting is presentation-only; the journal keeps machine-readable numbers."""
    _run(lambda d, c: GroundingVerdict(grounded=True), tmp_path)
    stored = InvestorLetterStore(path=tmp_path / "letters.jsonl").load()[0]
    assert stored["facts"]["return_pct"] == 0.03
    assert stored["facts"]["alpha"] == 0.01


# -- live regression: the real judge on the real failure ----------------------


def _live_run(letter, tmp_path):
    return generate_weekly_letter(
        week_end="2026-07-05",
        agent=FakeAgent(letter),
        judge=None,  # the REAL grounding judge
        portfolio_store=FakeStore(snapshot=_portfolio()),
        trade_store=FakeStore(rows=[]),
        performance_rows=PERF_231,
        benchmark_rows=BENCH_062,
        letter_store=InvestorLetterStore(path=tmp_path / "letters.jsonl"),
        public_dir=tmp_path / "public",
    )


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a live model for the judge")
def test_live_judge_accepts_percent_prose_against_decimal_facts(tmp_path):
    """Reproduces the letter-never-published bug: a letter stating "2.31%" against a
    fact of 0.0231 must pass grounding, not be flagged as a fabricated number."""
    letter = InvestorLetterResponse(
        headline="A quiet week of compounding",
        performance="The fund returned 2.31% this week versus 0.62% for the S&P 500, "
        "for 1.69% of alpha. Ending value was $1,023,100.",
        winners=["NVDA is up 50.00% on the position."],
        losers=["MSFT is down 20.00% on the position."],
        outlook="Constructive.",
    )
    result = _live_run(letter, tmp_path)

    # "unavailable" means the judge threw and check_grounding degraded open — the
    # letter would publish for the wrong reason and this test would pass vacuously.
    assert result["grounding"]["status"] == "ok", result["grounding"]
    assert result["grounding"]["severity"] != "material", result["grounding"]["issues"]
    assert result["status"] == "published", result["grounding"]["issues"]
    assert (tmp_path / "public" / "investor_letter.md").exists()


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a live model for the judge")
def test_live_judge_still_blocks_a_fabricated_price(tmp_path):
    """Guard against over-correcting: the gate must still catch a genuine invention.
    Nothing in the facts mentions a $999 print, a Broadcom position, or an earnings beat."""
    letter = InvestorLetterResponse(
        headline="Blowout week",
        performance="The fund returned 47.00% this week after NVDA closed at $999.00 "
        "on a blowout earnings beat, and our AVGO stake doubled.",
        winners=["AVGO gained 112.00% after its acquisition was announced."],
        losers=[],
        outlook="Euphoric.",
    )
    result = _live_run(letter, tmp_path)

    assert result["status"] == "blocked_grounding", result["grounding"]
    assert result["grounding"]["severity"] == "material"
    # And nothing leaked out to the dashboard or the journal.
    assert not (tmp_path / "public" / "investor_letter.md").exists()
    assert InvestorLetterStore(path=tmp_path / "letters.jsonl").load() == []
