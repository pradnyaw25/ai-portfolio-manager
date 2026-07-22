from src.agents.receipts_tweet import PREDICTIONS_URL, build_receipts_tweet


def _pred(symbol, *, direction, correct, confidence=0.7, horizon=5,
          symbol_return=0.05, spy_return=0.01):
    verb = "underperform" if direction == "UNDERPERFORM" else "outperform"
    return {
        "symbol": symbol,
        "prediction": f"{symbol} will {verb} SPY over {horizon} days",
        "direction": direction,
        "horizon_days": horizon,
        "confidence": confidence,
        "status": "scored",
        "result": {
            "symbol_return": symbol_return,
            "spy_return": spy_return,
            "correct": correct,
            "outperformed": symbol_return > spy_return,
        },
    }


_RECORD = {"total": 41, "correct": 24}


def test_none_when_nothing_resolved():
    assert build_receipts_tweet([], _RECORD) is None
    assert build_receipts_tweet([{"symbol": "AAPL", "result": None}], _RECORD) is None


def test_single_correct_underperform_call_reads_as_a_win_and_cashtags():
    # An underperform call that duly lagged is a WIN even though the stock fell.
    p = _pred("APLD", direction="UNDERPERFORM", correct=True, confidence=0.7,
              horizon=5, symbol_return=-0.055, spy_return=0.007)
    tweet = build_receipts_tweet([p], _RECORD)

    assert "$APLD" in tweet  # single symbol → cashtag
    assert "lag the S&P 500" in tweet
    assert "70% conviction" in tweet
    assert "✓ Right." in tweet
    assert "5d ago" in tweet
    assert "24/41 calls right (59%)" in tweet
    assert PREDICTIONS_URL in tweet
    assert len(tweet) <= 280


def test_single_missed_call_reads_as_a_loss():
    p = _pred("NVDA", direction="OUTPERFORM", correct=False,
              symbol_return=-0.02, spy_return=0.03)
    tweet = build_receipts_tweet([p], _RECORD)

    assert "✗ Missed." in tweet
    assert "beat the S&P 500" in tweet


def test_multiple_resolutions_lead_with_sharpest_and_stay_plain():
    high = _pred("AAPL", direction="OUTPERFORM", correct=True, confidence=0.8,
                 symbol_return=0.08, spy_return=0.008)
    mid = _pred("MSFT", direction="UNDERPERFORM", correct=True, confidence=0.6,
                symbol_return=-0.02, spy_return=0.01)
    low = _pred("GOOGL", direction="OUTPERFORM", correct=False, confidence=0.55,
                symbol_return=-0.01, spy_return=0.011)
    tweet = build_receipts_tweet([low, high, mid], _RECORD)

    # Highest-confidence calls lead (AAPL, then MSFT); the lowest is summarized.
    assert tweet.index("AAPL") < tweet.index("MSFT")
    assert "2/3 right today" in tweet
    assert "+1 more scored." in tweet
    assert "GOOGL" not in tweet  # the third call rolls into "+1 more"
    # No cashtags when several names appear (X rejects multiple cashtags).
    assert "$" not in tweet
    assert len(tweet) <= 280


def test_record_omitted_when_no_history():
    p = _pred("AAPL", direction="OUTPERFORM", correct=True)
    tweet = build_receipts_tweet([p], {"total": 0, "correct": 0})

    assert "Track record" not in tweet
    assert PREDICTIONS_URL in tweet


def test_derives_direction_and_horizon_from_text_for_legacy_rows():
    # A legacy row with no direction/horizon_days fields, only the call text.
    legacy = {
        "symbol": "AAPL",
        "prediction": "AAPL will outperform SPY over 30 days",
        "confidence": 0.8,
        "status": "scored",
        "result": {"symbol_return": 0.08, "spy_return": 0.008, "correct": True,
                   "outperformed": True},
    }
    tweet = build_receipts_tweet([legacy], _RECORD)

    assert "30d ago" in tweet
    assert "beat the S&P 500" in tweet
