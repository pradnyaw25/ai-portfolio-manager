from datetime import date, datetime

from src.agents.tweet_generator import TweetGeneratorAgent
from src.models.portfolio import PortfolioSnapshot, Position
from src.models.trade import Trade, TradeAction


def _agent():
    # Bypass __init__ so we don't read the prompt file — we only exercise helpers.
    return TweetGeneratorAgent.__new__(TweetGeneratorAgent)


def test_clean_tweet_removes_repetitive_disclaimer_lines():
    tweet = _agent()._clean_tweet(
        """Trimmed tech and kept cash near 30%.

Simulated portfolio. Not investment advice."""
    )
    assert tweet == "Trimmed tech and kept cash near 30%."


# --- Single-symbol cashtag -------------------------------------------------------

_KNOWN = {"AAPL", "NVDA", "PG", "MA", "BE", "V"}


def test_cashtag_added_when_exactly_one_symbol_mentioned():
    out = _agent()._apply_cashtag("Added AAPL on services strength.", _KNOWN)
    assert out == "Added $AAPL on services strength."


def test_no_cashtag_when_two_symbols_mentioned():
    # Multiple cashtags read as spam, so a multi-name tweet stays plain.
    text = "Trimmed NVDA, added AAPL as the AI trade broadens."
    assert _agent()._apply_cashtag(text, _KNOWN) == text


def test_cashtag_only_the_first_mention_of_the_lone_symbol():
    out = _agent()._apply_cashtag("AAPL into earnings; AAPL guidance is the swing.", _KNOWN)
    assert out == "$AAPL into earnings; AAPL guidance is the swing."


def test_cashtag_is_a_noop_when_already_present():
    text = "Still constructive on $AAPL here."
    assert _agent()._apply_cashtag(text, _KNOWN) == text


def test_cashtag_ignores_a_benchmark_only_reference():
    # SPY/QQQ are excluded from the vocabulary upstream, so "beat SPY" alone earns none.
    known_no_bench = _KNOWN  # already excludes benchmarks
    text = "The book leaned defensive but still beat the tape."
    assert _agent()._apply_cashtag(text, known_no_bench) == text


def test_cashtag_does_not_match_inside_a_longer_word():
    # "V" must not tag the V in "AVGO" or a stray substring.
    text = "AVGO strength carried the week."
    assert _agent()._apply_cashtag(text, {"V"}) == text


def test_known_symbols_excludes_benchmarks_and_includes_context():
    agent = _agent()
    trades = [Trade(datetime(2026, 7, 9), "AAPL", TradeAction.BUY, 10, 312.0)]
    decisions = {"market_calls": [{"symbol": "nvda"}], "trades": [{"symbol": "PG"}]}
    known = agent._known_symbols(_portfolio(), trades, decisions)

    assert {"AAPL", "NVDA", "PG", "MSFT"} <= known  # MSFT is the held position
    assert "SPY" not in known and "QQQ" not in known
    assert "" not in known


def test_generate_cashtags_the_single_traded_symbol(monkeypatch):
    # generate() wires vocabulary + cashtag + truncation together; drive it end-to-end
    # with a stubbed model that returns a plain-ticker tweet (as the prompt instructs).
    agent = _agent()
    agent.system_prompt = "system"
    monkeypatch.setattr(
        "src.agents.tweet_generator.complete_text",
        lambda *a, **k: "Added AAPL as buyback pace and services margin do the work.",
    )
    trades = [Trade(datetime(2026, 7, 9), "AAPL", TradeAction.BUY, 10, 312.0)]
    tweet = agent.generate(_portfolio(), trades, {"trades": [{"symbol": "AAPL"}]}, {})

    assert "$AAPL" in tweet
    assert tweet.endswith("glasshousefund.com/symbols/AAPL.html")  # single name → its hub
    assert len(tweet) <= 280


# --- Read-more link --------------------------------------------------------------


def test_link_points_to_symbol_hub_for_a_single_name():
    agent = _agent()
    text = "Added AAPL on services strength."
    linked = agent._append_link(text, agent._mentioned_symbols(text, _KNOWN))
    assert linked.endswith("\nglasshousefund.com/symbols/AAPL.html")


def test_link_falls_back_to_dashboard_for_multiple_or_no_names():
    agent = _agent()
    two = "Trimmed NVDA, added AAPL."
    none = "Quiet tape, nothing stands out."
    assert agent._append_link(two, agent._mentioned_symbols(two, _KNOWN)).endswith(
        "glasshousefund.com/dashboard.html"
    )
    assert agent._append_link(none, agent._mentioned_symbols(none, _KNOWN)).endswith(
        "glasshousefund.com/dashboard.html"
    )


def test_link_survives_truncation_of_a_long_tweet():
    agent = _agent()
    long = "word " * 80 + "AAPL"
    linked = agent._append_link(long, agent._mentioned_symbols(long, _KNOWN))
    assert len(linked) <= 280
    assert linked.endswith("glasshousefund.com/symbols/AAPL.html")  # URL never trimmed


