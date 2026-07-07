"""P5-3: weekly investor letter — facts, grounding gate, publish, idempotency."""

import json
from datetime import date

from src.agents.investor_letter import (
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
