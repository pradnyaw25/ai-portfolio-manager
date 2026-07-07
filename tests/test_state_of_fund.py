"""Weekly state-of-fund tweet: facts, chart PNG, generation, and media publishing."""

from types import SimpleNamespace

from src.agents import state_of_fund
from src.agents.state_of_fund import gather_state_facts, generate_state_tweet
from src.reporting.perf_chart import render_performance_chart


def _perf(*pairs):
    return [{"date": d, "total_value": str(v)} for d, v in pairs]


def _bench(symbol, *pairs):
    return [{"date": d, "symbol": symbol, "price": str(v)} for d, v in pairs]


_SNAPSHOT = SimpleNamespace(
    cash_pct=0.26,
    positions=[
        SimpleNamespace(symbol="AAPL", market_value=200_000),
        SimpleNamespace(symbol="NVDA", market_value=150_000),
        SimpleNamespace(symbol="MSFT", market_value=100_000),
    ],
)


class _FakeStore:
    def __init__(self, snapshot=None, rows=None):
        self._snapshot = snapshot
        self._rows = rows or []

    def load(self):
        return self._snapshot

    def load_all(self):
        return self._rows


# -- facts -------------------------------------------------------------------


def test_facts_compute_returns_and_relative_standing():
    facts = gather_state_facts(
        performance_rows=_perf(("2026-06-11", 1_000_000), ("2026-07-06", 1_022_983)),
        benchmark_rows=(
            _bench("SPY", ("2026-06-11", 100.0), ("2026-07-06", 101.7))
            + _bench("QQQ", ("2026-06-11", 100.0), ("2026-07-06", 100.65))
        ),
        portfolio_store=_FakeStore(snapshot=_SNAPSHOT),
        prediction_store=_FakeStore(rows=[{"status": "open"}, {"status": "open"}]),
    )
    assert facts["enough_data"] is True
    assert facts["fund_return_pct"] == 2.3
    assert facts["spy_return_pct"] == 1.7
    assert facts["qqq_return_pct"] == 0.65
    assert facts["ahead_of_spy"] is True and facts["ahead_of_qqq"] is True
    assert facts["alpha_vs_spy_pct"] == 0.6
    assert facts["cash_pct"] == 26.0
    assert facts["top_holdings"] == ["AAPL", "NVDA", "MSFT"]
    assert facts["resolved_predictions"] == 0
    assert facts["small_sample"] is True  # 25 days + 0 resolved


def test_facts_flag_insufficient_history():
    facts = gather_state_facts(
        performance_rows=_perf(("2026-06-11", 1_000_000)),
        benchmark_rows=[],
        portfolio_store=_FakeStore(snapshot=None),
        prediction_store=_FakeStore(rows=[]),
    )
    assert facts["enough_data"] is False


def test_behind_benchmark_is_reported_honestly():
    facts = gather_state_facts(
        performance_rows=_perf(("2026-06-11", 1_000_000), ("2026-07-06", 1_005_000)),
        benchmark_rows=_bench("SPY", ("2026-06-11", 100.0), ("2026-07-06", 103.0)),
        portfolio_store=_FakeStore(snapshot=_SNAPSHOT),
        prediction_store=_FakeStore(rows=[]),
    )
    assert facts["fund_return_pct"] == 0.5
    assert facts["ahead_of_spy"] is False
    assert facts["alpha_vs_spy_pct"] == -2.5


# -- generation --------------------------------------------------------------


def test_generate_state_tweet_uses_cheap_tier_and_truncates(monkeypatch):
    captured = {}

    def fake_complete(messages, *, tier, prompt_version):
        captured["tier"] = tier
        captured["has_facts"] = "fund_return_pct" in messages[-1]["content"]
        return "  Glasshouse is an autonomous AI fund… +2.3% vs SPY +1.7%. Early days. glasshousefund.com  "

    monkeypatch.setattr(state_of_fund, "complete_text", fake_complete)
    text = generate_state_tweet({"fund_return_pct": 2.3, "spy_return_pct": 1.7})

    assert captured["tier"] == "cheap"
    assert captured["has_facts"] is True
    assert text == text.strip() and len(text) <= 280
    assert "glasshousefund.com" in text


# -- chart -------------------------------------------------------------------


def test_render_chart_returns_png_bytes():
    png = render_performance_chart(
        _perf(("2026-06-11", 1_000_000), ("2026-06-20", 990_000), ("2026-07-06", 1_022_983)),
        _bench("SPY", ("2026-06-11", 100.0), ("2026-07-06", 101.7))
        + _bench("QQQ", ("2026-06-11", 100.0), ("2026-07-06", 100.65)),
    )
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
    assert len(png) > 1000


def test_render_chart_none_without_enough_points():
    assert render_performance_chart(_perf(("2026-06-11", 1_000_000)), []) is None
