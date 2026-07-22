from src.agents.spotlight_tweet import build_spotlight_tweet

CALLS = [
    {"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.72,
     "thesis": "Strong 30-day momentum and AI catalysts support outperformance."},
    {"symbol": "MU", "direction": "OUTPERFORM", "confidence": 0.68,
     "thesis": "Memory pricing has bottomed and datacenter demand is soaking up supply."},
    {"symbol": "TSLA", "direction": "UNDERPERFORM", "confidence": 0.55,
     "thesis": "Stretched multiple into a soft delivery quarter."},
]
RESEARCH = {"symbol_news": {"MU": [{"title": "Micron guides higher on HBM demand"}]}}


def test_spotlights_top_eligible_call_with_thesis_catalyst_and_link():
    tweet = build_spotlight_tweet(CALLS, RESEARCH, exclude={"AAPL"})
    assert tweet.startswith("Spotlight: $MU — the fund's 68% call to beat the S&P 500")
    assert "Memory pricing has bottomed" in tweet
    assert "Catalyst: Micron guides higher on HBM demand" in tweet
    assert tweet.endswith("glasshousefund.com/symbols/MU.html")
    assert len(tweet) <= 280


def test_excludes_the_forward_tweets_symbol():
    # AAPL is highest conviction but the forward tweet already led with it.
    tweet = build_spotlight_tweet(CALLS, RESEARCH, exclude={"AAPL"})
    assert "$MU" in tweet
    assert "AAPL" not in tweet


def test_underperform_call_reads_as_lag():
    calls = [{"symbol": "TSLA", "direction": "UNDERPERFORM", "confidence": 0.8,
              "thesis": "Rich multiple, softening deliveries."}]
    tweet = build_spotlight_tweet(calls, {})
    assert "call to lag the S&P 500" in tweet


def test_none_when_no_call_clears_the_confidence_floor():
    weak = [{"symbol": "PG", "direction": "OUTPERFORM", "confidence": 0.5, "thesis": "meh"}]
    assert build_spotlight_tweet(weak, {}) is None


def test_none_when_every_eligible_name_is_excluded():
    assert build_spotlight_tweet(CALLS, RESEARCH, exclude={"AAPL", "MU", "TSLA"}) is None


def test_cooldown_deprioritizes_but_still_picks_the_only_eligible_name():
    # MU is on cooldown, but AAPL is excluded and TSLA is below the floor, so MU (a
    # repeat) still beats posting nothing.
    tweet = build_spotlight_tweet(CALLS, RESEARCH, exclude={"AAPL"}, cooldown={"MU"})
    assert "$MU" in tweet


def test_prefers_a_fresh_name_over_a_higher_conviction_one_on_cooldown():
    calls = [
        {"symbol": "AAPL", "direction": "OUTPERFORM", "confidence": 0.9, "thesis": "hot"},
        {"symbol": "MU", "direction": "OUTPERFORM", "confidence": 0.7, "thesis": "cycle"},
    ]
    tweet = build_spotlight_tweet(calls, {}, cooldown={"AAPL"})
    assert "$MU" in tweet  # fresh name wins despite lower conviction


def test_omits_catalyst_line_when_no_news():
    tweet = build_spotlight_tweet([CALLS[1]], {})  # MU, no research
    assert "Catalyst:" not in tweet
    assert "$MU" in tweet