def _portfolio():
    return PortfolioSnapshot(
        date=date.today(), cash=270_000, positions=[Position("MSFT", 1750, 400, 400)]
    )


def test_context_includes_trade_reasoning_not_cash_or_position_count():
    trades = [Trade(datetime(2026, 7, 9), "AAPL", TradeAction.BUY, 10, 312.0)]
    decisions = {
        "outlook": "NEUTRAL",
        "trades": [{"symbol": "AAPL", "action": "BUY", "reason": "buyback pace and services margin"}],
        "market_calls": [],
    }
    ctx = _agent()._build_context(_portfolio(), trades, decisions, {})

    assert "BUY AAPL" in ctx
    assert "buyback pace and services margin" in ctx  # the WHY is fed to the model
    # The boring facts are deliberately absent.
    assert "positions" not in ctx.lower()
    assert "27.0%" not in ctx and "cash" not in ctx.lower()


def test_context_ties_a_trade_to_its_news_catalyst():
    trades = [Trade(datetime(2026, 7, 9), "AAPL", TradeAction.BUY, 10, 312.0)]
    decisions = {"trades": [{"symbol": "AAPL", "action": "BUY", "reason": "services strength"}]}
    research = {
        "symbol_news": {
            "AAPL": [
                {"title": "Apple guides higher on services strength", "source": "Reuters"},
                {"title": "Analysts lift Apple targets", "source": "CNBC"},
            ],
            "NVDA": [{"title": "Chip demand cools", "source": "WSJ"}],  # untraded — must not appear
        },
        "market_news": [{"title": "Markets extend rally on earnings", "source": "CNBC"}],
    }
    ctx = _agent()._build_context(_portfolio(), trades, decisions, research)

    assert "Apple guides higher on services strength" in ctx  # catalyst behind the trade
    assert "Chip demand cools" not in ctx  # NVDA wasn't traded, so its news isn't attached
    assert "Markets extend rally on earnings" in ctx  # top market headline available


def test_context_surfaces_sharpest_calls_with_direction():
    decisions = {
        "market_calls": [
            {"symbol": "NVDA", "direction": "UNDERPERFORM", "confidence": 0.7, "thesis": "stretched multiple"},
            {"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.65, "thesis": "momentum"},
            {"symbol": "PG", "direction": "OUTPERFORM", "confidence": 0.5, "thesis": "defensive"},
        ],
    }
    ctx = _agent()._build_context(_portfolio(), [], decisions, {})

    # Highest-conviction call first, with a plain-English direction and the thesis.
    assert "NVDA: lag the S&P 500" in ctx
    assert "70% conviction" in ctx
    assert "stretched multiple" in ctx
    assert "AAPL: beat the S&P 500" in ctx
    # No trades today reads as a hold, not a status dump.
    assert "the fund held" in ctx


def test_context_handles_no_decisions_gracefully():
    ctx = _agent()._build_context(_portfolio(), [], {}, {})
    assert "the fund held" in ctx
    assert "positions" not in ctx.lower()


# --- Cooldown / variety ----------------------------------------------------------


def _calls_lead(ctx):
    import re
    block = ctx.split("sharpest directional calls")[1]
    return re.search(r"- (\w+):", block).group(1)


def test_quiet_day_leads_with_a_fresh_name_when_top_call_is_on_cooldown():
    decisions = {
        "market_calls": [
            {"symbol": "AAPL", "confidence": 0.85, "direction": "OUTPERFORM", "thesis": "momentum"},
            {"symbol": "MU", "confidence": 0.70, "direction": "OUTPERFORM", "thesis": "memory cycle"},
        ]
    }
    ctx = _agent()._build_context(_portfolio(), [], decisions, {}, cooldown_symbols={"AAPL"})
    # AAPL has higher conviction but was tweeted recently, so the fresh name leads.
    assert _calls_lead(ctx) == "MU"


def test_highest_conviction_leads_when_nothing_is_on_cooldown():
    decisions = {
        "market_calls": [
            {"symbol": "AAPL", "confidence": 0.85, "direction": "OUTPERFORM", "thesis": "momentum"},
            {"symbol": "MU", "confidence": 0.70, "direction": "OUTPERFORM", "thesis": "memory cycle"},
        ]
    }
    ctx = _agent()._build_context(_portfolio(), [], decisions, {}, cooldown_symbols=set())
    assert _calls_lead(ctx) == "AAPL"


def test_all_on_cooldown_falls_back_to_conviction_order():
    decisions = {
        "market_calls": [
            {"symbol": "AAPL", "confidence": 0.85, "direction": "OUTPERFORM", "thesis": "momentum"},
            {"symbol": "MU", "confidence": 0.70, "direction": "OUTPERFORM", "thesis": "cycle"},
        ]
    }
    ctx = _agent()._build_context(_portfolio(), [], decisions, {}, cooldown_symbols={"AAPL", "MU"})
    # Better a repeat than nothing — highest conviction still leads.
    assert _calls_lead(ctx) == "AAPL"
